from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_usuario, criptografar_pin


@app.route('/verificar_usuario', methods=['POST'])
def verificar_usuario():
    dados = request.get_json()
    cpf = dados.get('cpf')
    cursor = None

    try:
        cursor = con.cursor()
        cursor.execute("""SELECT ID_USUARIO FROM USUARIO WHERE CPF = ?""", (cpf,))
        usuario = cursor.fetchone()

        if usuario:
            return jsonify({'usuario_existente': True}), 200

        return jsonify({'usuario_existente': False}), 200

    except Exception as e:
        return jsonify({'mensagem': f'Erro ao verificar usuário: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_usuario', methods=['POST'])
def adicionar_usuario():
    nome = request.form.get('nome')
    email = request.form.get('email')
    telefone = request.form.get('telefone')
    cpf = request.form.get('cpf')
    cnpj = request.form.get('cnpj')
    pin = request.form.get('pin')
    tipo_conta = request.form.get('tipo_conta')

    cep = request.form.get('cep')
    rua = request.form.get('rua')
    numero = request.form.get('numero')
    bairro = request.form.get('bairro')
    cidade = request.form.get('cidade')
    estado = request.form.get('estado')
    complemento = request.form.get('complemento')

    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')
    tipo = request.form.get('tipo')

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT 1 FROM USUARIO WHERE EMAIL = ?""", (email,))
        if cursor.fetchone():
            return jsonify({'mensagem': 'Email já cadastrado'}), 400

        cursor.execute("""INSERT INTO USUARIO (NOME, EMAIL, TELEFONE, CPF, CNPJ, TIPO, STATUS, TENTATIVAS, CEP, RUA, NUMERO, BAIRRO, CIDADE, ESTADO, COMPLEMENTO, NOME_FANTASIA, RAZAO_SOCIAL, REPRESENTANTE)
                          VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING ID_USUARIO""",
                       (nome, email, telefone, cpf, cnpj, tipo, cep, rua, numero, bairro, cidade, estado, complemento, nome_fantasia, razao_social, representante))

        id_usuario = cursor.fetchone()[0]

        cursor.execute("""SELECT MAX(NUMERO_CONTA) FROM CONTA""")
        numero_conta = cursor.fetchone()[0]

        if numero_conta is None:
            numero_conta = 0

        numero_conta += 1
        pin_hash = criptografar_pin(pin)

        cursor.execute("""INSERT INTO CONTA (ID_USUARIO, NUMERO_CONTA, AGENCIA, BANCO, TIPO_CONTA, PIN_HASH)
                          VALUES (?, ?, ?, ?, ?, ?) RETURNING ID_CONTA""",
                       (id_usuario, numero_conta, '0001', 248, tipo_conta, pin_hash))

        id_conta = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Usuário e conta cadastrados com sucesso',
            'id_usuario': id_usuario,
            'id_conta': id_conta
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao cadastrar usuário: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/edicao_usuario', methods=['PUT'])
def edicao_usuario():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não logado'}), 403

    nome = request.form.get('nome')
    email = request.form.get('email')
    cpf = request.form.get('cpf')
    cnpj = request.form.get('cnpj')
    telefone = request.form.get('telefone')

    cep = request.form.get('cep')
    rua = request.form.get('rua')
    bairro = request.form.get('bairro')
    numero = request.form.get('numero')
    nome_mae = request.form.get('nome_mae')
    nome_pai = request.form.get('nome_pai')
    cidade = request.form.get('cidade')
    estado = request.form.get('estado')
    complemento = request.form.get('complemento')

    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')


    try:
        cursor = con.cursor()

        cursor.execute("""SELECT 1 FROM USUARIO WHERE ID_USUARIO = ?""", (id_usuario,))
        if not cursor.fetchone():
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        cursor.execute("""SELECT 1 FROM USUARIO WHERE EMAIL = ? AND ID_USUARIO != ?""", (email, id_usuario))
        if cursor.fetchone():
            return jsonify({'mensagem': 'Email já cadastrado'}), 400

        cursor.execute("""UPDATE USUARIO SET NOME = ?, EMAIL = ?, CPF = ?, CNPJ = ?, TELEFONE = ?, CEP = ?, RUA = ?, BAIRRO = ?, NUMERO = ?, NOME_MAE = ?, NOME_PAI = ?, CIDADE = ?, ESTADO = ?, COMPLEMENTO = ?, NOME_FANTASIA = ?, RAZAO_SOCIAL = ?, REPRESENTANTE = ?
                          WHERE ID_USUARIO = ?""",
                       (nome, email, cpf, cnpj, telefone, cep, rua, bairro, numero, nome_mae, nome_pai, cidade, estado, complemento, nome_fantasia, razao_social, representante, id_usuario))

        con.commit()

        return jsonify({'mensagem': 'Usuário atualizado com sucesso', 'id_usuario': id_usuario}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao editar usuário: {e}'}), 500

    finally:
        if cursor:
            cursor.close()