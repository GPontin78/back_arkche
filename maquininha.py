from flask import jsonify, request
from main import app
from banco import con
from funcao import dados_conta, verificar_pin_usuario, calcular_saldo, data_atual

CARTOES_FISICOS = {
    '0D94A4A5': 4,  # Cartao da Lais
}


def normalizar_uid(uid):
    return ''.join(c for c in str(uid or '').upper() if c.isalnum())


def validar_conta_recebedora():
    conta = dados_conta()

    if not conta:
        return None, (jsonify({
            'aprovado': False,
            'codigo': 'EMPRESA_NAO_AUTENTICADA',
            'mensagem': 'Empresa nao autenticada'
        }), 403)

    if conta['tipo_conta'] != 1:
        return None, (jsonify({
            'aprovado': False,
            'codigo': 'CONTA_NAO_PJ',
            'mensagem': 'A maquininha esta disponivel apenas para contas PJ'
        }), 403)

    return conta['id_conta'], None


def buscar_cartao_fisico(uid):
    uid = normalizar_uid(uid)

    if not uid:
        return None

    id_cartao = CARTOES_FISICOS.get(uid)

    if not id_cartao:
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT
                CA.ID_CARTAO,
                CA.ID_CONTA,
                CA.NUMERO_CARTAO,
                CA.LIMITE,
                CA.STATUS,
                C.ID_USUARIO,
                U.NOME
            FROM CARTAO CA
            INNER JOIN CONTA C ON C.ID_CONTA = CA.ID_CONTA
            INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
            WHERE CA.ID_CARTAO = ?
        """, (id_cartao,))

        return cursor.fetchone()

    finally:
        if cursor:
            cursor.close()


@app.route('/maquininha/identificar', methods=['POST'])
def identificar_cartao_maquininha():
    id_recebedor, erro = validar_conta_recebedora()

    if erro:
        return erro

    dados = request.get_json(silent=True) or {}
    uid = normalizar_uid(dados.get('uid'))

    if not uid:
        return jsonify({
            'cartao_encontrado': False,
            'codigo': 'UID_INVALIDO',
            'mensagem': 'UID invalido'
        }), 400

    cartao = buscar_cartao_fisico(uid)

    if not cartao:
        return jsonify({
            'cartao_encontrado': False,
            'codigo': 'CARTAO_NAO_RECONHECIDO',
            'mensagem': 'Cartao fisico nao reconhecido'
        }), 404

    if cartao[4] == 1:
        return jsonify({
            'cartao_encontrado': True,
            'codigo': 'CARTAO_BLOQUEADO',
            'mensagem': 'Cartao bloqueado'
        }), 400

    numero_cartao = str(cartao[2])

    return jsonify({
        'cartao_encontrado': True,
        'mensagem': 'Cartao identificado',
        'final_cartao': numero_cartao[-4:],
        'nome': cartao[6]
    }), 200


@app.route('/maquininha/comprar', methods=['POST'])
def comprar_maquininha():
    id_recebedor, erro = validar_conta_recebedora()

    if erro:
        return erro

    dados = request.get_json(silent=True) or {}

    uid = normalizar_uid(dados.get('uid'))
    pin = str(dados.get('pin') or '')
    tipo = str(dados.get('tipo') or '').upper().strip()

    if not uid:
        return jsonify({
            'aprovado': False,
            'codigo': 'UID_INVALIDO',
            'mensagem': 'UID invalido'
        }), 400

    if len(pin) != 6 or not pin.isdigit():
        return jsonify({
            'aprovado': False,
            'codigo': 'DADOS_INVALIDOS',
            'mensagem': 'PIN deve possuir 6 numeros'
        }), 400

    try:
        valor = float(dados.get('valor'))
    except (TypeError, ValueError):
        return jsonify({
            'aprovado': False,
            'codigo': 'DADOS_INVALIDOS',
            'mensagem': 'Valor invalido'
        }), 400

    if valor <= 0:
        return jsonify({
            'aprovado': False,
            'codigo': 'DADOS_INVALIDOS',
            'mensagem': 'Valor invalido'
        }), 400

    if tipo != 'DEBITO':
        return jsonify({
            'aprovado': False,
            'codigo': 'MODALIDADE_INDISPONIVEL',
            'mensagem': 'Modalidade ainda nao disponivel'
        }), 400

    cartao = buscar_cartao_fisico(uid)

    if not cartao:
        return jsonify({
            'aprovado': False,
            'codigo': 'CARTAO_NAO_RECONHECIDO',
            'mensagem': 'Cartao fisico nao reconhecido'
        }), 404

    id_cartao = cartao[0]
    id_conta_pagador = cartao[1]
    numero_cartao = str(cartao[2])
    status_cartao = cartao[4]
    id_usuario = cartao[5]
    nome_usuario = cartao[6]

    if status_cartao == 1:
        return jsonify({
            'aprovado': False,
            'codigo': 'CARTAO_BLOQUEADO',
            'mensagem': 'Cartao bloqueado'
        }), 400

    if id_conta_pagador == id_recebedor:
        return jsonify({
            'aprovado': False,
            'codigo': 'CONTA_INVALIDA',
            'mensagem': 'A conta pagadora nao pode ser igual a conta recebedora'
        }), 400

    resultado_pin = verificar_pin_usuario(id_usuario, pin)

    if not resultado_pin.get('valido'):
        return jsonify({
            'aprovado': False,
            'codigo': 'PIN_INVALIDO',
            'mensagem': 'PIN invalido'
        }), 401

    saldo = calcular_saldo(id_conta_pagador)

    if saldo is None or float(saldo) < valor:
        return jsonify({
            'aprovado': False,
            'codigo': 'SALDO_INSUFICIENTE',
            'mensagem': 'Saldo insuficiente'
        }), 400

    cursor = None

    try:
        cursor = con.cursor()
        data_compra = data_atual()

        cursor.execute("""
            INSERT INTO COMPRA (
                ID_CARTAO,
                VALOR_COMPRA,
                DATA_COMPRA,
                TIPO
            )
            VALUES (?, ?, ?, ?)
        """, (
            id_cartao,
            valor,
            data_compra,
            0
        ))

        cursor.execute("""
            INSERT INTO MOVIMENTACAO (
                ID_PAGADOR,
                ID_RECEBEDOR,
                VALOR,
                DATA_MOVIMENTACAO
            )
            VALUES (?, ?, ?, ?)
        """, (
            id_conta_pagador,
            id_recebedor,
            valor,
            data_compra
        ))

        con.commit()

        return jsonify({
            'aprovado': True,
            'codigo': 'APROVADO',
            'mensagem': 'Compra aprovada',
            'valor': round(valor, 2),
            'final_cartao': numero_cartao[-4:],
            'nome': nome_usuario
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO MAQUININHA:', e)

        return jsonify({
            'aprovado': False,
            'codigo': 'ERRO_INTERNO',
            'mensagem': 'Erro ao processar compra'
        }), 500

    finally:
        if cursor:
            cursor.close()