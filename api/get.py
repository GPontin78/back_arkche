"""GET routes for the Arkhe HTTP API."""
from flask import jsonify, request

from banco import con
from funcao import calcular_saldo, calcular_limite_cartao, descobre_id_conta
from main import app
from pdf import gerar_boleto_pdf

from .common import autenticar_requisicao, nome_cliente_api, obter_periodo


# Dados da conta autenticada: nivel 1 no WhatsApp ou credencial da API externa.
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


# Consulta o saldo somente da conta resolvida pelo mecanismo de autenticacao.
@app.route('/api/v1/saldo', methods=['GET'])
def api_saldo():
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)

    if erro:
        return erro

    cursor = None
    try:
        saldo = calcular_saldo(integracao['id_conta'])
        if saldo is None:
            return jsonify({'mensagem': 'Saldo indisponivel no momento'}), 503
        cursor = con.cursor()
        cursor.execute(
            '''SELECT C.TIPO_CONTA, U.NOME, C.NOME_FANTASIA, C.RAZAO_SOCIAL, C.NUMERO_CONTA
               FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               WHERE C.ID_CONTA = ?''', (integracao['id_conta'],),
        )
        conta = cursor.fetchone()
        if not conta:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 404

        return jsonify({
            'saldo': float(saldo),
            'id_conta': integracao['id_conta'],
            'nome_conta': nome_cliente_api(conta[1], conta[2], conta[3], conta[0]),
            'tipo_conta': conta[0],
            'conta_final': str(conta[4] or '')[-4:],
        }), 200

    except Exception as e:
        print('ERRO API SALDO:', e)
        return jsonify({'mensagem': 'Erro ao consultar saldo'}), 500

    finally:
        if cursor:
            cursor.close()


# Extrato por periodo da conta autenticada; leitura permitida no nivel 1.
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


# Resumo financeiro: receitas, despesas e saldo do periodo da conta autenticada.
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


# Consulta cobranca Pix da conta atual; nunca retorna cobrancas de terceiros.
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


# Consulta boletos da conta atual, com acesso restrito pela autenticacao.
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


# Recupera o PDF de um boleto da conta autenticada; nivel 1 no WhatsApp.
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


# Consulta os boletos pendentes do DDA destinados a conta autenticada.
# Nao lista boletos emitidos por outras pessoas nem dados de outras contas.
@app.route('/api/v1/dda', methods=['GET'])
def api_listar_dda():
    autorizacao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT FIRST 50 CB.ID_COBRANCA, CB.ID_RECEBEDOR, CB.VALOR,
                                 CB.DATA_VENCIMENTO, CB.CODIGO_PAGAMENTO, CB.STATUS,
                                 U.NOME, C.NOME_FANTASIA, C.RAZAO_SOCIAL, C.TIPO_CONTA
                          FROM COBRANCA CB
                          INNER JOIN CONTA C ON C.ID_CONTA = CB.ID_RECEBEDOR
                          INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE CB.ID_PAGADOR = ? AND CB.TIPO_COBRANCA = 0 AND CB.STATUS = 0
                          ORDER BY CB.DATA_VENCIMENTO, CB.ID_COBRANCA''',
                       (autorizacao['id_conta'],))
        cobrancas = []
        for b in cursor.fetchall():
            nome = (b[7] or b[8] or b[6]) if int(b[9]) == 1 else b[6]
            cobrancas.append({'id_cobranca': b[0], 'id_recebedor': b[1],
                              'valor': float(b[2]), 'data_vencimento': str(b[3]) if b[3] else None,
                              'codigo_pagamento': b[4], 'status': b[5], 'recebedor': nome})
        return jsonify({'cobrancas': cobrancas}), 200
    except Exception:
        from main import app
        app.logger.exception('Falha consulta DDA API')
        return jsonify({'mensagem': 'Nao foi possivel consultar DDA'}), 500
    finally:
        if cursor:
            cursor.close()


def _buscar_cartao_api(id_conta):
    """Consulta cartao da conta informada, sem retornar numero completo ou CVV."""
    cursor = con.cursor()
    try:
        cursor.execute('''SELECT ID_CARTAO, NUMERO_CARTAO, VENCIMENTO, LIMITE,
                                 DIA_VENCIMENTO, FECHAMENTO, STATUS, MOTIVO_BLOQUEIO
                          FROM CARTAO WHERE ID_CONTA = ?''', (id_conta,))
        return cursor.fetchone()
    finally:
        cursor.close()


# Lista chaves Pix apenas da conta autenticada (nivel WhatsApp 1).
@app.route('/api/v1/chaves-pix', methods=['GET'])
def api_chaves_pix():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF,
                                 CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ
                          FROM CHAVE_PIX WHERE ID_CONTA = ?''', (contexto['id_conta'],))
        itens = []
        for registro in cursor.fetchall():
            for tipo, valor in zip(('email', 'telefone', 'cpf', 'aleatoria', 'cnpj'), registro):
                if valor:
                    itens.append({'tipo': tipo, 'valor': str(valor)})
        return jsonify({'chaves': itens}), 200
    except Exception:
        app.logger.exception('Falha ao listar chaves Pix API')
        return jsonify({'mensagem': 'Nao foi possivel consultar as chaves'}), 500
    finally:
        if cursor:
            cursor.close()


# Consulta cartao sem revelar numero completo, CVV ou PIN (nivel 1).
@app.route('/api/v1/cartao', methods=['GET'])
def api_cartao_consulta():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    try:
        c = _buscar_cartao_api(contexto['id_conta'])
        if not c:
            return jsonify({'possui_cartao': False, 'cartao': None})
        usado = calcular_limite_cartao(c[0])
        total = float(c[3] or 0)
        return jsonify({'possui_cartao': True, 'cartao': {
            'id_cartao': c[0], 'final': str(c[1] or '')[-4:],
            'vencimento': str(c[2]) if c[2] else None,
            'limite_total': total, 'limite_utilizado': usado,
            'limite_disponivel': round(total - usado, 2),
            'dia_vencimento': c[4], 'dia_fechamento': c[5],
            'status': c[6], 'motivo_bloqueio': c[7]}})
    except Exception:
        app.logger.exception('Falha consulta cartao API')
        return jsonify({'mensagem': 'Nao foi possivel consultar o cartao'}), 500


# Consulta limite do cartao da conta, sem dados sensiveis (nivel 1).
@app.route('/api/v1/cartao/limites', methods=['GET'])
def api_cartao_limites():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    try:
        c = _buscar_cartao_api(contexto['id_conta'])
        if not c:
            return jsonify({'mensagem': 'Cartao nao encontrado'}), 404
        usado, total = calcular_limite_cartao(c[0]), float(c[3] or 0)
        return jsonify({'limite_total': total, 'limite_utilizado': usado,
                        'limite_disponivel': round(total - usado, 2)})
    except Exception:
        app.logger.exception('Falha limite cartao API')
        return jsonify({'mensagem': 'Nao foi possivel consultar limites'}), 500


# Lista ate 50 compras do cartao da conta autenticada (nivel 1).
@app.route('/api/v1/cartao/compras', methods=['GET'])
def api_cartao_compras():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT FIRST 50 CM.ID_COMPRA, CM.VALOR_COMPRA,
                                 CM.DATA_COMPRA, CM.TIPO, CM.QTD_PARCELA
                          FROM COMPRA CM JOIN CARTAO CA ON CA.ID_CARTAO = CM.ID_CARTAO
                          WHERE CA.ID_CONTA = ?
                          ORDER BY CM.DATA_COMPRA DESC, CM.ID_COMPRA DESC''',
                       (contexto['id_conta'],))
        compras = [{'id_compra': c[0], 'valor': float(c[1]), 'data_compra': str(c[2]),
                    'tipo': c[3], 'parcelas': c[4]} for c in cursor.fetchall()]
        return jsonify({'compras': compras})
    except Exception:
        app.logger.exception('Falha compras cartao API')
        return jsonify({'mensagem': 'Nao foi possivel consultar compras'}), 500
    finally:
        if cursor:
            cursor.close()


# Lista faturas do cartao somente da conta autenticada (nivel 1).
@app.route('/api/v1/cartao/faturas', methods=['GET'])
def api_cartao_faturas():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT FIRST 30 ID_FATURA, VALOR_TOTAL, STATUS,
                                 DATA_FECHAMENTO, DATA_VENCIMENTO
                          FROM FATURA WHERE ID_CONTA = ?
                          ORDER BY DATA_FECHAMENTO DESC, ID_FATURA DESC''',
                       (contexto['id_conta'],))
        faturas = [{'id_fatura': f[0], 'valor_total': float(f[1] or 0), 'status': f[2],
                    'data_fechamento': str(f[3]) if f[3] else None,
                    'data_vencimento': str(f[4]) if f[4] else None}
                   for f in cursor.fetchall()]
        return jsonify({'faturas': faturas})
    except Exception:
        app.logger.exception('Falha faturas cartao API')
        return jsonify({'mensagem': 'Nao foi possivel consultar faturas'}), 500
    finally:
        if cursor:
            cursor.close()


# Detalha uma fatura e suas parcelas, confirmando a titularidade da conta (nivel 1).
@app.route('/api/v1/cartao/faturas/<int:id_fatura>', methods=['GET'])
def api_cartao_fatura_detalhe(id_fatura):
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=1)
    if erro:
        return erro
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT ID_FATURA, VALOR_TOTAL, STATUS, DATA_FECHAMENTO,
                                 DATA_VENCIMENTO FROM FATURA
                          WHERE ID_FATURA = ? AND ID_CONTA = ?''',
                       (id_fatura, contexto['id_conta']))
        f = cursor.fetchone()
        if not f:
            return jsonify({'mensagem': 'Fatura nao encontrada'}), 404
        cursor.execute('''SELECT FC.ID_FATURA_COMPRA, FC.ID_COMPRA, FC.NUMERO_PARCELA,
                                 FC.VALOR_PARCELA, FC.STATUS, FC.DATA_PARCELA
                          FROM FATURA_COMPRA FC
                          JOIN COMPRA CM ON CM.ID_COMPRA = FC.ID_COMPRA
                          JOIN CARTAO CA ON CA.ID_CARTAO = CM.ID_CARTAO
                          WHERE FC.ID_FATURA = ? AND CA.ID_CONTA = ?
                          ORDER BY FC.NUMERO_PARCELA, FC.ID_FATURA_COMPRA''',
                       (id_fatura, contexto['id_conta']))
        itens = [{'id_parcela': p[0], 'id_compra': p[1], 'numero_parcela': p[2],
                  'valor': float(p[3] or 0), 'status': p[4],
                  'data_parcela': str(p[5]) if p[5] else None} for p in cursor.fetchall()]
        return jsonify({'id_fatura': f[0], 'valor_total': float(f[1] or 0),
                        'status': f[2], 'data_fechamento': str(f[3]) if f[3] else None,
                        'data_vencimento': str(f[4]) if f[4] else None, 'itens': itens})
    except Exception:
        app.logger.exception('Falha detalhe fatura API')
        return jsonify({'mensagem': 'Nao foi possivel consultar a fatura'}), 500
    finally:
        if cursor:
            cursor.close()


# Permite ao MAURO conferir o nome da conta de destino antes de oferecer o Pix.
# A consulta é autorizada na conta WhatsApp de nivel 2 e não revela CPF, conta ou saldo.
@app.route('/api/v1/pix/destinatario', methods=['POST'])
def api_pix_destinatario():
    contexto, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=2)
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie tipo_chave e chave_pix em JSON'}), 400
    tipo = str(dados.get('tipo_chave') or '').strip().lower()
    chave = dados.get('chave_pix')
    colunas = {'cpf': 'CHAVE_PIX_CPF', 'cnpj': 'CHAVE_PIX_CNPJ',
               'email': 'CHAVE_PIX_EMAIL', 'telefone': 'CHAVE_PIX_TELEFONE',
               'aleatoria': 'CHAVE_PIX_ALEATORIA'}
    if tipo not in colunas or not isinstance(chave, str) or not 1 <= len(chave.strip()) <= 160:
        return jsonify({'mensagem': 'Chave Pix invalida'}), 400
    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('''SELECT C.ID_CONTA, C.TIPO_CONTA, U.NOME,
                                 C.NOME_FANTASIA, C.RAZAO_SOCIAL
                          FROM CHAVE_PIX K
                          JOIN CONTA C ON C.ID_CONTA = K.ID_CONTA
                          JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE K.''' + colunas[tipo] + ''' = ?''', (chave.strip(),))
        encontrados = cursor.fetchmany(2)
        if len(encontrados) != 1:
            return jsonify({'encontrado': False, 'mensagem': 'Chave nao encontrada ou ambigua'}), 404
        c = encontrados[0]
        if int(c[0]) == int(contexto['id_conta']):
            return jsonify({'encontrado': False, 'mensagem': 'Esta chave pertence a sua propria conta'}), 400
        nome = nome_cliente_api(c[2], c[3], c[4], c[1])
        return jsonify({'encontrado': True, 'destinatario': nome,
                        'tipo_conta': 'PJ' if c[1] == 1 else 'PF'}), 200
    except Exception:
        app.logger.exception('Falha ao consultar destinatario Pix')
        return jsonify({'mensagem': 'Destinatario temporariamente indisponivel'}), 500
    finally:
        if cursor:
            cursor.close()
