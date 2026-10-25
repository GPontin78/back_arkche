"""Regras recorrentes persistentes que materializam parcelas em agendamentos."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import current_app, jsonify, request

from agendamentos import (
    COLUNAS_CHAVE_PIX,
    _agora_local,
    _data_local,
    _hash_chave,
    _normalizar_chave,
    _rotulo_operacao,
    _serializar_data,
    _sessao_atual,
)
from banco import con
from notificacoes import registrar_notificacao_usuario, tentar_publicar_eventos
from operacoes_financeiras import _valor_monetario_api


FREQUENCIAS = {'SEMANAL', 'QUINZENAL', 'MENSAL'}
STATUS = {'ATIVA', 'PAUSADA', 'CANCELADA', 'FINALIZADA'}
STATUS_EXECUCAO_FINAL = {'CONCLUIDO', 'FALHOU', 'CANCELADO'}
MENSAGEM_BOLETO_REC = (
    'Pagamento recorrente de boleto indisponível: cada parcela precisa de uma nova '
    'cobrança válida. O boleto informado é de uso único; use o fluxo normal para '
    'pagar cada novo boleto.'
)


def proxima_data(data_atual, frequencia, dia_mes=None):
    """Calcula a próxima ocorrência no relógio de São Paulo, preservando a hora."""
    frequencia = str(frequencia or '').upper()
    if frequencia == 'SEMANAL':
        return data_atual + timedelta(days=7)
    if frequencia == 'QUINZENAL':
        return data_atual + timedelta(days=14)
    if frequencia != 'MENSAL':
        raise ValueError('Frequencia invalida')
    mes = data_atual.month + 1
    ano = data_atual.year
    if mes > 12:
        mes = 1
        ano += 1
    dia_base = int(dia_mes or data_atual.day)
    dia = min(dia_base, calendar.monthrange(ano, mes)[1])
    return data_atual.replace(year=ano, month=mes, day=dia)


def _data_fim(valor):
    if valor in (None, ''):
        return None
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except ValueError as erro:
        raise ValueError('Data final invalida') from erro


def _limite_execucoes(valor):
    if valor in (None, ''):
        return None
    try:
        limite = int(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError('Quantidade de execucoes invalida') from erro
    if not 1 <= limite <= 1200:
        raise ValueError('A quantidade de execucoes deve ficar entre 1 e 1200')
    return limite


def _frequencia(valor):
    frequencia = str(valor or '').strip().upper()
    if frequencia not in FREQUENCIAS:
        raise ValueError('Escolha uma frequencia semanal, quinzenal ou mensal')
    return frequencia


def _validar_termo(data_inicio, data_final, limite_execucoes):
    if data_final and limite_execucoes:
        raise ValueError('Escolha uma data final ou uma quantidade de execucoes')
    if data_final and data_final < data_inicio.date():
        raise ValueError('A data final deve ser igual ou posterior a primeira execucao')


def _validar_destino(cursor, id_conta, tipo_operacao, dados, valor_atual=None,
                     destino_atual=None, cobranca_atual=None, tipo_chave_atual=None,
                     hash_chave_atual=None):
    valor_informado = dados.get('valor') if 'valor' in dados else valor_atual
    valor = _valor_monetario_api(valor_informado)
    id_conta_destino = destino_atual
    id_cobranca = cobranca_atual
    tipo_chave = tipo_chave_atual
    hash_chave = hash_chave_atual

    if tipo_operacao == 'TRANSFERENCIA':
        if 'chave_pix' in dados or not id_conta_destino:
            tipo_chave = str(dados.get('tipo_chave') or '').strip().lower()
            coluna = COLUNAS_CHAVE_PIX.get(tipo_chave)
            chave = _normalizar_chave(tipo_chave, dados.get('chave_pix'))
            if not coluna or not chave or valor is None:
                raise ValueError('Informe uma chave Pix valida e um valor positivo')
            cursor.execute(f'SELECT ID_CONTA FROM CHAVE_PIX WHERE {coluna} = ?', (chave,))
            destinos = cursor.fetchall()
            if len(destinos) != 1:
                raise ValueError('Chave Pix nao encontrada ou com cadastro ambiguo')
            id_conta_destino = int(destinos[0][0])
            if id_conta_destino == int(id_conta):
                raise ValueError('Nao e possivel recorrencia para a mesma conta')
            hash_chave = _hash_chave(tipo_chave, chave)
        elif valor is None:
            raise ValueError('Informe um valor positivo para a recorrencia')
        return {
            'valor': valor,
            'id_conta_destino': int(id_conta_destino),
            'id_cobranca': None,
            'tipo_chave': tipo_chave,
            'hash_chave': hash_chave,
        }

    if 'id_cobranca' in dados or not id_cobranca:
        try:
            id_cobranca = int(dados.get('id_cobranca'))
        except (TypeError, ValueError) as erro:
            raise ValueError('Informe uma cobranca valida') from erro
    cursor.execute(
        '''SELECT ID_RECEBEDOR, VALOR, STATUS, TIPO_COBRANCA
           FROM COBRANCA WHERE ID_COBRANCA = ?''',
        (id_cobranca,),
    )
    cobranca = cursor.fetchone()
    if not cobranca:
        raise ValueError('Cobranca nao encontrada')
    id_recebedor, valor_cobranca, situacao, tipo_cobranca = cobranca
    tipo_esperado = 1 if tipo_operacao == 'PIX_COBRANCA' else 0
    if int(tipo_cobranca or 0) != tipo_esperado:
        raise ValueError('O tipo da cobranca nao corresponde a recorrencia')
    if int(situacao) != 0:
        raise ValueError('A cobranca nao esta pendente')
    if int(id_recebedor) == int(id_conta):
        raise ValueError('A conta recebedora nao pode pagar a propria cobranca')
    if valor_cobranca is None:
        if tipo_operacao != 'PIX_COBRANCA' or valor is None:
            raise ValueError('Informe um valor valido para esta cobranca')
    elif valor is not None and valor != valor_cobranca:
        raise ValueError('O valor desta cobranca e fixo e nao pode ser alterado')
    valor = valor_cobranca if valor_cobranca is not None else valor
    if valor is None or valor <= 0:
        raise ValueError('Informe um valor positivo para a recorrencia')
    return {
        'valor': valor,
        'id_conta_destino': None,
        'id_cobranca': int(id_cobranca),
        'tipo_chave': None,
        'hash_chave': None,
    }


def _registrar_aviso(cursor, id_recorrencia, numero, id_usuario, id_conta,
                      tipo_operacao, valor, estado, id_agendamento=None, motivo=None):
    categoria = 'BOLETO' if tipo_operacao == 'BOLETO' else 'PIX'
    rotulo = _rotulo_operacao(tipo_operacao)
    valor_formatado = f'R$ {Decimal(str(valor)):.2f}'.replace('.', ',')
    if estado == 'CRIADA':
        titulo = 'Recorrencia criada'
        mensagem = f'Os pagamentos recorrentes de {rotulo} de {valor_formatado} foram autorizados.'
    elif estado == 'CANCELADA':
        titulo = 'Recorrencia cancelada'
        mensagem = f'A recorrencia de {rotulo} de {valor_formatado} foi cancelada. Nao havera novas execucoes.'
    elif estado == 'PAUSADA_INDISPONIVEL':
        titulo = 'Recorrencia de boleto pausada'
        mensagem = motivo or MENSAGEM_BOLETO_REC
    elif estado == 'CONCLUIDO':
        titulo = 'Parcela recorrente executada'
        mensagem = f'A parcela {numero} de {rotulo} de {valor_formatado} foi executada.'
    else:
        titulo = 'Parcela recorrente recusada'
        mensagem = f'A parcela {numero} de {rotulo} de {valor_formatado} nao foi executada. {motivo or "Confira o historico."}'
    return registrar_notificacao_usuario(
        cursor,
        chave=f'recorrencia:{id_recorrencia}:{numero or 0}:{estado.lower()}',
        categoria=categoria,
        id_usuario=id_usuario,
        id_conta=id_conta,
        titulo=titulo,
        mensagem=mensagem[:500],
        dados={
            'id_recorrencia': int(id_recorrencia),
            'numero_execucao': int(numero or 0),
            'id_agendamento': int(id_agendamento) if id_agendamento else None,
            'tipo_operacao': tipo_operacao,
            'status': estado,
            'valor': str(valor),
            'motivo': motivo,
        },
        referencia_tipo='RECORRENCIA',
        referencia_id=id_recorrencia,
    )


def criar_recorrencia():
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    if dados.get('autorizacao_futura') is not True:
        return jsonify({'mensagem': 'Confirme a autorizacao das execucoes futuras'}), 400
    tipo_operacao = str(dados.get('tipo_operacao') or '').strip().upper()
    if tipo_operacao == 'BOLETO':
        return jsonify({'mensagem': MENSAGEM_BOLETO_REC}), 409
    if tipo_operacao not in ('TRANSFERENCIA', 'PIX_COBRANCA'):
        return jsonify({'mensagem': 'Tipo de operacao invalido'}), 400
    cursor = None
    try:
        data_inicio = _data_local(dados.get('data_inicio'))
        if data_inicio <= _agora_local():
            raise ValueError('A primeira execucao deve ser futura')
        frequencia = _frequencia(dados.get('frequencia'))
        data_final = _data_fim(dados.get('data_final'))
        limite_execucoes = _limite_execucoes(dados.get('limite_execucoes'))
        _validar_termo(data_inicio, data_final, limite_execucoes)
        cursor = con.cursor()
        alvo = _validar_destino(cursor, id_conta, tipo_operacao, dados)
        cursor.execute(
            '''INSERT INTO RECORRENCIA_FINANCEIRA
               (ID_USUARIO, ID_CONTA, TIPO_OPERACAO, ID_CONTA_DESTINO,
                ID_COBRANCA, TIPO_CHAVE, HASH_CHAVE, VALOR, FREQUENCIA,
                DATA_INICIAL, DATA_FINAL, LIMITE_EXECUCOES, EXECUCOES_CRIADAS,
                DIA_MES, PROXIMA_EXECUCAO, STATUS)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'ATIVA')
               RETURNING ID_RECORRENCIA''',
            (id_usuario, id_conta, tipo_operacao, alvo['id_conta_destino'],
             alvo['id_cobranca'], alvo['tipo_chave'], alvo['hash_chave'],
             alvo['valor'], frequencia, data_inicio, data_final,
             limite_execucoes, data_inicio.day if frequencia == 'MENSAL' else None,
             data_inicio),
        )
        id_recorrencia = int(cursor.fetchone()[0])
        evento = _registrar_aviso(
            cursor, id_recorrencia, 0, id_usuario, id_conta,
            tipo_operacao, alvo['valor'], 'CRIADA',
        )
        con.commit()
        tentar_publicar_eventos([evento])
        return jsonify({
            'id_recorrencia': id_recorrencia,
            'status': 'ATIVA',
            'proxima_execucao': data_inicio.isoformat(timespec='seconds'),
            'fuso': 'America/Sao_Paulo',
            'mensagem': 'Recorrencia autorizada. Nenhum valor foi movimentado agora.',
        }), 201
    except ValueError as validacao:
        con.rollback()
        return jsonify({'mensagem': str(validacao)}), 400
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao criar recorrencia para a conta %s', id_conta)
        return jsonify({'mensagem': 'Nao foi possivel criar a recorrencia'}), 500
    finally:
        if cursor:
            cursor.close()


def listar_recorrencias():
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT R.ID_RECORRENCIA, R.TIPO_OPERACAO, R.VALOR,
                      R.FREQUENCIA, R.DATA_INICIAL, R.DATA_FINAL,
                      R.LIMITE_EXECUCOES, R.EXECUCOES_CRIADAS,
                      R.PROXIMA_EXECUCAO, R.STATUS, R.CRIADO_EM,
                      COALESCE(D.NOME_FANTASIA, D.RAZAO_SOCIAL, UD.NOME,
                               CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, UR.NOME),
                      CB.CODIGO_PAGAMENTO
               FROM RECORRENCIA_FINANCEIRA R
               LEFT JOIN CONTA D ON D.ID_CONTA = R.ID_CONTA_DESTINO
               LEFT JOIN USUARIO UD ON UD.ID_USUARIO = D.ID_USUARIO
               LEFT JOIN COBRANCA CB ON CB.ID_COBRANCA = R.ID_COBRANCA
               LEFT JOIN CONTA CR ON CR.ID_CONTA = CB.ID_RECEBEDOR
               LEFT JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
               WHERE R.ID_USUARIO = ? AND R.ID_CONTA = ?
               ORDER BY R.CRIADO_EM DESC, R.ID_RECORRENCIA DESC''',
            (id_usuario, id_conta),
        )
        regras = cursor.fetchall()
        recorrencias = []
        for regra in regras:
            id_recorrencia = int(regra[0])
            cursor.execute(
                '''SELECT E.NUMERO_EXECUCAO, E.DATA_PREVISTA, E.STATUS,
                          E.MOTIVO_FALHA, E.ID_AGENDAMENTO, S.VALOR,
                          S.STATUS, S.MOTIVO_FALHA
                   FROM RECORRENCIA_EXECUCAO E
                   INNER JOIN AGENDAMENTO_FINANCEIRO S ON S.ID_AGENDAMENTO = E.ID_AGENDAMENTO
                   WHERE E.ID_RECORRENCIA = ?
                   ORDER BY E.NUMERO_EXECUCAO DESC''',
                (id_recorrencia,),
            )
            execucoes = []
            for item in cursor.fetchall():
                estado = item[6] or item[2]
                execucoes.append({
                    'numero': int(item[0]),
                    'data_prevista': _serializar_data(item[1]),
                    'status': estado,
                    'motivo_falha': item[7] or item[3],
                    'id_agendamento': int(item[4]),
                    'valor': float(item[5]),
                })
            recorrencias.append({
                'id_recorrencia': id_recorrencia,
                'tipo_operacao': regra[1],
                'valor': float(regra[2]),
                'frequencia': regra[3],
                'data_inicial': _serializar_data(regra[4]),
                'data_final': regra[5].isoformat() if regra[5] else None,
                'limite_execucoes': int(regra[6]) if regra[6] is not None else None,
                'execucoes_criadas': int(regra[7] or 0),
                'proxima_execucao': _serializar_data(regra[8]),
                'status': regra[9],
                'criado_em': _serializar_data(regra[10]),
                'destinatario': regra[11] or (f'Cobrança {regra[12]}' if regra[12] else 'Destinatário'),
                'codigo_pagamento': regra[12],
                'execucoes': execucoes,
            })
        return jsonify({'fuso': 'America/Sao_Paulo', 'recorrencias': recorrencias}), 200
    except Exception:
        current_app.logger.exception('Falha ao listar recorrencias da conta %s', id_conta)
        return jsonify({'mensagem': 'Nao foi possivel consultar as recorrencias'}), 500
    finally:
        if cursor:
            cursor.close()


def atualizar_recorrencia(id_recorrencia):
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    if dados.get('confirmado') is not True:
        return jsonify({'mensagem': 'Confirme que as alteracoes valem somente para execucoes futuras'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT TIPO_OPERACAO, ID_CONTA_DESTINO, ID_COBRANCA,
                      TIPO_CHAVE, HASH_CHAVE, VALOR, FREQUENCIA,
                      DATA_INICIAL, DATA_FINAL, LIMITE_EXECUCOES,
                      EXECUCOES_CRIADAS, DIA_MES, PROXIMA_EXECUCAO, STATUS
               FROM RECORRENCIA_FINANCEIRA
               WHERE ID_RECORRENCIA = ? AND ID_USUARIO = ? AND ID_CONTA = ? WITH LOCK''',
            (id_recorrencia, id_usuario, id_conta),
        )
        atual = cursor.fetchone()
        if not atual:
            con.rollback()
            return jsonify({'mensagem': 'Recorrencia nao encontrada'}), 404
        if atual[0] == 'BOLETO':
            con.rollback()
            return jsonify({'mensagem': MENSAGEM_BOLETO_REC}), 409
        if atual[13] not in ('ATIVA', 'PAUSADA'):
            con.rollback()
            return jsonify({'mensagem': 'Somente recorrencias ativas ou pausadas podem ser alteradas'}), 409
        if dados.get('proxima_execucao'):
            data_inicio = _data_local(dados.get('proxima_execucao'))
        elif atual[12]:
            data_inicio = atual[12]
        else:
            raise ValueError('Informe uma proxima execucao futura')
        if data_inicio <= _agora_local():
            raise ValueError('A proxima execucao deve ser futura')
        frequencia = _frequencia(dados.get('frequencia', atual[6]))
        data_final = _data_fim(dados.get('data_final')) if 'data_final' in dados else atual[8]
        limite_execucoes = _limite_execucoes(dados.get('limite_execucoes')) if 'limite_execucoes' in dados else atual[9]
        if limite_execucoes is not None and limite_execucoes < int(atual[10] or 0) + 1:
            raise ValueError('A quantidade total precisa incluir ao menos uma execucao futura')
        _validar_termo(data_inicio, data_final, limite_execucoes)
        tipo_operacao = str(dados.get('tipo_operacao') or atual[0]).strip().upper()
        if tipo_operacao != atual[0]:
            raise ValueError('O tipo da operacao nao pode ser alterado; cancele a regra e crie outra')
        alvo = _validar_destino(
            cursor, id_conta, tipo_operacao, dados,
            valor_atual=atual[5], destino_atual=atual[1], cobranca_atual=atual[2],
            tipo_chave_atual=atual[3], hash_chave_atual=atual[4],
        )
        cursor.execute(
            '''UPDATE RECORRENCIA_FINANCEIRA
               SET ID_CONTA_DESTINO = ?, ID_COBRANCA = ?, TIPO_CHAVE = ?,
                   HASH_CHAVE = ?, VALOR = ?, FREQUENCIA = ?, DATA_INICIAL = ?,
                   DATA_FINAL = ?, LIMITE_EXECUCOES = ?, DIA_MES = ?,
                   PROXIMA_EXECUCAO = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE ID_RECORRENCIA = ? AND ID_USUARIO = ? AND ID_CONTA = ?''',
            (alvo['id_conta_destino'], alvo['id_cobranca'], alvo['tipo_chave'],
             alvo['hash_chave'], alvo['valor'], frequencia, data_inicio,
             data_final, limite_execucoes,
             data_inicio.day if frequencia == 'MENSAL' else None,
             data_inicio, id_recorrencia, id_usuario, id_conta),
        )
        con.commit()
        return jsonify({'mensagem': 'Alteracoes aplicadas somente as proximas execucoes', 'status': atual[13]}), 200
    except ValueError as validacao:
        con.rollback()
        return jsonify({'mensagem': str(validacao)}), 400
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao alterar recorrencia %s', id_recorrencia)
        return jsonify({'mensagem': 'Nao foi possivel alterar a recorrencia'}), 500
    finally:
        if cursor:
            cursor.close()


def _alterar_status(id_recorrencia, novo_status):
    id_usuario, id_conta, erro = _sessao_atual()
    if erro:
        return erro
    cursor = None
    eventos = []
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT TIPO_OPERACAO, VALOR, FREQUENCIA, PROXIMA_EXECUCAO,
                      LIMITE_EXECUCOES, EXECUCOES_CRIADAS, STATUS
               FROM RECORRENCIA_FINANCEIRA
               WHERE ID_RECORRENCIA = ? AND ID_USUARIO = ? AND ID_CONTA = ? WITH LOCK''',
            (id_recorrencia, id_usuario, id_conta),
        )
        regra = cursor.fetchone()
        if not regra:
            con.rollback()
            return jsonify({'mensagem': 'Recorrencia nao encontrada'}), 404
        status_atual = regra[6]
        if novo_status == 'ATIVA' and regra[0] == 'BOLETO':
            con.rollback()
            return jsonify({'mensagem': MENSAGEM_BOLETO_REC}), 409
        if novo_status == 'PAUSADA':
            if status_atual != 'ATIVA':
                con.rollback()
                return jsonify({'mensagem': 'Somente recorrencias ativas podem ser pausadas'}), 409
            cursor.execute(
                '''UPDATE RECORRENCIA_FINANCEIRA SET STATUS = 'PAUSADA',
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_RECORRENCIA = ? AND STATUS = 'ATIVA' ''',
                (id_recorrencia,),
            )
        elif novo_status == 'ATIVA':
            if status_atual != 'PAUSADA' or regra[3] is None:
                con.rollback()
                return jsonify({'mensagem': 'Esta recorrencia nao possui execucoes futuras para reativar'}), 409
            cursor.execute(
                '''UPDATE RECORRENCIA_FINANCEIRA SET STATUS = 'ATIVA',
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_RECORRENCIA = ? AND STATUS = 'PAUSADA' ''',
                (id_recorrencia,),
            )
        elif novo_status == 'CANCELADA':
            if status_atual not in ('ATIVA', 'PAUSADA'):
                con.rollback()
                return jsonify({'mensagem': 'Esta recorrencia nao pode mais ser cancelada'}), 409
            cursor.execute(
                '''UPDATE RECORRENCIA_FINANCEIRA SET STATUS = 'CANCELADA',
                   PROXIMA_EXECUCAO = NULL, CANCELADO_EM = CURRENT_TIMESTAMP,
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_RECORRENCIA = ?''',
                (id_recorrencia,),
            )
            cursor.execute(
                '''UPDATE AGENDAMENTO_FINANCEIRO S
                   SET STATUS = 'CANCELADO', CANCELADO_EM = CURRENT_TIMESTAMP,
                       MOTIVO_FALHA = 'Recorrencia cancelada pelo cliente',
                       TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL,
                       ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE S.STATUS = 'AGENDADO'
                     AND EXISTS (SELECT 1 FROM RECORRENCIA_EXECUCAO E
                                 WHERE E.ID_AGENDAMENTO = S.ID_AGENDAMENTO
                                   AND E.ID_RECORRENCIA = ?)''',
                (id_recorrencia,),
            )
            cursor.execute(
                '''UPDATE RECORRENCIA_EXECUCAO E SET STATUS = 'CANCELADO',
                   MOTIVO_FALHA = 'Recorrencia cancelada pelo cliente',
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE E.ID_RECORRENCIA = ? AND E.STATUS IN ('AGENDADO', 'EXECUTANDO')
                     AND EXISTS (SELECT 1 FROM AGENDAMENTO_FINANCEIRO S
                                 WHERE S.ID_AGENDAMENTO = E.ID_AGENDAMENTO
                                   AND S.STATUS = 'CANCELADO')''',
                (id_recorrencia,),
            )
            eventos.append(_registrar_aviso(
                cursor, id_recorrencia, 0, id_usuario, id_conta,
                regra[0], regra[1], 'CANCELADA',
            ))
        con.commit()
        if eventos:
            tentar_publicar_eventos(eventos)
        return jsonify({'mensagem': 'Recorrencia atualizada', 'status': novo_status}), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao alterar status da recorrencia %s', id_recorrencia)
        return jsonify({'mensagem': 'Nao foi possivel atualizar a recorrencia'}), 500
    finally:
        if cursor:
            cursor.close()


def pausar_recorrencia(id_recorrencia):
    return _alterar_status(id_recorrencia, 'PAUSADA')


def reativar_recorrencia(id_recorrencia):
    return _alterar_status(id_recorrencia, 'ATIVA')


def cancelar_recorrencia(id_recorrencia):
    return _alterar_status(id_recorrencia, 'CANCELADA')


def _pausar_boleto_indisponivel(cursor, id_recorrencia, id_usuario, id_conta,
                                  valor, motivo=None):
    motivo = motivo or MENSAGEM_BOLETO_REC
    cursor.execute(
        '''UPDATE RECORRENCIA_FINANCEIRA SET STATUS = 'PAUSADA',
           ATUALIZADO_EM = CURRENT_TIMESTAMP
           WHERE ID_RECORRENCIA = ? AND STATUS = 'ATIVA' ''',
        (id_recorrencia,),
    )
    return _registrar_aviso(
        cursor, id_recorrencia, 0, id_usuario, id_conta,
        'BOLETO', valor, 'PAUSADA_INDISPONIVEL', motivo=motivo,
    )


def processar_recorrencias_pendentes(limite=20):
    """Cria no maximo uma parcela vencida por regra e avanca de forma atomica."""
    agora = _agora_local()
    limite = max(1, min(int(limite), 100))
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT FIRST ? ID_RECORRENCIA FROM RECORRENCIA_FINANCEIRA
               WHERE STATUS = 'ATIVA'
                 AND (TIPO_OPERACAO = 'BOLETO' OR
                      (PROXIMA_EXECUCAO IS NOT NULL AND PROXIMA_EXECUCAO <= ?))
               ORDER BY PROXIMA_EXECUCAO, ID_RECORRENCIA''',
            (limite, agora),
        )
        candidatos = [int(row[0]) for row in cursor.fetchall()]
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao localizar recorrencias vencidas')
        return 0
    finally:
        if cursor:
            cursor.close()

    materializadas = 0
    for id_recorrencia in candidatos:
        cursor = None
        try:
            cursor = con.cursor()
            cursor.execute(
                '''SELECT ID_USUARIO, ID_CONTA, TIPO_OPERACAO, ID_CONTA_DESTINO,
                          ID_COBRANCA, TIPO_CHAVE, HASH_CHAVE, VALOR, FREQUENCIA,
                          DATA_FINAL, LIMITE_EXECUCOES, EXECUCOES_CRIADAS,
                          DIA_MES, PROXIMA_EXECUCAO, STATUS
                   FROM RECORRENCIA_FINANCEIRA
                   WHERE ID_RECORRENCIA = ? WITH LOCK''',
                (id_recorrencia,),
            )
            regra = cursor.fetchone()
            if not regra or regra[14] != 'ATIVA':
                con.rollback()
                continue
            (id_usuario, id_conta, tipo_operacao, id_destino, id_cobranca,
             tipo_chave, hash_chave, valor, frequencia, data_final,
             limite_execucoes, criadas, dia_mes, prevista, _status) = regra
            if tipo_operacao == 'BOLETO':
                evento = _pausar_boleto_indisponivel(
                    cursor, id_recorrencia, id_usuario, id_conta, valor,
                )
                con.commit()
                tentar_publicar_eventos([evento])
                current_app.logger.warning(
                    'Recorrencia de boleto %s pausada; cada parcela exige nova cobranca',
                    id_recorrencia,
                )
                continue
            if not prevista or prevista > agora:
                con.rollback()
                continue
            numero = int(criadas or 0) + 1
            cursor.execute(
                '''INSERT INTO AGENDAMENTO_FINANCEIRO
                   (ID_USUARIO, ID_CONTA, TIPO_OPERACAO, ID_CONTA_DESTINO,
                    ID_COBRANCA, TIPO_CHAVE, HASH_CHAVE, VALOR, DATA_AGENDADA,
                    STATUS, TENTATIVAS)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AGENDADO', 0)
                   RETURNING ID_AGENDAMENTO''',
                (id_usuario, id_conta, tipo_operacao, id_destino, id_cobranca,
                 tipo_chave, hash_chave, valor, prevista),
            )
            id_agendamento = int(cursor.fetchone()[0])
            cursor.execute(
                '''INSERT INTO RECORRENCIA_EXECUCAO
                   (ID_RECORRENCIA, NUMERO_EXECUCAO, ID_AGENDAMENTO,
                    DATA_PREVISTA, STATUS)
                   VALUES (?, ?, ?, ?, 'AGENDADO')''',
                (id_recorrencia, numero, id_agendamento, prevista),
            )
            proxima = None
            if limite_execucoes is None or numero < int(limite_execucoes):
                proxima = proxima_data(prevista, frequencia, dia_mes)
                while proxima <= agora:
                    proxima = proxima_data(proxima, frequencia, dia_mes)
                if data_final and proxima.date() > data_final:
                    proxima = None
            cursor.execute(
                '''UPDATE RECORRENCIA_FINANCEIRA
                   SET EXECUCOES_CRIADAS = ?, PROXIMA_EXECUCAO = ?,
                       ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_RECORRENCIA = ?''',
                (numero, proxima, id_recorrencia),
            )
            con.commit()
            materializadas += 1
        except Exception:
            con.rollback()
            current_app.logger.exception('Falha ao materializar parcela da recorrencia %s', id_recorrencia)
        finally:
            if cursor:
                cursor.close()
    return materializadas


def sincronizar_resultado_recorrencia(cursor, id_agendamento, status, motivo=None,
                                       notificar=True):
    """Sincroniza status da parcela na mesma transacao do agendamento."""
    cursor.execute(
        '''SELECT E.ID_RECORRENCIA, E.NUMERO_EXECUCAO, R.ID_USUARIO,
                  R.ID_CONTA, R.TIPO_OPERACAO, R.VALOR
           FROM RECORRENCIA_EXECUCAO E
           INNER JOIN RECORRENCIA_FINANCEIRA R ON R.ID_RECORRENCIA = E.ID_RECORRENCIA
           WHERE E.ID_AGENDAMENTO = ?''',
        (id_agendamento,),
    )
    linha = cursor.fetchone()
    if not linha:
        return []
    cursor.execute(
        '''UPDATE RECORRENCIA_EXECUCAO SET STATUS = ?, MOTIVO_FALHA = ?,
           ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
        (status, str(motivo)[:500] if motivo else None, id_agendamento),
    )
    eventos = []
    if notificar and status in ('CONCLUIDO', 'FALHOU'):
        eventos.append(_registrar_aviso(
            cursor, linha[0], linha[1], linha[2], linha[3], linha[4], linha[5],
            status, id_agendamento=id_agendamento, motivo=motivo,
        ))
    cursor.execute(
        '''SELECT STATUS, PROXIMA_EXECUCAO FROM RECORRENCIA_FINANCEIRA
           WHERE ID_RECORRENCIA = ?''',
        (linha[0],),
    )
    regra = cursor.fetchone()
    if regra and regra[0] == 'ATIVA' and regra[1] is None:
        cursor.execute(
            '''SELECT COUNT(*) FROM RECORRENCIA_EXECUCAO
               WHERE ID_RECORRENCIA = ? AND STATUS NOT IN ('CONCLUIDO', 'FALHOU', 'CANCELADO')''',
            (linha[0],),
        )
        pendentes = int(cursor.fetchone()[0] or 0)
        if pendentes == 0:
            cursor.execute(
                '''UPDATE RECORRENCIA_FINANCEIRA SET STATUS = 'FINALIZADA',
                   ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE ID_RECORRENCIA = ? AND STATUS = 'ATIVA' AND PROXIMA_EXECUCAO IS NULL''',
                (linha[0],),
            )
    return eventos


def autorizar_execucao_recorrente(cursor, id_agendamento, token):
    """Trava a regra antes da parcela para serializar execucao, pausa e cancelamento."""
    cursor.execute(
        'SELECT ID_RECORRENCIA FROM RECORRENCIA_EXECUCAO WHERE ID_AGENDAMENTO = ?',
        (id_agendamento,),
    )
    link = cursor.fetchone()
    if not link:
        return True
    id_recorrencia = int(link[0])
    cursor.execute(
        '''SELECT STATUS, TIPO_OPERACAO, ID_USUARIO, ID_CONTA, VALOR
           FROM RECORRENCIA_FINANCEIRA WHERE ID_RECORRENCIA = ? WITH LOCK''',
        (id_recorrencia,),
    )
    regra = cursor.fetchone()
    if regra and regra[1] == 'BOLETO':
        cursor.execute(
            '''SELECT STATUS, TOKEN_EXECUCAO FROM AGENDAMENTO_FINANCEIRO
               WHERE ID_AGENDAMENTO = ? WITH LOCK''',
            (id_agendamento,),
        )
        agendamento = cursor.fetchone()
        if not agendamento or agendamento[0] != 'EXECUTANDO' or agendamento[1] != token:
            con.rollback()
            return False
        motivo = MENSAGEM_BOLETO_REC
        cursor.execute(
            '''UPDATE AGENDAMENTO_FINANCEIRO SET STATUS = 'CANCELADO',
               CANCELADO_EM = CURRENT_TIMESTAMP, MOTIVO_FALHA = ?,
               TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL, TENTAR_APOS = NULL,
               ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
            (motivo, id_agendamento),
        )
        sincronizar_resultado_recorrencia(
            cursor, id_agendamento, 'CANCELADO', motivo, notificar=False,
        )
        evento = _pausar_boleto_indisponivel(
            cursor, id_recorrencia, int(regra[2]), int(regra[3]), regra[4], motivo,
        )
        con.commit()
        tentar_publicar_eventos([evento])
        current_app.logger.warning(
            'Agendamento recorrente de boleto %s cancelado por exigir nova cobranca',
            id_agendamento,
        )
        return False
    if regra and regra[0] == 'ATIVA':
        cursor.execute(
            '''UPDATE RECORRENCIA_EXECUCAO SET STATUS = 'EXECUTANDO',
               ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ? AND STATUS = 'AGENDADO' ''',
            (id_agendamento,),
        )
        return True
    cursor.execute(
        '''SELECT STATUS, TOKEN_EXECUCAO FROM AGENDAMENTO_FINANCEIRO
           WHERE ID_AGENDAMENTO = ? WITH LOCK''',
        (id_agendamento,),
    )
    agendamento = cursor.fetchone()
    if agendamento and agendamento[0] == 'EXECUTANDO' and agendamento[1] == token:
        motivo = 'Recorrencia pausada ou cancelada antes da execucao'
        cursor.execute(
            '''UPDATE AGENDAMENTO_FINANCEIRO SET STATUS = 'CANCELADO',
               CANCELADO_EM = CURRENT_TIMESTAMP, MOTIVO_FALHA = ?,
               TOKEN_EXECUCAO = NULL, LEASE_ATE = NULL, TENTAR_APOS = NULL,
               ATUALIZADO_EM = CURRENT_TIMESTAMP WHERE ID_AGENDAMENTO = ?''',
            (motivo, id_agendamento),
        )
        sincronizar_resultado_recorrencia(
            cursor, id_agendamento, 'CANCELADO', motivo, notificar=False,
        )
        con.commit()
    else:
        con.rollback()
    return False


def status_recorrencia_para_agendamento(cursor, id_agendamento):
    """Obtém e trava a regra antes de um update do resultado da parcela."""
    cursor.execute(
        'SELECT ID_RECORRENCIA FROM RECORRENCIA_EXECUCAO WHERE ID_AGENDAMENTO = ?',
        (id_agendamento,),
    )
    link = cursor.fetchone()
    if not link:
        return None
    cursor.execute(
        'SELECT STATUS FROM RECORRENCIA_FINANCEIRA WHERE ID_RECORRENCIA = ? WITH LOCK',
        (int(link[0]),),
    )
    regra = cursor.fetchone()
    return regra[0] if regra else 'CANCELADA'


def registrar_rotas(app):
    app.add_url_rule('/api/v1/recorrencias', 'listar_recorrencias', listar_recorrencias, methods=['GET'])
    app.add_url_rule('/api/v1/recorrencias', 'criar_recorrencia', criar_recorrencia, methods=['POST'])
    app.add_url_rule('/api/v1/recorrencias/<int:id_recorrencia>', 'atualizar_recorrencia', atualizar_recorrencia, methods=['PUT'])
    app.add_url_rule('/api/v1/recorrencias/<int:id_recorrencia>/pausar', 'pausar_recorrencia', pausar_recorrencia, methods=['PATCH'])
    app.add_url_rule('/api/v1/recorrencias/<int:id_recorrencia>/reativar', 'reativar_recorrencia', reativar_recorrencia, methods=['PATCH'])
    app.add_url_rule('/api/v1/recorrencias/<int:id_recorrencia>/cancelar', 'cancelar_recorrencia', cancelar_recorrencia, methods=['PATCH'])
