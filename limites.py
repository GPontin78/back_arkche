"""Politicas diurnas/noturnas, verificacao transacional e auditoria de limites."""
import datetime
import json
import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import fdb
from flask import jsonify, request

from banco import con
from funcao import data_atual, dados_conta, dados_usuario
from main import app
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos


OPERACOES = ('TRANSFERENCIA', 'PAGAMENTO')
PERIODOS = ('DIURNO', 'NOTURNO')
TIPOS_CONTA = ('PF', 'PJ')


def _periodo_agora(agora=None):
    agora = agora or data_atual()
    dia = agora.date()
    hora = agora.hour
    if 6 <= hora < 22:
        return 'DIURNO', datetime.datetime.combine(dia, datetime.time(6)), datetime.datetime.combine(dia, datetime.time(22))
    if hora >= 22:
        return 'NOTURNO', datetime.datetime.combine(dia, datetime.time(22)), datetime.datetime.combine(dia + datetime.timedelta(days=1), datetime.time(6))
    return 'NOTURNO', datetime.datetime.combine(dia - datetime.timedelta(days=1), datetime.time(22)), datetime.datetime.combine(dia, datetime.time(6))


def _tipo_conta(cursor, id_conta):
    cursor.execute('SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?', (int(id_conta),))
    registro = cursor.fetchone()
    if not registro:
        return None
    return 'PJ' if int(registro[0]) == 1 else 'PF'


def _valor_decimal(valor):
    try:
        resultado = Decimal(str(valor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return resultado if resultado.is_finite() and resultado > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _uso_no_periodo(cursor, id_conta, inicio, fim):
    cursor.execute(
        '''SELECT COALESCE(SUM(M.VALOR), 0)
           FROM MOVIMENTACAO M
           WHERE M.ID_PAGADOR = ? AND M.DATA_MOVIMENTACAO >= ? AND M.DATA_MOVIMENTACAO < ?''',
        (int(id_conta), inicio, fim),
    )
    movimentacoes = Decimal(str(cursor.fetchone()[0] or 0))
    # Compras no credito nao debitam a conta na hora da venda, mas consomem
    # o limite operacional de pagamentos. Compras no debito ja estao em MOVIMENTACAO.
    cursor.execute(
        '''SELECT COALESCE(SUM(C.VALOR_COMPRA), 0)
           FROM COMPRA C
           INNER JOIN CARTAO CA ON CA.ID_CARTAO = C.ID_CARTAO
           WHERE CA.ID_CONTA = ? AND C.TIPO = 1
             AND C.DATA_COMPRA >= ? AND C.DATA_COMPRA < ?''',
        (int(id_conta), inicio, fim),
    )
    compras_credito = Decimal(str(cursor.fetchone()[0] or 0))
    return movimentacoes + compras_credito


def _politica_atual(cursor, tipo_conta, operacao, periodo):
    cursor.execute(
        '''SELECT ATIVO, LIMITE_POR_OPERACAO
           FROM POLITICA_LIMITE_OPERACAO
           WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
        (tipo_conta, operacao, periodo),
    )
    operacao_row = cursor.fetchone()
    cursor.execute(
        '''SELECT ATIVO, LIMITE_ACUMULADO
           FROM POLITICA_LIMITE_PERIODO
           WHERE TIPO_CONTA = ? AND PERIODO = ?''',
        (tipo_conta, periodo),
    )
    periodo_row = cursor.fetchone()
    return {
        'limite_por_operacao': Decimal(str(operacao_row[1])) if operacao_row and int(operacao_row[0]) == 1 and operacao_row[1] is not None else None,
        'limite_acumulado': Decimal(str(periodo_row[1])) if periodo_row and int(periodo_row[0]) == 1 and periodo_row[1] is not None else None,
    }


def _registrar_recusa(id_conta, id_usuario, tipo_conta, operacao, periodo,
                      solicitado, usado, politica, motivo):
    conexao = None
    cursor = None
    eventos = []
    persistido = False
    try:
        conexao = fdb.connect(
            host=app.config['DB_HOST'], port=app.config['DB_PORT'],
            database=app.config['DB_NAME'], user=app.config['DB_USER'],
            password=app.config['DB_PASSWORD'],
        )
        cursor = conexao.cursor()
        if id_usuario is None:
            cursor.execute('SELECT ID_USUARIO FROM CONTA WHERE ID_CONTA = ?', (id_conta,))
            titular = cursor.fetchone()
            id_usuario = int(titular[0]) if titular else None
        cursor.execute(
            '''INSERT INTO AUDITORIA_LIMITE
               (EVENTO, ID_USUARIO, ID_CONTA, TIPO_CONTA, OPERACAO, PERIODO,
                VALOR_SOLICITADO, VALOR_ACUMULADO, LIMITE_POR_OPERACAO,
                LIMITE_ACUMULADO, MOTIVO, DETALHES_JSON)
               VALUES ('OPERACAO_RECUSADA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (id_usuario, id_conta, tipo_conta, operacao, periodo, solicitado,
             usado, politica['limite_por_operacao'], politica['limite_acumulado'],
             motivo[:250], json.dumps({'canal': request.path, 'limite_por_operacao': str(politica['limite_por_operacao']) if politica['limite_por_operacao'] is not None else None,
                                      'limite_acumulado': str(politica['limite_acumulado']) if politica['limite_acumulado'] is not None else None}, ensure_ascii=False)),
        )
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'limite-recusa:{uuid.uuid4().hex}',
            categoria='INFORMATIVO', id_contas=[id_conta],
            referencia_tipo='LIMITE', referencia_id=None,
            titulo='Operação acima do limite',
            mensagem=motivo[:500],
            dados_adicionais={'operacao': operacao, 'periodo': periodo,
                              'valor_solicitado': str(solicitado), 'valor_utilizado': str(usado)},
        )
        conexao.commit()
        persistido = True
    except Exception:
        if conexao:
            try:
                conexao.rollback()
            except Exception:
                pass
        app.logger.exception('Falha ao registrar recusa por limite da conta %s', id_conta)
    finally:
        if cursor:
            cursor.close()
        if conexao:
            conexao.close()
    if persistido and eventos:
        tentar_publicar_eventos(eventos)
    return persistido


def aplicar_limite(cursor, id_conta, operacao, valor_total, *, valor_por_operacao=None, id_usuario=None):
    """Valida e bloqueia a conta durante a transacao financeira atual.

    A soma vem das movimentacoes ja confirmadas no Firebird. O registro de
    controle por conta serializa pagamentos concorrentes ate o commit/rollback
    da operacao financeira, sem usar Redis como fonte de verdade.
    Retorna None se permitido; em recusa retorna a resposta Flask 403.
    """
    operacao = str(operacao or '').upper()
    if operacao not in OPERACOES:
        raise ValueError('Operacao de limite invalida')
    total = _valor_decimal(valor_total)
    individual = _valor_decimal(valor_por_operacao if valor_por_operacao is not None else valor_total)
    if total is None or individual is None:
        return jsonify({'mensagem': 'Informe um valor positivo para verificar o limite', 'codigo': 'VALOR_INVALIDO'}), 400

    agora = data_atual()
    periodo, inicio, fim = _periodo_agora(agora)
    tipo_conta = _tipo_conta(cursor, id_conta)
    if not tipo_conta:
        return jsonify({'mensagem': 'Conta nao encontrada para aplicar os limites', 'codigo': 'CONTA_NAO_ENCONTRADA'}), 404
    politica = _politica_atual(cursor, tipo_conta, operacao, periodo)
    if politica['limite_por_operacao'] is None and politica['limite_acumulado'] is None:
        return None

    cursor.execute(
        'UPDATE CONTROLE_LIMITE_CONTA SET VERSAO = VERSAO + 1 WHERE ID_CONTA = ? RETURNING ID_CONTA',
        (int(id_conta),),
    )
    if not cursor.fetchone():
        raise RuntimeError('Registro de concorrencia dos limites ausente para a conta')

    usado = _uso_no_periodo(cursor, id_conta, inicio, fim)
    motivo = None
    if politica['limite_por_operacao'] is not None and individual > politica['limite_por_operacao']:
        motivo = f'O valor de R$ {individual:.2f} excede o limite de R$ {politica["limite_por_operacao"]:.2f} por operacao {operacao.lower()} neste periodo.'
    elif politica['limite_acumulado'] is not None and usado + total > politica['limite_acumulado']:
        disponivel = max(Decimal('0.00'), politica['limite_acumulado'] - usado)
        motivo = f'O limite acumulado do periodo {periodo.lower()} e R$ {politica["limite_acumulado"]:.2f}; ja foram utilizados R$ {usado:.2f} e restam R$ {disponivel:.2f}.'

    if motivo:
        con.rollback()
        if not _registrar_recusa(id_conta, id_usuario, tipo_conta, operacao, periodo,
                                 total, usado, politica, motivo):
            return jsonify({
                'mensagem': 'Operacao recusada pelo limite, mas o registro de auditoria ficou indisponivel; tente novamente mais tarde.',
                'codigo': 'AUDITORIA_INDISPONIVEL',
            }), 503
        return jsonify({
            'mensagem': motivo,
            'codigo': 'LIMITE_ATINGIDO',
            'operacao': operacao,
            'periodo': periodo,
            'limite_por_operacao': float(politica['limite_por_operacao']) if politica['limite_por_operacao'] is not None else None,
            'limite_acumulado': float(politica['limite_acumulado']) if politica['limite_acumulado'] is not None else None,
            'utilizado': float(usado),
        }), 403
    return None


def _resumo_conta(cursor, id_conta, tipo_conta):
    agora = data_atual()
    periodo, inicio, fim = _periodo_agora(agora)
    usado = _uso_no_periodo(cursor, id_conta, inicio, fim)
    cursor.execute(
        '''SELECT ATIVO, LIMITE_ACUMULADO FROM POLITICA_LIMITE_PERIODO
           WHERE TIPO_CONTA = ? AND PERIODO = ?''', (tipo_conta, periodo)
    )
    acumulado = cursor.fetchone()
    limite_acumulado = Decimal(str(acumulado[1])) if acumulado and int(acumulado[0]) == 1 and acumulado[1] is not None else None
    restante = max(Decimal('0.00'), limite_acumulado - usado) if limite_acumulado is not None else None
    cursor.execute(
        '''SELECT OPERACAO, ATIVO, LIMITE_POR_OPERACAO FROM POLITICA_LIMITE_OPERACAO
           WHERE TIPO_CONTA = ? AND PERIODO = ? ORDER BY OPERACAO''', (tipo_conta, periodo)
    )
    operacoes = []
    for operacao, ativo, maximo in cursor.fetchall():
        maximo = Decimal(str(maximo)) if int(ativo) == 1 and maximo is not None else None
        capacidade = min(maximo, restante) if maximo is not None and restante is not None else (maximo if maximo is not None else restante)
        operacoes.append({
            'operacao': operacao,
            'limite_por_operacao': float(maximo) if maximo is not None else None,
            'disponivel_agora': float(capacidade) if capacidade is not None else None,
            'configurado': maximo is not None or limite_acumulado is not None,
        })
    return {
        'periodo': periodo,
        'fuso': 'America/Sao_Paulo',
        'inicio': inicio.isoformat(timespec='minutes'),
        'fim': fim.isoformat(timespec='minutes'),
        'utilizado': float(usado),
        'limite_acumulado': float(limite_acumulado) if limite_acumulado is not None else None,
        'disponivel_periodo': float(restante) if restante is not None else None,
        'operacoes': operacoes,
    }


def _ids_administradores():
    ids = set()
    for valor in os.getenv('ARKHE_LIMITES_ADMIN_IDS', '').split(','):
        valor = valor.strip()
        if valor.isdigit() and int(valor) > 0:
            ids.add(int(valor))
    return ids


def _usuario_atual():
    usuario = dados_usuario()
    return usuario if usuario and usuario.get('id_usuario') else None


def _exigir_admin():
    usuario = _usuario_atual()
    if not usuario:
        return None, (jsonify({'mensagem': 'Autenticacao necessaria'}), 401)
    id_usuario = int(usuario['id_usuario'])
    if id_usuario not in _ids_administradores():
        return None, (jsonify({'mensagem': 'Acesso exclusivo ao administrador bancario'}), 403)
    return id_usuario, None


def _decimal_config(valor, campo, obrigatorio):
    if valor is None or valor == '':
        if obrigatorio:
            raise ValueError(f'Informe {campo}')
        return None
    resultado = _valor_decimal(valor)
    if resultado is None or resultado > Decimal('9999999999999.99'):
        raise ValueError(f'{campo} deve ser um valor positivo valido')
    return resultado


@app.route('/api/v1/limites', methods=['GET'])
def consultar_limites_conta():
    usuario = _usuario_atual()
    conta = dados_conta()
    if not usuario or not conta:
        return jsonify({'mensagem': 'Sessao invalida ou conta nao selecionada'}), 401
    cursor = None
    try:
        cursor = con.cursor()
        tipo_conta = 'PJ' if int(conta['tipo_conta']) == 1 else 'PF'
        return jsonify({
            'tipo_conta': tipo_conta,
            'administrador': int(usuario['id_usuario']) in _ids_administradores(),
            'limites': [_resumo_conta(cursor, int(conta['id_conta']), tipo_conta)],
        }), 200
    except Exception:
        app.logger.exception('Falha ao consultar limites da conta')
        return jsonify({'mensagem': 'Nao foi possivel consultar os limites'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/limites/admin/politicas', methods=['GET'])
def listar_politicas_limites():
    id_admin, erro = _exigir_admin()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT TIPO_CONTA, OPERACAO, PERIODO, ATIVO, LIMITE_POR_OPERACAO, ATUALIZADO_EM
               FROM POLITICA_LIMITE_OPERACAO ORDER BY TIPO_CONTA, PERIODO, OPERACAO'''
        )
        operacoes = [
            {'tipo_conta': r[0], 'operacao': r[1], 'periodo': r[2], 'ativo': bool(r[3]),
             'limite_por_operacao': float(r[4]) if r[4] is not None else None,
             'atualizado_em': r[5].isoformat() if r[5] else None}
            for r in cursor.fetchall()
        ]
        cursor.execute(
            '''SELECT TIPO_CONTA, PERIODO, ATIVO, LIMITE_ACUMULADO, ATUALIZADO_EM
               FROM POLITICA_LIMITE_PERIODO ORDER BY TIPO_CONTA, PERIODO'''
        )
        periodos = [
            {'tipo_conta': r[0], 'periodo': r[1], 'ativo': bool(r[2]),
             'limite_acumulado': float(r[3]) if r[3] is not None else None,
             'atualizado_em': r[4].isoformat() if r[4] else None}
            for r in cursor.fetchall()
        ]
        return jsonify({'operacoes': operacoes, 'periodos': periodos}), 200
    except Exception:
        app.logger.exception('Falha ao consultar politicas de limites')
        return jsonify({'mensagem': 'Nao foi possivel consultar as politicas'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/limites/admin/politicas', methods=['PUT'])
def atualizar_politicas_limites():
    id_admin, erro = _exigir_admin()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie as politicas de limite em JSON'}), 400
    tipo_conta = str(dados.get('tipo_conta') or '').upper()
    periodo = str(dados.get('periodo') or '').upper()
    motivo_alteracao = str(dados.get('motivo') or '').strip()
    politicas = dados.get('operacoes')
    if tipo_conta not in TIPOS_CONTA or periodo not in PERIODOS or not isinstance(politicas, dict):
        return jsonify({'mensagem': 'Tipo de conta, periodo ou operacoes invalidos'}), 400
    if not 5 <= len(motivo_alteracao) <= 250:
        return jsonify({'mensagem': 'Informe o motivo da alteracao (5 a 250 caracteres)'}), 400
    try:
        operacoes_normalizadas = {}
        for operacao in OPERACOES:
            regra = politicas.get(operacao)
            if not isinstance(regra, dict) or type(regra.get('ativo')) is not bool:
                raise ValueError(f'Configure {operacao} com ativo verdadeiro ou falso')
            operacoes_normalizadas[operacao] = {
                'ativo': regra['ativo'],
                'limite_por_operacao': _decimal_config(regra.get('limite_por_operacao'), f'limite de {operacao}', regra['ativo']),
            }
        acumulado_ativo = type(dados.get('acumulado_ativo')) is bool and dados['acumulado_ativo']
        if 'acumulado_ativo' not in dados or type(dados.get('acumulado_ativo')) is not bool:
            raise ValueError('Configure acumulado_ativo como verdadeiro ou falso')
        limite_acumulado = _decimal_config(dados.get('limite_acumulado'), 'limite acumulado', acumulado_ativo)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT ATIVO, LIMITE_POR_OPERACAO FROM POLITICA_LIMITE_OPERACAO
               WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
            (tipo_conta, OPERACOES[0], periodo),
        )
        anteriores = {'operacoes': {}, 'acumulado': None}
        for operacao in OPERACOES:
            cursor.execute(
                '''SELECT ATIVO, LIMITE_POR_OPERACAO FROM POLITICA_LIMITE_OPERACAO
                   WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
                (tipo_conta, operacao, periodo),
            )
            row = cursor.fetchone()
            anteriores['operacoes'][operacao] = {'ativo': bool(row[0]), 'limite_por_operacao': str(row[1]) if row[1] is not None else None}
        cursor.execute(
            '''SELECT ATIVO, LIMITE_ACUMULADO FROM POLITICA_LIMITE_PERIODO
               WHERE TIPO_CONTA = ? AND PERIODO = ?''', (tipo_conta, periodo)
        )
        row = cursor.fetchone()
        anteriores['acumulado'] = {'ativo': bool(row[0]), 'limite_acumulado': str(row[1]) if row[1] is not None else None}

        for operacao, regra in operacoes_normalizadas.items():
            cursor.execute(
                '''UPDATE POLITICA_LIMITE_OPERACAO
                   SET ATIVO = ?, LIMITE_POR_OPERACAO = ?, ATUALIZADO_POR = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
                (int(regra['ativo']), regra['limite_por_operacao'], id_admin, tipo_conta, operacao, periodo),
            )
        cursor.execute(
            '''UPDATE POLITICA_LIMITE_PERIODO
               SET ATIVO = ?, LIMITE_ACUMULADO = ?, ATUALIZADO_POR = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE TIPO_CONTA = ? AND PERIODO = ?''',
            (int(acumulado_ativo), limite_acumulado, id_admin, tipo_conta, periodo),
        )
        novas = {
            'operacoes': {k: {'ativo': v['ativo'], 'limite_por_operacao': str(v['limite_por_operacao']) if v['limite_por_operacao'] is not None else None} for k, v in operacoes_normalizadas.items()},
            'acumulado': {'ativo': acumulado_ativo, 'limite_acumulado': str(limite_acumulado) if limite_acumulado is not None else None},
        }
        cursor.execute(
            '''INSERT INTO AUDITORIA_LIMITE
               (EVENTO, ID_ADMINISTRADOR, TIPO_CONTA, PERIODO, MOTIVO, DETALHES_JSON)
               VALUES ('POLITICA_ATUALIZADA', ?, ?, ?, ?, ?)''',
            (id_admin, tipo_conta, periodo, motivo_alteracao,
             json.dumps({'antes': anteriores, 'depois': novas}, ensure_ascii=False)),
        )
        con.commit()
        return jsonify({'mensagem': 'Politicas atualizadas', 'tipo_conta': tipo_conta,
                        'periodo': periodo, 'operacoes': novas['operacoes'],
                        'acumulado': novas['acumulado']}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Falha ao atualizar politicas de limites')
        return jsonify({'mensagem': 'Nao foi possivel salvar as politicas'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/limites/admin/historico', methods=['GET'])
def historico_politicas_limites():
    _id_admin, erro = _exigir_admin()
    if erro:
        return erro
    try:
        limite = max(1, min(int(request.args.get('limite', '50')), 100))
    except ValueError:
        return jsonify({'mensagem': 'Limite de historico invalido'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            f'''SELECT FIRST {limite} ID_AUDITORIA, EVENTO, ID_ADMINISTRADOR, ID_USUARIO,
                       ID_CONTA, TIPO_CONTA, OPERACAO, PERIODO, VALOR_SOLICITADO,
                       VALOR_ACUMULADO, LIMITE_POR_OPERACAO, LIMITE_ACUMULADO,
                       MOTIVO, DETALHES_JSON, CRIADO_EM
                FROM AUDITORIA_LIMITE ORDER BY ID_AUDITORIA DESC'''
        )
        historico = [{
            'id': r[0], 'evento': r[1], 'id_administrador': r[2], 'id_usuario': r[3],
            'id_conta': r[4], 'tipo_conta': r[5], 'operacao': r[6], 'periodo': r[7],
            'valor_solicitado': float(r[8]) if r[8] is not None else None,
            'valor_acumulado': float(r[9]) if r[9] is not None else None,
            'limite_por_operacao': float(r[10]) if r[10] is not None else None,
            'limite_acumulado': float(r[11]) if r[11] is not None else None,
            'motivo': r[12], 'detalhes': r[13], 'criado_em': r[14].isoformat() if r[14] else None,
        } for r in cursor.fetchall()]
        return jsonify({'historico': historico}), 200
    except Exception:
        app.logger.exception('Falha ao consultar auditoria de limites')
        return jsonify({'mensagem': 'Nao foi possivel consultar o historico'}), 500
    finally:
        if cursor:
            cursor.close()
