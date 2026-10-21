"""POST routes for the Arkhe HTTP API and legacy WhatsApp query."""
import datetime
import secrets
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import fdb
from flask import jsonify, request

from banco import con
from funcao import calcular_limite_cartao, calcular_saldo, criptografar_pin, data_atual, descobre_id_conta, pode_debitar_saldo
from main import app

from .common import autenticar_integracao, autenticar_requisicao, valor_monetario_api
from .whatsapp import _conta_vinculada, _servico_valido


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


# Cria cobranca Pix: credencial empresarial original ou WhatsApp PJ nivel 3.
@app.route('/api/v1/cobrancas/pix', methods=['POST'])
@app.route('/api/v1/cobrancas/pix/qrcode', methods=['POST'])
def api_criar_cobranca_pix():
    # Cobranças feitas pelo MAURO exigem nível 3, disponível apenas para PJ.
    # Integrações empresariais usam as credenciais e regras antigas.
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=3)

    if erro:
        return erro

    from transferencia import criar_pix_para_conta
    return criar_pix_para_conta(integracao['id_conta'], request.get_json(silent=True))


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


# Emite boleto em nome da conta PJ autenticada; WhatsApp exige nivel 3.
@app.route('/api/v1/cobrancas/boletos', methods=['POST'])
def api_criar_boleto():
    # Cobranças feitas pelo MAURO exigem nível 3, disponível apenas para PJ.
    # Integrações empresariais usam as credenciais e regras antigas.
    integracao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=3)
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


@app.route('/api/v1/vendas/cartao', methods=['POST'])
def api_vender_cartao():
    integracao, erro = autenticar_integracao()
    if erro:
        return erro

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400

    numero = str(dados.get('numero_cartao') or '').replace(' ', '').replace('-', '')
    cvv = str(dados.get('cvv') or '')
    validade = str(dados.get('validade') or '')
    tipo = str(dados.get('tipo') or 'DEBITO').strip().upper()
    parcelas_texto = str(dados.get('parcelas', 1))
    valor = valor_monetario_api(dados.get('valor'))
    id_recebedor = integracao['id_conta']

    if len(numero) != 16 or not numero.isdigit() or len(cvv) != 3 or not cvv.isdigit():
        return jsonify({'mensagem': 'Informe numero de cartao com 16 digitos e CVV com 3 digitos'}), 400
    if valor is None:
        return jsonify({'mensagem': 'Informe um valor positivo em reais'}), 400
    if tipo not in ('DEBITO', 'CREDITO'):
        return jsonify({'mensagem': 'Tipo deve ser DEBITO ou CREDITO'}), 400
    if not parcelas_texto.isdigit() or not 1 <= int(parcelas_texto) <= 15:
        return jsonify({'mensagem': 'Parcelas deve ser um inteiro entre 1 e 15'}), 400
    parcelas = int(parcelas_texto)
    if tipo == 'DEBITO' and parcelas != 1:
        return jsonify({'mensagem': 'Debito deve ter apenas uma parcela'}), 400
    if valor < Decimal('0.01') * parcelas:
        return jsonify({'mensagem': 'Cada parcela deve ter pelo menos um centavo'}), 400
    try:
        validade_informada = datetime.datetime.strptime(validade, '%m/%Y').date()
        if len(validade) != 7:
            raise ValueError
    except ValueError:
        return jsonify({'mensagem': 'Validade deve estar no formato MM/YYYY'}), 400

    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute('SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?', (id_recebedor,))
        recebedor = cursor.fetchone()
        if not recebedor or recebedor[0] != 1:
            con.rollback()
            return jsonify({'mensagem': 'Apenas contas PJ podem receber vendas pela API'}), 403

        # A trava por conta evita duas compras consumindo o mesmo saldo ou limite.
        cursor.execute('SELECT ID_CONTA FROM CARTAO WHERE NUMERO_CARTAO = ?', (numero,))
        conta_cartao = cursor.fetchone()
        if not conta_cartao:
            con.rollback()
            return jsonify({'mensagem': 'Dados do cartao invalidos'}), 400
        id_pagador = conta_cartao[0]
        if id_pagador == id_recebedor:
            con.rollback()
            return jsonify({'mensagem': 'Pagador e recebedor devem ser contas diferentes'}), 400

        id_liquidacao = app.config['CONTA_LIQUIDACAO_CARTAO'] if tipo == 'CREDITO' else id_pagador
        for id_conta in sorted({id_pagador, id_recebedor, id_liquidacao}):
            cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_conta,))
            if not cursor.fetchone():
                con.rollback()
                return jsonify({'mensagem': 'Conta de liquidacao ou de pagamento nao configurada'}), 503

        cursor.execute(
            """SELECT ID_CARTAO, ID_CONTA, VENCIMENTO, CVV, LIMITE, STATUS
               FROM CARTAO WHERE NUMERO_CARTAO = ? WITH LOCK""", (numero,)
        )
        cartao = cursor.fetchone()
        hoje = data_atual().date()
        if not cartao or cartao[1] != id_pagador:
            con.rollback()
            return jsonify({'mensagem': 'Dados do cartao invalidos'}), 400
        vencimento = cartao[2]
        if (not vencimento or (vencimento.year, vencimento.month) != (validade_informada.year, validade_informada.month)
                or not secrets.compare_digest(str(cartao[3]).zfill(3), cvv)):
            con.rollback()
            return jsonify({'mensagem': 'Dados do cartao invalidos'}), 400
        if (vencimento.year, vencimento.month) < (hoje.year, hoje.month):
            con.rollback()
            return jsonify({'mensagem': 'Cartao vencido'}), 400
        if cartao[5] != 0:
            con.rollback()
            return jsonify({'mensagem': 'Cartao bloqueado'}), 400

        id_cartao = cartao[0]
        if tipo == 'DEBITO':
            valor_recebido = valor
            valor_parcela = None
            tipo_compra = 0
        else:
            valor_recebido = (valor * Decimal('0.95')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            valor_parcela = (valor / parcelas).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            tipo_compra = 1

        agora = data_atual()
        # Mesma protecao de cinco minutos usada pela maquininha, com tipo e parcelas.
        cursor.execute(
            """SELECT FIRST 1 C.ID_COMPRA FROM COMPRA C
               INNER JOIN MOVIMENTACAO M ON M.DATA_MOVIMENTACAO = C.DATA_COMPRA
                 AND M.ID_PAGADOR = ? AND M.ID_RECEBEDOR = ? AND M.VALOR = ?
                 AND M.ID_COBRANCA IS NULL
               WHERE C.ID_CARTAO = ? AND C.VALOR_COMPRA = ? AND C.TIPO = ?
                 AND C.QTD_PARCELA = ? AND C.DATA_COMPRA BETWEEN ? AND ?""",
            (id_liquidacao, id_recebedor, valor_recebido, id_cartao, valor, tipo_compra,
             parcelas, agora - datetime.timedelta(minutes=5), agora)
        )
        if cursor.fetchone():
            con.rollback()
            return jsonify({
                'mensagem': 'Venda semelhante aprovada nos ultimos cinco minutos. Confira o recebimento antes de cobrar novamente',
                'codigo': 'VENDA_SEMELHANTE_RECENTE'
            }), 409

        if tipo == 'DEBITO':
            if not pode_debitar_saldo(id_pagador, valor):
                con.rollback()
                return jsonify({'mensagem': 'Saldo insuficiente'}), 400
        else:
            limite = Decimal(str(cartao[4] or 0))
            utilizado = Decimal(str(calcular_limite_cartao(id_cartao) or 0))
            if utilizado + valor > limite:
                con.rollback()
                return jsonify({'mensagem': 'Limite insuficiente'}), 400

        cursor.execute(
            """INSERT INTO COMPRA
               (ID_CARTAO, VALOR_COMPRA, DATA_COMPRA, TIPO, VALOR_PARCELA, QTD_PARCELA)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING ID_COMPRA""",
            (id_cartao, valor, agora, tipo_compra, valor_parcela, parcelas)
        )
        id_compra = cursor.fetchone()[0]

        if tipo == 'CREDITO':
            # TG_AI_COMPRA ja cria as parcelas. Ajustamos somente os centavos da ultima.
            ultima_parcela = valor - valor_parcela * (parcelas - 1)
            cursor.execute(
                'UPDATE FATURA_COMPRA SET VALOR_PARCELA = ? WHERE ID_COMPRA = ? AND NUMERO_PARCELA = ?',
                (ultima_parcela, id_compra, parcelas)
            )
            cursor.execute('SELECT COUNT(*), CAST(SUM(VALOR_PARCELA) AS DECIMAL(18,2)) FROM FATURA_COMPRA WHERE ID_COMPRA = ?', (id_compra,))
            criadas, total = cursor.fetchone()
            if criadas != parcelas or total != valor:
                con.rollback()
                return jsonify({'mensagem': 'Regra de parcelas do banco precisa ser conferida'}), 503

        # No credito o banco antecipa 95%; o comprador deve 100% nas faturas.
        # Assim a compra a credito nao debita tambem o saldo do comprador.
        cursor.execute(
            """INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
               VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO""",
            (id_liquidacao, id_recebedor, valor_recebido, agora)
        )
        id_movimentacao = cursor.fetchone()[0]
        resposta = {
            'aprovado': True, 'mensagem': 'Venda aprovada',
            'id_compra': id_compra, 'id_movimentacao': id_movimentacao,
            'valor': float(valor), 'valor_recebido': float(valor_recebido),
            'taxa': float(valor - valor_recebido), 'tipo': tipo, 'parcelas': parcelas,
            'final_cartao': numero[-4:], 'data_compra': agora.isoformat()
        }
        con.commit()
        return jsonify(resposta), 201
    except (fdb.IntegrityError, fdb.TransactionConflict):
        con.rollback()
        return jsonify({'mensagem': 'Operacao concorrente. Confira o recebimento antes de enviar novamente'}), 409
    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao processar venda'}), 500
    finally:
        if cursor:
            cursor.close()


@app.route("/internal/whatsapp/consulta", methods=["POST"])
def whatsapp_consulta():
    """Consultas reais, isoladas pela conta vinculada e autorizacao atual do Firebird."""
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    acao = str(dados.get("acao", "")).lower()
    if acao not in ("saldo", "extrato"):
        return jsonify({"mensagem": "Consulta nao disponivel"}), 400
    try:
        conta = _conta_vinculada(chat_id)
        if not conta:
            return jsonify({"vinculado": False, "mensagem": "Vincule sua conta pelo site Arkhé para consultar dados bancarios"}), 403
        id_conta = conta["id_conta"]
        if acao == "saldo":
            saldo = calcular_saldo(id_conta)
            return jsonify({"vinculado": True, "acao": "saldo", "id_conta": id_conta,
                            "nivel": conta["nivel"], "saldo": float(saldo)})
        cursor = con.cursor()
        try:
            cursor.execute("""SELECT FIRST 10 ID_MOVIMENTACAO, VALOR, DATA_MOVIMENTACAO,
                              ID_PAGADOR, ID_RECEBEDOR FROM MOVIMENTACAO
                              WHERE ID_PAGADOR = ? OR ID_RECEBEDOR = ?
                              ORDER BY DATA_MOVIMENTACAO DESC, ID_MOVIMENTACAO DESC""",
                           (id_conta, id_conta))
            linhas = cursor.fetchall()
        finally:
            cursor.close()
        movimentos = [{"id": int(r[0]), "valor": float(r[1]),
                        "data": r[2].isoformat() if r[2] else None,
                        "tipo": "saida" if int(r[3] or 0) == id_conta else "entrada"}
                       for r in linhas]
        return jsonify({"vinculado": True, "acao": "extrato", "id_conta": id_conta,
                        "nivel": conta["nivel"], "movimentacoes": movimentos})
    except Exception:
        app.logger.exception("Falha na consulta bancaria do WhatsApp")
        return jsonify({"mensagem": "Consulta indisponivel no momento"}), 503
