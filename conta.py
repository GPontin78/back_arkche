from flask import jsonify, request, make_response
from main import app
from banco import con
from funcao import gerar_token, descobre_id_usuario, criptografar_pin, verificar_pin


@app.route('/login', methods=['POST'])
def login():
    dados = request.get_json()

    cpf = dados.get('cpf')
    pin = dados.get('pin')
    tipo_conta = dados.get('tipo_conta')
    cadastro_facial = dados.get('cadastro_facial', False)

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT U.ID_USUARIO, U.NOME, U.EMAIL, U.TELEFONE, U.CPF, C.ID_CONTA, C.PIN_HASH, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA
                          FROM USUARIO U INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO
                          WHERE U.CPF = ? AND C.TIPO_CONTA = ?""",
                       (cpf, tipo_conta))

        dados_do_banco = cursor.fetchone()

        if not dados_do_banco:
            return jsonify({'mensagem': 'CPF, PIN ou tipo de conta inválido'}), 401

        id_usuario = dados_do_banco[0]
        nome = dados_do_banco[1]
        email = dados_do_banco[2]
        telefone = dados_do_banco[3]
        cpf_usuario = dados_do_banco[4]

        id_conta = dados_do_banco[5]
        pin_hash = dados_do_banco[6]
        numero_conta = dados_do_banco[7]
        agencia = dados_do_banco[8]
        banco = dados_do_banco[9]
        tipo_conta_banco = dados_do_banco[10]

        if not verificar_pin(pin, pin_hash):
            return jsonify({'mensagem': 'CPF, PIN ou tipo de conta inválido'}), 401

        if not cadastro_facial:
            return jsonify({
                'mensagem': 'Credenciais válidas',
                'reconhecimento_facial_pendente': True
            }), 200

        token = gerar_token(id_usuario, id_conta)

        resposta = make_response(jsonify({
            'mensagem': 'Login com sucesso',
            'usuario': {
                'nome': nome,
                'email': email,
                'telefone': telefone,
                'cpf': cpf_usuario
            },
            'conta': {
                'numero_conta': numero_conta,
                'agencia': agencia,
                'banco': banco,
                'tipo_conta': tipo_conta_banco
            }
        }), 200)

        resposta.set_cookie('access_token', token, httponly=True, secure=False, samesite='Lax', path='/', max_age=7200)

        return resposta

    except Exception:
        return jsonify({'mensagem': 'Não foi possível realizar o login. Tente novamente.'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_conta', methods=['POST'])
def adicionar_conta():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não logado'}), 403

    tipo_conta = request.form.get('tipo_conta')
    pin = request.form.get('pin')

    cnpj = request.form.get('cnpj')
    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT ID_CONTA FROM CONTA WHERE ID_USUARIO = ? AND TIPO_CONTA = ?""",
                       (id_usuario, tipo_conta))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Usuário já possui esse tipo de conta'}), 400

        if str(tipo_conta) == '1':
            cursor.execute("""UPDATE USUARIO SET CNPJ = ?, NOME_FANTASIA = ?, RAZAO_SOCIAL = ?, REPRESENTANTE = ?
                              WHERE ID_USUARIO = ?""",
                           (cnpj, nome_fantasia, razao_social, representante, id_usuario))

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

        token = gerar_token(id_usuario, id_conta)

        resposta = make_response(jsonify({
            'mensagem': 'Conta criada com sucesso',
            'id_conta': id_conta,
            'numero_conta': numero_conta,
            'tipo_conta': tipo_conta
        }), 201)

        resposta.set_cookie('access_token', token, httponly=True, secure=False, samesite='Lax', path='/', max_age=7200)

        return resposta

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao criar conta: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/logout', methods=['POST'])
def logout():
    resposta = make_response(jsonify({'mensagem': 'Logout realizado com sucesso'}), 200)
    resposta.delete_cookie('access_token', path='/')

    return resposta