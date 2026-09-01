from flask import jsonify, request, make_response, render_template
from main import app, con
from funcao import gerar_token, descobre_tipo_usuario, descobre_id_usuario, gerar_codigo, enviando_email, data_atual, calcular_saldo
import bcrypt
import threading

@app.route('/adicionar_cobranca', methods=['POST'])
def adicionar_cobranca():
    dados = request.json
    valor = dados.get('valor')
    data_vencimento = dados.get('data_vencimento')
    agencia = dados.get('agencia')
    banco = dados.get('banco')
    numero_conta = dados.get('numero_conta')

    id_usuario_criador = descobre_id_usuario()

    if not id_usuario_criador:
        return jsonify({"message": "Usuario nao logado"}), 403
    
    cursor = con.cursor()
    cursor.execute(""" SELECT c.ID_CONTA , c.AGENCIA , c.BANCO , c.NUMERO_CONTA, c.ID_USUARIO 
                        FROM CONTA c 
                        WHERE c.AGENCIA = ? and c.BANCO = ? AND c.NUMERO_CONTA = ?""", 
                        (agencia, banco, numero_conta))
    
    conta_recebedor = cursor.fetchone()
    id_usuario_conta_pagador = conta_recebedor[4]
    
    cursor.execute(""" select id_conta from conta where id_usuario = ?""", 
                   (id_usuario_criador,))
    conta = cursor.fetchone()
    conta_criador = conta[0]

    cursor.execute(""" select id_conta from conta where id_usuario = ?""",
                   (id_usuario_conta_pagador,))
    conta = cursor.fetchone()
    conta_pagador = conta[0]

    cursor.execute(""" insert into cobranca (valor, data_vencimento, id_conta_pagador, id_conta_criador) values (?, ?, ?, ?)""",
                   (valor, data_vencimento, conta_pagador, conta_criador))
    con.commit()

    return jsonify({"message": "Cobrança adicionada com sucesso!"}), 200

@app.route('/baixar_cobranca', methods=['POST'])
def baixar_cobranca():
    dados = request.json
    id_cobranca = dados.get('id_cobranca')
    cursor = con.cursor()

    cursor.execute("""select id_cobranca, id_pagador, id_recebedor, 
    valor, status from cobranca where id_cobranca = ?""",
                   (id_cobranca,))
    cobranca = cursor.fetchone()
    id_cobranca = cobranca[0]
    id_pagador = cobranca[1]
    id_recebedor = cobranca[2]
    valor = cobranca[3]
    status = cobranca[4]

    saldo = calcular_saldo()
    if saldo < valor:
        return jsonify({"message": "Saldo insuficiente para baixar a cobrança!"}), 400
    data_atual = data_atual()

    if status == 1:
        return jsonify({"message": "Cobrança já foi baixada!"}), 400
    
    cursor.execute(""" update cobranca set status = 1 where id_cobranca = ?""",
                   (id_cobranca,))
    
    cursor.execute(""" insert into movimentacao (valor, 
                                                data_movimentacao,
                                                id_cobranca,
                                                id_pagador,
                                                id_recebedor)
                        values (?, ?, ?, ?, ?)""",
                        (valor, data_atual, id_cobranca, id_pagador, id_recebedor))
    con.commit()

    return jsonify({"message": "Cobrança baixada com sucesso!"}), 200
