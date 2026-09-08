from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, data_atual, calcular_saldo

@app.route('/adicionar_cobranca', methods=['POST'])
def adicionar_cobranca():
    dados = request.get_json()
    id_pagador = dados.get('id_pagador')
    valor = dados.get('valor')
    data_vencimento = dados.get('data_vencimento')

    id_recebedor = descobre_id_conta()

    if not id_recebedor:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    cursor.execute("""SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?""", (id_recebedor,))
    conta_recebedor = cursor.fetchone()

    if not conta_recebedor:
        cursor.close()
        return jsonify({'mensagem': 'Conta recebedora nao encontrada'}), 404

    if conta_recebedor[0] != 1:
        cursor.close()
        return jsonify({'mensagem': 'Apenas contas PJ podem criar boletos'}), 403

    cursor.execute("""SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ?""", (id_pagador,))
    conta_pagador = cursor.fetchone()

    if not conta_pagador:
        cursor.close()
        return jsonify({'mensagem': 'Conta pagadora nao encontrada'}), 404

    cursor.execute("""INSERT INTO COBRANCA (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, STATUS)
                      VALUES (?, ?, ?, ?, ?) RETURNING ID_COBRANCA""",
                   (id_pagador, id_recebedor, valor, data_vencimento, 0))

    id_cobranca = cursor.fetchone()[0]

    codigo_pagamento = '248' + str(id_cobranca).zfill(10)

    cursor.execute("""UPDATE COBRANCA SET CODIGO_PAGAMENTO = ? WHERE ID_COBRANCA = ?""",
                   (codigo_pagamento, id_cobranca))

    con.commit()
    cursor.close()

    return jsonify({
        'mensagem': 'Boleto criado com sucesso',
        'id_cobranca': id_cobranca,
        'codigo_pagamento': codigo_pagamento,
        'valor': valor,
        'data_vencimento': data_vencimento
    }), 201


@app.route('/baixar_cobranca', methods=['POST'])
def baixar_cobranca():
    dados = request.get_json()
    id_cobranca = dados.get('id_cobranca')

    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    cursor.execute("""SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR, STATUS FROM COBRANCA WHERE ID_COBRANCA = ?""", (id_cobranca,))
    cobranca = cursor.fetchone()

    if not cobranca:
        cursor.close()
        return jsonify({'mensagem': 'Cobranca nao encontrada'}), 404

    id_pagador = cobranca[1]
    id_recebedor = cobranca[2]
    valor = cobranca[3]
    status = cobranca[4]

    if id_pagador != id_conta:
        cursor.close()
        return jsonify({'mensagem': 'Essa cobranca nao pertence a esta conta'}), 403

    if status == 1:
        cursor.close()
        return jsonify({'mensagem': 'Cobranca ja foi paga'}), 400

    saldo = calcular_saldo(id_conta)

    if saldo < valor:
        cursor.close()
        return jsonify({'mensagem': 'Saldo insuficiente para pagar a cobranca'}), 400

    data_movimentacao = data_atual()

    cursor.execute("""UPDATE COBRANCA SET STATUS = 1 WHERE ID_COBRANCA = ?""", (id_cobranca,))
    cursor.execute("""INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA) VALUES (?, ?, ?, ?, ?)""", (id_pagador, id_recebedor, valor, data_movimentacao, id_cobranca))

    con.commit()
    cursor.close()

    return jsonify({'mensagem': 'Cobranca paga com sucesso'}), 200


@app.route('/adicionar_pix', methods=['POST'])
def adicionar_pix():
    dados = request.get_json()
    tipo_chave = dados.get('tipo_chave')
    chave_pix = dados.get('chave_pix')
    valor = dados.get('valor')

    id_pagador = descobre_id_conta()

    if not id_pagador:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    if tipo_chave == 'email':
        cursor.execute("""SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_EMAIL = ?""", (chave_pix,))

    elif tipo_chave == 'telefone':
        cursor.execute("""SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_TELEFONE = ?""", (chave_pix,))

    elif tipo_chave == 'cpf':
        cursor.execute("""SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_CPF = ?""", (chave_pix,))

    elif tipo_chave == 'cnpj':
        cursor.execute("""SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_CNPJ = ?""", (chave_pix,))

    elif tipo_chave == 'aleatoria':
        cursor.execute("""SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_ALEATORIA = ?""", (chave_pix,))

    else:
        cursor.close()
        return jsonify({'mensagem': 'Tipo de chave Pix invalido'}), 400

    conta_recebedor = cursor.fetchone()

    if not conta_recebedor:
        cursor.close()
        return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

    id_recebedor = conta_recebedor[0]

    if id_pagador == id_recebedor:
        cursor.close()
        return jsonify({'mensagem': 'Nao e possivel fazer Pix para a mesma conta'}), 400

    saldo = calcular_saldo(id_pagador)

    if saldo < valor:
        cursor.close()
        return jsonify({'mensagem': 'Saldo insuficiente para realizar o Pix'}), 400

    data_movimentacao = data_atual()

    cursor.execute("""INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
                      VALUES (?, ?, ?, ?)""",
                   (id_pagador, id_recebedor, valor, data_movimentacao))

    con.commit()
    cursor.close()

    return jsonify({'mensagem': 'Pix realizado com sucesso'}), 201


@app.route('/buscar_movimentacoes', methods=['GET'])
def buscar_movimentacoes():
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    cursor.execute("""SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, STATUS FROM COBRANCA WHERE ID_PAGADOR = ? OR ID_RECEBEDOR = ? ORDER BY DATA_VENCIMENTO DESC""", (id_conta, id_conta))
    cobrancas_banco = cursor.fetchall()

    cobrancas = []

    for cobranca in cobrancas_banco:
        if cobranca[1] == id_conta:
            tipo = 'pagar'
        else:
            tipo = 'receber'

        cobrancas.append({
            'id_cobranca': cobranca[0],
            'id_pagador': cobranca[1],
            'id_recebedor': cobranca[2],
            'valor': float(cobranca[3]),
            'data_vencimento': str(cobranca[4]),
            'status': cobranca[5],
            'tipo': tipo
        })

    cursor.execute("""SELECT ID_MOVIMENTACAO, ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA FROM MOVIMENTACAO WHERE ID_PAGADOR = ? OR ID_RECEBEDOR = ? ORDER BY DATA_MOVIMENTACAO DESC""", (id_conta, id_conta))
    movimentacoes_banco = cursor.fetchall()

    movimentacoes = []

    for movimentacao in movimentacoes_banco:
        if movimentacao[1] == id_conta:
            tipo = 'saida'
        else:
            tipo = 'entrada'

        if movimentacao[5] is None:
            origem = 'pix'
        else:
            origem = 'cobranca'

        movimentacoes.append({
            'id_movimentacao': movimentacao[0],
            'id_pagador': movimentacao[1],
            'id_recebedor': movimentacao[2],
            'valor': float(movimentacao[3]),
            'data_movimentacao': str(movimentacao[4]),
            'id_cobranca': movimentacao[5],
            'tipo': tipo,
            'origem': origem
        })

    cursor.close()

    return jsonify({
        'cobrancas': cobrancas,
        'movimentacoes': movimentacoes
    }), 200