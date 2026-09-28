from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, verificar_pin, calcular_saldo, calcular_limite_cartao, data_atual

CARTOES_FISICOS = {
    '0D94A4A5': 4,  # Cartao da Lais
}

def normalizar_uid(uid):
    return ''.join(c for c in str(uid or '').upper() if c.isalnum())


def buscar_cartao_fisico(uid):
    uid = normalizar_uid(uid)
    id_cartao = CARTOES_FISICOS.get(uid)

    if not id_cartao:
        return None

    cursor = con.cursor()

    try:
        cursor.execute("""
            SELECT CA.ID_CARTAO, CA.ID_CONTA, CA.NUMERO_CARTAO, CA.LIMITE, CA.STATUS,
                   C.ID_USUARIO, U.PIN_HASH, U.NOME
            FROM CARTAO CA
            INNER JOIN CONTA C ON C.ID_CONTA = CA.ID_CONTA
            INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
            WHERE CA.ID_CARTAO = ?
        """, (id_cartao,))

        return cursor.fetchone()

    finally:
        cursor.close()


@app.route('/maquininha/identificar', methods=['POST'])
def identificar_cartao_maquininha():
    id_recebedor = descobre_id_conta()

    if not id_recebedor:
        return jsonify({'mensagem': 'Empresa nao autenticada'}), 403

    dados = request.get_json() or {}
    uid = dados.get('uid')

    cartao = buscar_cartao_fisico(uid)

    if not cartao:
        return jsonify({
            'mensagem': 'Cartao fisico nao reconhecido'
        }), 404

    if cartao[4] == 1:
        return jsonify({
            'mensagem': 'Cartao bloqueado'
        }), 400

    numero = str(cartao[2])

    return jsonify({
        'mensagem': 'Cartao identificado',
        'cartao_encontrado': True,
        'final_cartao': numero[-4:],
        'nome': cartao[7]
    }), 200

