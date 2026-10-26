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
from limites import aplicar_limite
from notificacoes import registrar_evento_bancario, tentar_publicar_eventos

from .common import (autenticar_integracao, autenticar_requisicao, autorizar_pagamento_externo,
                     executar_operacao_idempotente, limitar_pagamento_whatsapp, valor_monetario_api)
from .whatsapp import _conta_vinculada, _servico_valido
from vendas_idempotencia import (
    assinatura_venda,
    obter_resposta_venda,
    registrar_venda_idempotente,
    validar_chave_venda,
)


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
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'cobranca:{id_cobranca}:emitida', categoria='BOLETO',
            id_contas=[id_recebedor], referencia_tipo='COBRANCA', referencia_id=id_cobranca,
            valor=valor, titulo='Boleto emitido', mensagem='Um boleto foi emitido pela sua conta.'
        )

        resposta = {
            'mensagem': 'Boleto criado com sucesso',
            'id_cobranca': id_cobranca, 'id_pagador': id_pagador, 'id_recebedor': id_recebedor,
            'valor': float(valor), 'data_vencimento': vencimento.isoformat(),
            'codigo_pagamento': codigo, 'status': 0, 'tipo_cobranca': 0,
            'url_pdf': f'/api/v1/cobrancas/boletos/{id_cobranca}/pdf'
        }
        con.commit()
        tentar_publicar_eventos(eventos)
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

    chave_idempotencia = validar_chave_venda(request.headers.get('X-Idempotency-Key'))
    if not chave_idempotencia:
        return jsonify({'mensagem': 'Envie X-Idempotency-Key unica (8 a 128 caracteres)'}), 400

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
        assinatura = assinatura_venda(
            id_pagador=int(id_pagador), id_recebedor=int(id_recebedor),
            id_cartao=int(id_cartao), valor=str(valor), tipo=tipo,
            parcelas=int(parcelas), validade=validade_informada.isoformat(),
        )
        repeticao = obter_resposta_venda(
            cursor, 'API', integracao['id_integracao'], chave_idempotencia,
            assinatura,
        )
        if repeticao is not None:
            con.rollback()
            return repeticao

        if tipo == 'DEBITO':
            valor_recebido = valor
            valor_parcela = None
            tipo_compra = 0
        else:
            valor_recebido = (valor * Decimal('0.95')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            valor_parcela = (valor / parcelas).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            tipo_compra = 1

        restricao_limite = aplicar_limite(
            cursor, id_pagador, 'PAGAMENTO', valor,
            id_usuario=integracao.get('id_usuario'),
        )
        if restricao_limite:
            return restricao_limite

        agora = data_atual()

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
            """INSERT INTO MOVIMENTACAO
               (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COMPRA)
               VALUES (?, ?, ?, ?, ?) RETURNING ID_MOVIMENTACAO""",
            (id_liquidacao, id_recebedor, valor_recebido, agora, id_compra)
        )
        id_movimentacao = cursor.fetchone()[0]
        eventos = registrar_evento_bancario(
            cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='CARTAO',
            id_contas=[id_pagador, id_recebedor], referencia_tipo='MOVIMENTACAO',
            referencia_id=id_movimentacao, valor=valor_recebido, id_pagador=id_pagador,
            dados_adicionais={'tipo_compra': tipo, 'parcelas': parcelas, 'final_cartao': numero[-4:]}
        )
        resposta = {
            'aprovado': True, 'mensagem': 'Venda aprovada',
            'id_compra': id_compra, 'id_movimentacao': id_movimentacao,
            'valor': float(valor), 'valor_recebido': float(valor_recebido),
            'taxa': float(valor - valor_recebido), 'tipo': tipo, 'parcelas': parcelas,
            'final_cartao': numero[-4:], 'data_compra': agora.isoformat()
        }
        registrar_venda_idempotente(
            cursor, 'API', integracao['id_integracao'], chave_idempotencia,
            assinatura, id_compra, id_movimentacao, resposta, 201,
        )
        con.commit()
        tentar_publicar_eventos(eventos)
        return jsonify(resposta), 201
    except (fdb.IntegrityError, fdb.TransactionConflict):
        con.rollback()
        if cursor and chave_idempotencia and 'integracao' in locals() and 'assinatura' in locals():
            try:
                repeticao = obter_resposta_venda(
                    cursor, 'API', integracao['id_integracao'],
                    chave_idempotencia, assinatura,
                )
                if repeticao is not None:
                    return repeticao
            except Exception:
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


# Envia um Pix com a conta pagadora definida EXCLUSIVAMENTE pela autenticacao.
# API externa: credencial da propria conta PJ. WhatsApp: vinculo e nivel 2.
# Idempotencia obrigatoria evita executar duas vezes a mesma requisicao.
@app.route('/api/v1/pagamentos/pix', methods=['POST'])
def api_pagar_pix():
    autorizacao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=2)
    if erro:
        return erro
    restricao_externa = autorizar_pagamento_externo(autorizacao)
    if restricao_externa:
        return restricao_externa
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400

    tipo = str(dados.get('tipo_chave') or '').lower()
    chave_pix = dados.get('chave_pix')
    valor = valor_monetario_api(dados.get('valor'))
    colunas = {'email': 'CHAVE_PIX_EMAIL', 'telefone': 'CHAVE_PIX_TELEFONE',
               'cpf': 'CHAVE_PIX_CPF', 'cnpj': 'CHAVE_PIX_CNPJ',
               'aleatoria': 'CHAVE_PIX_ALEATORIA'}
    if tipo not in colunas or not isinstance(chave_pix, str) or not 1 <= len(chave_pix.strip()) <= 160:
        return jsonify({'mensagem': 'Informe tipo_chave e chave_pix validos'}), 400
    if valor is None:
        return jsonify({'mensagem': 'Informe um valor monetario positivo'}), 400

    restricao = limitar_pagamento_whatsapp(autorizacao, valor)
    if restricao:
        return restricao

    id_pagador = autorizacao['id_conta']

    def realizar():
        cursor = None
        try:
            cursor = con.cursor()
            # Nome da coluna vem de lista fixa, nunca diretamente da requisicao.
            cursor.execute('SELECT ID_CONTA FROM CHAVE_PIX WHERE ' + colunas[tipo] + ' = ?',
                           (chave_pix.strip(),))
            contas = cursor.fetchall()
            if len(contas) != 1:
                con.rollback()
                return jsonify({'mensagem': 'Chave Pix nao encontrada ou ambigua'}), 404
            id_recebedor = int(contas[0][0])
            if id_pagador == id_recebedor:
                con.rollback()
                return jsonify({'mensagem': 'Nao e possivel transferir para a propria conta'}), 400

            restricao_limite = aplicar_limite(
                cursor, id_pagador, 'TRANSFERENCIA', valor,
                id_usuario=autorizacao.get('id_usuario'),
            )
            if restricao_limite:
                return restricao_limite

            # Trava contas em ordem para evitar pagamento paralelo com saldo duplicado.
            for id_conta in sorted({id_pagador, id_recebedor}):
                cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_conta,))
                if not cursor.fetchone():
                    con.rollback()
                    return jsonify({'mensagem': 'Conta indisponivel'}), 404
            if not pode_debitar_saldo(id_pagador, valor):
                con.rollback()
                return jsonify({'mensagem': 'Saldo insuficiente'}), 400

            cursor.execute('''INSERT INTO MOVIMENTACAO
                              (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
                              VALUES (?, ?, ?, ?) RETURNING ID_MOVIMENTACAO''',
                           (id_pagador, id_recebedor, valor, data_atual()))
            id_movimentacao = cursor.fetchone()[0]
            eventos = registrar_evento_bancario(
                cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='PIX',
                id_contas=[id_pagador, id_recebedor], referencia_tipo='MOVIMENTACAO',
                referencia_id=id_movimentacao, valor=valor, id_pagador=id_pagador
            )
            con.commit()
            tentar_publicar_eventos(eventos)
            return jsonify({'mensagem': 'Pix realizado com sucesso',
                            'id_movimentacao': id_movimentacao,
                            'valor': float(valor), 'id_recebedor': id_recebedor}), 201
        except fdb.TransactionConflict:
            con.rollback()
            return jsonify({'mensagem': 'Operacao concorrente; confira o extrato'}), 409
        except Exception:
            con.rollback()
            app.logger.exception('Falha Pix API')
            return jsonify({'mensagem': 'Nao foi possivel concluir o Pix'}), 500
        finally:
            if cursor:
                cursor.close()

    return executar_operacao_idempotente(autorizacao, 'pix', realizar)


# Paga um boleto ja registrado no DDA DA CONTA autenticada.
# WhatsApp exige nivel 2; nao aceita trocar conta pagadora no corpo do JSON.
@app.route('/api/v1/pagamentos/dda/<int:id_cobranca>', methods=['POST'])
def api_pagar_dda(id_cobranca):
    autorizacao, erro = autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=2)
    if erro:
        return erro
    restricao_externa = autorizar_pagamento_externo(autorizacao)
    if restricao_externa:
        return restricao_externa
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or dados:
        return jsonify({'mensagem': 'Envie um objeto JSON vazio; valor e pagador sao definidos pelo boleto'}), 400
    id_pagador = autorizacao['id_conta']

    def realizar():
        cursor = None
        try:
            cursor = con.cursor()
            cursor.execute('''SELECT ID_RECEBEDOR, VALOR, STATUS FROM COBRANCA
                              WHERE ID_COBRANCA = ? AND ID_PAGADOR = ? AND TIPO_COBRANCA = 0''',
                           (id_cobranca, id_pagador))
            boleto = cursor.fetchone()
            if not boleto:
                con.rollback()
                return jsonify({'mensagem': 'Boleto nao encontrado no DDA desta conta'}), 404
            id_recebedor, valor, status = int(boleto[0]), boleto[1], boleto[2]
            if id_pagador == id_recebedor:
                con.rollback()
                return jsonify({'mensagem': 'Nao e possivel pagar boleto da propria conta'}), 400
            if status != 0:
                con.rollback()
                return jsonify({'mensagem': 'Boleto ja pago ou indisponivel'}), 409
            valor = Decimal(str(valor or 0))
            if valor <= 0:
                con.rollback()
                return jsonify({'mensagem': 'Valor do boleto invalido'}), 400
            restricao = limitar_pagamento_whatsapp(autorizacao, valor)
            if restricao:
                con.rollback()
                return restricao

            for id_conta in sorted({id_pagador, id_recebedor}):
                cursor.execute('SELECT ID_CONTA FROM CONTA WHERE ID_CONTA = ? WITH LOCK', (id_conta,))
                if not cursor.fetchone():
                    con.rollback()
                    return jsonify({'mensagem': 'Conta indisponivel'}), 404

            cursor.execute('''SELECT VALOR, STATUS FROM COBRANCA
                              WHERE ID_COBRANCA = ? AND ID_PAGADOR = ? AND TIPO_COBRANCA = 0 WITH LOCK''',
                           (id_cobranca, id_pagador))
            confirmado = cursor.fetchone()
            if not confirmado or confirmado[1] != 0:
                con.rollback()
                return jsonify({'mensagem': 'Boleto ja pago ou indisponivel'}), 409
            valor = Decimal(str(confirmado[0] or 0))
            # O valor pode ter mudado antes do bloqueio; conferir o teto de novo.
            restricao = limitar_pagamento_whatsapp(autorizacao, valor)
            if restricao:
                con.rollback()
                return restricao
            restricao_limite = aplicar_limite(
                cursor, id_pagador, 'PAGAMENTO', valor,
                id_usuario=autorizacao.get('id_usuario'),
            )
            if restricao_limite:
                return restricao_limite
            if valor <= 0 or not pode_debitar_saldo(id_pagador, valor):
                con.rollback()
                return jsonify({'mensagem': 'Saldo insuficiente ou valor invalido'}), 400

            cursor.execute('''UPDATE COBRANCA SET STATUS = 1 WHERE ID_COBRANCA = ?
                              AND ID_PAGADOR = ? AND STATUS = 0 AND TIPO_COBRANCA = 0
                              RETURNING ID_COBRANCA''', (id_cobranca, id_pagador))
            if not cursor.fetchone():
                con.rollback()
                return jsonify({'mensagem': 'Boleto ja processado'}), 409
            cursor.execute('''INSERT INTO MOVIMENTACAO
                              (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO, ID_COBRANCA)
                              VALUES (?, ?, ?, ?, ?) RETURNING ID_MOVIMENTACAO''',
                           (id_pagador, id_recebedor, valor, data_atual(), id_cobranca))
            id_movimentacao = cursor.fetchone()[0]
            eventos = registrar_evento_bancario(
                cursor, chave_operacao=f'movimentacao:{id_movimentacao}', categoria='BOLETO',
                id_contas=[id_pagador, id_recebedor], referencia_tipo='MOVIMENTACAO',
                referencia_id=id_movimentacao, valor=valor, id_pagador=id_pagador,
                dados_adicionais={'id_cobranca': id_cobranca}
            )
            con.commit()
            tentar_publicar_eventos(eventos)
            return jsonify({'mensagem': 'Boleto pago com sucesso', 'id_cobranca': id_cobranca,
                            'id_movimentacao': id_movimentacao, 'valor': float(valor)}), 200
        except fdb.TransactionConflict:
            con.rollback()
            return jsonify({'mensagem': 'Pagamento concorrente; confira o DDA'}), 409
        except Exception:
            con.rollback()
            app.logger.exception('Falha pagamento DDA API')
            return jsonify({'mensagem': 'Nao foi possivel concluir o pagamento'}), 500
        finally:
            if cursor:
                cursor.close()

    return executar_operacao_idempotente(autorizacao, 'dda:' + str(id_cobranca), realizar)


def _documento_eh_valido(documento):
    """Valida CPF e CNPJ (inclusive CNPJ alfanumerico) pelo digito verificador."""
    import re
    valor = re.sub(r'[^A-Za-z0-9]', '', str(documento or '')).upper()
    if len(valor) == 11 and valor.isdigit():
        if len(set(valor)) == 1:
            return None
        for tamanho in (9, 10):
            soma = sum(int(valor[i]) * (tamanho + 1 - i) for i in range(tamanho))
            dv = (soma * 10) % 11
            if (0 if dv == 10 else dv) != int(valor[tamanho]):
                return None
        return 'cpf', valor
    if len(valor) == 14 and re.fullmatch(r'[A-Z0-9]{12}[0-9]{2}', valor):
        if len(set(valor)) == 1:
            return None
        pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        pesos2 = [6] + pesos1
        def digito(parte, pesos):
            resto = sum((ord(c) - 48) * p for c, p in zip(parte, pesos)) % 11
            return 0 if resto < 2 else 11 - resto
        if digito(valor[:12], pesos1) != int(valor[12]):
            return None
        if digito(valor[:13], pesos2) != int(valor[13]):
            return None
        return 'cnpj', valor
    return None


def _limitar_verificacoes_documento(id_conta):
    """Limite 5/minuto e 50/dia por conta, compartilhado entre workers Redis."""
    import os
    import redis
    from datetime import datetime, timezone
    endereco = os.getenv('ARKHE_WHATSAPP_REDIS_URL') or os.getenv('REDIS_URL')
    if not endereco:
        return False
    try:
        agora = datetime.now(timezone.utc)
        minuto = agora.strftime('%Y%m%d%H%M')
        dia = agora.strftime('%Y%m%d')
        cliente = redis.Redis.from_url(endereco, decode_responses=True,
                                     socket_timeout=3, socket_connect_timeout=3)
        # Lua atomica: limites validos globalmente em um mesmo Redis.
        script = """
        local m = tonumber(redis.call('GET', KEYS[1]) or '0')
        local d = tonumber(redis.call('GET', KEYS[2]) or '0')
        if m >= 5 or d >= 50 then return 0 end
        m = redis.call('INCR', KEYS[1])
        if m == 1 then redis.call('EXPIRE', KEYS[1], 120) end
        d = redis.call('INCR', KEYS[2])
        if d == 1 then redis.call('EXPIRE', KEYS[2], 172800) end
        return 1
        """
        return bool(cliente.eval(script, 2, 'arkhe:api:cpf:min:' + str(id_conta) + ':' + minuto,
                                 'arkhe:api:cpf:dia:' + str(id_conta) + ':' + dia))
    except Exception:
        app.logger.exception('Redis indisponivel para rate limit de documentos')
        return False


# Confere apenas se CPF/CNPJ possui conta no Arkhé, sem revelar dados da pessoa.
# Disponivel exclusivamente para integracoes externas, com limites por conta.
@app.route('/api/v1/contas/verificar-documento', methods=['POST'])
def api_verificar_documento():
    integracao, erro = autenticar_integracao()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({'mensagem': 'Envie um objeto JSON'}), 400
    documento = _documento_eh_valido(dados.get('documento'))
    if not documento:
        return jsonify({'mensagem': 'CPF ou CNPJ invalido'}), 400
    if not _limitar_verificacoes_documento(integracao['id_conta']):
        return jsonify({'mensagem': 'Limite de verificacoes atingido ou indisponivel'}), 429
    tipo, valor = documento
    cursor = None
    try:
        cursor = con.cursor()
        if tipo == 'cpf':
            cursor.execute('''SELECT FIRST 1 1 FROM CONTA C
                              JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                              WHERE C.TIPO_CONTA = 0
                              AND REPLACE(REPLACE(U.CPF, '.', ''), '-', '') = ?''', (valor,))
        else:
            cursor.execute('''SELECT FIRST 1 1 FROM CONTA
                              WHERE TIPO_CONTA = 1 AND
                              REPLACE(REPLACE(REPLACE(UPPER(CNPJ), '.', ''), '-', ''), '/', '') = ?''',
                           (valor,))
        return jsonify({'possui_conta': bool(cursor.fetchone())}), 200
    except Exception:
        app.logger.exception('Falha verificacao documento Arkhé')
        return jsonify({'mensagem': 'Verificacao indisponivel'}), 500
    finally:
        if cursor:
            cursor.close()
