"""Agendamentos financeiros persistentes, executados pelo worker do backend."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import fdb
from flask import current_app, jsonify, request

from banco import con
from funcao import (
    dados_conta,
    dados_usuario,
    descobre_id_conta,
    descobre_id_usuario,
    usuario_pode_acessar_conta,
)
from notificacoes import (
    registrar_notificacao_usuario,
    tentar_publicar_eventos,
)
from operacoes_financeiras import (
    ErroOperacaoFinanceira,
    executar_pagamento_cobranca,
    hash_chave_pix,
    executar_pix_para_conta,
    _valor_monetario_api,
)


FUSO = ZoneInfo('America/Sao_Paulo')
COLUNAS_CHAVE_PIX = {
    'email': 'CHAVE_PIX_EMAIL',
    'telefone': 'CHAVE_PIX_TELEFONE',
    'cpf': 'CHAVE_PIX_CPF',
    'cnpj': 'CHAVE_PIX_CNPJ',
    'aleatoria': 'CHAVE_PIX_ALEATORIA',
}
STATUS_VALIDOS = {'AGENDADO', 'EXECUTANDO', 'CONCLUIDO', 'CANCELADO', 'FALHOU'}
MAX_TENTATIVAS = 5
LEASE_SEGUNDOS = 90


def _agora_local():
    return datetime.now(FUSO).replace(tzinfo=None)


def _data_local(valor):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError('Informe a data e o horario do agendamento')
    try:
        momento = datetime.fromisoformat(valor.strip().replace('Z', '+00:00'))
    except ValueError as erro:
        raise ValueError('Data e horario invalidos') from erro
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=FUSO)
    return momento.astimezone(FUSO).replace(tzinfo=None)


def _normalizar_chave(tipo, chave):
    texto = str(chave or '').strip()
    if tipo in ('cpf', 'cnpj', 'telefone'):
        texto = ''.join(caractere for caractere in texto if caractere.isdigit())
    return texto


def _hash_chave(tipo, chave):
    return hash_chave_pix(tipo, chave)


def _categoria(tipo_operacao):
    return 'BOLETO' if tipo_operacao == 'BOLETO' else 'PIX'


def _rotulo_operacao(tipo_operacao):
    return {
        'TRANSFERENCIA': 'Pix',
        'PIX_COBRANCA': 'pagamento Pix',
        'BOLETO': 'boleto',
    }.get(tipo_operacao, 'operacao')


def _registrar_aviso(cursor, id_agendamento, id_usuario, id_conta,
                     tipo_operacao, valor, estado, motivo=None):
    categoria = _categoria(tipo_operacao)
    rotulo = _rotulo_operacao(tipo_operacao)
    valor_formatado = f'R$ {Decimal(str(valor)):.2f}'.replace('.', ',')
    if estado == 'AGENDADO':
        titulo = 'Operacao agendada'
        mensagem = f'{rotulo.capitalize()} de {valor_formatado} foi agendado.'
    elif estado == 'CANCELADO':
        titulo = 'Agendamento cancelado'
        mensagem = f'O agendamento de {rotulo} de {valor_formatado} foi cancelado.'
    elif estado == 'CONCLUIDO':
        titulo = 'Agendamento concluido'
        mensagem = f'O {rotulo} agendado de {valor_formatado} foi executado.'
    else:
        titulo = 'Agendamento nao executado'
        mensagem = f'O {rotulo} de {valor_formatado} nao foi executado. {motivo or "Confira o detalhe no historico de agendamentos."}'
    return registrar_notificacao_usuario(
        cursor,
        chave=f'agendamento:{id_agendamento}:{estado.lower()}',
        categoria=categoria,
        id_usuario=id_usuario,
        id_conta=id_conta,
        titulo=titulo,
        mensagem=mensagem[:500],
        dados={
            'id_agendamento': int(id_agendamento),
            'tipo_operacao': tipo_operacao,
            'status': estado,
            'valor': str(valor),
            'motivo': motivo,
        },
        referencia_tipo='AGENDAMENTO',
        referencia_id=id_agendamento,
    )


def _sessao_atual():
    usuario = dados_usuario()
    conta = dados_conta()
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()
    if not usuario or not conta or not id_usuario or not id_conta:
        return None, None, (jsonify({'mensagem': 'Sessao invalida ou conta nao selecionada'}), 401)
    if int(usuario['id_usuario']) != int(id_usuario) or int(conta['id_conta']) != int(id_conta):
        return None, None, (jsonify({'mensagem': 'Sessao invalida ou conta nao selecionada'}), 401)
    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None, None, (jsonify({'mensagem': 'Acesso a conta revogado ou indisponivel'}), 403)
    return int(id_usuario), int(id_conta), None


def _serializar_data(valor):
    return valor.isoformat(timespec='seconds') if valor else None


def listar_agendamentos():
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    filtro = str(request.args.get('status') or '').strip().upper()
    if filtro and filtro not in STATUS_VALIDOS:
        return jsonify({'mensagem': 'Status de agendamento invalido'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        sql = '''SELECT S.ID_AGENDAMENTO, S.TIPO_OPERACAO, S.VALOR,
                        S.DATA_AGENDADA, S.STATUS, S.CRIADO_EM, S.EXECUTADO_EM,
                        S.CANCELADO_EM, S.MOTIVO_FALHA,
                        COALESCE(D.NOME_FANTASIA, D.RAZAO_SOCIAL, UD.NOME,
                                 CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, UR.NOME),
                        CB.CODIGO_PAGAMENTO, RE.ID_RECORRENCIA
                 FROM AGENDAMENTO_FINANCEIRO S
                 LEFT JOIN CONTA D ON D.ID_CONTA = S.ID_CONTA_DESTINO
                 LEFT JOIN USUARIO UD ON UD.ID_USUARIO = D.ID_USUARIO
                 LEFT JOIN COBRANCA CB ON CB.ID_COBRANCA = S.ID_COBRANCA
                 LEFT JOIN CONTA CR ON CR.ID_CONTA = CB.ID_RECEBEDOR
                 LEFT JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                 LEFT JOIN RECORRENCIA_EXECUCAO RE ON RE.ID_AGENDAMENTO = S.ID_AGENDAMENTO
                 WHERE S.ID_USUARIO = ? AND S.ID_CONTA = ?'''
        parametros = [id_usuario, id_conta]
        if filtro:
            sql += ' AND S.STATUS = ?'
            parametros.append(filtro)
        sql += ' ORDER BY S.DATA_AGENDADA DESC, S.ID_AGENDAMENTO DESC'
        cursor.execute(sql, tuple(parametros))
        agendamentos = []
        for linha in cursor.fetchall():
            agendamentos.append({
                'id_agendamento': int(linha[0]),
                'tipo_operacao': linha[1],
                'valor': float(linha[2]),
                'data_agendada': _serializar_data(linha[3]),
                'status': linha[4],
                'criado_em': _serializar_data(linha[5]),
                'executado_em': _serializar_data(linha[6]),
                'cancelado_em': _serializar_data(linha[7]),
                'motivo_falha': linha[8],
                'destinatario': linha[9] or (f'Cobrança {linha[10]}' if linha[10] else 'Pagamento'),
                'codigo_pagamento': linha[10],
                'id_recorrencia': int(linha[11]) if linha[11] is not None else None,
            })
        return jsonify({'fuso': 'America/Sao_Paulo', 'agendamentos': agendamentos}), 200
    except Exception:
        current_app.logger.exception('Falha ao listar agendamentos da conta %s', id_conta)
        return jsonify({'mensagem': 'Nao foi possivel consultar os agendamentos'}), 500
    finally:
        if cursor:
            cursor.close()


def criar_agendamento():
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400

    tipo_operacao = str(dados.get('tipo_operacao') or '').strip().upper()
    if tipo_operacao not in ('TRANSFERENCIA', 'PIX_COBRANCA', 'BOLETO'):
        return jsonify({'mensagem': 'Tipo deve ser TRANSFERENCIA, PIX_COBRANCA ou BOLETO'}), 400
    try:
        data_agendada = _data_local(dados.get('data_agendada'))
        if data_agendada <= _agora_local():
            raise ValueError('Escolha uma data e horario futuros')
        valor_enviado = _valor_monetario_api(dados.get('valor'))
        tipo_chave = None
        hash_chave = None
        id_conta_destino = None
        id_cobranca = None
        valor = valor_enviado

        cursor = con.cursor()
        if tipo_operacao == 'TRANSFERENCIA':
            tipo_chave = str(dados.get('tipo_chave') or '').strip().lower()
            coluna = COLUNAS_CHAVE_PIX.get(tipo_chave)
            chave_pix = _normalizar_chave(tipo_chave, dados.get('chave_pix'))
            if not coluna or not chave_pix or valor is None:
                raise ValueError('Informe chave Pix valida e valor positivo')
            cursor.execute(f'SELECT ID_CONTA FROM CHAVE_PIX WHERE {coluna} = ?', (chave_pix,))
            destinos = cursor.fetchall()
            if len(destinos) != 1:
                raise ValueError('Chave Pix nao encontrada ou com cadastro ambiguo')
            id_conta_destino = int(destinos[0][0])
            if id_conta_destino == id_conta:
                raise ValueError('Nao e possivel agendar Pix para a mesma conta')
            hash_chave = _hash_chave(tipo_chave, chave_pix)
        else:
            try:
                id_cobranca = int(dados.get('id_cobranca'))
            except (TypeError, ValueError) as parse_erro:
                raise ValueError('Informe uma cobranca valida') from parse_erro
            cursor.execute(
                '''SELECT ID_RECEBEDOR, VALOR, STATUS, TIPO_COBRANCA
                   FROM COBRANCA WHERE ID_COBRANCA = ?''',
                (id_cobranca,),
            )
            cobranca = cursor.fetchone()
            if not cobranca:
                raise ValueError('Cobranca nao encontrada')
            id_recebedor, valor_cobranca, status, tipo_cobranca = cobranca
            tipo_esperado = 1 if tipo_operacao == 'PIX_COBRANCA' else 0
            if int(tipo_cobranca or 0) != tipo_esperado:
                raise ValueError('O tipo da cobranca nao corresponde ao agendamento')
            if int(status) != 0:
                raise ValueError('A cobranca nao esta pendente')
            if int(id_recebedor) == id_conta:
                raise ValueError('A conta recebedora nao pode pagar a propria cobranca')
            if valor_cobranca is None:
                if valor is None:
                    raise ValueError('Informe o valor para esta cobranca Pix')
            elif valor is not None and valor != valor_cobranca:
                raise ValueError('O valor desta cobranca e fixo e nao pode ser alterado')
            valor = valor_cobranca if valor_cobranca is not None else valor

        cursor.execute(
            '''INSERT INTO AGENDAMENTO_FINANCEIRO
               (ID_USUARIO, ID_CONTA, TIPO_OPERACAO, ID_CONTA_DESTINO,
                ID_COBRANCA, TIPO_CHAVE, HASH_CHAVE, VALOR, DATA_AGENDADA,
                STATUS, TENTATIVAS)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AGENDADO', 0)
               RETURNING ID_AGENDAMENTO''',
            (id_usuario, id_conta, tipo_operacao, id_conta_destino, id_cobranca,
             tipo_chave, hash_chave, valor, data_agendada),
        )
        id_agendamento = int(cursor.fetchone()[0])
        evento = _registrar_aviso(
            cursor, id_agendamento, id_usuario, id_conta,
            tipo_operacao, valor, 'AGENDADO',
        )
        con.commit()
        tentar_publicar_eventos([evento])
        return jsonify({
            'mensagem': 'Agendamento criado. O saldo nao foi movimentado.',
            'id_agendamento': id_agendamento,
            'status': 'AGENDADO',
            'data_agendada': data_agendada.isoformat(timespec='seconds'),
            'fuso': 'America/Sao_Paulo',
        }), 201
    except ValueError as validacao:
        con.rollback()
        return jsonify({'mensagem': str(validacao)}), 400
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao criar agendamento para a conta %s', id_conta)
        return jsonify({'mensagem': 'Nao foi possivel criar o agendamento'}), 500
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()


def cancelar_agendamento(id_agendamento):
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT TIPO_OPERACAO, VALOR, STATUS FROM AGENDAMENTO_FINANCEIRO
               WHERE ID_AGENDAMENTO = ? AND ID_USUARIO = ? AND ID_CONTA = ? WITH LOCK''',
            (id_agendamento, id_usuario, id_conta),
        )
        agendamento = cursor.fetchone()
        if not agendamento:
            con.rollback()
            return jsonify({'mensagem': 'Agendamento nao encontrado'}), 404
        if agendamento[2] != 'AGENDADO':
            con.rollback()
            return jsonify({'mensagem': 'Somente agendamentos ainda nao iniciados podem ser cancelados'}), 409
        cursor.execute(
            '''UPDATE AGENDAMENTO_FINANCEIRO
               SET STATUS = 'CANCELADO', CANCELADO_EM = CURRENT_TIMESTAMP,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE ID_AGENDAMENTO = ? AND STATUS = 'AGENDADO'
               RETURNING ID_AGENDAMENTO''',
            (id_agendamento,),
        )
        if not cursor.fetchone():
            con.rollback()
            return jsonify({'mensagem': 'O agendamento ja foi iniciado e nao pode ser cancelado'}), 409
        evento = _registrar_aviso(
            cursor, id_agendamento, id_usuario, id_conta,
            agendamento[0], agendamento[1], 'CANCELADO',
        )
        from recorrencias import sincronizar_resultado_recorrencia
        sincronizar_resultado_recorrencia(
            cursor, id_agendamento, 'CANCELADO', 'Cancelado pelo cliente', notificar=False,
        )
        con.commit()
        tentar_publicar_eventos([evento])
        return jsonify({'mensagem': 'Agendamento cancelado', 'status': 'CANCELADO'}), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao cancelar agendamento %s', id_agendamento)
        return jsonify({'mensagem': 'Nao foi possivel cancelar o agendamento'}), 500
    finally:
        if cursor:
            cursor.close()


def _reivindicar_agendamentos(limite=20):
    cursor = None
    reivindicados = []
    agora = _agora_local()
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT FIRST ? ID_AGENDAMENTO
               FROM AGENDAMENTO_FINANCEIRO
               WHERE DATA_AGENDADA <= ?
                 AND (TENTAR_APOS IS NULL OR TENTAR_APOS <= CURRENT_TIMESTAMP)
                 AND (STATUS = 'AGENDADO'
                      OR (STATUS = 'EXECUTANDO' AND (LEASE_ATE IS NULL OR LEASE_ATE < CURRENT_TIMESTAMP)))
               ORDER BY DATA_AGENDADA, ID_AGENDAMENTO''',
            (int(limite), agora),
        )
        candidatos = [int(linha[0]) for linha in cursor.fetchall()]
        for id_agendamento in candidatos:
            token = str(uuid.uuid4())
            cursor.execute(
                '''UPDATE AGENDAMENTO_FINANCEIRO
                   SET STATUS = 'EXECUTANDO', TOKEN_EXECUCAO = ?,
                       LEASE_ATE = DATEADD(? SECOND TO CURRENT_TIMESTAMP),
                       TENTATIVAS = TENTATIVAS + 1,
                       ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_AGENDAMENTO = ? AND DATA_AGENDADA <= ?
                     AND (TENTAR_APOS IS NULL OR TENTAR_APOS <= CURRENT_TIMESTAMP)
                     AND (STATUS = 'AGENDADO'
                          OR (STATUS = 'EXECUTANDO' AND (LEASE_ATE IS NULL OR LEASE_ATE < CURRENT_TIMESTAMP)))
                   RETURNING ID_AGENDAMENTO''',
                (token, LEASE_SEGUNDOS, id_agendamento, agora),
            )
            if cursor.fetchone():
                reivindicados.append((id_agendamento, token))
        con.commit()
        return reivindicados
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao reivindicar agendamentos vencidos')
        return []
    finally:
        if cursor:
            cursor.close()


def _marcar_concluido(cursor, id_agendamento, id_movimentacao, id_usuario,
                       id_conta, tipo_operacao, valor):
    cursor.execute(
        '''INSERT INTO AGENDAMENTO_EXECUCAO (ID_AGENDAMENTO, ID_MOVIMENTACAO)
           VALUES (?, ?)''',
        (id_agendamento, id_movimentacao),
    )
    cursor.execute(
        '''UPDATE AGENDAMENTO_FINANCEIRO
           SET STATUS = 'CONCLUIDO', EXECUTADO_EM = CURRENT_TIMESTAMP,
               TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL, TENTAR_APOS = NULL,
               MOTIVO_FALHA = NULL, ATUALIZADO_EM = CURRENT_TIMESTAMP
           WHERE ID_AGENDAMENTO = ? AND STATUS = 'EXECUTANDO' ''',
        (id_agendamento,),
    )
    from recorrencias import sincronizar_resultado_recorrencia
    eventos_recorrencia = sincronizar_resultado_recorrencia(
        cursor, id_agendamento, 'CONCLUIDO',
    )
    if eventos_recorrencia:
        return eventos_recorrencia
    evento = _registrar_aviso(
        cursor, id_agendamento, id_usuario, id_conta,
        tipo_operacao, valor, 'CONCLUIDO',
    )
    return [evento]


def _persistir_falha(id_agendamento, token, tipo_operacao, valor,
                     id_usuario, id_conta, motivo, permanente):
    cursor = None
    eventos = []
    try:
        cursor = con.cursor()
        from recorrencias import status_recorrencia_para_agendamento
        status_recorrencia = status_recorrencia_para_agendamento(cursor, id_agendamento)
        cursor.execute(
            '''SELECT STATUS, TOKEN_EXECUCAO, TENTATIVAS
               FROM AGENDAMENTO_FINANCEIRO WHERE ID_AGENDAMENTO = ? WITH LOCK''',
            (id_agendamento,),
        )
        atual = cursor.fetchone()
        if not atual or atual[0] != 'EXECUTANDO' or atual[1] != token:
            con.rollback()
            return
        if status_recorrencia and status_recorrencia != 'ATIVA':
            motivo_cancelamento = 'Recorrencia pausada ou cancelada antes da execucao'
            cursor.execute(
                '''UPDATE AGENDAMENTO_FINANCEIRO SET STATUS = 'CANCELADO',
                   CANCELADO_EM = CURRENT_TIMESTAMP, MOTIVO_FALHA = ?,
                   TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL, TENTAR_APOS = NULL,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
                (motivo_cancelamento, id_agendamento),
            )
            from recorrencias import sincronizar_resultado_recorrencia
            sincronizar_resultado_recorrencia(
                cursor, id_agendamento, 'CANCELADO', motivo_cancelamento,
                notificar=False,
            )
            con.commit()
            return
        cursor.execute(
            'SELECT ID_MOVIMENTACAO FROM AGENDAMENTO_EXECUCAO WHERE ID_AGENDAMENTO = ?',
            (id_agendamento,),
        )
        execucao_existente = cursor.fetchone()
        if execucao_existente:
            cursor.execute(
                '''UPDATE AGENDAMENTO_FINANCEIRO SET STATUS = 'CONCLUIDO',
                   EXECUTADO_EM = COALESCE(EXECUTADO_EM, CURRENT_TIMESTAMP),
                   TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
                (id_agendamento,),
            )
            from recorrencias import sincronizar_resultado_recorrencia
            eventos = sincronizar_resultado_recorrencia(
                cursor, id_agendamento, 'CONCLUIDO',
            )
            con.commit()
            if eventos:
                tentar_publicar_eventos(eventos)
            return

        encerrado = permanente or int(atual[2] or 0) >= MAX_TENTATIVAS
        status = 'FALHOU' if encerrado else 'AGENDADO'
        cursor.execute(
            '''UPDATE AGENDAMENTO_FINANCEIRO
               SET STATUS = ?, MOTIVO_FALHA = ?, TOKEN_EXECUCAO = NULL,
                   LEASE_ATE = NULL,
                   TENTAR_APOS = CASE WHEN ? = 'AGENDADO'
                       THEN DATEADD(1 MINUTE TO CURRENT_TIMESTAMP) ELSE NULL END,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE ID_AGENDAMENTO = ?''',
            (status, str(motivo)[:500], status, id_agendamento),
        )
        if encerrado:
            from recorrencias import sincronizar_resultado_recorrencia
            eventos = sincronizar_resultado_recorrencia(
                cursor, id_agendamento, 'FALHOU', str(motivo)[:350],
            )
            if not eventos:
                evento = _registrar_aviso(
                    cursor, id_agendamento, id_usuario, id_conta,
                    tipo_operacao, valor, 'FALHOU', str(motivo)[:350],
                )
                eventos.append(evento)
        con.commit()
        if eventos:
            tentar_publicar_eventos(eventos)
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao persistir resultado do agendamento %s', id_agendamento)
    finally:
        if cursor:
            cursor.close()


def _executar_agendamento(id_agendamento, token):
    cursor = None
    eventos = []
    id_usuario = None
    id_conta = None
    tipo_operacao = 'TRANSFERENCIA'
    valor = Decimal('0.00')
    try:
        cursor = con.cursor()
        from recorrencias import autorizar_execucao_recorrente
        if not autorizar_execucao_recorrente(cursor, id_agendamento, token):
            return False
        cursor.execute(
            '''SELECT ID_USUARIO, ID_CONTA, TIPO_OPERACAO, ID_CONTA_DESTINO,
                      ID_COBRANCA, TIPO_CHAVE, HASH_CHAVE, VALOR, STATUS, TOKEN_EXECUCAO
               FROM AGENDAMENTO_FINANCEIRO WHERE ID_AGENDAMENTO = ? WITH LOCK''',
            (id_agendamento,),
        )
        agendamento = cursor.fetchone()
        if (not agendamento or agendamento[8] != 'EXECUTANDO'
                or agendamento[9] != token):
            con.rollback()
            return False
        (id_usuario, id_conta, tipo_operacao, id_destino, id_cobranca,
         tipo_chave, hash_chave, valor, _status, _token) = agendamento
        id_usuario, id_conta = int(id_usuario), int(id_conta)
        valor = Decimal(str(valor))
        cursor.execute(
            'SELECT ID_MOVIMENTACAO FROM AGENDAMENTO_EXECUCAO WHERE ID_AGENDAMENTO = ?',
            (id_agendamento,),
        )
        execucao_existente = cursor.fetchone()
        if execucao_existente:
            cursor.execute(
                '''UPDATE AGENDAMENTO_FINANCEIRO SET STATUS = 'CONCLUIDO',
                   EXECUTADO_EM = COALESCE(EXECUTADO_EM, CURRENT_TIMESTAMP),
                   TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
                (id_agendamento,),
            )
            con.commit()
            return True

        if not usuario_pode_acessar_conta(id_usuario, id_conta):
            raise ErroOperacaoFinanceira('O acesso do usuario a conta foi revogado', 403, 'ACESSO_REVOGADO')

        if tipo_operacao == 'TRANSFERENCIA':
            coluna = COLUNAS_CHAVE_PIX.get(str(tipo_chave or '').lower())
            if not coluna:
                raise ErroOperacaoFinanceira('Tipo de chave Pix invalido', 400, 'CHAVE_INVALIDA')
            cursor.execute(
                f'SELECT {coluna} FROM CHAVE_PIX WHERE ID_CONTA = ?',
                (id_destino,),
            )
            valores_chave = [linha[0] for linha in cursor.fetchall() if linha[0] is not None]
            if sum(1 for chave in valores_chave if _hash_chave(tipo_chave, chave) == hash_chave) != 1:
                raise ErroOperacaoFinanceira('A chave Pix agendada foi removida ou alterada', 409, 'CHAVE_ALTERADA')
            resultado = executar_pix_para_conta(
                cursor, id_conta, int(id_destino), valor, id_usuario,
            )
        else:
            cursor.execute(
                'SELECT TIPO_COBRANCA FROM COBRANCA WHERE ID_COBRANCA = ?',
                (id_cobranca,),
            )
            cobranca = cursor.fetchone()
            tipo_esperado = 1 if tipo_operacao == 'PIX_COBRANCA' else 0
            if not cobranca or int(cobranca[0] or 0) != tipo_esperado:
                raise ErroOperacaoFinanceira('A cobranca foi removida ou mudou de tipo', 409, 'COBRANCA_ALTERADA')
            resultado = executar_pagamento_cobranca(
                cursor, id_conta, id_usuario, int(id_cobranca), valor,
            )

        eventos.extend(resultado['eventos'])
        eventos.extend(_marcar_concluido(
            cursor, id_agendamento, resultado['id_movimentacao'],
            id_usuario, id_conta, tipo_operacao, valor,
        ))
        con.commit()
        tentar_publicar_eventos(eventos)
        return True
    except ErroOperacaoFinanceira as erro:
        con.rollback()
        if cursor:
            cursor.close()
            cursor = None
        _persistir_falha(
            id_agendamento, token, tipo_operacao or 'TRANSFERENCIA', valor or Decimal('0'),
            id_usuario or 0, id_conta or 0, erro.mensagem, True,
        )
        return False
    except fdb.TransactionConflict as erro:
        con.rollback()
        if cursor:
            cursor.close()
            cursor = None
        _persistir_falha(
            id_agendamento, token, tipo_operacao or 'TRANSFERENCIA', valor or Decimal('0'),
            id_usuario or 0, id_conta or 0,
            'Conflito concorrente ao executar a operacao; nova verificacao agendada.', False,
        )
        return False
    except Exception as erro:
        con.rollback()
        current_app.logger.exception('Falha ao executar agendamento %s', id_agendamento)
        if cursor:
            cursor.close()
            cursor = None
        _persistir_falha(
            id_agendamento, token, tipo_operacao or 'TRANSFERENCIA', valor or Decimal('0'),
            id_usuario or 0, id_conta or 0,
            'Falha tecnica ao executar a operacao; nova verificacao agendada.', False,
        )
        return False
    finally:
        if cursor:
            cursor.close()


def processar_agendamentos_pendentes(limite=20):
    """Reivindica e processa agendamentos vencidos com lock e idempotencia."""
    total = 0
    for id_agendamento, token in _reivindicar_agendamentos(limite):
        if _executar_agendamento(id_agendamento, token):
            total += 1
    return total


def registrar_rotas(app):
    app.add_url_rule(
        '/api/v1/agendamentos', 'listar_agendamentos', listar_agendamentos,
        methods=['GET'],
    )
    app.add_url_rule(
        '/api/v1/agendamentos', 'criar_agendamento', criar_agendamento,
        methods=['POST'],
    )
    app.add_url_rule(
        '/api/v1/agendamentos/<int:id_agendamento>/cancelar',
        'cancelar_agendamento', cancelar_agendamento, methods=['PATCH'],
    )
