from flask import jsonify, request
from main import app
from banco import con
from funcao import *


def formatar_numero_cartao(numero):
    numero = str(numero or '')
    return ' '.join(numero[i:i + 4] for i in range(0, len(numero), 4))


def serializar_cartao(cartao):
    limite_total = float(cartao[5] or 0)
    limite_utilizado = calcular_limite_cartao(cartao[0])

    return {
        'id_cartao': cartao[0],
        'id_conta': cartao[1],
        'numero_cartao': str(cartao[2]),
        'numero_formatado': formatar_numero_cartao(cartao[2]),
        'vencimento': str(cartao[3]) if cartao[3] else None,
        'cvv': str(cartao[4]) if cartao[4] is not None else None,
        'limite_total': limite_total,
        'limite_utilizado': limite_utilizado,
        'limite_disponivel': limite_total - limite_utilizado,
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
                          WHERE ID_CONTA = ?""", (id_conta,))

        cartao = cursor.fetchone()

        if not cartao:
            return jsonify({'possui_cartao': False, 'cartao': None}), 200

        return jsonify({'possui_cartao': True, 'cartao': serializar_cartao(cartao)}), 200

    except Exception as e:
        return jsonify({'mensagem': 'Erro ao buscar cartao', 'erro': str(e)}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_cartao', methods=['POST'])
def adicionar_cartao():
    try:
        dados = request.get_json() or {}

        dia_vencimento = dados.get('dia_vencimento', 10)
        dia_fechamento = dados.get('dia_fechamento', 3)

        id_conta = descobre_id_conta()

        if id_conta is None:
            return jsonify({'mensagem': 'Usuario nao logado'}), 403

        cursor = con.cursor()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ?""", (id_conta,))

        cartao_existente = cursor.fetchone()

        if cartao_existente:
            return jsonify({
                'mensagem': 'Esta conta ja possui cartao',
                'possui_cartao': True,
                'cartao': serializar_cartao(cartao_existente)
            }), 409

        cvv = gerar_cvv()
        numero_cartao = gerar_numero_cartao()

        cursor.execute("""SELECT 1 FROM CARTAO WHERE NUMERO_CARTAO = ?""", (numero_cartao,))

        resultado = cursor.fetchone()

        if resultado:
            return jsonify({'mensagem': 'Numero de cartao ja existe'}), 400

        limite = float(5000)
        vencimento = gerar_vencimento()

        cursor.execute("""INSERT INTO CARTAO(ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (id_conta, numero_cartao, vencimento, cvv, limite, dia_vencimento, dia_fechamento))

        con.commit()

        cursor.execute("""SELECT ID_CARTAO, ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE, DIA_VENCIMENTO, FECHAMENTO
                          FROM CARTAO
                          WHERE ID_CONTA = ? AND NUMERO_CARTAO = ?""", (id_conta, numero_cartao))

        cartao = cursor.fetchone()

        return jsonify({
            'mensagem': 'Cartao adicionado com sucesso',
            'possui_cartao': True,
            'cartao': serializar_cartao(cartao)
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao adicionar cartao', 'erro': str(e)}), 500

    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
