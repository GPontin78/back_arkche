from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import jsonify, request
from main import app
from banco import con
from funcao import dados_conta, verificar_pin_usuario, pode_debitar_saldo, calcular_limite_cartao, data_atual

CARTOES_FISICOS = {
    '0D94A4A5': 4,  # Cartao da Lais
    'F590B889': 3,  # Cartao do Banco Arkhe - conta 9
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


def compra_duplicada_maquininha(id_cartao, id_conta_pagador, id_recebedor, valor, agora):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT FIRST 1 1
            FROM COMPRA C
            INNER JOIN MOVIMENTACAO M
                ON M.ID_PAGADOR = ?
               AND M.ID_RECEBEDOR = ?
               AND M.VALOR = C.VALOR_COMPRA
               AND M.DATA_MOVIMENTACAO = C.DATA_COMPRA
            WHERE C.ID_CARTAO = ?
              AND C.TIPO = 0
              AND C.VALOR_COMPRA = ?
              AND C.DATA_COMPRA BETWEEN DATEADD(-5 MINUTE TO ?) AND ?
        """, (
            id_conta_pagador,
            id_recebedor,
            id_cartao,
            valor,
            agora,
            agora
        ))

        return cursor.fetchone() is not None

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
        valor = Decimal(str(dados.get('valor'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
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

    if tipo not in ('DEBITO', 'CREDITO'):
        return jsonify({
            'aprovado': False,
            'codigo': 'MODALIDADE_INDISPONIVEL',
            'mensagem': 'Modalidade indisponivel'
        }), 400

    qtd_parcela = 1

    if tipo == 'CREDITO':
        try:
            qtd_parcela = int(dados.get('parcelas') or 1)
        except (TypeError, ValueError):
            qtd_parcela = 0

        if qtd_parcela < 1 or qtd_parcela > 15:
            return jsonify({
                'aprovado': False,
                'codigo': 'PARCELAS_INVALIDAS',
                'mensagem': 'Quantidade de parcelas deve ser entre 1 e 15'
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

    data_compra = data_atual()

    if tipo == 'DEBITO':
        if compra_duplicada_maquininha(
            id_cartao,
            id_conta_pagador,
            id_recebedor,
            valor,
            data_compra
        ):
            return jsonify({
                'aprovado': False,
                'codigo': 'COMPRA_DUPLICADA',
                'mensagem': 'Compra duplicada. Aguarde 5 minutos para repetir o mesmo valor neste estabelecimento.'
            }), 409

        if not pode_debitar_saldo(id_conta_pagador, valor):
            return jsonify({
                'aprovado': False,
                'codigo': 'SALDO_INSUFICIENTE',
                'mensagem': 'Saldo insuficiente'
            }), 400

    else:
        limite_total = Decimal(str(cartao[3] or 0))
        limite_utilizado = Decimal(str(calcular_limite_cartao(id_cartao) or 0))

        if limite_utilizado + valor > limite_total:
            return jsonify({
                'aprovado': False,
                'codigo': 'LIMITE_INSUFICIENTE',
                'mensagem': 'Limite insuficiente'
            }), 400

    cursor = None

    try:
        cursor = con.cursor()

        if tipo == 'DEBITO':
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

        else:
            valor_parcela = (valor / Decimal(qtd_parcela)).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP
            )

            cursor.execute("""
                INSERT INTO COMPRA (
                    ID_CARTAO,
                    VALOR_COMPRA,
                    DATA_COMPRA,
                    TIPO,
                    VALOR_PARCELA,
                    QTD_PARCELA
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                id_cartao,
                valor,
                data_compra,
                1,
                valor_parcela,
                qtd_parcela
            ))

        con.commit()

        return jsonify({
            'aprovado': True,
            'codigo': 'APROVADO',
            'mensagem': 'Compra aprovada',
            'valor': float(valor),
            'tipo': tipo,
            'parcelas': qtd_parcela,
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