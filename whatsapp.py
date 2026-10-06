import datetime
import os
import secrets

import jwt
from flask import jsonify, request

from banco import con
from funcao import gerar_token_mcp, listar_contas_usuario, usuario_pode_acessar_conta
from main import app


CARGOS_WHATSAPP = {
    0: 'Administrativo',
    1: 'Financeiro',
    2: 'Contador',
    3: 'RH',
    4: 'Compras',
    5: 'Outro'
}


def normalizar_telefone_whatsapp(valor):
    texto = str(valor or '').split('@')[0]
    numeros = ''.join(caractere for caractere in texto if caractere.isdigit())

    if len(numeros) in (10, 11):
        numeros = '55' + numeros

    return numeros


def autenticar_n8n():
    esperada = os.getenv('N8N_SERVICE_KEY')
    recebida = request.headers.get('X-Arkhe-N8N-Key')

    if not esperada:
        return jsonify({'mensagem': 'Integração n8n não configurada'}), 503

    if not recebida or not secrets.compare_digest(recebida, esperada):
        return jsonify({'mensagem': 'Serviço não autorizado'}), 401

    return None


def buscar_usuario_por_telefone(telefone):
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_USUARIO, NOME, TELEFONE
               FROM USUARIO
               WHERE TELEFONE IS NOT NULL"""
        )

        encontrados = []

        for usuario in cursor.fetchall():
            if normalizar_telefone_whatsapp(usuario[2]) == telefone:
                encontrados.append(usuario)

        if len(encontrados) != 1:
            return None

        return {
            'id_usuario': encontrados[0][0],
            'nome': encontrados[0][1],
            'telefone': telefone
        }

    finally:
        if cursor:
            cursor.close()


def nome_conta_whatsapp(conta, nome_usuario):
    if conta['tipo_conta'] == 0:
        return nome_usuario

    return (
        conta.get('nome_fantasia')
        or conta.get('razao_social')
        or 'Empresa Arkhé'
    )


def gerar_token_selecao_whatsapp(id_usuario, id_conta, telefone):
    agora = datetime.datetime.now(datetime.timezone.utc)

    return jwt.encode(
        {
            'id_usuario': int(id_usuario),
            'id_conta': int(id_conta),
            'telefone': telefone,
            'escopo': 'whatsapp_selecao_conta',
            'iat': agora,
            'exp': agora + datetime.timedelta(minutes=10)
        },
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )


@app.route('/internal/whatsapp/iniciar', methods=['POST'])
def whatsapp_iniciar():
    erro = autenticar_n8n()

    if erro:
        return erro

    dados = request.get_json() or {}
    telefone = normalizar_telefone_whatsapp(
        dados.get('telefone') or dados.get('chat_id')
    )

    if not telefone:
        return jsonify({'mensagem': 'Telefone não informado'}), 400

    usuario = buscar_usuario_por_telefone(telefone)

    if not usuario:
        return jsonify({
            'encontrado': False,
            'mensagem': 'Número não vinculado a um cliente Arkhé'
        }), 404

    contas = listar_contas_usuario(usuario['id_usuario'])
    opcoes = []

    for indice, conta in enumerate(contas, start=1):
        tipo = 'PJ' if conta['tipo_conta'] == 1 else 'PF'
        vinculo = conta.get('vinculo')
        cargo = conta.get('cargo')

        if vinculo == 'proprietario':
            cargo_nome = 'Proprietário'
        elif vinculo == 'titular':
            cargo_nome = 'Titular'
        else:
            cargo_nome = CARGOS_WHATSAPP.get(cargo, 'Outro')

        opcoes.append({
            'opcao': indice,
            'tipo_conta': tipo,
            'nome': nome_conta_whatsapp(conta, usuario['nome']),
            'vinculo': vinculo,
            'cargo': cargo_nome,
            'token_selecao': gerar_token_selecao_whatsapp(
                usuario['id_usuario'],
                conta['id_conta'],
                telefone
            )
        })

    return jsonify({
        'encontrado': True,
        'usuario': {
            'nome': usuario['nome']
        },
        'contas': opcoes
    }), 200


@app.route('/internal/whatsapp/selecionar-conta', methods=['POST'])
def whatsapp_selecionar_conta():
    erro = autenticar_n8n()

    if erro:
        return erro

    dados = request.get_json() or {}
    token = dados.get('token_selecao')
    telefone = normalizar_telefone_whatsapp(
        dados.get('telefone') or dados.get('chat_id')
    )

    if not token or not telefone:
        return jsonify({'mensagem': 'Seleção de conta inválida'}), 400

    try:
        payload = jwt.decode(
            token,
            app.config['SECRET_KEY'],
            algorithms=['HS256']
        )
    except jwt.ExpiredSignatureError:
        return jsonify({'mensagem': 'A seleção de conta expirou'}), 401
    except Exception:
        return jsonify({'mensagem': 'Seleção de conta inválida'}), 401

    if payload.get('escopo') != 'whatsapp_selecao_conta':
        return jsonify({'mensagem': 'Seleção de conta inválida'}), 401

    if payload.get('telefone') != telefone:
        return jsonify({'mensagem': 'Seleção de conta inválida'}), 403

    try:
        id_usuario = int(payload['id_usuario'])
        id_conta = int(payload['id_conta'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'mensagem': 'Seleção de conta inválida'}), 401

    usuario = buscar_usuario_por_telefone(telefone)

    if not usuario or usuario['id_usuario'] != id_usuario:
        return jsonify({'mensagem': 'Número não autorizado para esta conta'}), 403

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return jsonify({'mensagem': 'Acesso à conta não permitido'}), 403

    contas = listar_contas_usuario(id_usuario)
    conta = next(
        (item for item in contas if item['id_conta'] == id_conta),
        None
    )

    if not conta:
        return jsonify({'mensagem': 'Conta não encontrada'}), 404

    sessao_mcp = gerar_token_mcp(
        id_usuario,
        id_conta,
        canal='whatsapp',
        minutos=60
    )

    tipo = 'PJ' if conta['tipo_conta'] == 1 else 'PF'

    if conta.get('vinculo') == 'proprietario':
        cargo_nome = 'Proprietário'
    elif conta.get('vinculo') == 'titular':
        cargo_nome = 'Titular'
    else:
        cargo_nome = CARGOS_WHATSAPP.get(conta.get('cargo'), 'Outro')

    return jsonify({
        'mcp_session': sessao_mcp,
        'expira_em_minutos': 60,
        'conta': {
            'tipo_conta': tipo,
            'nome': nome_conta_whatsapp(conta, usuario['nome']),
            'vinculo': conta.get('vinculo'),
            'cargo': cargo_nome
        }
    }), 200
