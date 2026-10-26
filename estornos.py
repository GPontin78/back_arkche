"""Cancelamentos de cobrancas pendentes e devolucoes financeiras integrais."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath

import fdb
from fdb.services import connect as conectar_servicos
from flask import current_app, jsonify, request

from banco import con
from funcao import data_atual, descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta
from limites import aplicar_limite, usuario_eh_admin_bancario
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos


MOTIVO_MINIMO = 5
_CHAVE_IDEMPOTENCIA = re.compile(r'^[A-Za-z0-9._:-]{8,100}$')


class ErroEstorno(Exception):
    def __init__(self, mensagem, status=400, codigo=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.codigo = codigo


def _dados_corpo():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        raise ErroEstorno('Envie um objeto JSON', 400)
    if dados.get('confirmacao') is not True:
        raise ErroEstorno('Confirme explicitamente esta operação antes de continuar', 400, 'CONFIRMACAO_OBRIGATORIA')
    motivo = str(dados.get('motivo') or '').strip()
    if len(motivo) < MOTIVO_MINIMO:
        raise ErroEstorno('Informe um motivo com pelo menos 5 caracteres', 400, 'MOTIVO_OBRIGATORIO')
    motivo = motivo[:500]
    chave = str(dados.get('chave_idempotencia') or '').strip()
    if not _CHAVE_IDEMPOTENCIA.fullmatch(chave):
        raise ErroEstorno('Chave de idempotência inválida', 400, 'IDEMPOTENCIA_INVALIDA')
    return motivo, chave


def _autenticacao():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()
    if not id_usuario:
        raise ErroEstorno('Autenticação necessária', 401, 'AUTENTICACAO_NECESSARIA')
    return int(id_usuario), int(id_conta) if id_conta else None


def _serializar_data(valor):
    return valor.isoformat(sep=' ') if hasattr(valor, 'isoformat') else (str(valor) if valor else None)


def _tem_estrutura_estornos(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = 'ESTORNO_FINANCEIRO'"
    )
    linha = cursor.fetchone()
    return bool(linha and int(linha[0] or 0) >= 14)


def _arquivo_backup_banco(caminho_banco):
    caminho = PurePosixPath(str(caminho_banco).strip())
    if not caminho.name:
        raise ValueError('O Firebird não retornou o caminho do banco para o backup')
    horario = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return str(caminho.with_name(f'{caminho.stem}.antes-estornos-{horario}.fbk'))


def _executar_migracao_estornos(cursor):
    arquivo = Path(__file__).resolve().parent / 'migrations' / '006_estornos_cancelamentos.sql'
    if not arquivo.is_file():
        raise FileNotFoundError('Migração 006 não está disponível no container')
    conteudo = re.sub(r'/\*.*?\*/', '', arquivo.read_text(encoding='utf-8'), flags=re.DOTALL)
    conteudo = re.sub(r'--[^\r\n]*', '', conteudo)
    for comando in conteudo.split(';'):
        comando = comando.strip()
        if not comando or comando.upper().startswith(('SET BAIL', 'COMMIT')):
            continue
        cursor.execute(comando)


def status_migracao_estornos():
    id_usuario = descobre_id_usuario()
    if not id_usuario:
        return jsonify({'mensagem': 'Autenticação necessária'}), 401
    if not usuario_eh_admin_bancario(id_usuario):
        return jsonify({'mensagem': 'Acesso exclusivo ao administrador bancário'}), 403
    cursor = None
    try:
        cursor = con.cursor()
        instalada = _tem_estrutura_estornos(cursor)
        return jsonify({'instalada': instalada}), 200
    except Exception:
        current_app.logger.exception('Falha ao verificar estrutura de estornos')
        return jsonify({'mensagem': 'Não foi possível verificar a estrutura de estornos'}), 500
    finally:
        if cursor:
            cursor.close()


def instalar_migracao_estornos():
    id_usuario = descobre_id_usuario()
    if not id_usuario:
        return jsonify({'mensagem': 'Autenticação necessária'}), 401
    if not usuario_eh_admin_bancario(id_usuario):
        return jsonify({'mensagem': 'Acesso exclusivo ao administrador bancário'}), 403
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or dados.get('confirmacao') is not True:
        return jsonify({'mensagem': 'Confirme a criação do backup e a aplicação da migração'}), 400

    cursor = None
    servicos = None
    arquivo_backup = None
    try:
        cursor = con.cursor()
        if _tem_estrutura_estornos(cursor):
            con.rollback()
            return jsonify({'mensagem': 'A estrutura já está instalada', 'instalada': True}), 409
        cursor.execute('SELECT MON$DATABASE_NAME FROM MON$DATABASE')
        linha = cursor.fetchone()
        if not linha or not linha[0]:
            raise RuntimeError('Não foi possível identificar o arquivo Firebird para backup')
        caminho_banco = str(linha[0]).strip()
        arquivo_backup = _arquivo_backup_banco(caminho_banco)
        con.rollback()

        host = str(current_app.config['DB_HOST']).strip()
        porta = int(current_app.config.get('DB_PORT') or 3050)
        host_servicos = f'{host}/{porta}' if '/' not in host else host
        servicos = conectar_servicos(
            host=host_servicos,
            user=current_app.config['DB_USER'],
            password=current_app.config['DB_PASSWORD'],
        )
        saida_backup = []
        servicos.backup(caminho_banco, arquivo_backup, callback=saida_backup.append)
        erros_backup = [linha for linha in saida_backup if 'error' in linha.lower() or 'failed' in linha.lower()]
        if erros_backup:
            raise RuntimeError('O Firebird não confirmou a conclusão do backup')

        cursor = con.cursor()
        _executar_migracao_estornos(cursor)
        con.commit()
        if not _tem_estrutura_estornos(cursor):
            con.rollback()
            raise RuntimeError('A migração terminou sem criar a estrutura esperada')
        con.commit()
        current_app.logger.info('Migração 006 de estornos aplicada pelo administrador %s; backup=%s', id_usuario, PurePosixPath(arquivo_backup).name)
        return jsonify({
            'mensagem': 'Backup concluído e estrutura de estornos instalada',
            'instalada': True,
            'arquivo_backup': PurePosixPath(arquivo_backup).name,
        }), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao criar backup ou aplicar migração de estornos')
        corpo = {'mensagem': 'Não foi possível instalar estornos; a migração não foi confirmada'}
        if arquivo_backup:
            corpo['arquivo_backup'] = PurePosixPath(arquivo_backup).name
        return jsonify(corpo), 500
    finally:
        if servicos:
            servicos.close()
        if cursor:
            cursor.close()


def _conta_acessivel(id_usuario, id_conta):
    return bool(id_conta and usuario_pode_acessar_conta(id_usuario, id_conta))


def _buscar_cobranca(cursor, id_cobranca, lock=False):
    sql = '''SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR,
                    DATA_VENCIMENTO, STATUS, TIPO_COBRANCA, CODIGO_PAGAMENTO
             FROM COBRANCA WHERE ID_COBRANCA = ?'''
    if lock:
        sql += ' WITH LOCK'
    cursor.execute(sql, (id_cobranca,))
    return cursor.fetchone()


def cancelar_cobranca(id_cobranca):
    id_usuario, id_conta = _autenticacao()
    if not id_conta:
        return jsonify({'mensagem': 'Selecione a conta emissora da cobrança'}), 401
    try:
        motivo, chave = _dados_corpo()
    except ErroEstorno as erro:
        return jsonify({'mensagem': erro.mensagem, 'codigo': erro.codigo}), erro.status

    cursor = None
    eventos = []
    try:
        cursor = con.cursor()
        cobranca = _buscar_cobranca(cursor, int(id_cobranca))
        if not cobranca:
            return jsonify({'mensagem': 'Cobrança não encontrada'}), 404
        id_pagador, id_recebedor, valor, status = cobranca[1], int(cobranca[2]), cobranca[3], int(cobranca[5])
        if id_conta != id_recebedor or not _conta_acessivel(id_usuario, id_recebedor):
            return jsonify({'mensagem': 'Somente o emissor autenticado pode cancelar esta cobrança'}), 403

        cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_recebedor,))
        if not cursor.fetchone():
            raise ErroEstorno('Conta emissora indisponível', 404)
        cobranca = _buscar_cobranca(cursor, int(id_cobranca), lock=True)
        cursor.execute('SELECT ID_ESTORNO, STATUS, ID_COBRANCA, ID_USUARIO_RESPONSAVEL FROM ESTORNO_FINANCEIRO WHERE CHAVE_IDEMPOTENCIA = ?', (chave,))
        anterior = cursor.fetchone()
        if anterior:
            con.rollback()
            if int(anterior[2] or -1) != int(id_cobranca) or int(anterior[3]) != id_usuario:
                return jsonify({'mensagem': 'Chave de idempotência já utilizada em outra solicitação'}), 409
            return jsonify({'mensagem': 'Esta solicitação já foi processada', 'id_estorno': anterior[0], 'status': anterior[1]}), 200
        if not cobranca or int(cobranca[5]) != 0:
            con.rollback()
            return jsonify({'mensagem': 'A cobrança já foi paga, cancelada ou não está mais pendente'}), 409

        cursor.execute('UPDATE COBRANCA SET STATUS = 2 WHERE ID_COBRANCA = ? AND STATUS = 0 RETURNING ID_COBRANCA', (int(id_cobranca),))
        if not cursor.fetchone():
            raise ErroEstorno('A cobrança deixou de estar pendente', 409, 'COBRANCA_INDISPONIVEL')
        valor_registro = Decimal(str(cobranca[3] or 0))
        cursor.execute(
            '''INSERT INTO ESTORNO_FINANCEIRO
               (TIPO_OPERACAO, ID_COBRANCA, ID_CONTA_SOLICITANTE,
                ID_USUARIO_RESPONSAVEL, ID_CONTA_PAGADOR, ID_CONTA_RECEBEDOR,
                VALOR, STATUS, MOTIVO, CHAVE_IDEMPOTENCIA)
               VALUES ('CANCELAMENTO_COBRANCA', ?, ?, ?, ?, ?, ?, 'CANCELADO', ?, ?)
               RETURNING ID_ESTORNO''',
            (int(id_cobranca), id_conta, id_usuario, id_pagador, id_recebedor,
             valor_registro, motivo, chave),
        )
        id_estorno = int(cursor.fetchone()[0])
        contas_notificar = [id_recebedor] + ([int(id_pagador)] if id_pagador else [])
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'estorno:{id_estorno}:cobranca-cancelada',
            categoria='BOLETO', id_contas=contas_notificar,
            referencia_tipo='ESTORNO_FINANCEIRO', referencia_id=id_estorno,
            valor=valor if valor and valor > 0 else None,
            titulo='Cobrança cancelada', mensagem=f'A cobrança #{int(id_cobranca)} foi cancelada pelo emissor.',
            dados_adicionais={'id_cobranca': int(id_cobranca), 'motivo': motivo, 'status': 'CANCELADO'},
        )
        con.commit()
        tentar_publicar_eventos(eventos)
        return jsonify({'mensagem': 'Cobrança cancelada', 'id_cobranca': int(id_cobranca), 'id_estorno': id_estorno, 'status': 'CANCELADO'}), 200
    except ErroEstorno as erro:
        con.rollback()
        corpo = {'mensagem': erro.mensagem}
        if erro.codigo:
            corpo['codigo'] = erro.codigo
        return jsonify(corpo), erro.status
    except fdb.TransactionConflict:
        con.rollback()
        return jsonify({'mensagem': 'A cobrança está sendo atualizada em outra operação; consulte novamente'}), 409
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao cancelar cobrança %s', id_cobranca)
        return jsonify({'mensagem': 'Não foi possível cancelar a cobrança'}), 500
    finally:
        if cursor:
            cursor.close()


def _buscar_movimentacao(cursor, id_movimentacao):
    cursor.execute(
        '''SELECT M.ID_MOVIMENTACAO, M.ID_PAGADOR, M.ID_RECEBEDOR, M.VALOR,
                  M.DATA_MOVIMENTACAO, M.ID_COBRANCA, COB.TIPO_COBRANCA,
                  FI.ID_MOVIMENTACAO,
                  CASE WHEN EXISTS (
                      SELECT 1 FROM COMPRA CMP INNER JOIN CARTAO CAT ON CAT.ID_CARTAO = CMP.ID_CARTAO
                      WHERE CMP.DATA_COMPRA = M.DATA_MOVIMENTACAO
                        AND ((CMP.TIPO = 0 AND CAT.ID_CONTA = M.ID_PAGADOR
                              AND CMP.VALOR_COMPRA = M.VALOR)
                             OR (CMP.TIPO = 1
                                 AND ROUND(CMP.VALOR_COMPRA * 0.95, 2) = M.VALOR))
                  ) THEN 1 ELSE 0 END,
                  COB.STATUS, COB.ID_PAGADOR, COB.ID_RECEBEDOR, COB.VALOR
           FROM MOVIMENTACAO M
           LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
           LEFT JOIN FOLHA_ITEM FI ON FI.ID_MOVIMENTACAO = M.ID_MOVIMENTACAO
           WHERE M.ID_MOVIMENTACAO = ?''',
        (int(id_movimentacao),),
    )
    return cursor.fetchone()


def _saldo_disponivel(cursor, id_conta):
    if int(id_conta) == 9:  # Mantém a conta técnica com a semântica atual.
        return None
    cursor.execute('SELECT CAST(COALESCE(SUM(VALOR), 0) AS DECIMAL(18,2)) FROM MOVIMENTACAO WHERE ID_RECEBEDOR = ?', (id_conta,))
    creditos = Decimal(str(cursor.fetchone()[0] or 0))
    cursor.execute('SELECT CAST(COALESCE(SUM(VALOR), 0) AS DECIMAL(18,2)) FROM MOVIMENTACAO WHERE ID_PAGADOR = ?', (id_conta,))
    debitos = Decimal(str(cursor.fetchone()[0] or 0))
    return creditos - debitos


def _buscar_idempotencia(cursor, chave):
    cursor.execute(
        '''SELECT ID_ESTORNO, STATUS, ID_MOVIMENTACAO_REVERSA,
                  ID_MOVIMENTACAO_ORIGINAL, ID_USUARIO_RESPONSAVEL
           FROM ESTORNO_FINANCEIRO WHERE CHAVE_IDEMPOTENCIA = ?''',
        (chave,),
    )
    return cursor.fetchone()


def _registrar_recusa(cursor, *, tipo, id_mov, id_cobranca, id_usuario,
                      id_conta_solicitante, id_pagador, id_recebedor,
                      valor, motivo, chave):
    cursor.execute(
        '''INSERT INTO ESTORNO_FINANCEIRO
           (TIPO_OPERACAO, ID_COBRANCA, ID_MOVIMENTACAO_ORIGINAL,
            ID_CONTA_SOLICITANTE, ID_USUARIO_RESPONSAVEL, ID_CONTA_PAGADOR,
            ID_CONTA_RECEBEDOR, VALOR, STATUS, MOTIVO, CHAVE_IDEMPOTENCIA)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RECUSADO', ?, ?) RETURNING ID_ESTORNO''',
        (tipo, id_cobranca, id_mov, id_conta_solicitante, id_usuario,
         id_pagador, id_recebedor, valor, motivo[:500], chave),
    )
    return int(cursor.fetchone()[0])


def devolver_movimentacao(id_movimentacao, estorno_boleto=False):
    id_usuario, id_conta_sessao = _autenticacao()
    admin = usuario_eh_admin_bancario(id_usuario)
    try:
        motivo, chave = _dados_corpo()
    except ErroEstorno as erro:
        return jsonify({'mensagem': erro.mensagem, 'codigo': erro.codigo}), erro.status

    cursor = None
    eventos = []
    try:
        cursor = con.cursor()
        movimento = _buscar_movimentacao(cursor, id_movimentacao)
        if not movimento:
            return jsonify({'mensagem': 'Movimentação não encontrada'}), 404
        id_mov, id_pagador, id_recebedor = int(movimento[0]), int(movimento[1]), int(movimento[2])
        valor = Decimal(str(movimento[3]))
        id_cobranca = int(movimento[5]) if movimento[5] is not None else None
        tipo_cobranca = int(movimento[6]) if movimento[6] is not None else None
        origem_folha, origem_cartao = movimento[7] is not None, int(movimento[8] or 0) == 1
        status_cobranca = int(movimento[9]) if movimento[9] is not None else None
        cobranca_pagador = int(movimento[10]) if movimento[10] is not None else None
        cobranca_recebedor = int(movimento[11]) if movimento[11] is not None else None
        cobranca_valor = Decimal(str(movimento[12])) if movimento[12] is not None else None
        eh_boleto = id_cobranca is not None and tipo_cobranca == 0
        eh_pix_qr = id_cobranca is not None and tipo_cobranca == 1
        tipo_estorno = 'ESTORNO_BOLETO' if estorno_boleto else 'DEVOLUCAO_PIX_TRANSFERENCIA'

        if origem_folha or origem_cartao:
            return jsonify({'mensagem': 'Esta operação pertence a cartão ou folha de pagamento e não é suportada nesta etapa'}), 409
        if estorno_boleto:
            if not admin:
                return jsonify({'mensagem': 'Estorno de boleto concluído é exclusivo do administrador bancário'}), 403
            if not eh_boleto:
                return jsonify({'mensagem': 'Esta movimentação não é um pagamento de boleto'}), 400
            if (status_cobranca != 1 or cobranca_pagador != id_pagador
                    or cobranca_recebedor != id_recebedor or cobranca_valor != valor):
                return jsonify({'mensagem': 'A cobrança não está vinculada de forma consistente a este pagamento'}), 409
        else:
            if eh_boleto:
                return jsonify({'mensagem': 'Pagamento de boleto concluído exige estorno administrativo'}), 403
            if not admin and (id_conta_sessao != id_recebedor or not _conta_acessivel(id_usuario, id_recebedor)):
                return jsonify({'mensagem': 'Somente o recebedor autorizado pode devolver este Pix ou transferência'}), 403
            if not (eh_pix_qr or id_cobranca is None):
                return jsonify({'mensagem': 'Tipo de operação não suportado para devolução'}), 400

        if admin and not id_conta_sessao:
            id_conta_solicitante = id_recebedor
        else:
            id_conta_solicitante = id_conta_sessao
        contas = sorted({id_pagador, id_recebedor})
        for id_conta in contas:
            cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_conta,))
            if not cursor.fetchone():
                raise ErroEstorno('Uma das contas da operação não está disponível', 404)

        # Lock the source row after account locks. Account locks serialize refunds
        # against concurrent debits, including other API routes using the same order.
        cursor.execute('SELECT ID_MOVIMENTACAO FROM MOVIMENTACAO WHERE ID_MOVIMENTACAO = ? WITH LOCK', (id_mov,))
        if not cursor.fetchone():
            raise ErroEstorno('Movimentação não encontrada', 404)
        existente = _buscar_idempotencia(cursor, chave)
        if existente:
            con.rollback()
            if int(existente[4]) != id_usuario or int(existente[3] or -1) != id_mov:
                return jsonify({'mensagem': 'Chave de idempotência já utilizada em outra solicitação'}), 409
            return jsonify({'mensagem': 'Esta solicitação já foi processada', 'id_estorno': existente[0], 'id_movimentacao': existente[2], 'status': existente[1]}), 200

        cursor.execute(
            '''SELECT FIRST 1 ID_ESTORNO FROM ESTORNO_FINANCEIRO
               WHERE ID_MOVIMENTACAO_ORIGINAL = ? AND STATUS = 'CONCLUIDO' ''',
            (id_mov,),
        )
        if cursor.fetchone():
            id_estorno = _registrar_recusa(
                cursor, tipo=tipo_estorno, id_mov=id_mov, id_cobranca=id_cobranca,
                id_usuario=id_usuario, id_conta_solicitante=id_conta_solicitante,
                id_pagador=id_pagador, id_recebedor=id_recebedor, valor=valor,
                motivo='Devolução integral já concluída para esta movimentação.', chave=chave,
            )
            con.commit()
            return jsonify({'mensagem': 'Esta movimentação já foi devolvida integralmente', 'id_estorno': id_estorno, 'status': 'RECUSADO'}), 409

        saldo = _saldo_disponivel(cursor, id_recebedor)
        if saldo is not None and saldo < valor:
            id_estorno = _registrar_recusa(
                cursor, tipo=tipo_estorno, id_mov=id_mov, id_cobranca=id_cobranca,
                id_usuario=id_usuario, id_conta_solicitante=id_conta_solicitante,
                id_pagador=id_pagador, id_recebedor=id_recebedor, valor=valor,
                motivo='Saldo disponível insuficiente na conta recebedora para devolver o valor integral.', chave=chave,
            )
            con.commit()
            return jsonify({'mensagem': 'Saldo insuficiente na conta recebedora para a devolução integral', 'id_estorno': id_estorno, 'status': 'RECUSADO'}), 409

        # A devolução é uma saída financeira e também observa a política de limite
        # vigente para a conta de origem da devolução.
        restricao = aplicar_limite(cursor, id_recebedor, 'PAGAMENTO' if estorno_boleto else 'TRANSFERENCIA', valor, id_usuario=id_usuario)
        if restricao:
            resposta, status = restricao
            dados_erro = resposta.get_json(silent=True) or {}
            id_estorno = _registrar_recusa(
                cursor, tipo=tipo_estorno, id_mov=id_mov, id_cobranca=id_cobranca,
                id_usuario=id_usuario, id_conta_solicitante=id_conta_solicitante,
                id_pagador=id_pagador, id_recebedor=id_recebedor, valor=valor,
                motivo=dados_erro.get('mensagem', 'Operação recusada pelos limites configurados.'), chave=chave,
            )
            con.commit()
            return jsonify({'mensagem': dados_erro.get('mensagem', 'Operação recusada pelos limites configurados'), 'id_estorno': id_estorno, 'status': 'RECUSADO'}), status

        cursor.execute(
            '''INSERT INTO MOVIMENTACAO
               (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA)
               VALUES (?, ?, ?, ?, ?) RETURNING ID_MOVIMENTACAO''',
            (id_recebedor, id_pagador, valor, data_atual(), id_cobranca if (eh_boleto or eh_pix_qr) else None),
        )
        id_reversa = int(cursor.fetchone()[0])
        cursor.execute(
            '''INSERT INTO ESTORNO_FINANCEIRO
               (TIPO_OPERACAO, ID_COBRANCA, ID_MOVIMENTACAO_ORIGINAL,
                ID_MOVIMENTACAO_REVERSA, ID_CONTA_SOLICITANTE,
                ID_USUARIO_RESPONSAVEL, ID_CONTA_PAGADOR, ID_CONTA_RECEBEDOR,
                VALOR, STATUS, MOTIVO, CHAVE_IDEMPOTENCIA)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONCLUIDO', ?, ?)
               RETURNING ID_ESTORNO''',
            (tipo_estorno, id_cobranca, id_mov, id_reversa, id_conta_solicitante,
             id_usuario, id_pagador, id_recebedor, valor, motivo, chave),
        )
        id_estorno = int(cursor.fetchone()[0])
        categoria = 'BOLETO' if estorno_boleto else ('PIX' if eh_pix_qr or id_cobranca is None else 'TRANSFERENCIA')
        titulo = 'Estorno de boleto concluído' if estorno_boleto else 'Devolução concluída'
        mensagem = f'O valor de R$ {valor:.2f} foi devolvido integralmente. Referência #{id_estorno}.'
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'estorno:{id_estorno}:concluido', categoria=categoria,
            id_contas=[id_pagador, id_recebedor], referencia_tipo='ESTORNO_FINANCEIRO',
            referencia_id=id_estorno, valor=valor, id_pagador=id_recebedor,
            titulo=titulo, mensagem=mensagem,
            dados_adicionais={'id_movimentacao_original': id_mov, 'id_movimentacao_devolucao': id_reversa,
                              'id_cobranca': id_cobranca, 'motivo': motivo, 'status': 'CONCLUIDO'},
        )
        con.commit()
        tentar_publicar_eventos(eventos)
        return jsonify({'mensagem': titulo, 'id_estorno': id_estorno, 'id_movimentacao_original': id_mov,
                        'id_movimentacao': id_reversa, 'valor': float(valor), 'status': 'CONCLUIDO'}), 201
    except ErroEstorno as erro:
        con.rollback()
        corpo = {'mensagem': erro.mensagem}
        if erro.codigo:
            corpo['codigo'] = erro.codigo
        return jsonify(corpo), erro.status
    except fdb.TransactionConflict:
        con.rollback()
        return jsonify({'mensagem': 'Operação concorrente. Consulte o extrato antes de tentar novamente'}), 409
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao processar devolução/estorno da movimentação %s', id_movimentacao)
        return jsonify({'mensagem': 'Não foi possível processar a devolução'}), 500
    finally:
        if cursor:
            cursor.close()


def historico_estornos_conta():
    """Mostra apenas cancelamentos e devolucoes relacionados a conta ativa.

    Nao devolve dados de outras contas nem o identificador pessoal de quem
    executou a operacao. Historico global permanece exclusivo do admin.
    """
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()
    if not id_usuario or not id_conta:
        return jsonify({'mensagem': 'Entre na conta para consultar suas devoluções'}), 401
    if not _conta_acessivel(id_usuario, id_conta):
        return jsonify({'mensagem': 'Acesso não autorizado a esta conta'}), 403
    cursor = None
    try:
        cursor = con.cursor()
        if not _tem_estrutura_estornos(cursor):
            return jsonify({'instalada': False, 'historico': []}), 200
        cursor.execute(
            """SELECT FIRST 100 E.ID_ESTORNO, E.TIPO_OPERACAO, E.ID_COBRANCA,
                      E.ID_MOVIMENTACAO_ORIGINAL, E.ID_MOVIMENTACAO_REVERSA,
                      E.ID_CONTA_PAGADOR, E.ID_CONTA_RECEBEDOR, E.VALOR,
                      E.STATUS, E.MOTIVO, E.CRIADO_EM
                 FROM ESTORNO_FINANCEIRO E
                WHERE E.ID_CONTA_PAGADOR = ? OR E.ID_CONTA_RECEBEDOR = ?
                ORDER BY E.CRIADO_EM DESC, E.ID_ESTORNO DESC""",
            (int(id_conta), int(id_conta)),
        )
        registros = cursor.fetchall()
        historico = [{
            'id_estorno': r[0], 'tipo_operacao': r[1],
            'id_cobranca': r[2], 'id_movimentacao_original': r[3],
            'id_movimentacao_reversa': r[4],
            'valor': float(r[7]), 'status': r[8], 'motivo': r[9],
            'criado_em': _serializar_data(r[10]),
            'participacao': 'recebedor_original' if int(r[6]) == int(id_conta) else 'pagador_original',
        } for r in registros]
        return jsonify({'instalada': True, 'historico': historico}), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar devoluções da conta ativa')
        return jsonify({'mensagem': 'Não foi possível consultar as devoluções desta conta'}), 500
    finally:
        if cursor:
            cursor.close()


def historico_admin_estornos():
    id_usuario = descobre_id_usuario()
    if not id_usuario:
        return jsonify({'mensagem': 'Autenticação necessária'}), 401
    if not usuario_eh_admin_bancario(id_usuario):
        return jsonify({'mensagem': 'Acesso exclusivo ao administrador bancário'}), 403
    try:
        limite = max(1, min(int(request.args.get('limite', '100')), 200))
    except ValueError:
        return jsonify({'mensagem': 'Limite inválido'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''SELECT FIRST {limite} E.ID_ESTORNO, E.TIPO_OPERACAO, E.ID_COBRANCA,
                       E.ID_MOVIMENTACAO_ORIGINAL, E.ID_MOVIMENTACAO_REVERSA,
                       E.ID_CONTA_SOLICITANTE, E.ID_USUARIO_RESPONSAVEL,
                       E.ID_CONTA_PAGADOR, E.ID_CONTA_RECEBEDOR, E.VALOR,
                       E.STATUS, E.MOTIVO, E.CRIADO_EM
                FROM ESTORNO_FINANCEIRO E ORDER BY E.CRIADO_EM DESC, E.ID_ESTORNO DESC'''
        )
        historico = [{
            'id_estorno': r[0], 'tipo_operacao': r[1], 'id_cobranca': r[2],
            'id_movimentacao_original': r[3], 'id_movimentacao_reversa': r[4],
            'id_conta_solicitante': r[5], 'id_usuario_responsavel': r[6],
            'id_conta_pagador': r[7], 'id_conta_recebedor': r[8],
            'valor': float(r[9]), 'status': r[10], 'motivo': r[11],
            'criado_em': _serializar_data(r[12]),
        } for r in cursor.fetchall()]
        return jsonify({'historico': historico}), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar histórico administrativo de estornos')
        return jsonify({'mensagem': 'Não foi possível consultar o histórico de estornos'}), 500
    finally:
        if cursor:
            cursor.close()


def registrar_rotas(app):
    app.add_url_rule('/api/v1/cobrancas/<int:id_cobranca>/cancelar', 'cancelar_cobranca_financeira', cancelar_cobranca, methods=['POST'])
    app.add_url_rule('/api/v1/movimentacoes/<int:id_movimentacao>/devolver', 'devolver_movimentacao', devolver_movimentacao, methods=['POST'])
    app.add_url_rule('/api/v1/movimentacoes/<int:id_movimentacao>/estornar', 'estornar_boleto', lambda id_movimentacao: devolver_movimentacao(id_movimentacao, True), methods=['POST'])
    app.add_url_rule('/api/v1/estornos/minha-conta', 'historico_estornos_conta', historico_estornos_conta, methods=['GET'])
    app.add_url_rule('/api/v1/estornos/admin', 'historico_admin_estornos', historico_admin_estornos, methods=['GET'])
    app.add_url_rule('/api/v1/estornos/admin/migracao', 'status_migracao_estornos', status_migracao_estornos, methods=['GET'])
    app.add_url_rule('/api/v1/estornos/admin/migracao', 'instalar_migracao_estornos', instalar_migracao_estornos, methods=['POST'])
