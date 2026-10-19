import datetime
import fdb
from flask import jsonify, request
from main import app
from banco import con
from api import autenticar_integracao, valor_monetario_api
from funcao import data_atual
from pdf import gerar_boleto_pdf


@app.route('/api/v1/cobrancas/boletos', methods=['POST'])
def api_criar_boleto():
    integracao, erro = autenticar_integracao()
    if erro:
        return erro

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400

    documento = ''.join(c for c in str(dados.get('documento_pagador') or '') if c.isdigit())
    valor = valor_monetario_api(dados.get('valor'))
    id_recebedor = integracao['id_conta']

    if len(documento) not in (11, 14):
        return jsonify({'mensagem': 'Informe o CPF ou CNPJ da conta pagadora'}), 400
    if valor is None:
        return jsonify({'mensagem': 'Informe um valor positivo em reais'}), 400

    try:
        vencimento = datetime.date.fromisoformat(str(dados.get('data_vencimento') or ''))
    except ValueError:
        return jsonify({'mensagem': 'Informe data_vencimento no formato YYYY-MM-DD'}), 400

    cursor = None
    try:
        cursor = con.cursor()
        # A trava tambem serializa pedidos repetidos da mesma conta.
        cursor.execute('SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_recebedor,))
        conta = cursor.fetchone()
        if not conta or conta[0] != 1:
            con.rollback()
            return jsonify({'mensagem': 'Apenas contas PJ podem emitir boletos'}), 403

        if vencimento < data_atual().date():
            con.rollback()
            return jsonify({'mensagem': 'O vencimento nao pode estar no passado'}), 400

        cursor.execute(
            """SELECT C.ID_CONTA FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE (C.TIPO_CONTA = 0 AND
                   REPLACE(REPLACE(U.CPF, '.', ''), '-', '') = ?)
                  OR (C.TIPO_CONTA = 1 AND
                   REPLACE(REPLACE(REPLACE(C.CNPJ, '.', ''), '-', ''), '/', '') = ?)""",
            (documento, documento)
        )
        contas = cursor.fetchall()
        if not contas:
            con.rollback()
            return jsonify({'mensagem': 'Conta pagadora Arkhe nao encontrada'}), 404
        if len(contas) != 1:
            con.rollback()
            return jsonify({'mensagem': 'Documento possui mais de uma conta do mesmo tipo; confira o cadastro'}), 409

        id_pagador = contas[0][0]
        if id_pagador == id_recebedor:
            con.rollback()
            return jsonify({'mensagem': 'Pagador e recebedor devem ser contas diferentes'}), 400

        cursor.execute(
            """SELECT FIRST 1 ID_COBRANCA FROM COBRANCA
               WHERE ID_PAGADOR = ? AND ID_RECEBEDOR = ? AND VALOR = ?
                 AND DATA_VENCIMENTO = ? AND STATUS = 0 AND TIPO_COBRANCA = 0
               ORDER BY ID_COBRANCA DESC""",
            (id_pagador, id_recebedor, valor, vencimento)
        )
        existente = cursor.fetchone()
        if existente:
            con.rollback()
            return jsonify({
                'mensagem': 'Ja existe boleto pendente com este pagador, valor e vencimento. Consulte o boleto existente',
                'codigo': 'BOLETO_PENDENTE_EXISTENTE', 'id_cobranca': existente[0]
            }), 409

        cursor.execute(
            """INSERT INTO COBRANCA
               (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, STATUS, TIPO_COBRANCA)
               VALUES (?, ?, ?, ?, 0, 0) RETURNING ID_COBRANCA""",
            (id_pagador, id_recebedor, valor, vencimento)
        )
        id_cobranca = cursor.fetchone()[0]
        codigo = '248' + str(id_cobranca).zfill(10)
        cursor.execute('UPDATE COBRANCA SET CODIGO_PAGAMENTO = ? WHERE ID_COBRANCA = ?', (codigo, id_cobranca))

        resposta = {
            'mensagem': 'Boleto criado com sucesso',
            'id_cobranca': id_cobranca, 'id_pagador': id_pagador, 'id_recebedor': id_recebedor,
            'valor': float(valor), 'data_vencimento': vencimento.isoformat(),
            'codigo_pagamento': codigo, 'status': 0, 'tipo_cobranca': 0,
            'url_pdf': f'/api/v1/cobrancas/boletos/{id_cobranca}/pdf'
        }
        con.commit()
        return jsonify(resposta), 201
    except (fdb.IntegrityError, fdb.TransactionConflict):
        con.rollback()
        return jsonify({'mensagem': 'Operacao concorrente. Confira os boletos antes de enviar novamente'}), 409
    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao emitir boleto'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/cobrancas/boletos/<int:id_cobranca>', methods=['GET'])
def api_consultar_boleto(id_cobranca):
    integracao, erro = autenticar_integracao()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT ID_COBRANCA, ID_PAGADOR, ID_RECEBEDOR, VALOR,
                      DATA_VENCIMENTO, CODIGO_PAGAMENTO, STATUS
               FROM COBRANCA WHERE ID_COBRANCA = ? AND ID_RECEBEDOR = ? AND TIPO_COBRANCA = 0""",
            (id_cobranca, integracao['id_conta'])
        )
        boleto = cursor.fetchone()
        if not boleto:
            return jsonify({'mensagem': 'Boleto nao encontrado'}), 404
        return jsonify({
            'id_cobranca': boleto[0], 'id_pagador': boleto[1], 'id_recebedor': boleto[2],
            'valor': float(boleto[3]), 'data_vencimento': str(boleto[4]),
            'codigo_pagamento': boleto[5], 'status': boleto[6], 'tipo_cobranca': 0,
            'url_pdf': f'/api/v1/cobrancas/boletos/{boleto[0]}/pdf'
        }), 200
    except Exception:
        return jsonify({'mensagem': 'Erro ao consultar boleto'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/api/v1/cobrancas/boletos/<int:id_cobranca>/pdf', methods=['GET'])
def api_boleto_pdf(id_cobranca):
    integracao, erro = autenticar_integracao()
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            'SELECT ID_COBRANCA FROM COBRANCA WHERE ID_COBRANCA = ? AND ID_RECEBEDOR = ? AND TIPO_COBRANCA = 0',
            (id_cobranca, integracao['id_conta'])
        )
        if not cursor.fetchone():
            return jsonify({'mensagem': 'Boleto nao encontrado'}), 404
        return gerar_boleto_pdf(id_cobranca, integracao['id_conta'])
    except Exception:
        return jsonify({'mensagem': 'Erro ao gerar PDF do boleto'}), 500
    finally:
        if cursor:
            cursor.close()
