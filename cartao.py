from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, gerar_cvv, gerar_numero_cartao, gerar_vencimento, calcular_limite_cartao


def formatar_numero_cartao(numero):
    numero = str(numero or '')
    return ' '.join(numero[i:i + 4] for i in range(0, len(numero), 4))


def serializar_cartao(cartao):
    limite_total = float(cartao[5] or 0)
    limite_utilizado = calcular_limite_cartao(cartao[0])
    limite_disponivel = max(limite_total - limite_utilizado, 0)

    return {
        'id_cartao': cartao[0],
        'id_conta': cartao[1],
        'numero_cartao': str(cartao[2]),
        'numero_formatado': formatar_numero_cartao(cartao[2]),
        'vencimento': str(cartao[3]) if cartao[3] else None,
        'cvv': str(cartao[4]).zfill(3) if cartao[4] is not None else None,
        'limite_total': limite_total,
        'limite_utilizado': limite_utilizado,
        'limite_disponivel': limite_disponivel,
        'dia_vencimento': cartao[6],
        'dia_fechamento': cartao[7]
    }


@app.route('/cartao', methods=['GET'])
def buscar_cartao():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ?
                          ORDER BY ID_CARTAO DESC
                          ROWS 1""", (id_conta,))
        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({'possui_cartao': False, 'cartao': None}), 200

        return jsonify({'possui_cartao': True, 'cartao': serializar_cartao(cartao)}), 200

    except Exception as e:
        print('ERRO BUSCAR CARTAO:', e)
        return jsonify({'mensagem': 'Erro ao buscar cartao'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_cartao', methods=['POST'])
def adicionar_cartao():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    dados = request.get_json(silent=True) or {}
    dia_vencimento = dados.get('dia_vencimento', 10)
    dia_fechamento = dados.get('dia_fechamento', 3)

    try:
        dia_vencimento = int(dia_vencimento)
        dia_fechamento = int(dia_fechamento)
    except (TypeError, ValueError):
        return jsonify({'mensagem': 'Dias de vencimento e fechamento invalidos'}), 400

    if not 1 <= dia_vencimento <= 28 or not 1 <= dia_fechamento <= 28:
        return jsonify({'mensagem': 'Os dias de vencimento e fechamento devem estar entre 1 e 28'}), 400

    if dia_vencimento == dia_fechamento:
        return jsonify({'mensagem': 'O dia de fechamento deve ser diferente do vencimento'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ?
                          ORDER BY ID_CARTAO DESC
                          ROWS 1""", (id_conta,))
        cartao_existente = cursor.fetchone()

        if cartao_existente:
            return jsonify({
                'mensagem': 'Esta conta ja possui cartao',
                'possui_cartao': True,
                'cartao': serializar_cartao(cartao_existente)
            }), 409

        numero_cartao = None

        for _ in range(20):
            candidato = gerar_numero_cartao()
            cursor.execute("SELECT 1 FROM CARTAO WHERE NUMERO_CARTAO = ?", (candidato,))
            if not cursor.fetchone():
                numero_cartao = candidato
                break

        if numero_cartao is None:
            return jsonify({'mensagem': 'Nao foi possivel gerar um numero de cartao unico'}), 500

        cvv = gerar_cvv()
        limite = 5000.0
        vencimento = gerar_vencimento()

        cursor.execute("""INSERT INTO CARTAO
                          (ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO)
                          VALUES (?, ?, ?, ?, ?, ?, ?)
                          RETURNING ID_CARTAO""",
                       (id_conta, numero_cartao, vencimento, cvv, limite, dia_vencimento, dia_fechamento))

        id_cartao = cursor.fetchone()[0]
        con.commit()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CARTAO = ?""", (id_cartao,))
        cartao = cursor.fetchone()

        return jsonify({
            'mensagem': 'Cartao gerado com sucesso',
            'possui_cartao': True,
            'cartao': serializar_cartao(cartao)
        }), 201

    except Exception as e:
        con.rollback()
        print('ERRO ADICIONAR CARTAO:', e)
        return jsonify({'mensagem': 'Erro ao adicionar cartao'}), 500

    finally:
        if cursor:
            cursor.close()
