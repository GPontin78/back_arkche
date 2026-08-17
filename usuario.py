from flask import jsonify, request, make_response
from main import app, con
from funcao import gerar_token
import bcrypt


@app.route('/adicionar_usuario', methods=['POST'])
def adicionar_usuario():
    nome = request.form.get('nome')
    email = request.form.get('email')
    telefone = request.form.get('telefone')
    cpf = request.form.get('cpf')
    cnpj = request.form.get('cnpj')
    senha = request.form.get('senha')
    data_nascimento = request.form.get('data_nascimento')

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

    # ========================================
    # VALIDA SENHA
    # ========================================

    if not nome or not nome.strip():
        return jsonify({
            'mensagem': 'Nome é obrigatório'
        }), 400
    try:
        cursor = con.cursor()

        # ========================================
        # VERIFICA EMAIL
        # ========================================

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