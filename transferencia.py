from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, data_atual, calcular_saldo
import uuid

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

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR, STATUS
                          FROM COBRANCA
                          WHERE ID_COBRANCA = ?""",
                       (id_cobranca,))

        cobranca = cursor.fetchone()

        if not cobranca:
            return jsonify({'mensagem': 'Cobranca nao encontrada'}), 404

        id_recebedor = cobranca[2]
        valor = cobranca[3]
        status = cobranca[4]

        if status == 1:
            return jsonify({'mensagem': 'Cobranca ja foi paga'}), 400

        if id_conta == id_recebedor:
            return jsonify({'mensagem': 'A conta recebedora nao pode pagar o proprio boleto'}), 400

        saldo = calcular_saldo(id_conta)

        if saldo < valor:
            return jsonify({'mensagem': 'Saldo insuficiente para pagar a cobranca'}), 400

        data_movimentacao = data_atual()

        cursor.execute("""UPDATE COBRANCA SET STATUS = 1 WHERE ID_COBRANCA = ?""",
                       (id_cobranca,))

        cursor.execute("""INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA)
                          VALUES (?, ?, ?, ?, ?) RETURNING ID_MOVIMENTACAO""",
                       (id_conta, id_recebedor, valor, data_movimentacao, id_cobranca))

        id_movimentacao = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Cobranca paga com sucesso',
            'id_movimentacao': id_movimentacao
        }), 200

    except Exception as e:
        con.rollback()
        print("ERRO:", e)
        return jsonify({'mensagem': 'Erro ao pagar cobranca'}), 500

    finally:
        if cursor:
            cursor.close()


                        
@app.route('/adicionar_pix', methods=['POST'])
def adicionar_pix():
    dados = request.get_json()
    tipo_chave = dados.get('tipo_chave')
    chave_pix = dados.get('chave_pix')
    valor = dados.get('valor')

    id_pagador = descobre_id_conta()

    if not id_pagador:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
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
            return jsonify({'mensagem': 'Tipo de chave Pix invalido'}), 400

        conta_recebedor = cursor.fetchone()

        if not conta_recebedor:
            return jsonify({'mensagem': 'Chave Pix nao encontrada'}), 404

        id_recebedor = conta_recebedor[0]

        if id_pagador == id_recebedor:
            return jsonify({'mensagem': 'Nao e possivel fazer Pix para a mesma conta'}), 400

        saldo = calcular_saldo(id_pagador)
        print("ID PAGADOR:", id_pagador, "TIPO:", type(id_pagador), "SALDO:", saldo, "VALOR:", valor)
        if id_pagador != 9:
            if saldo < valor:
                return jsonify({'mensagem': 'Saldo insuficiente para realizar o Pix'}), 400

        data_movimentacao = data_atual()

        cursor.execute("""INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
                          VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO""",
                       (id_pagador, id_recebedor, valor, data_movimentacao))

        id_movimentacao = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Pix realizado com sucesso',
            'id_movimentacao': id_movimentacao
        }), 201

    except Exception as e:
        con.rollback()
        print("ERRO:", e)
        return jsonify({'mensagem': 'Erro ao realizar Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/buscar_movimentacoes', methods=['GET'])
def buscar_movimentacoes():
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT COB.ID_COBRANCA, COB.ID_PAGADOR, COB.ID_RECEBEDOR, COB.VALOR, COB.DATA_VENCIMENTO, COB.STATUS, COB.TIPO_COBRANCA,
                                 UP.NOME, CP.NOME_FANTASIA, CP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                                 UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA
                          FROM COBRANCA COB
                          INNER JOIN CONTA CP ON CP.ID_CONTA = COB.ID_PAGADOR
                          INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
                          INNER JOIN CONTA CR ON CR.ID_CONTA = COB.ID_RECEBEDOR
                          INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                          WHERE (COB.ID_PAGADOR = ? OR COB.ID_RECEBEDOR = ?) AND COB.TIPO_COBRANCA = 0
                          ORDER BY COB.DATA_VENCIMENTO DESC""",
                       (id_conta, id_conta))

        cobrancas_banco = cursor.fetchall()
        cobrancas = []

        for cobranca in cobrancas_banco:
            tipo = 'pagar' if cobranca[1] == id_conta else 'receber'

            if cobranca[10] == 1:
                nome_pagador = cobranca[8] or cobranca[9] or cobranca[7]
            else:
                nome_pagador = cobranca[7]

            if cobranca[14] == 1:
                nome_recebedor = cobranca[12] or cobranca[13] or cobranca[11]
            else:
                nome_recebedor = cobranca[11]

            cobrancas.append({
                'id_cobranca': cobranca[0],
                'id_pagador': cobranca[1],
                'id_recebedor': cobranca[2],
                'valor': float(cobranca[3]),
                'data_vencimento': str(cobranca[4]) if cobranca[4] else None,
                'status': cobranca[5],
                'tipo_cobranca': cobranca[6],
                'tipo': tipo,
                'nome_pagador': nome_pagador,
                'nome_recebedor': nome_recebedor
            })

        cursor.execute("""SELECT M.ID_MOVIMENTACAO, M.ID_PAGADOR, M.ID_RECEBEDOR, M.VALOR, M.DATA_MOVIMENTACAO, M.ID_COBRANCA, COB.TIPO_COBRANCA,
                                 UP.NOME, CP.NOME_FANTASIA, CP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                                 UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA
                          FROM MOVIMENTACAO M
                          INNER JOIN CONTA CP ON CP.ID_CONTA = M.ID_PAGADOR
                          INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
                          INNER JOIN CONTA CR ON CR.ID_CONTA = M.ID_RECEBEDOR
                          INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                          LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
                          WHERE M.ID_PAGADOR = ? OR M.ID_RECEBEDOR = ?
                          ORDER BY M.DATA_MOVIMENTACAO DESC""",
                       (id_conta, id_conta))

        movimentacoes_banco = cursor.fetchall()
        movimentacoes = []

        for movimentacao in movimentacoes_banco:
            tipo = 'saida' if movimentacao[1] == id_conta else 'entrada'

            if movimentacao[5] is None:
                origem = 'pix'
            elif movimentacao[6] == 1:
                origem = 'pix_qrcode'
            else:
                origem = 'boleto'

            if movimentacao[10] == 1:
                nome_pagador = movimentacao[8] or movimentacao[9] or movimentacao[7]
            else:
                nome_pagador = movimentacao[7]

            if movimentacao[14] == 1:
                nome_recebedor = movimentacao[12] or movimentacao[13] or movimentacao[11]
            else:
                nome_recebedor = movimentacao[11]

            nome_contraparte = nome_recebedor if tipo == 'saida' else nome_pagador

            movimentacoes.append({
                'id_movimentacao': movimentacao[0],
                'id_pagador': movimentacao[1],
                'id_recebedor': movimentacao[2],
                'valor': float(movimentacao[3]),
                'data_movimentacao': str(movimentacao[4]),
                'id_cobranca': movimentacao[5],
                'tipo_cobranca': movimentacao[6],
                'tipo': tipo,
                'origem': origem,
                'nome_pagador': nome_pagador,
                'nome_recebedor': nome_recebedor,
                'nome_contraparte': nome_contraparte
            })

        return jsonify({
            'cobrancas': cobrancas,
            'movimentacoes': movimentacoes
        }), 200

    except Exception as e:
        print("ERRO BUSCAR MOVIMENTACOES:", e)
        return jsonify({'mensagem': 'Erro ao buscar movimentacoes'}), 500

    finally:
        if cursor:
            cursor.close()
@app.route('/buscar_cobranca_codigo', methods=['POST'])
def buscar_cobranca_codigo():
    dados = request.get_json() or {}
    codigo_pagamento = dados.get('codigo_pagamento')

    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if not codigo_pagamento:
        return jsonify({'mensagem': 'Codigo de pagamento nao informado'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT COB.ID_COBRANCA, COB.ID_PAGADOR, COB.ID_RECEBEDOR, COB.VALOR, COB.DATA_VENCIMENTO,
                                 COB.CODIGO_PAGAMENTO, COB.STATUS, COB.TIPO_COBRANCA,
                                 U.NOME, C.NOME_FANTASIA, C.RAZAO_SOCIAL, C.TIPO_CONTA
                          FROM COBRANCA COB
                          INNER JOIN CONTA C ON C.ID_CONTA = COB.ID_RECEBEDOR
                          INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE COB.CODIGO_PAGAMENTO = ?""",
                       (codigo_pagamento,))

        cobranca = cursor.fetchone()

        if not cobranca:
            return jsonify({'mensagem': 'Cobranca nao encontrada'}), 404

        if cobranca[11] == 1:
            nome_recebedor = cobranca[9] or cobranca[10] or cobranca[8]
        else:
            nome_recebedor = cobranca[8]

        return jsonify({
            'id_cobranca': cobranca[0],
            'id_pagador': cobranca[1],
            'id_recebedor': cobranca[2],
            'valor': float(cobranca[3]),
            'data_vencimento': str(cobranca[4]) if cobranca[4] else None,
            'codigo_pagamento': cobranca[5],
            'status': cobranca[6],
            'tipo_cobranca': cobranca[7],
            'recebedor': nome_recebedor
        }), 200

    except Exception as e:
        print("ERRO BUSCAR COBRANCA:", e)
        return jsonify({'mensagem': 'Erro ao buscar cobranca'}), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/criar_cobranca_pix', methods=['POST'])
def criar_cobranca_pix():
    dados = request.get_json()
    valor = dados.get('valor')
    id_recebedor = descobre_id_conta()

    if not id_recebedor:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if valor is None:
        return jsonify({'mensagem': 'Valor nao informado'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        codigo_pagamento = 'ARKHEPIX:' + uuid.uuid4().hex.upper()

        cursor.execute("""INSERT INTO COBRANCA (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, CODIGO_PAGAMENTO, STATUS, TIPO_COBRANCA)
                          VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING ID_COBRANCA""",
                       (None, id_recebedor, valor, None, codigo_pagamento, 0, 1))

        id_cobranca = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Cobranca Pix criada com sucesso',
            'id_cobranca': id_cobranca,
            'codigo_pagamento': codigo_pagamento,
            'valor': valor,
            'status': 0,
            'tipo_cobranca': 1
        }), 201

    except Exception as e:
        con.rollback()
        print("ERRO:", e)
        return jsonify({'mensagem': 'Erro ao criar cobranca Pix'}), 500

    finally:
        if cursor:
            cursor.close()