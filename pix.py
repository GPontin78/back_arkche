from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_conta, gerar_chave_pix, validar_chave_pix
import uuid


@app.route('/adicionar_chave_pix', methods=['POST'])
def adicionar_chave_pix():
    dados = request.get_json()
    chave_pix_email = dados.get('chave_pix_email')
    chave_pix_telefone = dados.get('chave_pix_telefone')
    chave_pix_cpf = dados.get('chave_pix_cpf')
    chave_pix_aleatoria = dados.get('chave_pix_aleatoria')
    chave_pix_cnpj = dados.get('chave_pix_cnpj')

    if chave_pix_aleatoria:
        chave_pix_aleatoria = gerar_chave_pix()

    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        if chave_pix_email:
            validar_chavona = validar_chave_pix(chave_pix_email, 'chave_pix_email',1)

            if validar_chavona:
                return jsonify({'mensagem': 'Chave PIX de email ja cadastrada'}), 400


        if chave_pix_telefone:
            validar_chavona = validar_chave_pix(chave_pix_telefone, 'chave_pix_telefone',1)
            if validar_chavona:
                return jsonify({'mensagem': 'Chave PIX de telefone ja cadastrada'}), 400


        if chave_pix_cpf:
            validar_chavona = validar_chave_pix(chave_pix_cpf, 'chave_pix_cpf',1)
            if validar_chavona:
                return jsonify({'mensagem': 'Chave PIX de CPF ja cadastrada'}), 400


        if chave_pix_aleatoria:
            validar_chavona = validar_chave_pix(chave_pix_aleatoria, 'chave_pix_aleatoria',1)

            if validar_chavona:
                return jsonify({'mensagem': 'Chave PIX aleatoria ja cadastrada'}), 400


        if chave_pix_cnpj:
            validar_chavona = validar_chave_pix(chave_pix_cnpj, 'chave_pix_cnpj',1)

            if validar_chavona:
                return jsonify({'mensagem': 'Chave PIX de CNPJ ja cadastrada'}), 400

        cursor.execute("""  SELECT 1 FROM CHAVE_PIX WHERE ID_CONTA = ?""", (id_conta,))
        if not cursor.fetchone():
            cursor.execute("""
                insert into chave_pix(id_conta) values(?)
            """, (id_conta,))

        if chave_pix_email:
            validar_chave_pix(chave_pix_email, 'chave_pix_email',id_conta, 2)

        if chave_pix_telefone:
            validar_chave_pix(chave_pix_telefone, 'chave_pix_telefone',id_conta, 2)
           
        if chave_pix_cpf:
            validar_chave_pix(chave_pix_cpf, 'chave_pix_cpf',id_conta, 2)

        if chave_pix_aleatoria:
            validar_chave_pix(chave_pix_aleatoria, 'chave_pix_aleatoria',id_conta, 2)

        if chave_pix_cnpj:
            validar_chave_pix(chave_pix_cnpj, 'chave_pix_cnpj',id_conta, 2)

        con.commit()

        return jsonify({
            'mensagem': 'Chave Pix cadastrada com sucesso',
            'chave_pix_aleatoria': chave_pix_aleatoria
        }), 201

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao cadastrar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()