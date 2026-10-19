import datetime
import secrets
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import fdb
from flask import jsonify, request
from main import app
from banco import con
from api import autenticar_integracao, valor_monetario_api
from funcao import calcular_limite_cartao, data_atual, pode_debitar_saldo


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
