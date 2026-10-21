"""GET routes for the Arkhe HTTP API."""
from flask import jsonify, request

from banco import con
from funcao import calcular_saldo
from main import app
from pdf import gerar_boleto_pdf

from .common import autenticar_requisicao, nome_cliente_api, obter_periodo


@app.route('/api/v1/conta', methods=['GET'])
def api_conta():
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

    if erro:
        return erro

    cursor = con.cursor()

    try:
        cursor.execute(
            """SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA,
                      U.NOME, C.NOME_FANTASIA, C.RAZAO_SOCIAL
               FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_CONTA = ?""",
            (integracao['id_conta'],)
        )

        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 404

        nome = nome_cliente_api(
            conta[5],
            conta[6],
            conta[7],
            conta[4]
        )

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
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

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
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

    if erro:
        return erro

    id_conta = integracao['id_conta']
    data_inicio, data_fim, erro_periodo = obter_periodo()

    if erro_periodo:
        return erro_periodo

    cursor = con.cursor()

    try:
        cursor.execute(
            """SELECT M.ID_MOVIMENTACAO, M.ID_PAGADOR, M.ID_RECEBEDOR,
                      M.VALOR, M.DATA_MOVIMENTACAO, M.ID_COBRANCA,
                      COB.TIPO_COBRANCA,
                      UP.NOME, CP.NOME_FANTASIA, CP.RAZAO_SOCIAL, CP.TIPO_CONTA,
                      UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA
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
            (
                id_conta,
                id_conta,
                data_inicio,
                data_fim
            )
        )

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

            nome_contraparte = (
                nome_recebedor
                if tipo == 'saida'
                else nome_pagador
            )

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
        return jsonify({
            'mensagem': 'Erro ao consultar movimentacoes'
        }), 500

    finally:
        cursor.close()


@app.route('/api/v1/resumo-financeiro', methods=['GET'])
def api_resumo_financeiro():
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

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


@app.route('/api/v1/cobrancas/pix/<int:id_cobranca>', methods=['GET'])
def api_consultar_cobranca_pix(id_cobranca):
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

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
            'valor': float(cobranca[2]) if cobranca[2] is not None else None,
            'valor_livre': cobranca[2] is None,
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


@app.route('/api/v1/cobrancas/boletos/<int:id_cobranca>', methods=['GET'])
def api_consultar_boleto(id_cobranca):
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
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
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
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
