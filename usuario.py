from flask import jsonify, request, make_response, render_template
from main import app, con
from funcao import gerar_token, descobre_tipo_usuario, descobre_id_usuario, gerar_codigo, enviando_email
import bcrypt
import threading


@app.route('/adicionar_usuario', methods=['POST'])
def adicionar_usuario():
    nome = request.form.get('nome')
    email = request.form.get('email')
    telefone = request.form.get('telefone')
    cpf = request.form.get('cpf')
    cnpj = request.form.get('cnpj')
    senha = request.form.get('senha')


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

    if email:
        email = email.lower()

    if not nome or not nome.strip():
        return jsonify({
            'mensagem': 'Nome é obrigatório'
        }), 400
    try:
        cursor = con.cursor()
        cursor.execute(
            "SELECT 1 FROM USUARIO WHERE EMAIL = ?",
            (email,)
        )

        if cursor.fetchone():
            return jsonify({
                'mensagem': 'Email já cadastrado'
            }), 400
        cursor.execute(
            "SELECT 1 FROM USUARIO WHERE CPF = ?",
            (cpf,)
        )

        if cursor.fetchone():
            return jsonify({
                'mensagem': 'CPF já cadastrado'
            }), 400

        if cnpj:
            cursor.execute(
                "SELECT 1 FROM USUARIO WHERE CNPJ = ?",
                (cnpj,)
            )

            if cursor.fetchone():
                return jsonify({
                    'mensagem': 'CNPJ já cadastrado'
                }), 400

        senha_hash = bcrypt.hashpw(
            senha.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        cursor.execute("""
            INSERT INTO USUARIO (
                NOME,EMAIL,TELEFONE,CPF,CNPJ,SENHA,TIPO,STATUS,TENTATIVAS,CEP,RUA,NUMERO,BAIRRO,CIDADE,ESTADO,COMPLEMENTO,NOME_FANTASIA,RAZAO_SOCIAL,REPRESENTANTE)VALUES (?, ?, ?, ?, ?, ?, ?,1, 0,?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING ID_USUARIO
        """, (
            nome,email,telefone,cpf,cnpj,senha_hash,tipo,cep,rua,numero,bairro,cidade,estado,complemento,nome_fantasia,razao_social,representante))

        id_usuario = cursor.fetchone()[0]

        con.commit()

        return jsonify({
            'mensagem': 'Usuário cadastrado com sucesso',
            'id_usuario': id_usuario
        }), 201

    except Exception as e:
        con.rollback()

        return jsonify({
            'mensagem': f'Erro ao cadastrar usuário: {e}'
        }), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/login', methods=['POST'])
def login():
    dados = request.get_json()

    cpf = dados.get('cpf')
    senha = dados.get('senha')

    cadastro_facial = dados.get('cadastro_facial', False)


    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT
                ID_USUARIO,
                NOME,
                EMAIL,
                SENHA,
                TELEFONE,
                CPF,
                TIPO
            FROM USUARIO
            WHERE CPF = ?
        """, (cpf,))

        dados_do_banco = cursor.fetchone()

        if not dados_do_banco:
            return jsonify({
                'mensagem': 'CPF ou senha inválida'
            }), 401

        id_usuario = dados_do_banco[0]
        nome_usuario = dados_do_banco[1]
        email_usuario = dados_do_banco[2]
        senha_banco = dados_do_banco[3]
        telefone = dados_do_banco[4]
        cpf_usuario = dados_do_banco[5]
        tipo = dados_do_banco[6]

        senha_correta = bcrypt.checkpw(
            senha.encode('utf-8'),
            senha_banco.encode('utf-8')
        )

        if not senha_correta:
            return jsonify({
                'mensagem': 'CPF ou senha inválida'
            }), 401

        if not cadastro_facial:
            return jsonify({
                'mensagem': 'Credenciais válidas',
                'reconhecimento_facial_pendente': True,
                'usuario': {
                    'id_usuario': id_usuario,
                    'nome': nome_usuario,
                    'email': email_usuario,
                    'tipo': tipo,
                    'telefone': telefone,
                    'cpf': cpf_usuario
                }
            }), 200

        token = gerar_token(
            id_usuario,
            tipo
        )

        resposta = make_response(jsonify({
            'mensagem': 'Login com sucesso',

            'usuario': {
                'id_usuario': id_usuario,
                'nome': nome_usuario,
                'email': email_usuario,
                'tipo': tipo,
                'telefone': telefone,
                'cpf': cpf_usuario
            },

            'token': token

        }), 200)

        resposta.set_cookie(
            'access_token',
            token,
            httponly=True,
            secure=False,
            samesite='Lax',
            path='/',
            max_age=7200
        )

        return resposta

    except Exception as e:
        return jsonify({
            'mensagem': f'Erro no login: {e}'
        }), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/esqueci_senha', methods=['POST'])
def esqueci_senha():
    dados = request.get_json()
    email = dados.get('email')

    try:
        cursor = con.cursor()

        cursor.execute("SELECT id_usuario FROM usuario WHERE email = ?", (email,))
        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Email não encontrado'}), 404

        id_usuario = usuario[0]
        codigo = gerar_codigo()

        cursor.execute("DELETE FROM recuperacao_senha WHERE id_usuario = ?", (id_usuario,))

        cursor.execute("""
            INSERT INTO recuperacao_senha (id_usuario, codigo)
            VALUES (?, ?)
        """, (id_usuario, codigo))

        con.commit()
        html = render_template('codigo_verificacao.html', codigo=codigo)

        thread = threading.Thread(
            target=enviando_email,
            args=(email, "Código de Recuperação de Senha - WebCar", html)
        )
        thread.start()

        return jsonify({'mensagem': 'Código enviado com sucesso'}), 200

    except:
        return jsonify({'mensagem': 'Erro ao enviar código'}), 500

    finally:
        cursor.close()

@app.route('/verificar_codigo', methods=['POST'])
def verificar_codigo():
    dados = request.get_json()
    email = dados.get('email')
    codigo = int(dados.get('codigo'))

    try:
        cursor = con.cursor()
        cursor.execute("""
            SELECT r.codigo
            FROM usuario u
            INNER JOIN recuperacao_senha r ON u.id_usuario = r.id_usuario
            WHERE u.email = ?
        """, (email,))

        resultado = cursor.fetchone()

        if not resultado:
            return jsonify({'mensagem': 'Código inválido'}), 400

        codigo_banco = int(resultado[0])

        if codigo != codigo_banco:
            return jsonify({'mensagem': 'Código inválido'}), 400

        return jsonify({'mensagem': 'Código válido'}), 200

    except:
        return jsonify({'mensagem': 'Erro ao verificar código'}), 500

    finally:
        cursor.close()

@app.route('/trocar_senha', methods=['POST'])
def trocar_senha():
    dados = request.get_json()

    email = dados.get('email')
    codigo = dados.get('codigo')
    nova_senha = dados.get('nova_senha')
    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT u.id_usuario, u.senha
            FROM usuario u
            INNER JOIN recuperacao_senha r 
                ON u.id_usuario = r.id_usuario
            WHERE u.email = ?
            AND r.codigo = ?
        """, (email, codigo))

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({
                'mensagem': 'Código inválido'
            }), 400

        id_usuario = usuario[0]
        senha_atual = usuario[1]

        # Verifica se a nova senha é igual à senha atual
        senha_igual = bcrypt.checkpw(
            nova_senha.encode('utf-8'),
            senha_atual.encode('utf-8')
        )

        if senha_igual:
            return jsonify({
                'mensagem': 'A nova senha não pode ser igual à senha atual'
            }), 400

        # Cria o hash da nova senha
        nova_senha_hash = bcrypt.hashpw(
            nova_senha.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

        # Atualiza a senha do usuário
        cursor.execute("""
            UPDATE usuario
            SET senha = ?
            WHERE id_usuario = ?
        """, (
            nova_senha_hash,
            id_usuario
        ))

        # Apaga o código de recuperação depois que ele foi usado
        cursor.execute("""
            DELETE FROM recuperacao_senha
            WHERE id_usuario = ?
        """, (
            id_usuario,
        ))

        con.commit()

        return jsonify({
            'mensagem': 'Senha alterada com sucesso'
        }), 200

    except Exception as e:
        con.rollback()

        return jsonify({
            'mensagem': f'Erro ao trocar senha: {e}'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/edicao_usuario/<int:id_usuario>', methods=['PUT'])
def edicao_usuario(id_usuario):
    tipo_usuario = descobre_tipo_usuario()
    id_usuario_logado = descobre_id_usuario()

    if tipo_usuario is None or id_usuario_logado is None:
        return jsonify({'mensagem': 'Usuário não logado'}), 403

    if tipo_usuario != 0:
        if id_usuario_logado != id_usuario:
            return jsonify({'mensagem': 'Usuário não pertence a essa conta'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("SELECT NOME, EMAIL, CPF, CNPJ, TELEFONE, CEP, RUA, BAIRRO, NUMERO, NOME_MAE, NOME_PAI, CIDADE, ESTADO, COMPLEMENTO, NOME_FANTASIA, RAZAO_SOCIAL, REPRESENTANTE FROM USUARIO WHERE ID_USUARIO = ?", (id_usuario,))
        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        nome = request.form.get('nome', usuario[0])
        email = request.form.get('email', usuario[1])
        cpf = request.form.get('cpf', usuario[2])
        cnpj = request.form.get('cnpj', usuario[3])
        telefone = request.form.get('telefone', usuario[4])
        cep = request.form.get('cep', usuario[5])
        rua = request.form.get('rua', usuario[6])
        bairro = request.form.get('bairro', usuario[7])
        numero = request.form.get('numero', usuario[8])
        nome_mae = request.form.get('nome_mae', usuario[9])
        nome_pai = request.form.get('nome_pai', usuario[10])
        cidade = request.form.get('cidade', usuario[11])
        estado = request.form.get('estado', usuario[12])
        complemento = request.form.get('complemento', usuario[13])
        nome_fantasia = request.form.get('nome_fantasia', usuario[14])
        razao_social = request.form.get('razao_social', usuario[15])
        representante = request.form.get('representante', usuario[16])

        if email:
            email = email.strip().lower()

        if not nome or not nome.strip():
            return jsonify({'mensagem': 'Nome é obrigatório'}), 400

        if not email or not email.strip():
            return jsonify({'mensagem': 'Email é obrigatório'}), 400

        if not cpf or not cpf.strip():
            return jsonify({'mensagem': 'CPF é obrigatório'}), 400

        if cnpj is not None:
            cnpj = cnpj.strip()

            if cnpj == "":
                cnpj = None

        conta_pj = cnpj is not None

        if not conta_pj:
            nome_fantasia = None
            razao_social = None
            representante = None

        cursor.execute("SELECT 1 FROM USUARIO WHERE EMAIL = ? AND ID_USUARIO != ?", (email, id_usuario))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Email já cadastrado'}), 400

        cursor.execute("SELECT 1 FROM USUARIO WHERE CPF = ? AND ID_USUARIO != ?", (cpf, id_usuario))

        if cursor.fetchone():
            return jsonify({'mensagem': 'CPF já cadastrado'}), 400

        if conta_pj:
            cursor.execute("SELECT 1 FROM USUARIO WHERE CNPJ = ? AND ID_USUARIO != ?", (cnpj, id_usuario))

            if cursor.fetchone():
                return jsonify({'mensagem': 'CNPJ já cadastrado'}), 400

        cursor.execute("UPDATE USUARIO SET NOME = ?, EMAIL = ?, CPF = ?, CNPJ = ?, TELEFONE = ?, CEP = ?, RUA = ?, BAIRRO = ?, NUMERO = ?, NOME_MAE = ?, NOME_PAI = ?, CIDADE = ?, ESTADO = ?, COMPLEMENTO = ?, NOME_FANTASIA = ?, RAZAO_SOCIAL = ?, REPRESENTANTE = ? WHERE ID_USUARIO = ?", (nome, email, cpf, cnpj, telefone, cep, rua, bairro, numero, nome_mae, nome_pai, cidade, estado, complemento, nome_fantasia, razao_social, representante, id_usuario))

        con.commit()

        return jsonify({
            'mensagem': 'Usuário atualizado com sucesso',
            'id_usuario': id_usuario,
            'tipo_conta': 'PJ' if conta_pj else 'PF'
        }), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'Erro ao editar usuário: {e}'}), 500

    finally:
        if cursor:
            cursor.close()
