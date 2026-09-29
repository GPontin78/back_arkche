from decimal import Decimal, ROUND_HALF_UP
from flask import jsonify, request
from main import app
from banco import con
from funcao import *


@app.route('/adicionar_compra', methods=['POST'])
def adicionar_compra():
    try:
        dados = request.get_json()

        valor_compra = float(dados.get('valor_compra'))
        tipo = int(dados.get('tipo'))
        qtd_parcela = int(dados.get('qtd_parcela') or 1)
        numero_cartao = dados.get('numero_cartao')

        id_conta = descobre_id_conta()

        if id_conta is None:
            return jsonify({
                'mensagem': 'Usuario nao logado'
            }), 403

        cursor = con.cursor()

        cursor.execute("""
            SELECT
                C.ID_CARTAO,
                C.ID_CONTA,
                C.LIMITE,
                C.STATUS
            FROM CARTAO C
            INNER JOIN CONTA CN
                ON C.ID_CONTA = CN.ID_CONTA
            WHERE C.NUMERO_CARTAO = ?
        """, (numero_cartao,))

        cartao = cursor.fetchone()

        if cartao is None:
            return jsonify({
                'mensagem': 'Cartao nao encontrado'
            }), 404

        id_cartao_pagador = cartao[0]
        id_conta_pagador = cartao[1]
        limite_cartao = float(cartao[2] or 0)
        status_cartao = cartao[3]

        data_compra = data_atual()


        if status_cartao == 1:
            return jsonify({
                'mensagem': 'Erro ao realizar compra, cartao bloqueado'
            }), 400

        cursor.execute("""
            SELECT 1
            FROM COMPRA C
            INNER JOIN CARTAO CA
                ON CA.ID_CARTAO = C.ID_CARTAO
            INNER JOIN MOVIMENTACAO M
                ON M.ID_PAGADOR = CA.ID_CONTA
            WHERE C.ID_CARTAO = ?
              AND C.VALOR_COMPRA = ?
              AND M.ID_RECEBEDOR = ?
              AND C.DATA_COMPRA BETWEEN DATEADD(-5 MINUTE TO ?)
                                     AND ?
              AND M.DATA_MOVIMENTACAO BETWEEN DATEADD(-5 MINUTE TO ?)
                                          AND ?
        """, (
            id_cartao_pagador,
            valor_compra,
            id_conta,
            data_compra,
            data_compra,
            data_compra,
            data_compra
        ))

        compra_duplicada = cursor.fetchone()

        if compra_duplicada:
            return jsonify({
                'mensagem': 'Compra duplicada. A mesma transacao ja foi realizada.'
            }), 409

        if tipo == 0:

            if not pode_debitar_saldo(id_conta_pagador, valor_compra):
                return jsonify({
                    'mensagem': 'Erro ao realizar compra, saldo insuficiente'
                }), 400

            cursor.execute("""
                INSERT INTO COMPRA (
                    ID_CARTAO,
                    VALOR_COMPRA,
                    DATA_COMPRA,
                    TIPO
                )
                VALUES (?, ?, ?, ?)
            """, (
                id_cartao_pagador,
                valor_compra,
                data_compra,
                tipo
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
                id_conta,
                valor_compra,
                data_compra
            ))

            con.commit()

            return jsonify({
                'mensagem': 'Compra realizada com sucesso'
            }), 200

        if tipo == 1:

            limite_cartao_utilizado = calcular_limite_cartao(
                id_cartao_pagador
            )

            if limite_cartao_utilizado + valor_compra > limite_cartao:
                return jsonify({
                    'mensagem': 'Erro ao realizar compra, limite insuficiente'
                }), 400

            valor_parcela = valor_compra / qtd_parcela

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
                id_cartao_pagador,
                valor_compra,
                data_compra,
                tipo,
                valor_parcela,
                qtd_parcela
            ))

            valor_recebido_vendedor = valor_compra * 0.95

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
                id_conta,
                valor_recebido_vendedor,
                data_compra
            ))

            con.commit()

            return jsonify({
                'mensagem': 'Compra realizada com sucesso'
            }), 200

        return jsonify({
            'mensagem': 'Tipo de compra invalido'
        }), 400

    except Exception as e:
        return jsonify({
            'mensagem': 'Erro ao realizar compra',
            'erro': str(e)
        }), 500

