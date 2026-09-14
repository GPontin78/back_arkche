from flask import request, jsonify
from main import app, con
from funcao import descobre_id_conta, criptografar_pin, verificar_pin
import uuid


def autenticar_integracao():
    client_id = request.headers.get('X-Client-ID')
    client_secret = request.headers.get('X-Client-Secret')

    if not client_id or not client_secret:
        return None, (jsonify({'mensagem': 'Credenciais da API nao informadas'}), 401)

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT ID_INTEGRACAO, ID_CONTA, CLIENT_SECRET_HASH, ATIVO FROM INTEGRACAO_API WHERE CLIENT_ID = ?""", (client_id,))
        integracao = cursor.fetchone()

        if not integracao:
            return None, (jsonify({'mensagem': 'Credenciais da API invalidas'}), 401)

        id_integracao = integracao[0]
        id_conta = integracao[1]
        client_secret_hash = integracao[2]
        ativo = integracao[3]

        if ativo != 1:
            return None, (jsonify({'mensagem': 'Integracao desativada'}), 403)

        if not verificar_pin(client_secret, client_secret_hash):
            return None, (jsonify({'mensagem': 'Credenciais da API invalidas'}), 401)

        cursor.execute("""UPDATE INTEGRACAO_API SET ULTIMO_USO = CURRENT_TIMESTAMP WHERE ID_INTEGRACAO = ?""", (id_integracao,))
        con.commit()

        return {
            'id_integracao': id_integracao,
            'id_conta': id_conta
        }, None

    except Exception as e:
        con.rollback()
        print('ERRO AUTENTICAR INTEGRACAO:', e)
        return None, (jsonify({'mensagem': 'Erro ao autenticar integracao'}), 500)

    finally:
        cursor.close()


@app.route('/integracoes/api', methods=['POST'])
def criar_integracao_api():
    id_conta = descobre_id_conta()
    dados = request.get_json() or {}
    nome = dados.get('nome')

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if not nome:
        return jsonify({'mensagem': 'Nome da integracao nao informado'}), 400

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?""", (id_conta,))
        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 404

        if conta[0] != 1:
            return jsonify({'mensagem': 'Integracoes disponiveis apenas para contas PJ'}), 403

        client_id = uuid.uuid4().hex
        client_secret = uuid.uuid4().hex
        client_secret_hash = criptografar_pin(client_secret)

        cursor.execute("""INSERT INTO INTEGRACAO_API (ID_CONTA, NOME, CLIENT_ID, CLIENT_SECRET_HASH, ATIVO) VALUES (?, ?, ?, ?, ?) RETURNING ID_INTEGRACAO""",
                       (id_conta, nome.strip(), client_id, client_secret_hash, 1))

        id_integracao = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Integracao criada com sucesso',
            'id_integracao': id_integracao,
            'nome': nome.strip(),
            'client_id': client_id,
            'client_secret': client_secret
        }), 201

    except Exception as e:
        con.rollback()
        print('ERRO CRIAR INTEGRACAO:', e)
        return jsonify({'mensagem': 'Erro ao criar integracao'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/conta', methods=['GET'])
def api_conta():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA, U.NOME, U.NOME_FANTASIA, U.RAZAO_SOCIAL FROM CONTA C INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO WHERE C.ID_CONTA = ?""",
                       (integracao['id_conta'],))

        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 404

        nome = conta[6] or conta[7] or conta[5]

        return jsonify({
            'id_conta': conta[0],
            'numero_conta': conta[1],
            'agencia': conta[2],
            'banco': conta[3],
            'tipo_conta': conta[4],
            'nome': nome
        }), 200

    except Exception as e:
        print('ERRO API CONTA:', e)
        return jsonify({'mensagem': 'Erro ao consultar conta'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/saldo', methods=['GET'])
def api_saldo():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    id_conta = integracao['id_conta']
    cursor = con.cursor()

    try:
        cursor.execute("""SELECT COALESCE(SUM(CASE WHEN ID_RECEBEDOR = ? THEN VALOR ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN ID_PAGADOR = ? THEN VALOR ELSE 0 END), 0) FROM MOVIMENTACAO WHERE ID_RECEBEDOR = ? OR ID_PAGADOR = ?""",
                       (id_conta, id_conta, id_conta, id_conta))

        saldo = cursor.fetchone()[0]

        return jsonify({
            'saldo': float(saldo or 0)
        }), 200

    except Exception as e:
        print('ERRO API SALDO:', e)
        return jsonify({'mensagem': 'Erro ao consultar saldo'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/movimentacoes', methods=['GET'])
def api_movimentacoes():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    id_conta = integracao['id_conta']
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    cursor = con.cursor()

    try:
        sql = """SELECT ID_MOVIMENTACAO, ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA FROM MOVIMENTACAO WHERE (ID_PAGADOR = ? OR ID_RECEBEDOR = ?)"""
        parametros = [id_conta, id_conta]

        if data_inicio:
            sql += """ AND DATA_MOVIMENTACAO >= ?"""
            parametros.append(data_inicio)

        if data_fim:
            sql += """ AND DATA_MOVIMENTACAO < DATEADD(1 DAY TO CAST(? AS DATE))"""
            parametros.append(data_fim)

        sql += """ ORDER BY DATA_MOVIMENTACAO DESC"""

        cursor.execute(sql, tuple(parametros))
        movimentacoes = cursor.fetchall()

        resultado = []

        for movimentacao in movimentacoes:
            tipo = 'entrada' if movimentacao[2] == id_conta else 'saida'

            resultado.append({
                'id_movimentacao': movimentacao[0],
                'id_pagador': movimentacao[1],
                'id_recebedor': movimentacao[2],
                'valor': float(movimentacao[3]),
                'data_movimentacao': str(movimentacao[4]),
                'id_cobranca': movimentacao[5],
                'tipo': tipo
            })

        return jsonify(resultado), 200

    except Exception as e:
        print('ERRO API MOVIMENTACOES:', e)
        return jsonify({'mensagem': 'Erro ao consultar movimentacoes'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/cobrancas/pix', methods=['POST'])
def api_criar_cobranca_pix():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    dados = request.get_json() or {}
    valor = dados.get('valor')
    id_recebedor = integracao['id_conta']

    if valor is None:
        return jsonify({'mensagem': 'Valor nao informado'}), 400

    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return jsonify({'mensagem': 'Valor invalido'}), 400

    if valor <= 0:
        return jsonify({'mensagem': 'O valor deve ser maior que zero'}), 400

    cursor = con.cursor()

    try:
        codigo_pagamento = 'ARKHEPIX:' + uuid.uuid4().hex.upper()

        cursor.execute("""INSERT INTO COBRANCA (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, CODIGO_PAGAMENTO, STATUS, TIPO_COBRANCA) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING ID_COBRANCA""",
                       (None, id_recebedor, valor, None, codigo_pagamento, 0, 1))

        id_cobranca = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'id_cobranca': id_cobranca,
            'valor': valor,
            'codigo_pagamento': codigo_pagamento,
            'status': 0,
            'tipo_cobranca': 1
        }), 201

    except Exception as e:
        con.rollback()
        print('ERRO API CRIAR COBRANCA PIX:', e)
        return jsonify({'mensagem': 'Erro ao criar cobranca Pix'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/cobrancas/pix/<int:id_cobranca>', methods=['GET'])
def api_consultar_cobranca_pix(id_cobranca):
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    id_conta = integracao['id_conta']
    cursor = con.cursor()

    try:
        cursor.execute("""SELECT ID_COBRANCA, ID_RECEBEDOR, VALOR, CODIGO_PAGAMENTO, STATUS, TIPO_COBRANCA FROM COBRANCA WHERE ID_COBRANCA = ? AND ID_RECEBEDOR = ? AND TIPO_COBRANCA = 1""",
                       (id_cobranca, id_conta))

        cobranca = cursor.fetchone()

        if not cobranca:
            return jsonify({'mensagem': 'Cobranca Pix nao encontrada'}), 404

        return jsonify({
            'id_cobranca': cobranca[0],
            'id_recebedor': cobranca[1],
            'valor': float(cobranca[2]),
            'codigo_pagamento': cobranca[3],
            'status': cobranca[4],
            'tipo_cobranca': cobranca[5]
        }), 200

    except Exception as e:
        print('ERRO API CONSULTAR COBRANCA PIX:', e)
        return jsonify({'mensagem': 'Erro ao consultar cobranca Pix'}), 500

    finally:
        cursor.close()