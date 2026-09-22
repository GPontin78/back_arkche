from flask import jsonify, request, make_response, render_template
import os
import requests
from main import app
from banco import con
from funcao import gerar_token, gerar_token_usuario, descobre_id_usuario, descobre_id_conta, criptografar_pin, verificar_pin, verificar_pin_usuario, usuario_pode_acessar_conta, listar_contas_usuario, dados_usuario, dados_conta, gerar_codigo, enviando_email, data_atual


def criar_sessao_facial(cpf):
    resposta = requests.post(
        os.getenv('FACE_API_URL') + '/v1/verifications',
        headers={
            'X-Client-Id': os.getenv('FACE_CLIENT_ID'),
            'X-Client-Secret': os.getenv('FACE_CLIENT_SECRET')
        },
        json={
            'cpf': cpf,
            'purpose': 'login',
            'ttl_minutes': 10
        },
        timeout=20
    )

    print('FACE STATUS:', resposta.status_code)
    print('FACE RESPOSTA:', resposta.text)

    if not resposta.ok:
        return None

    return resposta.json()


@app.route('/login_usuario', methods=['POST'])
def login_usuario():
    dados = request.get_json() or {}

    cpf = dados.get('cpf')
    pin = dados.get('pin')
    cadastro_facial = dados.get('cadastro_facial', False)
    mobile = dados.get('mobile', False)

    if not cpf or pin is None:
        return jsonify({'mensagem': 'CPF e PIN são obrigatórios'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_USUARIO, NOME, EMAIL, TELEFONE, CPF, STATUS, PRIMEIRO_ACESSO
               FROM USUARIO
               WHERE CPF = ?""",
            (cpf,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'CPF ou PIN inválido'}), 401

        id_usuario = usuario[0]
        nome = usuario[1]
        email = usuario[2]
        telefone = usuario[3]
        cpf_usuario = usuario[4]
        status = usuario[5]
        primeiro_acesso = usuario[6]

        resultado_pin = verificar_pin_usuario(id_usuario, pin)

        if resultado_pin.get('temporario_expirado'):
            return jsonify({
                'mensagem': 'PIN temporário expirado',
                'pin_temporario_expirado': True
            }), 401

        if not resultado_pin['valido']:
            return jsonify({
                'mensagem': 'CPF ou PIN inválido'
            }), 401

        if not cadastro_facial:
            if mobile:
                sessao_facial = criar_sessao_facial(cpf_usuario)

                if not sessao_facial:
                    return jsonify({
                        'mensagem': 'Não foi possível iniciar o reconhecimento facial'
                    }), 500

                return jsonify({
                    'mensagem': 'Credenciais válidas',
                    'reconhecimento_facial_pendente': True,
                    'sessao_facial': sessao_facial,
                    'troca_pin_obrigatoria': bool(
                        resultado_pin.get('legado')
                        or resultado_pin.get('temporario')
                        or primeiro_acesso == 1
                    )
                }), 200

            return jsonify({
                'mensagem': 'Credenciais válidas',
                'reconhecimento_facial_pendente': True,
                'troca_pin_obrigatoria': bool(
                    resultado_pin.get('legado')
                    or resultado_pin.get('temporario')
                    or primeiro_acesso == 1
                )
            }), 200

        token = gerar_token_usuario(id_usuario)

        troca_pin_obrigatoria = bool(
            resultado_pin.get('legado')
            or resultado_pin.get('temporario')
            or primeiro_acesso == 1
        )

        resposta = make_response(jsonify({
            'mensagem': 'Usuário autenticado com sucesso',
            'usuario': {
                'id_usuario': id_usuario,
                'nome': nome,
                'email': email,
                'telefone': telefone,
                'cpf': cpf_usuario,
                'status': status
            },
            'troca_pin_obrigatoria': troca_pin_obrigatoria,
            'selecao_conta_pendente': not troca_pin_obrigatoria
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
        print('ERRO LOGIN USUARIO:', e)

        return jsonify({
            'mensagem': 'Não foi possível realizar o login. Tente novamente.'
        }), 500

    finally:
        if cursor:
            cursor.close()

            

@app.route('/definir_pin_pessoal', methods=['POST'])
def definir_pin_pessoal():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não autenticado'}), 401

    dados = request.get_json() or {}
    novo_pin = dados.get('novo_pin')

    if novo_pin is None:
        return jsonify({'mensagem': 'Novo PIN não informado'}), 400

    novo_pin = str(novo_pin)

    if len(novo_pin) != 6 or not novo_pin.isdigit():
        return jsonify({'mensagem': 'O PIN deve possuir exatamente 6 números'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT PIN_HASH, PRIMEIRO_ACESSO
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        pin_hash_atual = usuario[0]
        primeiro_acesso = usuario[1]

        if pin_hash_atual is not None and primeiro_acesso != 1:
            return jsonify({'mensagem': 'Este usuário já possui um PIN pessoal'}), 400

        novo_pin_hash = criptografar_pin(novo_pin)

        cursor.execute(
            """UPDATE USUARIO
               SET PIN_HASH = ?, PRIMEIRO_ACESSO = 0, PIN_TEMPORARIO_EXPIRA_EM = NULL
               WHERE ID_USUARIO = ?""",
            (novo_pin_hash, id_usuario)
        )

        cursor.execute(
            """UPDATE CONTA
               SET PIN_HASH = ?
               WHERE ID_USUARIO = ?""",
            (novo_pin_hash, id_usuario)
        )

        con.commit()

        return jsonify({'mensagem': 'PIN pessoal definido com sucesso'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO DEFINIR PIN PESSOAL:', e)
        return jsonify({'mensagem': 'Erro ao definir PIN pessoal'}), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/contas_disponiveis', methods=['GET'])
def contas_disponiveis():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não autenticado'}), 401

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT PRIMEIRO_ACESSO, PIN_HASH
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        if usuario[0] == 1 or usuario[1] is None:
            return jsonify({
                'mensagem': 'Defina seu PIN pessoal antes de escolher uma conta',
                'troca_pin_obrigatoria': True
            }), 403

        contas = listar_contas_usuario(id_usuario)

        return jsonify({
            'contas': contas
        }), 200

    except Exception as e:
        print('ERRO CONTAS DISPONIVEIS:', e)

        return jsonify({
            'mensagem': 'Erro ao buscar contas disponíveis'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/selecionar_conta', methods=['POST'])
def selecionar_conta():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não autenticado'}), 401

    dados = request.get_json() or {}
    id_conta = dados.get('id_conta')

    if not id_conta:
        return jsonify({'mensagem': 'Conta não informada'}), 400

    cursor = None

    try:
        id_conta = int(id_conta)

        cursor = con.cursor()

        cursor.execute(
            """SELECT PRIMEIRO_ACESSO, PIN_HASH
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        if usuario[0] == 1 or usuario[1] is None:
            return jsonify({
                'mensagem': 'Defina seu PIN pessoal antes de selecionar uma conta',
                'troca_pin_obrigatoria': True
            }), 403

        if not usuario_pode_acessar_conta(id_usuario, id_conta):
            return jsonify({
                'mensagem': 'Você não possui acesso a esta conta'
            }), 403

        contas = listar_contas_usuario(id_usuario)
        conta_selecionada = None

        for conta in contas:
            if conta['id_conta'] == id_conta:
                conta_selecionada = conta
                break

        if not conta_selecionada:
            return jsonify({'mensagem': 'Conta não encontrada'}), 404

        token = gerar_token(id_usuario, id_conta)

        resposta = make_response(jsonify({
            'mensagem': 'Conta selecionada com sucesso',
            'conta': conta_selecionada
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

    except (TypeError, ValueError):
        return jsonify({'mensagem': 'Conta inválida'}), 400

    except Exception as e:
        print('ERRO SELECIONAR CONTA:', e)

        return jsonify({
            'mensagem': 'Erro ao selecionar conta'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/sessao_usuario', methods=['GET'])
def sessao_usuario():
    usuario = dados_usuario()

    if not usuario:
        return jsonify({
            'mensagem': 'Sessão inválida ou expirada'
        }), 401

    id_conta = descobre_id_conta()

    return jsonify({
        'usuario': usuario,
        'conta_selecionada': id_conta is not None
    }), 200


@app.route('/login', methods=['POST'])
def login():
    dados = request.get_json()

    cpf = dados.get('cpf')
    pin = dados.get('pin')
    tipo_conta = dados.get('tipo_conta')
    cadastro_facial = dados.get('cadastro_facial', False)
    mobile = dados.get('mobile', False)

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT U.ID_USUARIO, U.NOME, U.EMAIL, U.TELEFONE, U.CPF,
                      C.ID_CONTA, C.PIN_HASH, C.NUMERO_CONTA, C.AGENCIA,
                      C.BANCO, C.TIPO_CONTA
               FROM USUARIO U
               INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO
               WHERE U.CPF = ? AND C.TIPO_CONTA = ?""",
            (cpf, tipo_conta)
        )

        dados_do_banco = cursor.fetchone()

        if not dados_do_banco:
            return jsonify({
                'mensagem': 'CPF, PIN ou tipo de conta inválido'
            }), 401

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
            return jsonify({
                'mensagem': 'CPF, PIN ou tipo de conta inválido'
            }), 401

        if not cadastro_facial:
            if mobile:
                sessao_facial = criar_sessao_facial(cpf)

                if not sessao_facial:
                    return jsonify({
                        'mensagem': 'Não foi possível iniciar o reconhecimento facial'
                    }), 500

                return jsonify({
                    'mensagem': 'Credenciais válidas',
                    'reconhecimento_facial_pendente': True,
                    'sessao_facial': sessao_facial
                }), 200

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
        print('ERRO LOGIN:', e)

        return jsonify({
            'mensagem': 'Não foi possível realizar o login. Tente novamente.'
        }), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/adicionar_conta', methods=['POST'])
def adicionar_conta():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({'mensagem': 'Usuário não autenticado'}), 401

    tipo_conta = request.form.get('tipo_conta')

    cnpj = request.form.get('cnpj')
    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')

    if tipo_conta is None:
        return jsonify({'mensagem': 'Tipo de conta não informado'}), 400

    try:
        tipo_conta = int(tipo_conta)

        if tipo_conta not in (0, 1):
            return jsonify({'mensagem': 'Tipo de conta inválido'}), 400

    except (TypeError, ValueError):
        return jsonify({'mensagem': 'Tipo de conta inválido'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT PIN_HASH, PRIMEIRO_ACESSO
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Usuário não encontrado'}), 404

        pin_hash_usuario = usuario[0]
        primeiro_acesso = usuario[1]

        if pin_hash_usuario is None or primeiro_acesso == 1:
            return jsonify({
                'mensagem': 'Defina seu PIN pessoal antes de abrir uma conta'
            }), 403

        cursor.execute(
            """SELECT ID_CONTA
               FROM CONTA
               WHERE ID_USUARIO = ? AND TIPO_CONTA = ?""",
            (id_usuario, tipo_conta)
        )

        if cursor.fetchone():
            return jsonify({
                'mensagem': 'Usuário já possui esse tipo de conta'
            }), 400

        if tipo_conta == 1:
            if not cnpj or not nome_fantasia or not razao_social:
                return jsonify({
                    'mensagem': 'CNPJ, nome fantasia e razão social são obrigatórios para conta PJ'
                }), 400

            cursor.execute(
                """UPDATE USUARIO
                   SET CNPJ = ?, NOME_FANTASIA = ?, RAZAO_SOCIAL = ?, REPRESENTANTE = ?
                   WHERE ID_USUARIO = ?""",
                (
                    cnpj,
                    nome_fantasia,
                    razao_social,
                    representante,
                    id_usuario
                )
            )

        cursor.execute("SELECT MAX(NUMERO_CONTA) FROM CONTA")
        numero_conta = cursor.fetchone()[0] or 0
        numero_conta += 1

        cursor.execute(
            """INSERT INTO CONTA
               (ID_USUARIO, NUMERO_CONTA, AGENCIA, BANCO, TIPO_CONTA, PIN_HASH,
                CNPJ, NOME_FANTASIA, RAZAO_SOCIAL)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               RETURNING ID_CONTA""",
            (
                id_usuario,
                numero_conta,
                '0001',
                248,
                tipo_conta,
                pin_hash_usuario,
                cnpj if tipo_conta == 1 else None,
                nome_fantasia if tipo_conta == 1 else None,
                razao_social if tipo_conta == 1 else None
            )
        )

        id_conta = cursor.fetchone()[0]

        data_movimentacao = data_atual()

        cursor.execute(
            """INSERT INTO MOVIMENTACAO
               (ID_PAGADOR, ID_RECEBEDOR, VALOR, DATA_MOVIMENTACAO)
               VALUES (?, ?, ?, ?)""",
            (
                9,
                id_conta,
                5000,
                data_movimentacao
            )
        )

        con.commit()

        token = gerar_token(id_usuario, id_conta)

        resposta = make_response(jsonify({
            'mensagem': 'Conta criada com sucesso',
            'id_conta': id_conta,
            'numero_conta': numero_conta,
            'tipo_conta': tipo_conta
        }), 201)

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
        con.rollback()
        print('ERRO ADICIONAR CONTA:', e)
        return jsonify({'mensagem': 'Erro ao criar conta'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/logout', methods=['POST'])
def logout():
    resposta = make_response(jsonify({
        'mensagem': 'Logout realizado com sucesso'
    }), 200)

    resposta.delete_cookie(
        'access_token',
        path='/'
    )

    return resposta


@app.route('/sessao', methods=['GET'])
def sessao():
    usuario = dados_usuario()
    conta = dados_conta()

    if not usuario or not conta:
        return jsonify({
            'mensagem': 'Sessão inválida ou expirada.'
        }), 401

    return jsonify({
        'usuario': usuario,
        'conta': conta
    }), 200


@app.route('/esqueci_pin', methods=['POST'])
def esqueci_pin():
    dados = request.get_json()
    email = dados.get('email')

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            "SELECT ID_USUARIO FROM USUARIO WHERE EMAIL = ?",
            (email,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({
                'mensagem': 'Email não encontrado'
            }), 404

        id_usuario = usuario[0]
        codigo = gerar_codigo()

        cursor.execute(
            "DELETE FROM RECUPERACAO_SENHA WHERE ID_USUARIO = ?",
            (id_usuario,)
        )

        cursor.execute(
            """INSERT INTO RECUPERACAO_SENHA
               (ID_USUARIO, CODIGO)
               VALUES (?, ?)""",
            (id_usuario, codigo)
        )

        con.commit()

        html = render_template(
            'codigo_verificacao.html',
            codigo=codigo
        )

        enviando_email(
            email,
            'Código de Recuperação de PIN - Banco Arkhé',
            html
        )

        return jsonify({
            'mensagem': 'Código enviado com sucesso'
        }), 200

    except Exception as e:
        con.rollback()

        return jsonify({
            'mensagem': f'Erro ao enviar código: {e}'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/verificar_codigo', methods=['POST'])
def verificar_codigo():
    dados = request.get_json()
    email = dados.get('email')
    codigo = dados.get('codigo')

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT R.CODIGO
               FROM USUARIO U
               INNER JOIN RECUPERACAO_SENHA R
               ON U.ID_USUARIO = R.ID_USUARIO
               WHERE U.EMAIL = ?""",
            (email,)
        )

        resultado = cursor.fetchone()

        if not resultado:
            return jsonify({
                'mensagem': 'Código inválido'
            }), 400

        codigo_banco = str(resultado[0])

        if str(codigo) != codigo_banco:
            return jsonify({
                'mensagem': 'Código inválido'
            }), 400

        return jsonify({
            'mensagem': 'Código válido'
        }), 200

    except Exception as e:
        return jsonify({
            'mensagem': f'Erro ao verificar código: {e}'
        }), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/trocar_pin', methods=['POST'])
def trocar_pin():
    dados = request.get_json() or {}

    email = dados.get('email')
    codigo = dados.get('codigo')
    novo_pin = dados.get('novo_pin')

    if not email or not codigo or novo_pin is None:
        return jsonify({'mensagem': 'Email, código e novo PIN são obrigatórios'}), 400

    novo_pin = str(novo_pin)

    if len(novo_pin) != 6 or not novo_pin.isdigit():
        return jsonify({'mensagem': 'O PIN deve possuir exatamente 6 números'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT U.ID_USUARIO, U.PIN_HASH
               FROM USUARIO U
               INNER JOIN RECUPERACAO_SENHA R ON R.ID_USUARIO = U.ID_USUARIO
               WHERE U.EMAIL = ? AND R.CODIGO = ?""",
            (email, codigo)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return jsonify({'mensagem': 'Código inválido'}), 400

        id_usuario = usuario[0]
        pin_atual = usuario[1]

        if pin_atual and verificar_pin(novo_pin, pin_atual):
            return jsonify({'mensagem': 'O novo PIN não pode ser igual ao PIN atual'}), 400

        novo_pin_hash = criptografar_pin(novo_pin)

        cursor.execute(
            """UPDATE USUARIO
               SET PIN_HASH = ?, PRIMEIRO_ACESSO = 0, PIN_TEMPORARIO_EXPIRA_EM = NULL
               WHERE ID_USUARIO = ?""",
            (novo_pin_hash, id_usuario)
        )

        cursor.execute(
            """UPDATE CONTA
               SET PIN_HASH = ?
               WHERE ID_USUARIO = ?""",
            (novo_pin_hash, id_usuario)
        )

        cursor.execute(
            """DELETE FROM RECUPERACAO_SENHA
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        con.commit()

        return jsonify({'mensagem': 'PIN alterado com sucesso'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO TROCAR PIN:', e)
        return jsonify({'mensagem': 'Erro ao trocar PIN'}), 500

    finally:
        if cursor:
            cursor.close()

@app.route('/buscar_contas_usuario', methods=['POST'])
def buscar_contas_usuario():
    dados = request.get_json() or {}
    busca = dados.get('busca')

    id_conta = descobre_id_conta()

    if not id_conta:
        return jsonify({
            'mensagem': 'Usuário não logado'
        }), 403

    if not busca:
        return jsonify({
            'mensagem': 'Busca não informada'
        }), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA,
                      U.NOME, U.EMAIL, U.TELEFONE, U.CPF,
                      C.CNPJ, C.NOME_FANTASIA, C.RAZAO_SOCIAL,
                      P.CHAVE_PIX_EMAIL, P.CHAVE_PIX_TELEFONE,
                      P.CHAVE_PIX_CPF, P.CHAVE_PIX_ALEATORIA,
                      P.CHAVE_PIX_CNPJ
               FROM CONTA C
               INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
               LEFT JOIN CHAVE_PIX P ON P.ID_CONTA = C.ID_CONTA
               WHERE CAST(U.CPF AS VARCHAR(255)) = ?
                  OR CAST(C.CNPJ AS VARCHAR(255)) = ?
                  OR CAST(U.EMAIL AS VARCHAR(255)) = ?
                  OR CAST(U.TELEFONE AS VARCHAR(255)) = ?
                  OR UPPER(CAST(U.NOME AS VARCHAR(255))) LIKE UPPER(?)
                  OR UPPER(CAST(C.NOME_FANTASIA AS VARCHAR(255))) LIKE UPPER(?)
                  OR UPPER(CAST(C.RAZAO_SOCIAL AS VARCHAR(255))) LIKE UPPER(?)
               ORDER BY C.ID_CONTA""",
            (
                busca,
                busca,
                busca,
                busca,
                '%' + busca + '%',
                '%' + busca + '%',
                '%' + busca + '%'
            )
        )

        contas_banco = cursor.fetchall()

        if not contas_banco:
            return jsonify({
                'mensagem': 'Nenhuma conta encontrada'
            }), 404

        contas = []

        for conta in contas_banco:
            chaves_pix = []

            if conta[12]:
                chaves_pix.append({
                    'tipo': 'email',
                    'valor': conta[12]
                })

            if conta[13]:
                chaves_pix.append({
                    'tipo': 'telefone',
                    'valor': conta[13]
                })

            if conta[14]:
                chaves_pix.append({
                    'tipo': 'cpf',
                    'valor': conta[14]
                })

            if conta[15]:
                chaves_pix.append({
                    'tipo': 'aleatoria',
                    'valor': conta[15]
                })

            if conta[16]:
                chaves_pix.append({
                    'tipo': 'cnpj',
                    'valor': conta[16]
                })

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

        return jsonify({
            'contas': contas
        }), 200

    except Exception as e:
        print('ERRO BUSCAR CONTAS:', e)

        return jsonify({
            'mensagem': 'Erro ao buscar contas'
        }), 500

    finally:
        if cursor:
            cursor.close()