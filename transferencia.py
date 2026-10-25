from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, descobre_id_usuario
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos
import uuid
import fdb
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from operacoes_financeiras import (
    ErroOperacaoFinanceira,
    executar_pagamento_cobranca,
    executar_pix_por_chave,
)


def criar_pix_para_conta(id_recebedor, dados):
    """Cria uma cobranca Pix, preservando as rotas web e de integracao existentes."""
    from api import valor_monetario_api

    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    valor_livre = dados.get('valor_livre', False)
    if not isinstance(valor_livre, bool):
        return jsonify({'mensagem': 'valor_livre deve ser true ou false'}), 400
    valor = None if valor_livre else valor_monetario_api(dados.get('valor'))
    if not valor_livre and valor is None:
        return jsonify({'mensagem': 'Informe um valor positivo em reais ou valor_livre: true'}), 400

    cursor = None
    try:
        codigo = 'ARKHEPIX:' + uuid.uuid4().hex.upper()
        desenho = Drawing(256, 256)
        desenho.add(QrCodeWidget(codigo, barWidth=256, barHeight=256, barBorder=4, barLevel='M'))
        imagem = renderSVG.drawToString(desenho)
        cursor = con.cursor()
        cursor.execute(
            """INSERT INTO COBRANCA
               (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_VENCIMENTO, CODIGO_PAGAMENTO, STATUS, TIPO_COBRANCA)
               VALUES (NULL, ?, ?, NULL, ?, 0, 1) RETURNING ID_COBRANCA""",
            (id_recebedor, valor, codigo),
        )
        id_cobranca = cursor.fetchone()[0]
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'cobranca:{id_cobranca}:pix-criada', categoria='PIX',
            id_contas=[id_recebedor], referencia_tipo='COBRANCA', referencia_id=id_cobranca,
            valor=valor, titulo='Cobranca Pix criada', mensagem='Uma cobranca Pix foi criada pela sua conta.',
        )
        con.commit()
        tentar_publicar_eventos(eventos)
        return jsonify({
            'mensagem': 'QR Code Pix criado com sucesso',
            'id_cobranca': id_cobranca, 'codigo_pagamento': codigo,
            'valor': float(valor) if valor is not None else None,
            'valor_livre': valor_livre, 'qr_code_svg': imagem, 'status': 0, 'tipo_cobranca': 1,
        }), 201
    except Exception:
        con.rollback()
        app.logger.exception('Erro ao criar cobranca Pix para a conta %s', id_recebedor)
        return jsonify({'mensagem': 'Erro ao gerar QR Code Pix'}), 500
    finally:
        if cursor:
            cursor.close()



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

    try:
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'cobranca:{id_cobranca}:emitida', categoria='BOLETO',
            id_contas=[id_recebedor], referencia_tipo='COBRANCA', referencia_id=id_cobranca,
            valor=valor, titulo='Boleto emitido', mensagem='Um boleto foi emitido pela sua conta.'
        )
    except Exception:
        con.rollback()
        cursor.close()
        raise

    con.commit()
    tentar_publicar_eventos(eventos)
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
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    id_conta = descobre_id_conta()
    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403
    cursor = None
    try:
        cursor = con.cursor()
        resultado = executar_pagamento_cobranca(
            cursor, int(id_conta), descobre_id_usuario(),
            dados.get('id_cobranca'), dados.get('valor'),
        )
        con.commit()
        tentar_publicar_eventos(resultado['eventos'])
        return jsonify({
            'mensagem': 'Cobranca paga com sucesso',
            'id_movimentacao': resultado['id_movimentacao'],
            'valor': float(resultado['valor']),
        }), 200
    except ErroOperacaoFinanceira as erro:
        con.rollback()
        corpo = {'mensagem': erro.mensagem}
        if erro.codigo:
            corpo['codigo'] = erro.codigo
        return jsonify(corpo), erro.status
    except fdb.TransactionConflict:
        con.rollback()
        return jsonify({'mensagem': 'Pagamento concorrente. Confira a cobranca antes de tentar novamente'}), 409
    except Exception as erro:
        con.rollback()
        app.logger.exception('Erro ao pagar cobranca %s', dados.get('id_cobranca'))
        return jsonify({'mensagem': 'Erro ao pagar cobranca'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_pix', methods=['POST'])
def adicionar_pix():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    id_pagador = descobre_id_conta()
    if not id_pagador:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403
    cursor = None
    try:
        cursor = con.cursor()
        resultado = executar_pix_por_chave(
            cursor, int(id_pagador), descobre_id_usuario(),
            dados.get('tipo_chave'), dados.get('chave_pix'),
            dados.get('valor'), dados.get('id_favorito'),
        )
        con.commit()
        tentar_publicar_eventos(resultado['eventos'])
        return jsonify({
            'mensagem': 'Pix realizado com sucesso',
            'id_movimentacao': resultado['id_movimentacao'],
        }), 201
    except ErroOperacaoFinanceira as erro:
        con.rollback()
        corpo = {'mensagem': erro.mensagem}
        if erro.codigo:
            corpo['codigo'] = erro.codigo
        return jsonify(corpo), erro.status
    except Exception:
        con.rollback()
        app.logger.exception('Erro ao realizar Pix para a conta %s', id_pagador)
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
                                 UR.NOME, CR.NOME_FANTASIA, CR.RAZAO_SOCIAL, CR.TIPO_CONTA,
                                 FI.ID_FOLHA,
                                 CASE WHEN EXISTS (
                                     SELECT 1
                                     FROM COMPRA CMP
                                     INNER JOIN CARTAO CAT ON CAT.ID_CARTAO = CMP.ID_CARTAO
                                     WHERE CAT.ID_CONTA = M.ID_PAGADOR
                                       AND CMP.VALOR_COMPRA = M.VALOR
                                       AND CMP.DATA_COMPRA = M.DATA_MOVIMENTACAO
                                       AND CMP.TIPO = 0
                                 ) THEN 1 ELSE 0 END AS COMPRA_CARTAO
                          FROM MOVIMENTACAO M
                          INNER JOIN CONTA CP ON CP.ID_CONTA = M.ID_PAGADOR
                          INNER JOIN USUARIO UP ON UP.ID_USUARIO = CP.ID_USUARIO
                          INNER JOIN CONTA CR ON CR.ID_CONTA = M.ID_RECEBEDOR
                          INNER JOIN USUARIO UR ON UR.ID_USUARIO = CR.ID_USUARIO
                          LEFT JOIN COBRANCA COB ON COB.ID_COBRANCA = M.ID_COBRANCA
                          LEFT JOIN FOLHA_ITEM FI ON FI.ID_MOVIMENTACAO = M.ID_MOVIMENTACAO
                          WHERE M.ID_PAGADOR = ? OR M.ID_RECEBEDOR = ?
                          ORDER BY M.DATA_MOVIMENTACAO DESC""",
                       (id_conta, id_conta))

        movimentacoes_banco = cursor.fetchall()
        movimentacoes = []

        for movimentacao in movimentacoes_banco:
            tipo = 'saida' if movimentacao[1] == id_conta else 'entrada'

            if movimentacao[15] is not None:
                origem = 'folha_pagamento'
            elif movimentacao[16] == 1:
                origem = 'compra_cartao'
            elif movimentacao[5] is None:
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
                'id_folha': movimentacao[15],
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
            'valor': float(cobranca[3]) if cobranca[3] is not None else None,
            'valor_livre': cobranca[7] == 1 and cobranca[3] is None,
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
    id_recebedor = descobre_id_conta()

    if not id_recebedor:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    return criar_pix_para_conta(id_recebedor, request.get_json(silent=True))
