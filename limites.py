"""Politicas diurnas/noturnas, verificacao transacional e auditoria de limites."""
import datetime
import json
import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import fdb
from flask import current_app, has_request_context, jsonify, request

from banco import con
from funcao import data_atual, dados_conta, dados_usuario
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos


OPERACOES = ('TRANSFERENCIA', 'PAGAMENTO')
PERIODOS = ('DIURNO', 'NOTURNO')
TIPOS_CONTA = ('PF', 'PJ')
# Regra de seguranca para PF/PJ em ambos os periodos quando o administrador
# ainda nao configurou uma politica explicita. O admin pode alterar os tetos
# pela rota autorizada de politica, sem conceder esse poder aos titulares.
TETO_PADRAO_SEM_POLITICA = Decimal('5000.00')


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
        '''SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
           FROM MOVIMENTACAO M
           WHERE M.ID_PAGADOR = ? AND M.DATA_MOVIMENTACAO >= ? AND M.DATA_MOVIMENTACAO < ?
             AND M.ID_COMPRA IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM COMPRA C
                 INNER JOIN CARTAO CA ON CA.ID_CARTAO = C.ID_CARTAO
                 WHERE CA.ID_CONTA = M.ID_PAGADOR
                   AND C.TIPO IN (0, 1)
                   AND C.DATA_COMPRA = M.DATA_MOVIMENTACAO
                   AND M.ID_RECEBEDOR = CA.ID_CONTA
                   AND M.VALOR = CASE
                       WHEN C.TIPO = 0 THEN C.VALOR_COMPRA
                       ELSE CAST(C.VALOR_COMPRA * 0.95 AS DECIMAL(18,2))
                   END
             )''',
        (int(id_conta), inicio, fim),
    )
    movimentacoes = Decimal(str(cursor.fetchone()[0] or 0))
    # COMPRA e a fonte da compra no cartao (debito ou credito). Movimentacoes
    # vinculadas e compras legadas com o mesmo instante ficam fora da soma acima.
    cursor.execute(
        '''SELECT CAST(COALESCE(SUM(C.VALOR_COMPRA), 0) AS DECIMAL(18,2))
           FROM COMPRA C
           INNER JOIN CARTAO CA ON CA.ID_CARTAO = C.ID_CARTAO
           WHERE CA.ID_CONTA = ? AND C.TIPO IN (0, 1)
             AND C.DATA_COMPRA >= ? AND C.DATA_COMPRA < ?''',
        (int(id_conta), inicio, fim),
    )
    compras_cartao = Decimal(str(cursor.fetchone()[0] or 0))
    return movimentacoes + compras_cartao


def _politica_atual(cursor, tipo_conta, operacao, periodo):
    cursor.execute(
        '''SELECT ATIVO, LIMITE_POR_OPERACAO, LIMITE_POR_OPERACAO_FAVORITO
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
        'limite_por_operacao': Decimal(str(operacao_row[1])) if operacao_row and int(operacao_row[0]) == 1 and operacao_row[1] is not None else TETO_PADRAO_SEM_POLITICA,
        'limite_por_operacao_favorito': Decimal(str(operacao_row[2])) if operacao_row and int(operacao_row[0]) == 1 and len(operacao_row) > 2 and operacao_row[2] is not None else None,
        'limite_acumulado': Decimal(str(periodo_row[1])) if periodo_row and int(periodo_row[0]) == 1 and periodo_row[1] is not None else TETO_PADRAO_SEM_POLITICA,
    }


def _politica_da_conta(cursor, id_conta, operacao, periodo):
    cursor.execute(
        '''SELECT LIMITE_POR_OPERACAO, LIMITE_POR_OPERACAO_FAVORITO
           FROM LIMITE_CONTA_OPERACAO
           WHERE ID_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
        (int(id_conta), operacao, periodo),
    )
    operacao_row = cursor.fetchone()
    cursor.execute(
        '''SELECT LIMITE_ACUMULADO FROM LIMITE_CONTA_PERIODO
           WHERE ID_CONTA = ? AND PERIODO = ?''',
        (int(id_conta), periodo),
    )
    periodo_row = cursor.fetchone()
    return {
        'limite_por_operacao': Decimal(str(operacao_row[0])) if operacao_row and operacao_row[0] is not None else None,
        'limite_por_operacao_favorito': Decimal(str(operacao_row[1])) if operacao_row and operacao_row[1] is not None else None,
        'limite_acumulado': Decimal(str(periodo_row[0])) if periodo_row and periodo_row[0] is not None else None,
    }


def _menor_teto(teto_banco, teto_conta):
    if teto_banco is None:
        return teto_conta
    if teto_conta is None:
        return teto_banco
    return min(teto_banco, teto_conta)


def _teto_favorito(banco, conta):
    # Sem uma regra individual para favoritos, o teto pessoal normal também
    # vale para favoritos. Uma excecao maior precisa ser configurada na conta.
    teto_banco = banco['limite_por_operacao_favorito'] or banco['limite_por_operacao']
    teto_conta = conta['limite_por_operacao_favorito'] or conta['limite_por_operacao']
    return _menor_teto(teto_banco, teto_conta)


def _politica_efetiva(cursor, id_conta, tipo_conta, operacao, periodo):
    banco = _politica_atual(cursor, tipo_conta, operacao, periodo)
    conta = _politica_da_conta(cursor, id_conta, operacao, periodo)
    efetiva = {
        'limite_por_operacao': _menor_teto(banco['limite_por_operacao'], conta['limite_por_operacao']),
        'limite_por_operacao_favorito': _teto_favorito(banco, conta),
        'limite_acumulado': _menor_teto(banco['limite_acumulado'], conta['limite_acumulado']),
        'limite_por_operacao_banco': banco['limite_por_operacao'],
        'limite_por_operacao_favorito_banco': banco['limite_por_operacao_favorito'],
        'limite_acumulado_banco': banco['limite_acumulado'],
        'limite_por_operacao_conta': conta['limite_por_operacao'],
        'limite_por_operacao_favorito_conta': conta['limite_por_operacao_favorito'],
        'limite_acumulado_conta': conta['limite_acumulado'],
    }
    return efetiva


def _registrar_recusa(id_conta, id_usuario, tipo_conta, operacao, periodo,
                      solicitado, usado, politica, motivo):
    conexao = None
    cursor = None
    eventos = []
    persistido = False
    try:
        conexao = fdb.connect(
            host=current_app.config['DB_HOST'], port=current_app.config['DB_PORT'],
            database=current_app.config['DB_NAME'], user=current_app.config['DB_USER'],
            password=current_app.config['DB_PASSWORD'],
            charset=current_app.config.get('DB_CHARSET', 'UTF8'),
        )
        cursor = conexao.cursor()
        if id_usuario is None:
            cursor.execute('SELECT ID_USUARIO FROM CONTA WHERE ID_CONTA = ?', (id_conta,))
            titular = cursor.fetchone()
            id_usuario = int(titular[0]) if titular else None
        canal = request.path if has_request_context() else '/worker/agendamentos'
        cursor.execute(
            '''INSERT INTO AUDITORIA_LIMITE
               (EVENTO, ID_USUARIO, ID_CONTA, TIPO_CONTA, OPERACAO, PERIODO,
                VALOR_SOLICITADO, VALOR_ACUMULADO, LIMITE_POR_OPERACAO,
                LIMITE_ACUMULADO, MOTIVO, DETALHES_JSON)
               VALUES ('OPERACAO_RECUSADA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (id_usuario, id_conta, tipo_conta, operacao, periodo, solicitado,
             usado, politica['limite_por_operacao'], politica['limite_acumulado'],
              motivo[:250], json.dumps({'canal': canal, 'limite_por_operacao': str(politica['limite_por_operacao']) if politica['limite_por_operacao'] is not None else None,
                                       'limite_acumulado': str(politica['limite_acumulado']) if politica['limite_acumulado'] is not None else None,
                                       'destinatario_favorito': bool(politica.get('destinatario_favorito'))}, ensure_ascii=False)),
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
        current_app.logger.exception('Falha ao registrar recusa por limite da conta %s', id_conta)
    finally:
        if cursor:
            cursor.close()
        if conexao:
            conexao.close()
    if persistido and eventos:
        tentar_publicar_eventos(eventos)
    return persistido


def aplicar_limite(cursor, id_conta, operacao, valor_total, *, valor_por_operacao=None,
                   id_usuario=None, destinatario_favorito=False):
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

    # A mesma linha serializa pagamentos concorrentes e alteracoes dos limites
    # individuais da conta ate o commit da operacao.
    cursor.execute(
        'UPDATE CONTROLE_LIMITE_CONTA SET VERSAO = VERSAO + 1 WHERE ID_CONTA = ? RETURNING ID_CONTA',
        (int(id_conta),),
    )
    if not cursor.fetchone():
        raise RuntimeError('Registro de concorrencia dos limites ausente para a conta')

    politica = _politica_efetiva(cursor, id_conta, tipo_conta, operacao, periodo)
    if (destinatario_favorito and operacao == 'TRANSFERENCIA'
            and politica['limite_por_operacao_favorito'] is not None):
        politica['limite_por_operacao'] = politica['limite_por_operacao_favorito']
    politica['destinatario_favorito'] = bool(destinatario_favorito)
    if politica['limite_por_operacao'] is None and politica['limite_acumulado'] is None:
        return None

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
    limite_acumulado_banco = Decimal(str(acumulado[1])) if acumulado and int(acumulado[0]) == 1 and acumulado[1] is not None else TETO_PADRAO_SEM_POLITICA
    cursor.execute(
        '''SELECT LIMITE_ACUMULADO FROM LIMITE_CONTA_PERIODO
           WHERE ID_CONTA = ? AND PERIODO = ?''', (int(id_conta), periodo)
    )
    acumulado_conta = cursor.fetchone()
    limite_acumulado_conta = Decimal(str(acumulado_conta[0])) if acumulado_conta and acumulado_conta[0] is not None else None
    limite_acumulado = _menor_teto(limite_acumulado_banco, limite_acumulado_conta)
    restante = max(Decimal('0.00'), limite_acumulado - usado) if limite_acumulado is not None else None
    cursor.execute(
        '''SELECT OPERACAO, ATIVO, LIMITE_POR_OPERACAO, LIMITE_POR_OPERACAO_FAVORITO FROM POLITICA_LIMITE_OPERACAO
           WHERE TIPO_CONTA = ? AND PERIODO = ? ORDER BY OPERACAO''', (tipo_conta, periodo)
    )
    operacoes = []
    for operacao, ativo, maximo, maximo_favorito in cursor.fetchall():
        maximo_banco = Decimal(str(maximo)) if int(ativo) == 1 and maximo is not None else TETO_PADRAO_SEM_POLITICA
        maximo_favorito_banco = Decimal(str(maximo_favorito)) if int(ativo) == 1 and maximo_favorito is not None else None
        conta = _politica_da_conta(cursor, id_conta, operacao, periodo)
        maximo_conta = conta['limite_por_operacao']
        maximo_favorito_conta = conta['limite_por_operacao_favorito']
        maximo = _menor_teto(maximo_banco, maximo_conta)
        maximo_favorito = _teto_favorito(
            {'limite_por_operacao': maximo_banco, 'limite_por_operacao_favorito': maximo_favorito_banco},
            {'limite_por_operacao': maximo_conta, 'limite_por_operacao_favorito': maximo_favorito_conta},
        )
        capacidade = min(maximo, restante) if maximo is not None and restante is not None else (maximo if maximo is not None else restante)
        capacidade_favorito = min(maximo_favorito, restante) if maximo_favorito is not None and restante is not None else (maximo_favorito if maximo_favorito is not None else restante)
        operacoes.append({
            'operacao': operacao,
            'limite_por_operacao': float(maximo) if maximo is not None else None,
            'limite_por_operacao_favorito': float(maximo_favorito) if maximo_favorito is not None else None,
            'limite_por_operacao_banco': float(maximo_banco) if maximo_banco is not None else None,
            'limite_por_operacao_conta': float(maximo_conta) if maximo_conta is not None else None,
            'limite_por_operacao_favorito_banco': float(maximo_favorito_banco) if maximo_favorito_banco is not None else None,
            'limite_por_operacao_favorito_conta': float(maximo_favorito_conta) if maximo_favorito_conta is not None else None,
            'disponivel_favorito_agora': float(capacidade_favorito) if capacidade_favorito is not None else None,
            'disponivel_agora': float(capacidade) if capacidade is not None else None,
            'configurado': maximo is not None or maximo_favorito is not None or limite_acumulado is not None,
        })
    return {
        'periodo': periodo,
        'fuso': 'America/Sao_Paulo',
        'inicio': inicio.isoformat(timespec='minutes'),
        'fim': fim.isoformat(timespec='minutes'),
        'utilizado': float(usado),
        'limite_acumulado': float(limite_acumulado) if limite_acumulado is not None else None,
        'limite_acumulado_banco': float(limite_acumulado_banco) if limite_acumulado_banco is not None else None,
        'limite_acumulado_conta': float(limite_acumulado_conta) if limite_acumulado_conta is not None else None,
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


def usuario_eh_admin_bancario(id_usuario=None):
    """Valida administrador do banco pela lista central de IDs autorizados."""
    if id_usuario is None:
        usuario = _usuario_atual()
        id_usuario = usuario.get('id_usuario') if usuario else None
    try:
        return int(id_usuario) in _ids_administradores()
    except (TypeError, ValueError):
        return False


def _usuario_atual():
    usuario = dados_usuario()
    return usuario if usuario and usuario.get('id_usuario') else None


def _exigir_admin():
    usuario = _usuario_atual()
    if not usuario:
        return None, (jsonify({'mensagem': 'Autenticacao necessaria'}), 401)
    id_usuario = int(usuario['id_usuario'])
    if not usuario_eh_admin_bancario(id_usuario):
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
            'vinculo': conta.get('vinculo'),
            'pode_configurar_conta': conta.get('vinculo') in ('titular', 'proprietario'),
            'administrador': int(usuario['id_usuario']) in _ids_administradores(),
            'limites': [_resumo_conta(cursor, int(conta['id_conta']), tipo_conta)],
        }), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar limites da conta')
        return jsonify({'mensagem': 'Nao foi possivel consultar os limites'}), 500
    finally:
        if cursor:
            cursor.close()


def listar_politicas_limites():
    id_admin, erro = _exigir_admin()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT TIPO_CONTA, OPERACAO, PERIODO, ATIVO, LIMITE_POR_OPERACAO,
                      LIMITE_POR_OPERACAO_FAVORITO, ATUALIZADO_EM
               FROM POLITICA_LIMITE_OPERACAO ORDER BY TIPO_CONTA, PERIODO, OPERACAO'''
        )
        operacoes = [
            {'tipo_conta': r[0], 'operacao': r[1], 'periodo': r[2], 'ativo': bool(r[3]),
             'limite_por_operacao': float(r[4]) if r[4] is not None else None,
             'favorito_ativo': r[5] is not None,
             'limite_por_operacao_favorito': float(r[5]) if r[5] is not None else None,
             'atualizado_em': r[6].isoformat() if r[6] else None}
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
        current_app.logger.exception('Falha ao consultar politicas de limites')
        return jsonify({'mensagem': 'Nao foi possivel consultar as politicas'}), 500
    finally:
        if cursor:
            cursor.close()


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
            favorito_ativo = regra.get('favorito_ativo')
            if favorito_ativo is not None and type(favorito_ativo) is not bool:
                raise ValueError('Configure o limite para favoritos com verdadeiro ou falso')
            if operacao == 'PAGAMENTO' and favorito_ativo:
                raise ValueError('O limite maior para favoritos só se aplica a transferências Pix')
            limite_favorito = None
            if favorito_ativo is True:
                limite_favorito = _decimal_config(
                    regra.get('limite_por_operacao_favorito'),
                    'limite de transferência para favoritos', True,
                )
            limite_normal = _decimal_config(
                regra.get('limite_por_operacao'), f'limite de {operacao}', regra['ativo']
            )
            if favorito_ativo is True and not regra['ativo']:
                raise ValueError('Ative o limite normal antes de configurar um limite maior para favoritos')
            if (favorito_ativo is True and limite_favorito <= limite_normal):
                raise ValueError('O limite para destinatários favoritos deve ser maior que o limite normal')
            operacoes_normalizadas[operacao] = {
                'ativo': regra['ativo'],
                'limite_por_operacao': limite_normal,
                # None means an older client omitted the new field; preserve it.
                'favorito_ativo': favorito_ativo,
                'limite_por_operacao_favorito': limite_favorito,
            }
        if type(dados.get('acumulado_ativo')) is not bool:
            raise ValueError('Configure acumulado_ativo como verdadeiro ou falso')
        acumulado_ativo = dados['acumulado_ativo']
        limite_acumulado = _decimal_config(dados.get('limite_acumulado'), 'limite acumulado', acumulado_ativo)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    cursor = None
    try:
        cursor = con.cursor()
        anteriores = {'operacoes': {}, 'acumulado': None}
        for operacao in OPERACOES:
            cursor.execute(
                '''SELECT ATIVO, LIMITE_POR_OPERACAO, LIMITE_POR_OPERACAO_FAVORITO
                   FROM POLITICA_LIMITE_OPERACAO
                   WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
                (tipo_conta, operacao, periodo),
            )
            row = cursor.fetchone()
            anteriores['operacoes'][operacao] = {
                'ativo': bool(row[0]),
                'limite_por_operacao': str(row[1]) if row[1] is not None else None,
                'limite_por_operacao_favorito': str(row[2]) if row[2] is not None else None,
            }
        cursor.execute(
            '''SELECT ATIVO, LIMITE_ACUMULADO FROM POLITICA_LIMITE_PERIODO
               WHERE TIPO_CONTA = ? AND PERIODO = ?''', (tipo_conta, periodo)
        )
        row = cursor.fetchone()
        anteriores['acumulado'] = {'ativo': bool(row[0]), 'limite_acumulado': str(row[1]) if row[1] is not None else None}

        operacoes_depois = {}
        for operacao, regra in operacoes_normalizadas.items():
            anterior_favorito = anteriores['operacoes'][operacao]['limite_por_operacao_favorito']
            limite_favorito = (Decimal(anterior_favorito) if regra['favorito_ativo'] is None and anterior_favorito is not None
                               else (None if regra['favorito_ativo'] is None else regra['limite_por_operacao_favorito']))
            if (limite_favorito is not None and (not regra['ativo'] or regra['limite_por_operacao'] is None
                    or limite_favorito <= regra['limite_por_operacao'])):
                raise ValueError('O limite para destinatários favoritos deve ser maior que o limite normal')
            cursor.execute(
                '''UPDATE POLITICA_LIMITE_OPERACAO
                   SET ATIVO = ?, LIMITE_POR_OPERACAO = ?, LIMITE_POR_OPERACAO_FAVORITO = ?,
                       ATUALIZADO_POR = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
                   WHERE TIPO_CONTA = ? AND OPERACAO = ? AND PERIODO = ?''',
                (int(regra['ativo']), regra['limite_por_operacao'], limite_favorito,
                 id_admin, tipo_conta, operacao, periodo),
            )
            operacoes_depois[operacao] = {
                'ativo': regra['ativo'],
                'limite_por_operacao': str(regra['limite_por_operacao']) if regra['limite_por_operacao'] is not None else None,
                'favorito_ativo': limite_favorito is not None,
                'limite_por_operacao_favorito': str(limite_favorito) if limite_favorito is not None else None,
            }
        cursor.execute(
            '''UPDATE POLITICA_LIMITE_PERIODO
               SET ATIVO = ?, LIMITE_ACUMULADO = ?, ATUALIZADO_POR = ?, ATUALIZADO_EM = CURRENT_TIMESTAMP
               WHERE TIPO_CONTA = ? AND PERIODO = ?''',
            (int(acumulado_ativo), limite_acumulado, id_admin, tipo_conta, periodo),
        )
        novas = {
            'operacoes': operacoes_depois,
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
    except ValueError as e:
        con.rollback()
        return jsonify({'mensagem': str(e)}), 400
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao atualizar politicas de limites')
        return jsonify({'mensagem': 'Nao foi possivel salvar as politicas'}), 500
    finally:
        if cursor:
            cursor.close()


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
        current_app.logger.exception('Falha ao consultar auditoria de limites')
        return jsonify({'mensagem': 'Nao foi possivel consultar o historico'}), 500
    finally:
        if cursor:
            cursor.close()


def _conta_propria_atual():
    usuario = _usuario_atual()
    conta = dados_conta()
    if not usuario or not conta:
        return None, None, (jsonify({'mensagem': 'Sessao invalida ou conta nao selecionada'}), 401)
    if conta.get('vinculo') not in ('titular', 'proprietario') or int(conta.get('id_titular') or 0) != int(usuario['id_usuario']):
        return None, None, (jsonify({'mensagem': 'Somente o titular pode configurar limites individuais desta conta'}), 403)
    return usuario, conta, None


def consultar_configuracao_limites_conta():
    usuario, conta, erro = _conta_propria_atual()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        id_conta = int(conta['id_conta'])
        tipo = 'PJ' if int(conta['tipo_conta']) == 1 else 'PF'
        periodos = []
        for periodo in PERIODOS:
            cursor.execute(
                '''SELECT ATIVO, LIMITE_ACUMULADO FROM POLITICA_LIMITE_PERIODO
                   WHERE TIPO_CONTA = ? AND PERIODO = ?''', (tipo, periodo)
            )
            row = cursor.fetchone()
            teto_acumulado_banco = Decimal(str(row[1])) if row and int(row[0]) == 1 and row[1] is not None else TETO_PADRAO_SEM_POLITICA
            cursor.execute(
                '''SELECT LIMITE_ACUMULADO FROM LIMITE_CONTA_PERIODO
                   WHERE ID_CONTA = ? AND PERIODO = ?''', (id_conta, periodo)
            )
            own_row = cursor.fetchone()
            limite_acumulado_conta = Decimal(str(own_row[0])) if own_row and own_row[0] is not None else None
            operacoes = {}
            for operacao in OPERACOES:
                banco = _politica_atual(cursor, tipo, operacao, periodo)
                own = _politica_da_conta(cursor, id_conta, operacao, periodo)
                operacoes[operacao] = {
                    'limite_por_operacao_banco': float(banco['limite_por_operacao']) if banco['limite_por_operacao'] is not None else None,
                    'limite_por_operacao_favorito_banco': float(banco['limite_por_operacao_favorito']) if banco['limite_por_operacao_favorito'] is not None else None,
                    'limite_por_operacao_conta': float(own['limite_por_operacao']) if own['limite_por_operacao'] is not None else None,
                    'limite_por_operacao_favorito_conta': float(own['limite_por_operacao_favorito']) if own['limite_por_operacao_favorito'] is not None else None,
                    'limite_por_operacao_efetivo': float(_menor_teto(banco['limite_por_operacao'], own['limite_por_operacao'])) if _menor_teto(banco['limite_por_operacao'], own['limite_por_operacao']) is not None else None,
                    'limite_por_operacao_favorito_efetivo': float(_teto_favorito(banco, own)) if _teto_favorito(banco, own) is not None else None,
                }
            periodos.append({
                'periodo': periodo,
                'limite_acumulado_banco': float(teto_acumulado_banco) if teto_acumulado_banco is not None else None,
                'limite_acumulado_conta': float(limite_acumulado_conta) if limite_acumulado_conta is not None else None,
                'limite_acumulado_efetivo': float(_menor_teto(teto_acumulado_banco, limite_acumulado_conta)) if _menor_teto(teto_acumulado_banco, limite_acumulado_conta) is not None else None,
                'operacoes': operacoes,
            })
        return jsonify({'id_conta': id_conta, 'tipo_conta': tipo, 'periodos': periodos}), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar configuracao individual de limites')
        return jsonify({'mensagem': 'Nao foi possivel consultar os limites individuais'}), 500
    finally:
        if cursor:
            cursor.close()


def atualizar_configuracao_limites_conta():
    usuario, conta, erro = _conta_propria_atual()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie a configuracao de limites em JSON'}), 400
    periodo = str(dados.get('periodo') or '').upper()
    motivo = str(dados.get('motivo') or '').strip()
    operacoes_in = dados.get('operacoes')
    if periodo not in PERIODOS or not isinstance(operacoes_in, dict):
        return jsonify({'mensagem': 'Periodo ou operacoes invalidos'}), 400
    if not 5 <= len(motivo) <= 250:
        return jsonify({'mensagem': 'Informe o motivo da alteracao (5 a 250 caracteres)'}), 400
    try:
        normalizadas = {}
        for operacao in OPERACOES:
            regra = operacoes_in.get(operacao)
            if not isinstance(regra, dict):
                raise ValueError(f'Configure os limites individuais de {operacao}')
            normalizadas[operacao] = {
                'limite_por_operacao': _decimal_config(regra.get('limite_por_operacao'), f'limite individual de {operacao}', False),
                'limite_por_operacao_favorito': _decimal_config(regra.get('limite_por_operacao_favorito'), 'limite individual para favoritos', False),
            }
            if operacao == 'PAGAMENTO' and normalizadas[operacao]['limite_por_operacao_favorito'] is not None:
                raise ValueError('Limite para favoritos só se aplica a transferências Pix')
        limite_acumulado = _decimal_config(dados.get('limite_acumulado'), 'limite acumulado da conta', False)
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400

    cursor = None
    try:
        cursor = con.cursor()
        id_conta = int(conta['id_conta'])
        id_usuario = int(usuario['id_usuario'])
        tipo = 'PJ' if int(conta['tipo_conta']) == 1 else 'PF'
        cursor.execute(
            'UPDATE CONTROLE_LIMITE_CONTA SET VERSAO = VERSAO + 1 WHERE ID_CONTA = ? RETURNING ID_CONTA',
            (id_conta,),
        )
        if not cursor.fetchone():
            raise RuntimeError('Controle concorrente da conta ausente')

        anteriores = {'operacoes': {}, 'limite_acumulado': None}
        for operacao, regra in normalizadas.items():
            teto_banco = _politica_atual(cursor, tipo, operacao, periodo)
            valor_conta = regra['limite_por_operacao']
            valor_favorito = regra['limite_por_operacao_favorito']
            if (valor_conta is not None and teto_banco['limite_por_operacao'] is not None
                    and valor_conta > teto_banco['limite_por_operacao']):
                raise ValueError(f'O limite individual de {operacao} não pode superar o teto bancário ativo ({teto_banco["limite_por_operacao"] or "inexistente"})')
            if valor_favorito is not None and (teto_banco['limite_por_operacao_favorito'] is None or valor_favorito > teto_banco['limite_por_operacao_favorito']):
                raise ValueError('O limite individual para favoritos não pode superar o teto bancário ativo para favoritos')
            anterior = _politica_da_conta(cursor, id_conta, operacao, periodo)
            anteriores['operacoes'][operacao] = {
                'limite_por_operacao': str(anterior['limite_por_operacao']) if anterior['limite_por_operacao'] is not None else None,
                'limite_por_operacao_favorito': str(anterior['limite_por_operacao_favorito']) if anterior['limite_por_operacao_favorito'] is not None else None,
            }
            cursor.execute(
                '''UPDATE OR INSERT INTO LIMITE_CONTA_OPERACAO
                   (ID_CONTA, OPERACAO, PERIODO, LIMITE_POR_OPERACAO,
                    LIMITE_POR_OPERACAO_FAVORITO, ATUALIZADO_POR, ATUALIZADO_EM)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   MATCHING (ID_CONTA, OPERACAO, PERIODO)''',
                (id_conta, operacao, periodo, valor_conta, valor_favorito, id_usuario),
            )
        cursor.execute('SELECT LIMITE_ACUMULADO FROM LIMITE_CONTA_PERIODO WHERE ID_CONTA = ? AND PERIODO = ?', (id_conta, periodo))
        row = cursor.fetchone()
        anteriores['limite_acumulado'] = str(row[0]) if row and row[0] is not None else None
        cursor.execute('SELECT ATIVO, LIMITE_ACUMULADO FROM POLITICA_LIMITE_PERIODO WHERE TIPO_CONTA = ? AND PERIODO = ?', (tipo, periodo))
        banco_periodo = cursor.fetchone()
        teto_acumulado_banco = Decimal(str(banco_periodo[1])) if banco_periodo and int(banco_periodo[0]) == 1 and banco_periodo[1] is not None else TETO_PADRAO_SEM_POLITICA
        if (limite_acumulado is not None and teto_acumulado_banco is not None
                and limite_acumulado > teto_acumulado_banco):
            raise ValueError('O limite acumulado individual não pode superar o teto bancário ativo')
        cursor.execute(
            '''UPDATE OR INSERT INTO LIMITE_CONTA_PERIODO
               (ID_CONTA, PERIODO, LIMITE_ACUMULADO, ATUALIZADO_POR, ATUALIZADO_EM)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) MATCHING (ID_CONTA, PERIODO)''',
            (id_conta, periodo, limite_acumulado, id_usuario),
        )
        depois = {
            'operacoes': {op: {
                'limite_por_operacao': str(regra['limite_por_operacao']) if regra['limite_por_operacao'] is not None else None,
                'limite_por_operacao_favorito': str(regra['limite_por_operacao_favorito']) if regra['limite_por_operacao_favorito'] is not None else None,
            } for op, regra in normalizadas.items()},
            'limite_acumulado': str(limite_acumulado) if limite_acumulado is not None else None,
        }
        cursor.execute(
            '''INSERT INTO AUDITORIA_LIMITE
               (EVENTO, ID_USUARIO, ID_CONTA, TIPO_CONTA, PERIODO, MOTIVO, DETALHES_JSON)
               VALUES ('LIMITE_CONTA_ATUALIZADO', ?, ?, ?, ?, ?, ?)''',
            (id_usuario, id_conta, tipo, periodo, motivo,
             json.dumps({'antes': anteriores, 'depois': depois}, ensure_ascii=False)),
        )
        con.commit()
        return jsonify({'mensagem': 'Limites individuais atualizados', 'id_conta': id_conta, 'periodo': periodo}), 200
    except ValueError as e:
        con.rollback()
        return jsonify({'mensagem': str(e)}), 400
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao atualizar limites individuais da conta')
        return jsonify({'mensagem': 'Nao foi possivel salvar os limites individuais'}), 500
    finally:
        if cursor:
            cursor.close()


def listar_cartoes_limites_admin():
    _admin, erro = _exigir_admin()
    if erro:
        return erro
    try:
        limite = max(1, min(int(request.args.get('limite', '100')), 200))
        id_conta = request.args.get('id_conta')
        if id_conta not in (None, ''):
            id_conta = int(id_conta)
            if id_conta <= 0:
                raise ValueError
    except ValueError:
        return jsonify({'mensagem': 'Filtro de conta ou pagina invalido'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        filtro = 'WHERE (? IS NULL OR C.ID_CONTA = ?)'
        cursor.execute(
            f'''SELECT FIRST {limite} C.ID_CARTAO, C.ID_CONTA, CN.TIPO_CONTA,
                       RIGHT(C.NUMERO_CARTAO, 4), C.LIMITE,
                       CAST(COALESCE(SUM(FC.VALOR_PARCELA), 0) AS DECIMAL(18,2)),
                       CN.NOME_FANTASIA, CN.RAZAO_SOCIAL
                FROM CARTAO C
                INNER JOIN CONTA CN ON CN.ID_CONTA = C.ID_CONTA
                LEFT JOIN COMPRA CM ON CM.ID_CARTAO = C.ID_CARTAO AND CM.TIPO = 1
                LEFT JOIN FATURA_COMPRA FC ON FC.ID_COMPRA = CM.ID_COMPRA AND FC.STATUS = 0
                {filtro}
                GROUP BY C.ID_CARTAO, C.ID_CONTA, CN.TIPO_CONTA, C.NUMERO_CARTAO,
                         C.LIMITE, CN.NOME_FANTASIA, CN.RAZAO_SOCIAL
                ORDER BY C.ID_CARTAO DESC''',
            (id_conta, id_conta),
        )
        cartoes = [{
            'id_cartao': row[0], 'id_conta': row[1],
            'tipo_conta': 'PJ' if int(row[2]) == 1 else 'PF',
            'final_cartao': row[3], 'limite': float(row[4] or 0),
            'utilizado': float(row[5] or 0),
            'disponivel': max(0.0, float(row[4] or 0) - float(row[5] or 0)),
            'identificacao_conta': row[6] or row[7] or f'Conta {row[1]}',
        } for row in cursor.fetchall()]
        return jsonify({'cartoes': cartoes}), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar limites de credito dos cartoes')
        return jsonify({'mensagem': 'Nao foi possivel consultar os cartoes'}), 500
    finally:
        if cursor:
            cursor.close()


def atualizar_limite_credito_cartao(id_cartao):
    id_admin, erro = _exigir_admin()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie o novo limite e o motivo em JSON'}), 400
    motivo = str(dados.get('motivo') or '').strip()
    try:
        limite = _decimal_config(dados.get('limite'), 'limite de credito do cartao', True)
        if limite > Decimal('9999999999999.99'):
            raise ValueError('Limite de credito fora do intervalo permitido')
    except ValueError as e:
        return jsonify({'mensagem': str(e)}), 400
    if not 5 <= len(motivo) <= 250:
        return jsonify({'mensagem': 'Informe o motivo da alteracao (5 a 250 caracteres)'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            '''SELECT C.ID_CARTAO, C.ID_CONTA, C.LIMITE
               FROM CARTAO C WHERE C.ID_CARTAO = ? WITH LOCK''', (int(id_cartao),)
        )
        cartao = cursor.fetchone()
        if not cartao:
            return jsonify({'mensagem': 'Cartao nao encontrado'}), 404
        atual = Decimal(str(cartao[2] or 0))
        cursor.execute(
            '''SELECT CAST(COALESCE(SUM(FC.VALOR_PARCELA), 0) AS DECIMAL(18,2))
               FROM FATURA_COMPRA FC INNER JOIN COMPRA CM ON CM.ID_COMPRA = FC.ID_COMPRA
               WHERE FC.STATUS = 0 AND CM.ID_CARTAO = ?''', (int(id_cartao),)
        )
        utilizado = Decimal(str(cursor.fetchone()[0] or 0))
        if limite < utilizado:
            con.rollback()
            return jsonify({'mensagem': 'O limite nao pode ser menor que o credito ja utilizado',
                            'codigo': 'LIMITE_MENOR_QUE_UTILIZADO', 'utilizado': float(utilizado)}), 409
        cursor.execute('UPDATE CARTAO SET LIMITE = ? WHERE ID_CARTAO = ?', (limite, int(id_cartao)))
        cursor.execute(
            '''INSERT INTO AUDITORIA_LIMITE_CARTAO
               (ID_ADMINISTRADOR, ID_CARTAO, ID_CONTA, LIMITE_ANTERIOR, LIMITE_NOVO, MOTIVO)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (id_admin, int(id_cartao), int(cartao[1]), atual, limite, motivo),
        )
        con.commit()
        return jsonify({'mensagem': 'Limite de credito do cartao atualizado',
                        'id_cartao': int(id_cartao), 'limite': float(limite),
                        'utilizado': float(utilizado), 'disponivel': float(limite - utilizado)}), 200
    except Exception:
        con.rollback()
        current_app.logger.exception('Falha ao atualizar limite de credito do cartao %s', id_cartao)
        return jsonify({'mensagem': 'Nao foi possivel atualizar o limite de credito'}), 500
    finally:
        if cursor:
            cursor.close()


def historico_limites_cartoes_admin():
    _admin, erro = _exigir_admin()
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
            f'''SELECT FIRST {limite} ID_AUDITORIA, ID_ADMINISTRADOR, ID_CARTAO,
                       ID_CONTA, LIMITE_ANTERIOR, LIMITE_NOVO, MOTIVO, CRIADO_EM
                FROM AUDITORIA_LIMITE_CARTAO ORDER BY ID_AUDITORIA DESC'''
        )
        return jsonify({'historico': [{
            'id': row[0], 'id_administrador': row[1], 'id_cartao': row[2],
            'id_conta': row[3], 'limite_anterior': float(row[4]), 'limite_novo': float(row[5]),
            'motivo': row[6], 'criado_em': row[7].isoformat() if row[7] else None,
        } for row in cursor.fetchall()]}), 200
    except Exception:
        current_app.logger.exception('Falha ao consultar historico de limites de cartoes')
        return jsonify({'mensagem': 'Nao foi possivel consultar o historico de cartoes'}), 500
    finally:
        if cursor:
            cursor.close()


def registrar_rotas(app):
    app.add_url_rule('/api/v1/limites', 'consultar_limites_conta', consultar_limites_conta, methods=['GET'])
    app.add_url_rule('/api/v1/limites/conta/configuracao', 'consultar_configuracao_limites_conta', consultar_configuracao_limites_conta, methods=['GET'])
    app.add_url_rule('/api/v1/limites/conta/configuracao', 'atualizar_configuracao_limites_conta', atualizar_configuracao_limites_conta, methods=['PUT'])
    app.add_url_rule('/api/v1/limites/admin/politicas', 'listar_politicas_limites', listar_politicas_limites, methods=['GET'])
    app.add_url_rule('/api/v1/limites/admin/politicas', 'atualizar_politicas_limites', atualizar_politicas_limites, methods=['PUT'])
    app.add_url_rule('/api/v1/limites/admin/historico', 'historico_politicas_limites', historico_politicas_limites, methods=['GET'])
    app.add_url_rule('/api/v1/limites/admin/cartoes', 'listar_cartoes_limites_admin', listar_cartoes_limites_admin, methods=['GET'])
    app.add_url_rule('/api/v1/limites/admin/cartoes/historico', 'historico_limites_cartoes_admin', historico_limites_cartoes_admin, methods=['GET'])
    app.add_url_rule('/api/v1/limites/admin/cartoes/<int:id_cartao>', 'atualizar_limite_credito_cartao', atualizar_limite_credito_cartao, methods=['PUT'])
