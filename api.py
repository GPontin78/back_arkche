from flask import request, jsonify
from main import app
from banco import con
from funcao import descobre_id_conta, criptografar_pin, verificar_pin, calcular_saldo
import uuid
import datetime


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


def obter_periodo():
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    hoje = datetime.date.today()

    if not data_inicio and not data_fim:
        data_inicio = hoje.replace(day=1).isoformat()
        data_fim = hoje.isoformat()
        return data_inicio, data_fim, None

    if not data_inicio or not data_fim:
        return None, None, (jsonify({'mensagem': 'Informe data_inicio e data_fim juntas'}), 400)

    try:
        inicio = datetime.date.fromisoformat(data_inicio)
        fim = datetime.date.fromisoformat(data_fim)
    except ValueError:
        return None, None, (jsonify({'mensagem': 'Datas invalidas. Use o formato YYYY-MM-DD'}), 400)

    if inicio > fim:
        return None, None, (jsonify({'mensagem': 'data_inicio nao pode ser maior que data_fim'}), 400)

    return inicio.isoformat(), fim.isoformat(), None


def nome_cliente_api(nome, nome_fantasia, razao_social, tipo_conta):
    if tipo_conta == 1:
        return nome_fantasia or razao_social or nome or 'Conta Arkhe'

    return nome or 'Conta Arkhe'


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

        nome = nome_cliente_api(conta[5], conta[6], conta[7], conta[4])

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

    try:
        saldo = calcular_saldo(integracao['id_conta'])

        return jsonify({
            'saldo': float(saldo or 0)
        }), 200

    except Exception as e:
        print('ERRO API SALDO:', e)
        return jsonify({'mensagem': 'Erro ao consultar saldo'}), 500


@app.route('/api/v1/movimentacoes', methods=['GET'])
def api_movimentacoes():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    id_conta = integracao['id_conta']
    data_inicio, data_fim, erro_periodo = obter_periodo()

    if erro_periodo:
        return erro_periodo

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT M.ID_MOVIMENTACAO, M.ID_PAGADOR, M.ID_RECEBEDOR, M.VALOR, M.DATA_MOVIMENTACAO, M.ID_COBRANCA, COB.TIPO_COBRANCA,
                          UP.NOME, UP.NOME_FANTASIA, UP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                          UR.NOME, UR.NOME_FANTASIA, UR.RAZAO_SOCIAL, CR.TIPO_CONTA
                          FROM MOVIMENTACAO M
                          INNER JOIN CONTA CP ON CP.ID_CONTA = M.ID_PAGADOR
                          INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
                          INNER JOIN CONTA CR ON CR.ID_CONTA = M.ID_RECEBEDOR
                          INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                          LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
                          WHERE (M.ID_PAGADOR = ? OR M.ID_RECEBEDOR = ?)
                          AND M.DATA_MOVIMENTACAO >= CAST(? AS DATE)
                          AND M.DATA_MOVIMENTACAO < DATEADD(1 DAY TO CAST(? AS DATE))
                          ORDER BY M.DATA_MOVIMENTACAO DESC""",
                       (id_conta, id_conta, data_inicio, data_fim))

        movimentacoes = cursor.fetchall()
        resultado = []

        for movimentacao in movimentacoes:
            tipo = 'entrada' if movimentacao[2] == id_conta else 'saida'

            if movimentacao[5] is None:
                origem = 'pix'
            elif movimentacao[6] == 1:
                origem = 'pix_qrcode'
            else:
                origem = 'boleto'

            nome_pagador = nome_cliente_api(
                movimentacao[7],
                movimentacao[8],
                movimentacao[9],
                movimentacao[10]
            )

            nome_recebedor = nome_cliente_api(
                movimentacao[11],
                movimentacao[12],
                movimentacao[13],
                movimentacao[14]
            )

            nome_contraparte = nome_recebedor if tipo == 'saida' else nome_pagador

            resultado.append({
                'id_movimentacao': movimentacao[0],
                'id_pagador': movimentacao[1],
                'nome_pagador': nome_pagador,
                'id_recebedor': movimentacao[2],
                'nome_recebedor': nome_recebedor,
                'nome_contraparte': nome_contraparte,
                'valor': float(movimentacao[3]),
                'data_movimentacao': str(movimentacao[4]),
                'id_cobranca': movimentacao[5],
                'tipo_cobranca': movimentacao[6],
                'tipo': tipo,
                'origem': origem
            })

        return jsonify({
            'data_inicio': data_inicio,
            'data_fim': data_fim,
            'movimentacoes': resultado
        }), 200

    except Exception as e:
        print('ERRO API MOVIMENTACOES:', e)
        return jsonify({'mensagem': 'Erro ao consultar movimentacoes'}), 500

    finally:
        cursor.close()


@app.route('/api/v1/resumo-financeiro', methods=['GET'])
def api_resumo_financeiro():
    integracao, erro = autenticar_integracao()

    if erro:
        return erro

    id_conta = integracao['id_conta']
    data_inicio, data_fim, erro_periodo = obter_periodo()

    if erro_periodo:
        return erro_periodo

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT CAST(COALESCE(SUM(VALOR), 0) AS DECIMAL(18,2)) FROM MOVIMENTACAO WHERE ID_RECEBEDOR = ? AND DATA_MOVIMENTACAO >= CAST(? AS DATE) AND DATA_MOVIMENTACAO < DATEADD(1 DAY TO CAST(? AS DATE))""",
                       (id_conta, data_inicio, data_fim))
        total_receitas = cursor.fetchone()[0]

        cursor.execute("""SELECT CAST(COALESCE(SUM(VALOR), 0) AS DECIMAL(18,2)) FROM MOVIMENTACAO WHERE ID_PAGADOR = ? AND DATA_MOVIMENTACAO >= CAST(? AS DATE) AND DATA_MOVIMENTACAO < DATEADD(1 DAY TO CAST(? AS DATE))""",
                       (id_conta, data_inicio, data_fim))
        total_despesas = cursor.fetchone()[0]

        total_receitas = float(total_receitas or 0)
        total_despesas = float(total_despesas or 0)

        return jsonify({
            'data_inicio': data_inicio,
            'data_fim': data_fim,
            'total_receitas': total_receitas,
            'total_despesas': total_despesas,
            'saldo_periodo': total_receitas - total_despesas
        }), 200

    except Exception as e:
        print('ERRO API RESUMO FINANCEIRO:', e)
        return jsonify({'mensagem': 'Erro ao consultar resumo financeiro'}), 500

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


@app.route('/integracoes/api', methods=['GET'])
def listar_integracoes_api():
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT ID_INTEGRACAO, NOME, CLIENT_ID, ATIVO, DATA_CRIACAO, ULTIMO_USO FROM INTEGRACAO_API WHERE ID_CONTA = ? ORDER BY DATA_CRIACAO DESC""", (id_conta,))
        integracoes = cursor.fetchall()

        resultado = []

        for integracao in integracoes:
            resultado.append({
                'id_integracao': integracao[0],
                'nome': integracao[1],
                'client_id': integracao[2],
                'ativo': integracao[3],
                'data_criacao': str(integracao[4]) if integracao[4] else None,
                'ultimo_uso': str(integracao[5]) if integracao[5] else None
            })

        return jsonify(resultado), 200

    except Exception as e:
        print('ERRO LISTAR INTEGRACOES:', e)
        return jsonify({'mensagem': 'Erro ao listar integracoes'}), 500

    finally:
        cursor.close()


@app.route('/integracoes/api/<int:id_integracao>/regenerar-secret', methods=['POST'])
def regenerar_secret_integracao(id_integracao):
    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT ID_INTEGRACAO FROM INTEGRACAO_API WHERE ID_INTEGRACAO = ? AND ID_CONTA = ?""", (id_integracao, id_conta))
        integracao = cursor.fetchone()

        if not integracao:
            return jsonify({'mensagem': 'Integracao nao encontrada'}), 404

        client_secret = uuid.uuid4().hex
        client_secret_hash = criptografar_pin(client_secret)

        cursor.execute("""UPDATE INTEGRACAO_API SET CLIENT_SECRET_HASH = ? WHERE ID_INTEGRACAO = ? AND ID_CONTA = ?""", (client_secret_hash, id_integracao, id_conta))
        con.commit()

        return jsonify({
            'mensagem': 'Novo Client Secret gerado',
            'client_secret': client_secret
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO REGENERAR SECRET:', e)
        return jsonify({'mensagem': 'Erro ao gerar novo Client Secret'}), 500

    finally:
        cursor.close()
