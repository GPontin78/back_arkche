from flask import jsonify, request
from main import app
from banco import con
from funcao import *


@app.route('/adicionar_cartao', methods=['POST'])
def adicionar_cartao():
    try:
        dados = request.get_json()

        dia_vencimento = dados.get('dia_vencimento')
        dia_fechamento = dados.get('dia_fechamento')

        id_conta = descobre_id_conta()

        if id_conta is None:
            return jsonify({'mensagem': 'Usuario nao logado'}), 403

        cursor = con.cursor()

        cvv = gerar_cvv()
        numero_cartao = gerar_numero_cartao()

        cursor.execute("""
            SELECT 1 FROM CARTAO WHERE NUMERO_CARTAO = ?
        """, (numero_cartao,))

        resultado = cursor.fetchone()

        if resultado:
            return jsonify({'mensagem': 'Numero de cartao ja existe'}), 400

        limite = float(5000)

        vencimento = gerar_vencimento()

        cursor.execute("""
            INSERT INTO CARTAO(ID_CONTA, NUMERO_CARTAO, VENCIMENTO, CVV, LIMITE,
            DIA_VENCIMENTO, FECHAMENTO, ID_CONTA)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            id_conta, numero_cartao, vencimento, cvv, 
            limite, dia_vencimento, dia_fechamento, id_conta))

        con.commit()

        return jsonify({'mensagem': 'Cartao adicionado com sucesso'}), 200

    except Exception as e:

        return jsonify({'mensagem': 'Erro ao adicionar cartao','erro': str(e)}), 500