from flask import jsonify, request
import datetime
from main import app
from banco import con
from funcao import descobre_id_usuario, descobre_id_conta, criptografar_pin, data_atual


@app.route('/verificar_usuario', methods=['POST'])
def verificar_usuario():
    dados = request.get_json() or {}
    cpf = dados.get('cpf')

    if not cpf:
        return jsonify({'mensagem': 'CPF não informado'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_USUARIO, NOME, EMAIL, TELEFONE
               FROM USUARIO
               WHERE CPF = ?""",
            (cpf,)
        )

        usuario = cursor.fetchone()

        if usuario:
            return jsonify({
                'usuario_existente': True,
                'usuario': {
                    'id_usuario': usuario[0],
                    'nome': usuario[1],
                    'email': usuario[2],
                    'telefone': usuario[3]
                }
            }), 200

        return jsonify({
            'usuario_existente': False
        }), 200

    except Exception as e:
        print('ERRO VERIFICAR USUARIO:', e)

        return jsonify({
            'mensagem': 'Erro ao verificar usuário'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/adicionar_usuario', methods=['POST'])
def adicionar_usuario():
    nome = request.form.get('nome')
    email = request.form.get('email')
    telefone = request.form.get('telefone')
    cpf = request.form.get('cpf')
    pin = request.form.get('pin')
    tipo_conta = request.form.get('tipo_conta')
    tipo = request.form.get('tipo')

    data_nascimento = request.form.get('data_nascimento')

    cep = request.form.get('cep')
    rua = request.form.get('rua')
    numero = request.form.get('numero')
    bairro = request.form.get('bairro')
    cidade = request.form.get('cidade')
    estado = request.form.get('estado')
    complemento = request.form.get('complemento')

    cnpj = request.form.get('cnpj')
    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')

    if not nome or not email or not cpf or pin is None or tipo_conta is None:
        return jsonify({
            'mensagem': 'Nome, email, CPF, PIN e tipo de conta são obrigatórios'
        }), 400

    pin = str(pin)

    if len(pin) != 6 or not pin.isdigit():
        return jsonify({
            'mensagem': 'O PIN deve possuir exatamente 6 números'
        }), 400

    try:
        tipo_conta = int(tipo_conta)

        if tipo_conta not in (0, 1):
            return jsonify({
                'mensagem': 'Tipo de conta inválido'
            }), 400

    except (TypeError, ValueError):
        return jsonify({
            'mensagem': 'Tipo de conta inválido'
        }), 400

    if data_nascimento:
        try:
            data_nascimento = datetime.datetime.strptime(
                data_nascimento,
                '%Y-%m-%d'
            ).date()

        except ValueError:
            return jsonify({
                'mensagem': 'Data de nascimento inválida'
            }), 400

    if tipo_conta == 1:
        if not cnpj or not nome_fantasia or not razao_social:
            return jsonify({
                'mensagem': 'CNPJ, nome fantasia e razão social são obrigatórios para conta PJ'
            }), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT 1
               FROM USUARIO
               WHERE EMAIL = ?""",
            (email,)
        )

        if cursor.fetchone():
            return jsonify({
                'mensagem': 'Email já cadastrado'
            }), 400

        cursor.execute(
            """SELECT 1
               FROM USUARIO
               WHERE CPF = ?""",
            (cpf,)
        )

        if cursor.fetchone():
            return jsonify({
                'mensagem': 'CPF já cadastrado'
            }), 400

        if tipo_conta == 1:
            cursor.execute(
                """SELECT 1
                   FROM CONTA
                   WHERE CNPJ = ?""",
                (cnpj,)
            )

            if cursor.fetchone():
                return jsonify({
                    'mensagem': 'CNPJ já cadastrado'
                }), 400

        pin_hash = criptografar_pin(pin)

        cursor.execute(
            """INSERT INTO USUARIO
               (NOME, EMAIL, TELEFONE, CPF, CNPJ, TIPO, STATUS, TENTATIVAS,
                CEP, RUA, NUMERO, BAIRRO, CIDADE, ESTADO, COMPLEMENTO,
                NOME_FANTASIA, RAZAO_SOCIAL, REPRESENTANTE,
                PIN_HASH, DATA_NASCIMENTO, PRIMEIRO_ACESSO, PIN_TEMPORARIO_EXPIRA_EM)
               VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
               RETURNING ID_USUARIO""",
            (
                nome,
                email,
                telefone,
                cpf,
                cnpj if tipo_conta == 1 else None,
                tipo,
                cep,
                rua,
                numero,
                bairro,
                cidade,
                estado,
                complemento,
                nome_fantasia if tipo_conta == 1 else None,
                razao_social if tipo_conta == 1 else None,
                representante if tipo_conta == 1 else None,
                pin_hash,
                data_nascimento
            )
        )

        id_usuario = cursor.fetchone()[0]

        cursor.execute(
            """SELECT MAX(NUMERO_CONTA)
               FROM CONTA"""
        )

        numero_conta = cursor.fetchone()[0] or 0
        numero_conta += 1

        cursor.execute(
            """INSERT INTO CONTA
               (ID_USUARIO, NUMERO_CONTA, AGENCIA, BANCO, TIPO_CONTA,
                PIN_HASH, CNPJ, NOME_FANTASIA, RAZAO_SOCIAL)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               RETURNING ID_CONTA""",
            (
                id_usuario,
                numero_conta,
                '0001',
                248,
                tipo_conta,
                pin_hash,
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

        return jsonify({
            'mensagem': 'Usuário e conta cadastrados com sucesso',
            'id_usuario': id_usuario,
            'id_conta': id_conta,
            'numero_conta': numero_conta,
            'tipo_conta': tipo_conta
        }), 201

    except Exception as e:
        con.rollback()
        print('ERRO ADICIONAR USUARIO:', e)

        return jsonify({
            'mensagem': 'Erro ao cadastrar usuário'
        }), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/edicao_usuario', methods=['PUT'])
def edicao_usuario():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return jsonify({
            'mensagem': 'Usuário não autenticado'
        }), 401

    id_conta = descobre_id_conta()

    nome = request.form.get('nome')
    email = request.form.get('email')
    cpf = request.form.get('cpf')
    telefone = request.form.get('telefone')

    data_nascimento = request.form.get('data_nascimento')

    cep = request.form.get('cep')
    rua = request.form.get('rua')
    bairro = request.form.get('bairro')
    numero = request.form.get('numero')
    nome_mae = request.form.get('nome_mae')
    nome_pai = request.form.get('nome_pai')
    cidade = request.form.get('cidade')
    estado = request.form.get('estado')
    complemento = request.form.get('complemento')

    cnpj = request.form.get('cnpj')
    nome_fantasia = request.form.get('nome_fantasia')
    razao_social = request.form.get('razao_social')
    representante = request.form.get('representante')

    if data_nascimento:
        try:
            data_nascimento = datetime.datetime.strptime(
                data_nascimento,
                '%Y-%m-%d'
            ).date()

        except ValueError:
            return jsonify({
                'mensagem': 'Data de nascimento inválida'
            }), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT 1
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        if not cursor.fetchone():
            return jsonify({
                'mensagem': 'Usuário não encontrado'
            }), 404

        if email:
            cursor.execute(
                """SELECT 1
                   FROM USUARIO
                   WHERE EMAIL = ? AND ID_USUARIO != ?""",
                (email, id_usuario)
            )

            if cursor.fetchone():
                return jsonify({
                    'mensagem': 'Email já cadastrado'
                }), 400

        if cpf:
            cursor.execute(
                """SELECT 1
                   FROM USUARIO
                   WHERE CPF = ? AND ID_USUARIO != ?""",
                (cpf, id_usuario)
            )

            if cursor.fetchone():
                return jsonify({
                    'mensagem': 'CPF já cadastrado'
                }), 400

        cursor.execute(
            """UPDATE USUARIO
               SET NOME = ?, EMAIL = ?, CPF = ?, TELEFONE = ?,
                   CEP = ?, RUA = ?, BAIRRO = ?, NUMERO = ?,
                   NOME_MAE = ?, NOME_PAI = ?, CIDADE = ?, ESTADO = ?,
                   COMPLEMENTO = ?, DATA_NASCIMENTO = ?
               WHERE ID_USUARIO = ?""",
            (
                nome,
                email,
                cpf,
                telefone,
                cep,
                rua,
                bairro,
                numero,
                nome_mae,
                nome_pai,
                cidade,
                estado,
                complemento,
                data_nascimento,
                id_usuario
            )
        )

        if id_conta and (
            cnpj is not None
            or nome_fantasia is not None
            or razao_social is not None
            or representante is not None
        ):
            cursor.execute(
                """SELECT TIPO_CONTA, ID_USUARIO
                   FROM CONTA
                   WHERE ID_CONTA = ?""",
                (id_conta,)
            )

            conta = cursor.fetchone()

            if conta and conta[0] == 1 and conta[1] == id_usuario:
                if cnpj:
                    cursor.execute(
                        """SELECT 1
                           FROM CONTA
                           WHERE CNPJ = ? AND ID_CONTA != ?""",
                        (cnpj, id_conta)
                    )

                    if cursor.fetchone():
                        con.rollback()

                        return jsonify({
                            'mensagem': 'CNPJ já cadastrado'
                        }), 400

                cursor.execute(
                    """UPDATE CONTA
                       SET CNPJ = ?, NOME_FANTASIA = ?, RAZAO_SOCIAL = ?
                       WHERE ID_CONTA = ?""",
                    (
                        cnpj,
                        nome_fantasia,
                        razao_social,
                        id_conta
                    )
                )

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

        con.commit()

        return jsonify({
            'mensagem': 'Usuário atualizado com sucesso',
            'id_usuario': id_usuario
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO EDITAR USUARIO:', e)

        return jsonify({
            'mensagem': 'Erro ao editar usuário'
        }), 500

    finally:
        if cursor:
            cursor.close()