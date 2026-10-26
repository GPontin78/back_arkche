from decimal import Decimal, ROUND_HALF_UP
import fdb
from flask import jsonify, request
from main import app
from banco import con
from funcao import *
from limites import aplicar_limite
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos
from vendas_idempotencia import (
    assinatura_venda,
    obter_resposta_venda,
    registrar_venda_idempotente,
    validar_chave_venda,
)


@app.route('/adicionar_compra', methods=['POST'])
def adicionar_compra():
    cursor = None
    try:
        dados = request.get_json()

        valor_compra = float(dados.get('valor_compra'))
        tipo = int(dados.get('tipo'))
        qtd_parcela = int(dados.get('qtd_parcela') or 1)
        numero_cartao = dados.get('numero_cartao')
        chave_idempotencia = validar_chave_venda(
            request.headers.get('X-Idempotency-Key') or dados.get('chave_idempotencia')
        )

        if not chave_idempotencia:
            return jsonify({'mensagem': 'Informe uma chave de idempotencia para esta venda.'}), 400

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
        if int(id_conta) != int(id_conta_pagador):
            return jsonify({'mensagem': 'Cartao nao pertence a conta ativa'}), 403
        cursor.execute('SELECT LIMITE, STATUS FROM CARTAO WHERE ID_CARTAO = ? WITH LOCK', (id_cartao_pagador,))
        cartao_bloqueado = cursor.fetchone()
        if not cartao_bloqueado:
            return jsonify({'mensagem': 'Cartao nao encontrado'}), 404
        cartao = (id_cartao_pagador, id_conta_pagador, cartao_bloqueado[0], cartao_bloqueado[1])
        limite_cartao = float(cartao[2] or 0)
        status_cartao = cartao[3]

        data_compra = data_atual()


        if status_cartao == 1:
            return jsonify({
                'mensagem': 'Erro ao realizar compra, cartao bloqueado'
            }), 400

        assinatura = assinatura_venda(
            id_cartao=int(id_cartao_pagador), id_pagador=int(id_conta_pagador),
            id_recebedor=int(id_conta), valor=str(Decimal(str(valor_compra))),
            tipo=int(tipo), parcelas=int(qtd_parcela),
        )
        repeticao = obter_resposta_venda(
            cursor, 'LEGADO', id_conta, chave_idempotencia, assinatura,
        )
        if repeticao is not None:
            con.rollback()
            return repeticao

        restricao_limite = aplicar_limite(
            cursor, id_conta_pagador, 'PAGAMENTO', valor_compra,
            id_usuario=descobre_id_usuario(),
        )
        if restricao_limite:
            return restricao_limite

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
                RETURNING ID_COMPRA
            """, (
                id_cartao_pagador,
                valor_compra,
                data_compra,
                tipo
            ))

            id_compra = cursor.fetchone()[0]

            cursor.execute("""
                INSERT INTO MOVIMENTACAO (
                    ID_PAGADOR,
                    ID_RECEBEDOR,
                    VALOR,
                    DATA_MOVIMENTACAO,
                    ID_COMPRA
                )
                VALUES (?, ?, ?, ?, ?)
                RETURNING ID_MOVIMENTACAO
            """, (
                id_conta_pagador,
                id_conta,
                valor_compra,
                data_compra,
                id_compra
            ))

            id_movimentacao = cursor.fetchone()[0]
            eventos = registrar_evento_bancario(
                cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='CARTAO',
                id_contas=[id_conta_pagador, id_conta], referencia_tipo='MOVIMENTACAO',
                referencia_id=id_movimentacao, valor=valor_compra, id_pagador=id_conta_pagador
            )

            resposta = {'mensagem': 'Compra realizada com sucesso', 'id_compra': id_compra,
                        'id_movimentacao': id_movimentacao}
            registrar_venda_idempotente(
                cursor, 'LEGADO', id_conta, chave_idempotencia, assinatura,
                id_compra, id_movimentacao, resposta, 200,
            )
            con.commit()
            tentar_publicar_eventos(eventos)

            return jsonify(resposta), 200

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
                RETURNING ID_COMPRA
            """, (
                id_cartao_pagador,
                valor_compra,
                data_compra,
                tipo,
                valor_parcela,
                qtd_parcela
            ))

            id_compra = cursor.fetchone()[0]

            valor_recebido_vendedor = valor_compra * 0.95

            cursor.execute("""
                INSERT INTO MOVIMENTACAO (
                    ID_PAGADOR,
                    ID_RECEBEDOR,
                    VALOR,
                    DATA_MOVIMENTACAO,
                    ID_COMPRA
                )
                VALUES (?, ?, ?, ?, ?)
                RETURNING ID_MOVIMENTACAO
            """, (
                id_conta_pagador,
                id_conta,
                valor_recebido_vendedor,
                data_compra,
                id_compra
            ))

            id_movimentacao = cursor.fetchone()[0]
            eventos = registrar_evento_bancario(
                cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='CARTAO',
                id_contas=[id_conta_pagador, id_conta], referencia_tipo='MOVIMENTACAO',
                referencia_id=id_movimentacao, valor=valor_recebido_vendedor, id_pagador=id_conta_pagador
            )

            resposta = {'mensagem': 'Compra realizada com sucesso', 'id_compra': id_compra,
                        'id_movimentacao': id_movimentacao}
            registrar_venda_idempotente(
                cursor, 'LEGADO', id_conta, chave_idempotencia, assinatura,
                id_compra, id_movimentacao, resposta, 200,
            )
            con.commit()
            tentar_publicar_eventos(eventos)

            return jsonify(resposta), 200

        return jsonify({
            'mensagem': 'Tipo de compra invalido'
        }), 400

    except (fdb.IntegrityError, fdb.TransactionConflict):
        con.rollback()
        if cursor and 'assinatura' in locals() and 'chave_idempotencia' in locals():
            try:
                repeticao = obter_resposta_venda(
                    cursor, 'LEGADO', id_conta, chave_idempotencia, assinatura,
                )
                if repeticao is not None:
                    return repeticao
            except Exception:
                con.rollback()
        return jsonify({'mensagem': 'Venda concorrente. Confira o extrato antes de repetir.'}), 409
    except Exception:
        con.rollback()
        return jsonify({
            'mensagem': 'Erro ao realizar compra',
        }), 500
    finally:
        if cursor:
            cursor.close()

