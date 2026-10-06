import os
import secrets

import jwt
from flask import jsonify, request

from banco import con
from funcao import calcular_saldo, usuario_pode_acessar_conta
from main import app


CARGOS = {
    0: 'Administrativo',
    1: 'Financeiro',
    2: 'Contador',
    3: 'RH',
    4: 'Compras',
    5: 'Outro'
}


def autenticar_requisicao_mcp():
    """Valida o serviço MCP e a sessão bancária emitida pelo backend."""
    chave_esperada = os.getenv('MCP_SERVICE_KEY')
    chave_recebida = request.headers.get('X-Arkhe-MCP-Key')
    token_sessao = request.headers.get('X-Arkhe-Session')

    if not chave_esperada:
        return None, (jsonify({'mensagem': 'Integração MCP não configurada'}), 503)

    if not chave_recebida or not secrets.compare_digest(chave_recebida, chave_esperada):
        return None, (jsonify({'mensagem': 'Serviço MCP não autorizado'}), 401)

    if not token_sessao:
        return None, (jsonify({'mensagem': 'Sessão Arkhé não informada'}), 401)

    try:
        payload = jwt.decode(
            token_sessao,
            app.config['SECRET_KEY'],
            algorithms=['HS256']
        )
    except jwt.ExpiredSignatureError:
        return None, (jsonify({'mensagem': 'Sessão Arkhé expirada'}), 401)
    except Exception:
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    if payload.get('escopo') != 'mcp':
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    try:
        id_usuario = int(payload['id_usuario'])
        id_conta = int(payload['id_conta'])
    except (KeyError, TypeError, ValueError):
        return None, (jsonify({'mensagem': 'Sessão Arkhé inválida'}), 401)

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None, (jsonify({'mensagem': 'Usuário sem acesso à conta selecionada'}), 403)

    return {
        'id_usuario': id_usuario,
        'id_conta': id_conta,
        'canal': payload.get('canal')
    }, None


def buscar_dados_conta_mcp(id_usuario, id_conta):
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT C.ID_CONTA, C.ID_USUARIO, C.NUMERO_CONTA, C.AGENCIA,
                      C.BANCO, C.TIPO_CONTA, C.NOME_FANTASIA, C.RAZAO_SOCIAL,
                      U.NOME
               FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_CONTA = ?""",
            (id_conta,)
        )
        conta = cursor.fetchone()

        if not conta:
            return None

        id_titular = conta[1]
        tipo_conta = conta[5]
        cargo = None
        cargo_nome = None

        if id_titular == id_usuario:
            vinculo = 'titular' if tipo_conta == 0 else 'proprietario'
        else:
            vinculo = 'acesso'
            cursor.execute(
                """SELECT CARGO
                   FROM ACESSO_CONTA
                   WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1""",
                (id_conta, id_usuario)
            )
            acesso = cursor.fetchone()

            if not acesso:
                return None

            cargo = acesso[0]
            cargo_nome = CARGOS.get(cargo, 'Outro')

        nome = conta[8]

        if tipo_conta == 1:
            nome = conta[6] or conta[7] or conta[8] or 'Empresa Arkhé'

        return {
            'id_conta': conta[0],
            'numero_conta': conta[2],
            'agencia': conta[3],
            'banco': conta[4],
            'tipo_conta': tipo_conta,
            'nome': nome,
            'vinculo': vinculo,
            'cargo': cargo,
            'cargo_nome': cargo_nome
        }

    finally:
        if cursor:
            cursor.close()


@app.route('/internal/mcp/conta', methods=['GET'])
def mcp_consultar_conta():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    try:
        conta = buscar_dados_conta_mcp(
            contexto['id_usuario'],
            contexto['id_conta']
        )

        if not conta:
            return jsonify({'mensagem': 'Conta não encontrada'}), 404

        return jsonify(conta), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR CONTA:', e)
        return jsonify({'mensagem': 'Erro ao consultar conta'}), 500


@app.route('/internal/mcp/saldo', methods=['GET'])
def mcp_consultar_saldo():
    contexto, erro = autenticar_requisicao_mcp()

    if erro:
        return erro

    try:
        saldo = calcular_saldo(contexto['id_conta'])

        if saldo is None:
            return jsonify({'mensagem': 'Conta não encontrada'}), 404

        return jsonify({
            'saldo': float(saldo)
        }), 200

    except Exception as e:
        print('ERRO MCP CONSULTAR SALDO:', e)
        return jsonify({'mensagem': 'Erro ao consultar saldo'}), 500
