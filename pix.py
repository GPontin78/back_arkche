from flask import jsonify, request
import hashlib
import os
import random
import requests

from main import app
from banco import con
from funcao import descobre_id_conta, dados_usuario, gerar_chave_pix, validar_chave_pix, criptografar_pin, verificar_pin, enviando_email, data_atual


def garantir_linha_chave_pix(cursor, id_conta):
    cursor.execute("SELECT 1 FROM CHAVE_PIX WHERE ID_CONTA = ?", (id_conta,))

    if not cursor.fetchone():
        cursor.execute("INSERT INTO CHAVE_PIX (ID_CONTA) VALUES (?)", (id_conta,))


def cancelar_verificacoes_pendentes(cursor, id_conta, tipo_chave):
    cursor.execute(
        """UPDATE VERIFICACAO_PIX
           SET STATUS = 3
           WHERE ID_CONTA = ? AND TIPO_CHAVE = ? AND STATUS = 0""",
        (id_conta, tipo_chave)
    )


def enviar_codigo_telefone(telefone, canal, codigo):
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')
    numero = os.getenv('TWILIO_PHONE_NUMBER')
    whatsapp = os.getenv('TWILIO_WHATSAPP_NUMBER')

    if not sid or not token:
        return False, 'O provedor de telefone ainda não foi configurado no servidor.'

    telefone = '+' + ''.join(c for c in str(telefone) if c.isdigit())
    mensagem = f'Seu código de confirmação Pix do Banco Arkhé é {codigo}. Ele expira em 5 minutos.'

    if canal in ('SMS', 'WHATSAPP'):
        origem = whatsapp if canal == 'WHATSAPP' else numero

        if not origem:
            return False, 'Este canal ainda não foi configurado no servidor.'

        destino = f'whatsapp:{telefone}' if canal == 'WHATSAPP' else telefone
        origem = f'whatsapp:{origem}' if canal == 'WHATSAPP' and not str(origem).startswith('whatsapp:') else origem

        resposta = requests.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json',
            auth=(sid, token),
            data={'From': origem, 'To': destino, 'Body': mensagem},
            timeout=20
        )

    elif canal == 'LIGACAO':
        if not numero:
            return False, 'O canal de ligação ainda não foi configurado no servidor.'

        resposta = requests.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json',
            auth=(sid, token),
            data={
                'From': numero,
                'To': telefone,
                'Twiml': f'<Response><Say language="pt-BR">Seu código de confirmação Pix é {codigo}</Say></Response>'
            },
            timeout=20
        )

    else:
        return False, 'Canal inválido.'

    if not resposta.ok:
        return False, 'Não foi possível enviar o código por este canal.'

    return True, None


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
            'mensagem': 'E-mail e telefone precisam ser confirmados antes do cadastro.'
        }), 400

    if chave_pix_aleatoria:
        chave_pix_aleatoria = gerar_chave_pix()

    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = None

    try:
        cursor = con.cursor()

        for valor, coluna, nome in (
            (chave_pix_cpf, 'chave_pix_cpf', 'CPF'),
            (chave_pix_aleatoria, 'chave_pix_aleatoria', 'aleatória'),
            (chave_pix_cnpj, 'chave_pix_cnpj', 'CNPJ'),
        ):
            if valor and validar_chave_pix(valor, coluna, 1):
                return jsonify({'mensagem': f'Chave PIX de {nome} já cadastrada'}), 400

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
        print('ERRO CHAVE PIX:', e)
        return jsonify({'mensagem': 'Erro ao cadastrar chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/email/iniciar', methods=['POST'])
def iniciar_verificacao_email_pix():
    id_conta = descobre_id_conta()
    usuario = dados_usuario()

    if not id_conta or not usuario:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    email = str(usuario.get('email') or '').strip().lower()

    if not email:
        return jsonify({'mensagem': 'Sua conta não possui e-mail cadastrado'}), 400

    if validar_chave_pix(email, 'chave_pix_email', 1):
        return jsonify({'mensagem': 'Este e-mail já é uma chave Pix'}), 400

    token = os.urandom(32).hex()
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    expira_em = data_atual() + __import__('datetime').timedelta(minutes=15)
    cursor = None

    try:
        cursor = con.cursor()
        cancelar_verificacoes_pendentes(cursor, id_conta, 'EMAIL')

        cursor.execute(
            """INSERT INTO VERIFICACAO_PIX
               (ID_CONTA, TIPO_CHAVE, VALOR_CHAVE, CANAL, TOKEN_HASH, EXPIRA_EM, TENTATIVAS, STATUS, DATA_CRIACAO)
               VALUES (?, 'EMAIL', ?, 'EMAIL', ?, ?, 0, 0, ?)""",
            (id_conta, email, token_hash, expira_em, data_atual())
        )

        con.commit()

        link = app.config['FRONTEND_URL'].rstrip('/') + '/confirmar-chave-pix#token=' + token
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;padding:24px">
            <h2>Confirme sua chave Pix</h2>
            <p>Você pediu para cadastrar <strong>{email}</strong> como chave Pix no Banco Arkhé.</p>
            <p>O link é válido por 15 minutos e funciona uma única vez.</p>
            <p style="margin:28px 0"><a href="{link}" style="background:#0D4D4D;color:white;text-decoration:none;padding:12px 18px;border-radius:8px">Confirmar chave Pix</a></p>
            <p style="font-size:13px;color:#66746F">Se você não solicitou este cadastro, ignore este e-mail.</p>
        </div>
        """

        enviando_email(email, 'Confirme sua chave Pix - Banco Arkhé', html)

        return jsonify({
            'mensagem': 'Enviamos um link de confirmação para seu e-mail.'
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO VERIFICACAO EMAIL PIX:', e)
        return jsonify({'mensagem': 'Não foi possível iniciar a confirmação do e-mail'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/email/confirmar', methods=['POST'])
def confirmar_verificacao_email_pix():
    dados = request.get_json() or {}
    token = dados.get('token')

    if not token:
        return jsonify({'mensagem': 'Link inválido'}), 400

    token_hash = hashlib.sha256(str(token).encode('utf-8')).hexdigest()
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_VERIFICACAO, ID_CONTA, VALOR_CHAVE
               FROM VERIFICACAO_PIX
               WHERE TOKEN_HASH = ? AND TIPO_CHAVE = 'EMAIL'
               AND STATUS = 0 AND EXPIRA_EM > ?""",
            (token_hash, data_atual())
        )

        verificacao = cursor.fetchone()

        if not verificacao:
            return jsonify({'mensagem': 'Este link é inválido ou expirou'}), 400

        id_verificacao, id_conta, email = verificacao

        if validar_chave_pix(email, 'chave_pix_email', 1):
            cursor.execute("UPDATE VERIFICACAO_PIX SET STATUS = 3 WHERE ID_VERIFICACAO = ?", (id_verificacao,))
            con.commit()
            return jsonify({'mensagem': 'Este e-mail já está cadastrado como chave Pix'}), 400

        garantir_linha_chave_pix(cursor, id_conta)
        cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_EMAIL = ? WHERE ID_CONTA = ?", (email, id_conta))
        cursor.execute(
            """UPDATE VERIFICACAO_PIX
               SET STATUS = 1, CONFIRMADO_EM = ?
               WHERE ID_VERIFICACAO = ?""",
            (data_atual(), id_verificacao)
        )

        con.commit()

        return jsonify({'mensagem': 'E-mail confirmado e cadastrado como chave Pix.'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO CONFIRMAR EMAIL PIX:', e)
        return jsonify({'mensagem': 'Não foi possível confirmar a chave Pix'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/telefone/iniciar', methods=['POST'])
def iniciar_verificacao_telefone_pix():
    id_conta = descobre_id_conta()
    usuario = dados_usuario()
    dados = request.get_json() or {}
    canal = str(dados.get('canal') or '').upper()

    if not id_conta or not usuario:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if canal not in ('SMS', 'WHATSAPP', 'LIGACAO'):
        return jsonify({'mensagem': 'Escolha SMS, WhatsApp ou ligação'}), 400

    telefone = ''.join(c for c in str(usuario.get('telefone') or '') if c.isdigit())

    if not telefone:
        return jsonify({'mensagem': 'Sua conta não possui telefone cadastrado'}), 400

    if validar_chave_pix(telefone, 'chave_pix_telefone', 1):
        return jsonify({'mensagem': 'Este telefone já é uma chave Pix'}), 400

    codigo = str(random.randint(100000, 999999))
    codigo_hash = criptografar_pin(codigo)
    expira_em = data_atual() + __import__('datetime').timedelta(minutes=5)

    enviado, erro_envio = enviar_codigo_telefone(telefone, canal, codigo)

    if not enviado:
        return jsonify({'mensagem': erro_envio}), 503

    cursor = None

    try:
        cursor = con.cursor()
        cancelar_verificacoes_pendentes(cursor, id_conta, 'TELEFONE')

        cursor.execute(
            """INSERT INTO VERIFICACAO_PIX
               (ID_CONTA, TIPO_CHAVE, VALOR_CHAVE, CANAL, CODIGO_HASH, EXPIRA_EM, TENTATIVAS, STATUS, DATA_CRIACAO)
               VALUES (?, 'TELEFONE', ?, ?, ?, ?, 0, 0, ?)
               RETURNING ID_VERIFICACAO""",
            (id_conta, telefone, canal, codigo_hash, expira_em, data_atual())
        )

        id_verificacao = cursor.fetchone()[0]
        con.commit()

        return jsonify({
            'mensagem': 'Código enviado com sucesso.',
            'id_verificacao': id_verificacao
        }), 200

    except Exception as e:
        con.rollback()
        print('ERRO VERIFICACAO TELEFONE PIX:', e)
        return jsonify({'mensagem': 'Não foi possível iniciar a confirmação do telefone'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/pix/verificacao/telefone/confirmar', methods=['POST'])
def confirmar_verificacao_telefone_pix():
    id_conta = descobre_id_conta()
    dados = request.get_json() or {}
    id_verificacao = dados.get('id_verificacao')
    codigo = str(dados.get('codigo') or '')

    if not id_conta:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    if not id_verificacao or len(codigo) != 6 or not codigo.isdigit():
        return jsonify({'mensagem': 'Informe o código de 6 números'}), 400

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT VALOR_CHAVE, CODIGO_HASH, TENTATIVAS, EXPIRA_EM
               FROM VERIFICACAO_PIX
               WHERE ID_VERIFICACAO = ? AND ID_CONTA = ?
               AND TIPO_CHAVE = 'TELEFONE' AND STATUS = 0""",
            (id_verificacao, id_conta)
        )

        verificacao = cursor.fetchone()

        if not verificacao:
            return jsonify({'mensagem': 'Confirmação não encontrada'}), 404

        telefone, codigo_hash, tentativas, expira_em = verificacao

        if expira_em <= data_atual():
            cursor.execute("UPDATE VERIFICACAO_PIX SET STATUS = 2 WHERE ID_VERIFICACAO = ?", (id_verificacao,))
            con.commit()
            return jsonify({'mensagem': 'O código expirou. Solicite outro.'}), 400

        if not verificar_pin(codigo, codigo_hash):
            tentativas = int(tentativas or 0) + 1
            status = 3 if tentativas >= 5 else 0
            cursor.execute(
                "UPDATE VERIFICACAO_PIX SET TENTATIVAS = ?, STATUS = ? WHERE ID_VERIFICACAO = ?",
                (tentativas, status, id_verificacao)
            )
            con.commit()

            if status == 3:
                return jsonify({'mensagem': 'Muitas tentativas incorretas. Solicite outro código.'}), 400

            return jsonify({
                'mensagem': 'Código incorreto',
                'tentativas_restantes': 5 - tentativas
            }), 400

        if validar_chave_pix(telefone, 'chave_pix_telefone', 1):
            return jsonify({'mensagem': 'Este telefone já está cadastrado como chave Pix'}), 400

        garantir_linha_chave_pix(cursor, id_conta)
        cursor.execute("UPDATE CHAVE_PIX SET CHAVE_PIX_TELEFONE = ? WHERE ID_CONTA = ?", (telefone, id_conta))
        cursor.execute(
            """UPDATE VERIFICACAO_PIX
               SET STATUS = 1, CONFIRMADO_EM = ?
               WHERE ID_VERIFICACAO = ?""",
            (data_atual(), id_verificacao)
        )

        con.commit()

        return jsonify({'mensagem': 'Telefone confirmado e cadastrado como chave Pix.'}), 200

    except Exception as e:
        con.rollback()
        print('ERRO CONFIRMAR TELEFONE PIX:', e)
        return jsonify({'mensagem': 'Não foi possível confirmar o telefone'}), 500

    finally:
        if cursor:
            cursor.close()


@app.route('/deletar_chave_pix', methods=['POST'])
def deletar_chave_pix():
    dados = request.get_json() or {}
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    chaves = [
        (dados.get('chave_pix_email'), 'chave_pix_email'),
        (dados.get('chave_pix_telefone'), 'chave_pix_telefone'),
        (dados.get('chave_pix_cpf'), 'chave_pix_cpf'),
        (dados.get('chave_pix_aleatoria'), 'chave_pix_aleatoria'),
        (dados.get('chave_pix_cnpj'), 'chave_pix_cnpj'),
    ]

    try:
        for valor, coluna in chaves:
            if valor:
                validar_chave_pix(valor, coluna, 3, id_conta)

        con.commit()
        return jsonify({'mensagem': 'Chave Pix deletada com sucesso'}), 200

    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Erro ao deletar chave Pix'}), 500


@app.route('/chaves_pix', methods=['GET'])
def chaves_pix():
    id_conta = descobre_id_conta()

    if id_conta is None:
        return jsonify({'mensagem': 'Usuario nao logado'}), 403

    cursor = con.cursor()

    try:
        cursor.execute(
            """SELECT ID_CHAVE_PIX, CHAVE_PIX_EMAIL, CHAVE_PIX_TELEFONE, CHAVE_PIX_CPF,
                      CHAVE_PIX_ALEATORIA, CHAVE_PIX_CNPJ
               FROM CHAVE_PIX WHERE ID_CONTA = ?""",
            (id_conta,)
        )

        lista_chaves = []

        for registro in cursor.fetchall():
            id_chave_pix = registro[0]

            for tipo, valor in (
                ('email', registro[1]),
                ('telefone', registro[2]),
                ('cpf', registro[3]),
                ('aleatoria', registro[4]),
                ('cnpj', registro[5]),
            ):
                if valor:
                    lista_chaves.append({
                        'id_chave_pix': id_chave_pix,
                        'tipo': tipo,
                        'valor': valor
                    })

        return jsonify({'chaves': lista_chaves}), 200

    except Exception:
        return jsonify({'mensagem': 'Erro ao buscar chaves Pix'}), 500

    finally:
        cursor.close()
