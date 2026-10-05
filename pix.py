from flask import jsonify, request
import hashlib
import os
import requests

from main import app
from banco import con
from funcao import descobre_id_conta, dados_usuario, gerar_chave_pix, validar_chave_pix, enviando_email, montar_email_arkhe, data_atual


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


def normalizar_telefone_twilio(telefone):
    telefone = ''.join(c for c in str(telefone or '') if c.isdigit())

    if len(telefone) in (10, 11):
        telefone = '55' + telefone

    return '+' + telefone


def mensagem_erro_twilio(resposta, canal):
    try:
        erro = resposta.json()
    except Exception:
        erro = {}

    codigo = erro.get('code')
    mensagem = str(erro.get('message') or '')

    print('TWILIO VERIFY ERRO:', resposta.status_code, codigo, mensagem[:300])

    if resposta.status_code in (401, 403):
        return 'A integração com a Twilio não está autenticada. Confira as credenciais no servidor.'

    if resposta.status_code == 404:
        return 'O serviço de verificação da Twilio não foi encontrado. Confira o Service SID.'

    if codigo in (60203, 60207, 60212, 60624, 60626):
        return 'Muitas tentativas de envio em pouco tempo. Aguarde alguns minutos e tente novamente.'

    if codigo in (60006, 60200):
        return 'O telefone cadastrado não foi aceito pela Twilio. Confira o número e tente novamente.'

    if codigo == 60610:
        return 'A Twilio não oferece este canal para o telefone ou país informado nesta conta.'

    if codigo in (14111,):
        return 'Este telefone ainda não está verificado na sua conta Twilio de teste.'

    if codigo in (68008, 63008):
        return 'O WhatsApp ainda não está configurado no serviço Twilio Verify.'

    if codigo == 60217:
        return 'O serviço Twilio Verify precisa ser configurado antes de enviar códigos.'

    return f'Não foi possível enviar o código por {canal.lower()}. Código Twilio: {codigo or resposta.status_code}.'


def iniciar_twilio_verify(telefone, canal):
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')
    service_sid = os.getenv('TWILIO_VERIFY_SERVICE_SID')

    if not sid or not token or not service_sid:
        return False, 'O Twilio Verify ainda não foi configurado no servidor.'

    canais = {
        'SMS': 'sms',
        'WHATSAPP': 'whatsapp',
        'LIGACAO': 'call'
    }

    canal_twilio = canais.get(canal)

    if not canal_twilio:
        return False, 'Canal de confirmação inválido.'

    try:
        resposta = requests.post(
            f'https://verify.twilio.com/v2/Services/{service_sid}/Verifications',
            auth=(sid, token),
            data={
                'To': normalizar_telefone_twilio(telefone),
                'Channel': canal_twilio
            },
            timeout=20
        )
    except requests.RequestException as e:
        print('TWILIO VERIFY INDISPONIVEL:', e)
        return False, 'A Twilio está temporariamente indisponível. Tente novamente em instantes.'

    if not resposta.ok:
        return False, mensagem_erro_twilio(resposta, canal)

    resultado = resposta.json()

    if resultado.get('status') != 'pending':
        return False, 'A Twilio não iniciou a confirmação deste telefone.'

    return True, None


def confirmar_twilio_verify(telefone, codigo):
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')
    service_sid = os.getenv('TWILIO_VERIFY_SERVICE_SID')

    if not sid or not token or not service_sid:
        return False, 'O Twilio Verify ainda não foi configurado no servidor.'

    try:
        resposta = requests.post(
            f'https://verify.twilio.com/v2/Services/{service_sid}/VerificationCheck',
            auth=(sid, token),
            data={
                'To': normalizar_telefone_twilio(telefone),
                'Code': codigo
            },
            timeout=20
        )
    except requests.RequestException as e:
        print('TWILIO VERIFY CHECK INDISPONIVEL:', e)
        return False, 'A Twilio está temporariamente indisponível. Tente novamente em instantes.'

    if not resposta.ok:
        return False, mensagem_erro_twilio(resposta, 'confirmação')

    return resposta.json().get('status') == 'approved', None


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
        html = montar_email_arkhe(
            titulo='Confirme sua chave Pix',
            texto='Você iniciou o cadastro do seu e-mail como chave Pix no Banco Arkhé. Confirme a posse deste endereço para concluir o cadastro.',
            preheader='Confirme seu e-mail para ativar a chave Pix.',
            destaque_titulo='Chave a confirmar',
            destaque_valor=email,
            botao_texto='Confirmar chave Pix',
            botao_url=link,
            aviso='Este link expira em 15 minutos e funciona uma única vez. Se você não solicitou este cadastro, ignore a mensagem.'
        )

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
        return jsonify({'mensagem': 'Escolha SMS ou ligação'}), 400

    telefone = ''.join(c for c in str(usuario.get('telefone') or '') if c.isdigit())

    if not telefone:
        return jsonify({'mensagem': 'Sua conta não possui telefone cadastrado'}), 400

    if validar_chave_pix(telefone, 'chave_pix_telefone', 1):
        return jsonify({'mensagem': 'Este telefone já é uma chave Pix'}), 400

    enviado, erro_envio = iniciar_twilio_verify(telefone, canal)

    if not enviado:
        return jsonify({'mensagem': erro_envio}), 503

    expira_em = data_atual() + __import__('datetime').timedelta(minutes=10)
    cursor = None

    try:
        cursor = con.cursor()
        cancelar_verificacoes_pendentes(cursor, id_conta, 'TELEFONE')

        cursor.execute(
            """INSERT INTO VERIFICACAO_PIX
               (ID_CONTA, TIPO_CHAVE, VALOR_CHAVE, CANAL, EXPIRA_EM, TENTATIVAS, STATUS, DATA_CRIACAO)
               VALUES (?, 'TELEFONE', ?, ?, ?, 0, 0, ?)
               RETURNING ID_VERIFICACAO""",
            (id_conta, telefone, canal, expira_em, data_atual())
        )

        id_verificacao = cursor.fetchone()[0]
        con.commit()

        return jsonify({
            'mensagem': 'Código enviado com sucesso.',
            'id_verificacao': id_verificacao,
            'canal': canal
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
            """SELECT VALOR_CHAVE, TENTATIVAS, EXPIRA_EM
               FROM VERIFICACAO_PIX
               WHERE ID_VERIFICACAO = ? AND ID_CONTA = ?
               AND TIPO_CHAVE = 'TELEFONE' AND STATUS = 0""",
            (id_verificacao, id_conta)
        )

        verificacao = cursor.fetchone()

        if not verificacao:
            return jsonify({'mensagem': 'Confirmação não encontrada ou já encerrada'}), 404

        telefone, tentativas, expira_em = verificacao

        if expira_em <= data_atual():
            cursor.execute("UPDATE VERIFICACAO_PIX SET STATUS = 2 WHERE ID_VERIFICACAO = ?", (id_verificacao,))
            con.commit()
            return jsonify({'mensagem': 'O código expirou. Solicite outro.'}), 400

        aprovado, erro_twilio = confirmar_twilio_verify(telefone, codigo)

        if erro_twilio:
            return jsonify({'mensagem': erro_twilio}), 503

        if not aprovado:
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
