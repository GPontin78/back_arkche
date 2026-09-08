import jwt
import datetime
import random
import smtplib
import os
import bcrypt
from main import app
from banco import con
from flask import request, current_app
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import uuid


def obter_token():
    return request.cookies.get('access_token')


def gerar_token(id_usuario, id_conta):
    payload = {
        'id_usuario': int(id_usuario),
        'id_conta': int(id_conta),
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=120)
    }

    return jwt.encode(
        payload,
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )


def descobre_id_usuario():
    token = obter_token()

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            app.config['SECRET_KEY'],
            algorithms=['HS256']
        )

        return int(payload['id_usuario'])

    except Exception:
        return None


def descobre_id_conta():
    token = obter_token()

    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            app.config['SECRET_KEY'],
            algorithms=['HS256']
        )

        return int(payload['id_conta'])

    except Exception:
        return None


def descobre_tipo_usuario():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT TIPO
            FROM USUARIO
            WHERE ID_USUARIO = ?
        """, (id_usuario,))

        usuario = cursor.fetchone()

        if not usuario:
            return None

        return usuario[0]

    except Exception:
        return None

    finally:
        if cursor:
            cursor.close()


def dados_usuario():
    id_usuario = descobre_id_usuario()

    if not id_usuario:
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT
                ID_USUARIO,
                NOME,
                EMAIL,
                TELEFONE,
                CPF,
                CNPJ,
                TIPO,
                STATUS
            FROM USUARIO
            WHERE ID_USUARIO = ?
        """, (id_usuario,))

        usuario = cursor.fetchone()

        if not usuario:
            return None

        return {
            'id_usuario': usuario[0],
            'nome': usuario[1],
            'email': usuario[2],
            'telefone': usuario[3],
            'cpf': usuario[4],
            'cnpj': usuario[5],
            'tipo': usuario[6],
            'status': usuario[7]
        }

    finally:
        if cursor:
            cursor.close()


def dados_conta():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()

    if not id_usuario or not id_conta:
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""
            SELECT
                ID_CONTA,
                ID_USUARIO,
                NUMERO_CONTA,
                AGENCIA,
                BANCO,
                TIPO_CONTA
            FROM CONTA
            WHERE ID_CONTA = ?
            AND ID_USUARIO = ?
        """, (
            id_conta,
            id_usuario
        ))

        conta = cursor.fetchone()

        if not conta:
            return None

        return {
            'id_conta': conta[0],
            'id_usuario': conta[1],
            'numero_conta': conta[2],
            'agencia': conta[3],
            'banco': conta[4],
            'tipo_conta': conta[5]
        }

    finally:
        if cursor:
            cursor.close()


def criptografar_pin(pin):
    return bcrypt.hashpw(
        str(pin).encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def verificar_pin(pin, pin_hash):
    try:
        return bcrypt.checkpw(
            str(pin).encode('utf-8'),
            pin_hash.encode('utf-8')
        )
    except Exception:
        return False


def gerar_codigo():
    return str(random.randint(100000, 999999))


def enviando_email(destinatario, assunto, html):
    user_email = 'webcar89@gmail.com'
    senha = os.getenv('EMAIL_APP_PASSWORD')

    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = assunto
        msg['From'] = user_email
        msg['To'] = destinatario

        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP_SSL(
            'smtp.gmail.com',
            465,
            timeout=10
        )

        server.login(user_email, senha)
        server.send_message(msg)
        server.quit()

        print("EMAIL ENVIADO")

    except Exception as e:
        print("ERRO:", e)


def calcular_saldo(id_conta=None):
    if id_conta is None:
        id_conta = descobre_id_conta()

    if not id_conta:
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute("""SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
                          FROM MOVIMENTACAO M
                          WHERE M.ID_RECEBEDOR = ?""", (id_conta,))

        receita = cursor.fetchone()[0]

        cursor.execute("""SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
                          FROM MOVIMENTACAO M
                          WHERE M.ID_PAGADOR = ?""", (id_conta,))

        despesa = cursor.fetchone()[0]

        return receita - despesa

    finally:
        if cursor:
            cursor.close()

def gerar_chave_pix():
    return str(uuid.uuid4())

def validar_chave_pix(chave_pix, chave, acao, id_conta=None):
    cursor = None

    try:
        cursor = con.cursor()

        if acao == 1:
            cursor.execute("SELECT 1 FROM CHAVE_PIX WHERE " + chave + " = ?", (chave_pix,))
            resultado = cursor.fetchone()

            if resultado:
                return True

            return False

        elif acao == 2:
            cursor.execute("UPDATE CHAVE_PIX SET " + chave + " = ? WHERE ID_CONTA = ?", (chave_pix, id_conta))

        elif acao == 3:
            cursor.execute("UPDATE CHAVE_PIX SET " + chave + " = NULL WHERE ID_CONTA = ?", (id_conta,))

    except Exception as e:
        print("ERRO:", e)

    finally:
        if cursor:
            cursor.close()


def data_atual():
    return datetime.datetime.now()