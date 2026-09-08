from flask import jsonify, request, make_response, render_template
from main import app
from banco import con
from funcao import gerar_token, descobre_id_usuario, descobre_id_conta, criptografar_pin, verificar_pin, dados_usuario, dados_conta, gerar_codigo, enviando_email,data_atual
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

        data_movimentacao = data_atual()

        cursor.execute("""INSERT INTO MOVIMENTACAO (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
                          VALUES (?, ?, ?, ?)""",
                       (9, id_conta, 5000, data_movimentacao))

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

@app.route('/sessao', methods=['GET'])
def sessao():
    usuario = dados_usuario()
    conta = dados_conta()

    if not usuario or not conta:
        return jsonify({'mensagem': 'Sessão inválida ou expirada.'}), 401

    return jsonify({'usuario': usuario, 'conta': conta}), 200

@app.route('/esqueci_pin', methods=['POST'])
def esqueci_pin():
    dados = request.get_json()
    email = dados.get('email')

    try:
        cursor = con.cursor()

        cursor.execute("SELECT ID_USUARIO FROM USUARIO WHERE EMAIL = ?", (email,))
        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Email não encontrado'}), 404

        id_usuario = usuario[0]
        codigo = gerar_codigo()

        cursor.execute("DELETE FROM RECUPERACAO_SENHA WHERE ID_USUARIO = ?", (id_usuario,))
        cursor.execute("INSERT INTO RECUPERACAO_SENHA (ID_USUARIO, CODIGO) VALUES (?, ?)", (id_usuario, codigo))

        con.commit()

        html = render_template('codigo_verificacao.html', codigo=codigo)
        enviando_email(email, 'Código de Recuperação de PIN - Banco Arkhé', html)

        return jsonify({'mensagem': 'Código enviado com sucesso'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao enviar código: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/verificar_codigo', methods=['POST'])
def verificar_codigo():
    dados = request.get_json()
    email = dados.get('email')
    codigo = dados.get('codigo')

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT R.CODIGO FROM USUARIO U INNER JOIN RECUPERACAO_SENHA R ON U.ID_USUARIO = R.ID_USUARIO WHERE U.EMAIL = ?""", (email,))
        resultado = cursor.fetchone()

        if not resultado:
            return jsonify({'mensagem': 'Código inválido'}), 400

        codigo_banco = str(resultado[0])

        if str(codigo) != codigo_banco:
            return jsonify({'mensagem': 'Código inválido'}), 400

        return jsonify({'mensagem': 'Código válido'}), 200

    except Exception as e:
        return jsonify({'mensagem': f'Erro ao verificar código: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/trocar_pin', methods=['POST'])
def trocar_pin():
    dados = request.get_json()

    email = dados.get('email')
    codigo = dados.get('codigo')
    tipo_conta = dados.get('tipo_conta')
    novo_pin = dados.get('novo_pin')

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT U.ID_USUARIO, C.ID_CONTA, C.PIN_HASH FROM USUARIO U INNER JOIN RECUPERACAO_SENHA R ON U.ID_USUARIO = R.ID_USUARIO INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO WHERE U.EMAIL = ? AND R.CODIGO = ? AND C.TIPO_CONTA = ?""", (email, codigo, tipo_conta))
        conta = cursor.fetchone()

        if not conta:
            return jsonify({'mensagem': 'Código inválido'}), 400

        id_usuario = conta[0]
        id_conta = conta[1]
        pin_atual = conta[2]

        if verificar_pin(novo_pin, pin_atual):
            return jsonify({'mensagem': 'O novo PIN não pode ser igual ao PIN atual'}), 400

        novo_pin_hash = criptografar_pin(novo_pin)

        cursor.execute("UPDATE CONTA SET PIN_HASH = ? WHERE ID_CONTA = ?", (novo_pin_hash, id_conta))
        cursor.execute("DELETE FROM RECUPERACAO_SENHA WHERE ID_USUARIO = ?", (id_usuario,))

        con.commit()

        return jsonify({'mensagem': 'PIN alterado com sucesso'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao trocar PIN: {e}'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/buscar_contas_usuario', methods=['POST'])
def buscar_contas_usuario():
    dados = request.get_json()
    busca = dados.get('busca')

    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    cursor.execute("""SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA,
                      U.NOME, U.EMAIL, U.TELEFONE, U.CPF, U.CNPJ, U.NOME_FANTASIA, U.RAZAO_SOCIAL,
                      P.CHAVE_PIX_EMAIL, P.CHAVE_PIX_TELEFONE, P.CHAVE_PIX_CPF, P.CHAVE_PIX_ALEATORIA, P.CHAVE_PIX_CNPJ
                      FROM USUARIO U
                      INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO
                      LEFT JOIN CHAVE_PIX P ON P.ID_CONTA = C.ID_CONTA
                      WHERE CAST(U.CPF AS VARCHAR(255)) = ?
                      OR CAST(U.CNPJ AS VARCHAR(255)) = ?
                      OR CAST(U.EMAIL AS VARCHAR(255)) = ?
                      OR CAST(U.TELEFONE AS VARCHAR(255)) = ?
                      OR UPPER(CAST(U.NOME AS VARCHAR(255))) LIKE UPPER(?)
                      OR UPPER(CAST(U.NOME_FANTASIA AS VARCHAR(255))) LIKE UPPER(?)
                      OR UPPER(CAST(U.RAZAO_SOCIAL AS VARCHAR(255))) LIKE UPPER(?)""",
                   (busca, busca, busca, busca, '%' + busca + '%', '%' + busca + '%', '%' + busca + '%'))

    contas_banco = cursor.fetchall()
    cursor.close()

    if not contas_banco:
        return jsonify({'mensagem': 'Nenhuma conta encontrada'}), 404

    contas = []

    for conta in contas_banco:
        chaves_pix = []

        if conta[12]:
            chaves_pix.append({'tipo': 'email', 'valor': conta[12]})

        if conta[13]:
            chaves_pix.append({'tipo': 'telefone', 'valor': conta[13]})

        if conta[14]:
            chaves_pix.append({'tipo': 'cpf', 'valor': conta[14]})

        if conta[15]:
            chaves_pix.append({'tipo': 'aleatoria', 'valor': conta[15]})

        if conta[16]:
            chaves_pix.append({'tipo': 'cnpj', 'valor': conta[16]})

        contas.append({
            'id_conta': conta[0],
            'numero_conta': conta[1],
            'agencia': conta[2],
            'banco': conta[3],
            'tipo_conta': conta[4],
            'nome': conta[5],
            'email': conta[6],
            'telefone': conta[7],
            'cpf': conta[8],
            'cnpj': conta[9],
            'nome_fantasia': conta[10],
            'razao_social': conta[11],
            'chaves_pix': chaves_pix
        })

    return jsonify({'contas': contas}), 200