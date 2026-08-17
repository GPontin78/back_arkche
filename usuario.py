from flask import jsonify, request, make_response, render_template
from main import app, con
from funcao import gerar_token, descobre_id_usuario, descobre_tipo_usuario, gerar_codigo, enviando_email
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
            INNER JOIN recuperacao_senha r ON u.id_usuario = r.id_usuario
            WHERE u.email = ? AND r.codigo = ?
        """, (email, codigo))

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Código inválido'}), 400

        id_usuario = usuario[0]
        senha_atual = usuario[1]

        nova_senha_hash = bcrypt.hashpw(nova_senha).decode('utf-8')

        cursor.execute("""
            INSERT INTO historico_senha (id_usuario, senha_anterior)
            VALUES (?, ?)
        """, (id_usuario, senha_atual))

        cursor.execute("""
            UPDATE usuario
            SET senha = ?
            WHERE id_usuario = ?
        """, (nova_senha_hash, id_usuario))

        cursor.execute("""
            DELETE FROM recuperacao_senha
            WHERE id_usuario = ?
        """, (id_usuario,))

        con.commit()
        cursor.execute("""
            DELETE FROM historico_senha
            WHERE id_usuario = ?
            AND id_historico_senha NOT IN (
                SELECT FIRST 3 id_historico_senha
                FROM historico_senha
                WHERE id_usuario = ?
                ORDER BY id_historico_senha DESC
            )
        """, (id_usuario, id_usuario))

        con.commit()

        return jsonify({'mensagem': 'Senha alterada com sucesso'}), 200

    except:
        return jsonify({'mensagem': 'Erro ao trocar senha'}), 500

    finally:
        cursor.close()


@app.route('/edicao_usuario/<int:id_usuario>', methods=['PUT'])
def edicao_usuario(id_usuario):

    tipo_usuario = descobre_tipo_usuario()
    id_usuario_logado = descobre_id_usuario()

    if tipo_usuario is None:
        return jsonify({'mensagem': 'usuario nao logado'}), 403

    if tipo_usuario != 0:
        if id_usuario_logado != id_usuario:
            return jsonify({'mensagem': 'usuario nao pertence a essa conta'}), 403

    cursor = con.cursor()

    try:
        cursor.execute("""
            SELECT NOME, EMAIL, CPF, CNPJ, TELEFONE, TIPO, SENHA,
                   STATUS, TENTATIVAS, CEP, RUA, BAIRRO, NUMERO,
                   NOME_MAE, NOME_PAI, CIDADE, ESTADO, COMPLEMENTO,
                   NOME_FANTASIA, RAZAO_SOCIAL, REPRESENTANTE
            FROM USUARIO
            WHERE ID_USUARIO = ?
        """, (id_usuario,))

        existe_usuario = cursor.fetchone()

        if not existe_usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        nome = request.form.get('nome')
        email = request.form.get('email')
        cpf = request.form.get('cpf')
        cnpj = request.form.get('cnpj')
        telefone = request.form.get('telefone')
        senha = request.form.get('senha')
        tipo = request.form.get('tipo', existe_usuario[5])
        status = request.form.get('status', existe_usuario[7])
        tentativas = request.form.get('tentativas', existe_usuario[8])
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

        if not nome or not nome.strip():
            return jsonify({'mensagem': 'Nome é obrigatório'}), 400

        if not email or not email.strip():
            return jsonify({'mensagem': 'Email é obrigatório'}), 400

        if not cpf or not cpf.strip():
            return jsonify({'mensagem': 'CPF é obrigatório'}), 400

        alterar_senha = senha is not None and senha.strip() != ""

        cursor.execute("""
            SELECT 1
            FROM USUARIO
            WHERE EMAIL = ?
            AND ID_USUARIO != ?
        """, (email, id_usuario))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Email já cadastrado'}), 400

        cursor.execute("""
            SELECT 1
            FROM USUARIO
            WHERE CPF = ?
            AND ID_USUARIO != ?
        """, (cpf, id_usuario))

        if cursor.fetchone():
            return jsonify({'mensagem': 'CPF já cadastrado'}), 400

        if cnpj:
            cursor.execute("""
                SELECT 1
                FROM USUARIO
                WHERE CNPJ = ?
                AND ID_USUARIO != ?
            """, (cnpj, id_usuario))

            if cursor.fetchone():
                return jsonify({'mensagem': 'CNPJ já cadastrado'}), 400

        if alterar_senha:
            senha_hash = bcrypt.hashpw(
                senha.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')

            cursor.execute("""
                UPDATE USUARIO
                SET NOME = ?,
                    EMAIL = ?,
                    CPF = ?,
                    CNPJ = ?,
                    TELEFONE = ?,
                    SENHA = ?,
                    TIPO = ?,
                    STATUS = ?,
                    TENTATIVAS = ?,
                    CEP = ?,
                    RUA = ?,
                    BAIRRO = ?,
                    NUMERO = ?,
                    NOME_MAE = ?,
                    NOME_PAI = ?,
                    CIDADE = ?,
                    ESTADO = ?,
                    COMPLEMENTO = ?,
                    NOME_FANTASIA = ?,
                    RAZAO_SOCIAL = ?,
                    REPRESENTANTE = ?
                WHERE ID_USUARIO = ?
            """, (
                nome, email, cpf, cnpj, telefone, senha_hash, tipo,
                status, tentativas, cep, rua, bairro, numero, nome_mae,
                nome_pai, cidade, estado, complemento, nome_fantasia,
                razao_social, representante, id_usuario
            ))

            cursor.execute("""
                INSERT INTO historico_senha(id_usuario, senha_anterior)
                VALUES (?, ?)
            """, (id_usuario, senha_hash))

            con.commit()

            cursor.execute("""
                DELETE FROM historico_senha
                WHERE id_usuario = ?
                AND id_historico_senha NOT IN (
                    SELECT FIRST 3 id_historico_senha
                    FROM historico_senha
                    WHERE id_usuario = ?
                    ORDER BY id_historico_senha DESC
                )
            """, (id_usuario, id_usuario))

            con.commit()

        else:
            cursor.execute("""
                UPDATE USUARIO
                SET NOME = ?,
                    EMAIL = ?,
                    CPF = ?,
                    CNPJ = ?,
                    TELEFONE = ?,
                    TIPO = ?,
                    STATUS = ?,
                    TENTATIVAS = ?,
                    CEP = ?,
                    RUA = ?,
                    BAIRRO = ?,
                    NUMERO = ?,
                    NOME_MAE = ?,
                    NOME_PAI = ?,
                    CIDADE = ?,
                    ESTADO = ?,
                    COMPLEMENTO = ?,
                    NOME_FANTASIA = ?,
                    RAZAO_SOCIAL = ?,
                    REPRESENTANTE = ?
                WHERE ID_USUARIO = ?
            """, (
                nome, email, cpf, cnpj, telefone, tipo, status, tentativas,
                cep, rua, bairro, numero, nome_mae, nome_pai, cidade,
                estado, complemento, nome_fantasia, razao_social,
                representante, id_usuario
            ))

            con.commit()

        return jsonify({
            'mensagem': 'Usuário atualizado com sucesso',
            'id_usuario': id_usuario
        }), 200

    except Exception as e:
        con.rollback()
        return jsonify({'mensagem': f'erro ao editar: {e}'}), 500

    finally:
        cursor.close()
