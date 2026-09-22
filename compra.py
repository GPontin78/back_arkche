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
            return jsonify({'mensagem': 'Usuario nao logado'}), 403
        
        cursor = con.cursor()

        cursor.execute("""SELECT C.ID_CARTAO, C.ID_CONTA, c.limite
                            FROM CARTAO c 
                            INNER JOIN CONTA cn ON C.ID_CONTA = CN.ID_CONTA 
                            WHERE C.NUMERO_CARTAO = ?""", (numero_cartao,))
        cartao = cursor.fetchone()
        id_cartao_pagador = cartao[0]
        id_conta_pagador = cartao[1]
        limite_cartao = float(cartao[2] or 0)
        data_compra = data_atual()
        
        if tipo == 0: #debito

            cursor.execute("""SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
                                FROM MOVIMENTACAO M
                                WHERE M.ID_RECEBEDOR = ?""", (id_conta_pagador,))

            receita = cursor.fetchone()[0]

            cursor.execute("""SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
                                FROM MOVIMENTACAO M
                                WHERE M.ID_PAGADOR = ?""", (id_conta_pagador,))

            despesa = cursor.fetchone()[0]

            saldo = receita - despesa

            if saldo < valor_compra:
                return jsonify({'mensagem': 'Erro ao realizar compra, saldo insuficiente'}), 500

            cursor.execute(""" insert into compra (id_cartao, valor_compra, data_compra, tipo)
            values (?, ?, ?, ?)""", (id_cartao_pagador, valor_compra, data_compra, tipo))


            cursor.execute(""" insert into movimentacao(id_pagador, id_recebedor, valor, data_movimentacao)
            values (?, ?, ?, ?)""", (id_conta_pagador, id_conta, valor_compra, data_compra))

            con.commit()
            return jsonify({'mensagem': 'Compra realizada com sucesso'}), 200
        
        if tipo == 1: #credito

            limite_cartao_utilizado = calcular_limite_cartao(id_cartao_pagador)

            if limite_cartao_utilizado + valor_compra > limite_cartao:
                return jsonify({'mensagem': 'Erro ao realizar compra, limite insuficiente'}), 400

            valor_parcela = valor_compra / qtd_parcela

            cursor.execute(""" insert into compra (id_cartao, valor_compra, data_compra, tipo, valor_parcela, qtd_parcela)
            values (?, ?, ?, ?, ?, ?)""", (id_cartao_pagador, valor_compra, data_compra, tipo, valor_parcela, qtd_parcela))

            valor_recebido_vendedor = valor_compra * 0.95

            cursor.execute(""" insert into movimentacao(id_pagador, id_recebedor, valor, data_movimentacao)
            values (?, ?, ?, ?)""", (id_conta_pagador, id_conta, valor_recebido_vendedor, data_compra))

            con.commit()

            return jsonify({'mensagem': 'Compra realizada com sucesso'}), 200

    except Exception as e:

        return jsonify({'mensagem': 'Erro ao realizar compra','erro': str(e)}), 500




        




        