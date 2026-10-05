import datetime
from flask import jsonify, request, render_template
from main import app
from banco import con
from funcao import (
    descobre_id_conta,
    gerar_chave_pix,
    validar_chave_pix,
    gerar_token_aleatorio,
    hash_token_simples,
    gerar_codigo,
    criptografar_pin,
    verificar_pin,
    data_atual,
    enviando_email,
    enviar_codigo_telefone
)


def garantir_linha_chave_pix(cursor, id_conta):
    cursor.execute("SELECT ID_CHAVE_PIX FROM CHAVE_PIX WHERE ID_CONTA = ?", (id_conta,))

    if not cursor.fetchone():
        cursor.execute("INSERT INTO CHAVE_PIX (ID_CONTA) VALUES (?)", (id_conta,))


def dados_contato_conta(cursor, id_conta):
    cursor.execute(
        """SELECT U.EMAIL, U.TELEFONE
           FROM CONTA C
           INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
           WHERE C.ID_CONTA = ?""",
        (id_conta,)
    )

    return cursor.fetchone()


@app.route('/adicionar_chave_pix', methods=['POST'])
def adicionar_chave_pix():
    dados = request.get_json() or {}
    chave_pix_email = dados.get('chave_pix_email')
    chave_pix_telefone = dados.get('chave_pix_telefone')
    chave_pix_cpf = dados.get('chave_pix_cpf')
    chave_pix_aleatoria = dados.get('chave_pix_aleatoria')
    chave_pix_cnpj = dados.get('chave_pix_cnpj')

    if chave_pix_email or chave_pix_telefone:
        return jsonify({
            'mensagem': 'Email e telefone precisam ser confirmados antes do cadastro da chave Pix'
        }), 400

    if chave_pix_aleatoria:
        chave_pix_aleatoria = gerar_chave_pix()

    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        if chave_pix_cpf and validar_chave_pix(chave_pix_cpf, 'chave_pix_cpf', 1):
            return jsonify({'mensagem': 'Chave PIX de CPF ja cadastrada'}), 400

        if chave_pix_aleatoria and validar_chave_pix(chave_pix_aleatoria, 'chave_pix_aleatoria', 1):
            return jsonify({'mensagem': 'Chave PIX aleatoria ja cadastrada'}), 400

        if chave_pix_cnpj and validar_chave_pix(chave_pix_cnpj, 'chave_pix_cnpj', 1):
            return jsonify({'mensagem': 'Chave PIX de CNPJ ja cadastrada'}), 400

        garantir_linha_chave_pix(cursor, id_conta)

        if chave_pix_cpf:
            validar_chave_pix(chave_pix_cpf, 'chave_pix_cpf', 2, id_conta)

        if chave_pix_aleatoria:
            validar_chave_pix(chave_pix_aleatoria, 'chave_pix_aleatoria', 2, id_conta)

        if chave_pix_cnpj:
            validar_chave_pix(chave_pix_cnpj, 'chave_pix_cnpj', 2, id_conta)

        con.commit()

        return jsonify({
            'mensagem': 'Chave Pix cadastrada com sucesso',
            'chave_pix_aleatoria': chave_pix_aleatoria
        }), 201

    except Exception as e:
        con.rollback()
        print('ERRO ADICIONAR CHAVE PIX:', e)
        return jsonify({'mensagem': 'Erro ao cadastrar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/iniciar', methods=['POST'])
def iniciar_verificacao_pix():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    dados = request.get_json() or {}
    tipo = str(dados.get('tipo') or '').upper()
    canal = str(dados.get('canal') or '').upper()

    if tipo not in ('EMAIL', 'TELEFONE'):
        return jsonify({'mensagem': 'Tipo de verificacao invalido'}), 400

    if tipo == 'EMAIL':
        canal = 'EMAIL'

    if tipo == 'TELEFONE' and canal not in ('SMS', 'WHATSAPP', 'LIGACAO'):
        return jsonify({'mensagem': 'Escolha SMS, WhatsApp ou ligacao'}), 400

    cursor = None

    try:
        cursor = con.cursor()
        contato = dados_contato_conta(cursor, id_conta)

        if not contato:
            return jsonify({'mensagem': 'Conta nao encontrada'}), 404

        valor = contato[0] if tipo == 'EMAIL' else contato[1]

        if not valor:
            return jsonify({'mensagem': 'A conta nao possui esse contato cadastrado'}), 400

        campo = 'CHAVE_PIX_EMAIL' if tipo == 'EMAIL' else 'CHAVE_PIX_TELEFONE'
        cursor.execute(f"SELECT ID_CONTA FROM CHAVE_PIX WHERE {campo} = ? AND ID_CONTA <> ?", (valor, id_conta))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Esse contato ja esta cadastrado como chave Pix'}), 400

        cursor.execute(
            """UPDATE VERIFICACAO_PIX
               SET STATUS = 3
               WHERE ID_CONTA = ? AND TIPO_CHAVE = ? AND STATUS = 0""",
            (id_conta, tipo)
        )

        criado_em = data_atual()

        if tipo == 'EMAIL':
            token = gerar_token_aleatorio()
            token_hash = hash_token_simples(token)
            expira_em = criado_em + datetime.timedelta(minutes=15)

            cursor.execute(
                """INSERT INTO VERIFICACAO_PIX
                   (ID_CONTA, TIPO_CHAVE, VALOR_CHAVE, CANAL, TOKEN_HASH, CODIGO_HASH,
                    EXPIRA_EM, TENTATIVAS, STATUS, DATA_CRIACAO, CONFIRMADO_EM)
                   VALUES (?, ?, ?, ?, ?, NULL, ?, 0, 0, ?, NULL)
                   RETURNING ID_VERIFICACAO""",
                (id_conta, tipo, valor, canal, token_hash, expira_em, criado_em)
            )

            id_verificacao = cursor.fetchone()[0]
            con.commit()

            link = app.config['FRONTEND_URL'].rstrip('/') + '/confirmar-chave-pix#token=' + token
            html = render_template('confirmacao_chave_pix.html', link=link, valor=valor)

            enviando_email(
                valor,
                'Confirme sua chave Pix - Banco Arkhé',
                html
            )

            return jsonify({
                'mensagem': 'Enviamos um link de confirmacao para seu email',
                'id_verificacao': id_verificacao,
                'tipo': 'email'
            }), 200

        codigo = gerar_codigo()
        codigo_hash = criptografar_pin(codigo)
        expira_em = criado_em + datetime.timedelta(minutes=5)

        cursor.execute(
            """INSERT INTO VERIFICACAO_PIX
               (ID_CONTA, TIPO_CHAVE, VALOR_CHAVE, CANAL, TOKEN_HASH, CODIGO_HASH,
                EXPIRA_EM, TENTATIVAS, STATUS, DATA_CRIACAO, CONFIRMADO_EM)
               VALUES (?, ?, ?, ?, NULL, ?, ?, 0, 0, ?, NULL)
               RETURNING ID_VERIFICACAO""",
            (id_conta, tipo, valor, canal, codigo_hash, expira_em, criado_em)
        )

        id_verificacao = cursor.fetchone()[0]

        if not enviar_codigo_telefone(valor, codigo, canal):
            con.rollback()
            return jsonify({
                'mensagem': 'O canal de confirmacao por telefone ainda nao esta configurado no servidor'
            }), 503

        con.commit()

        return jsonify({
            'mensagem': 'Codigo enviado para confirmacao',
            'id_verificacao': id_verificacao,
            'tipo': 'telefone',
            'canal': canal
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO INICIAR VERIFICACAO PIX:', e)
        return jsonify({'mensagem': 'Erro ao iniciar confirmacao da chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/confirmar-email', methods=['POST'])
def confirmar_email_pix():
    dados = request.get_json() or {}
    token = dados.get('token')

    if not token:
        return jsonify({'mensagem': 'Link de confirmacao invalido'}), 400

    cursor = None

    try:
        cursor = con.cursor()
        agora = data_atual()
        token_hash = hash_token_simples(token)

        cursor.execute(
            """SELECT ID_VERIFICACAO, ID_CONTA, VALOR_CHAVE, EXPIRA_EM
               FROM VERIFICACAO_PIX
               WHERE TOKEN_HASH = ? AND TIPO_CHAVE = 'EMAIL' AND STATUS = 0""",
            (token_hash,)
        )

        verificacao = cursor.fetchone()

        if not verificacao:
            return jsonify({'mensagem': 'Link de confirmacao invalido ou ja utilizado'}), 400

        if verificacao[3] <= agora:
            cursor.execute("UPDATE VERIFICACAO_PIX SET STATUS = 2 WHERE ID_VERIFICACAO = ?", (verificacao[0],))
            con.commit()
            return jsonify({'mensagem': 'Esse link de confirmacao expirou'}), 400

        id_verificacao = verificacao[0]
        id_conta = verificacao[1]
        valor = verificacao[2]

        cursor.execute("SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_EMAIL = ? AND ID_CONTA <> ?", (valor, id_conta))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Esse email ja esta cadastrado como chave Pix'}), 400

        garantir_linha_chave_pix(cursor, id_conta)
        cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_EMAIL = ? WHERE ID_CONTA = ?", (valor, id_conta))
        cursor.execute(
            """UPDATE VERIFICACAO_PIX
               SET STATUS = 1, CONFIRMADO_EM = ?
               WHERE ID_VERIFICACAO = ?""",
            (agora, id_verificacao)
        )

        con.commit()

        return jsonify({'mensagem': 'Email confirmado e chave Pix cadastrada com sucesso'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO CONFIRMAR EMAIL PIX:', e)
        return jsonify({'mensagem': 'Erro ao confirmar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/confirmar-telefone', methods=['POST'])
def confirmar_telefone_pix():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    dados = request.get_json() or {}
    id_verificacao = dados.get('id_verificacao')
    codigo = str(dados.get('codigo') or '')

    if not id_verificacao or len(codigo) != 6 or not codigo.isdigit():
        return jsonify({'mensagem': 'Informe o codigo de 6 numeros'}), 400

    cursor = None

    try:
        cursor = con.cursor()
        agora = data_atual()

        cursor.execute(
            """SELECT ID_VERIFICACAO, VALOR_CHAVE, CODIGO_HASH, EXPIRA_EM, TENTATIVAS
               FROM VERIFICACAO_PIX
               WHERE ID_VERIFICACAO = ? AND ID_CONTA = ?
                 AND TIPO_CHAVE = 'TELEFONE' AND STATUS = 0""",
            (id_verificacao, id_conta)
        )

        verificacao = cursor.fetchone()

        if not verificacao:
            return jsonify({'mensagem': 'Confirmacao nao encontrada ou ja finalizada'}), 400

        if verificacao[3] <= agora:
            cursor.execute("UPDATE VERIFICACAO_PIX SET STATUS = 2 WHERE ID_VERIFICACAO = ?", (id_verificacao,))
            con.commit()
            return jsonify({'mensagem': 'O codigo expirou. Solicite outro.'}), 400

        tentativas = int(verificacao[4] or 0)

        if not verificar_pin(codigo, verificacao[2]):
            tentativas += 1
            novo_status = 3 if tentativas >= 5 else 0
            cursor.execute(
                "UPDATE VERIFICACAO_PIX SET TENTATIVAS = ?, STATUS = ? WHERE ID_VERIFICACAO = ?",
                (tentativas, novo_status, id_verificacao)
            )
            con.commit()

            if novo_status == 3:
                return jsonify({'mensagem': 'Muitas tentativas incorretas. Solicite um novo codigo.'}), 400

            return jsonify({
                'mensagem': 'Codigo incorreto',
                'tentativas_restantes': 5 - tentativas
            }), 400

        valor = verificacao[1]
        cursor.execute("SELECT ID_CONTA FROM CHAVE_PIX WHERE CHAVE_PIX_TELEFONE = ? AND ID_CONTA <> ?", (valor, id_conta))

        if cursor.fetchone():
            return jsonify({'mensagem': 'Esse telefone ja esta cadastrado como chave Pix'}), 400

        garantir_linha_chave_pix(cursor, id_conta)
        cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_TELEFONE = ? WHERE ID_CONTA = ?", (valor, id_conta))
        cursor.execute(
            """UPDATE VERIFICACAO_PIX
               SET STATUS = 1, CONFIRMADO_EM = ?
               WHERE ID_VERIFICACAO = ?""",
            (agora, id_verificacao)
        )

        con.commit()

        return jsonify({'mensagem': 'Telefone confirmado e chave Pix cadastrada com sucesso'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO CONFIRMAR TELEFONE PIX:', e)
        return jsonify({'mensagem': 'Erro ao confirmar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/deletar_chave_pix', methods=['POST'])
def deletar_chave_pix():
    dados = request.get_json() or {}
    chave_pix_email = dados.get('chave_pix_email')
    chave_pix_telefone = dados.get('chave_pix_telefone')
    chave_pix_cpf = dados.get('chave_pix_cpf')
    chave_pix_aleatoria = dados.get('chave_pix_aleatoria')
    chave_pix_cnpj = dados.get('chave_pix_cnpj')

    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        if chave_pix_email:
            validar_chave_pix(chave_pix_email, 'chave_pix_email', 3, id_conta)

        if chave_pix_telefone:
            validar_chave_pix(chave_pix_telefone, 'chave_pix_telefone', 3, id_conta)

        if chave_pix_cpf:
            validar_chave_pix(chave_pix_cpf, 'chave_pix_cpf', 3, id_conta)

        if chave_pix_aleatoria:
            validar_chave_pix(chave_pix_aleatoria, 'chave_pix_aleatoria', 3, id_conta)

        if chave_pix_cnpj:
            validar_chave_pix(chave_pix_cnpj, 'chave_pix_cnpj', 3, id_conta)

        con.commit()

        return jsonify({'mensagem': 'Chave Pix deletada com sucesso'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO DELETAR CHAVE PIX:', e)
        return jsonify({'mensagem': 'Erro ao deletar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/chaves_pix', methods=['GET'])
def chaves_pix():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute(
            """SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE,
                      CHAVE_PIX_CPF, CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ
               FROM CHAVE_PIX
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )

        registros = cursor.fetchall()
        lista_chaves = []

        for registro in registros:
            if registro[1]:
                lista_chaves.append({'id_chave_pix': registro[0], 'tipo': 'email', 'valor': registro[1]})
            if registro[2]:
                lista_chaves.append({'id_chave_pix': registro[0], 'tipo': 'telefone', 'valor': registro[2]})
            if registro[3]:
                lista_chaves.append({'id_chave_pix': registro[0], 'tipo': 'cpf', 'valor': registro[3]})
            if registro[4]:
                lista_chaves.append({'id_chave_pix': registro[0], 'tipo': 'aleatoria', 'valor': registro[4]})
            if registro[5]:
                lista_chaves.append({'id_chave_pix': registro[0], 'tipo': 'cnpj', 'valor': registro[5]})

        return jsonify({'chaves': lista_chaves}), 200

    except Exception as e:
        print('ERRO BUSCAR CHAVES PIX:', e)
        return jsonify({'mensagem': 'Erro ao buscar chaves Pix'}), 500

    finally:
        cursor.close()
