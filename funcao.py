import jwt
import datetime
from main import app, con
from flask import request, current_app
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask_bcrypt import check_password_hash

def gerar_token(id_usuario, tipo):
    payload = {
        'id_usuario': int(id_usuario),
        'tipo': int(tipo),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=120)
    }
    token = jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')
    return token

def descobre_tipo_usuario():
    token = request.cookies.get('access_token')
    print("TOKEN RECEBIDO:", token)

    if not token:
        return None

    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        print("PAYLOAD:", payload)
        print("TIPO:", payload['tipo'])
        return payload['tipo']
    except Exception as e:
        print("ERRO TOKEN:", e)
        return None

def descobre_id_usuario():
    token = request.cookies.get('access_token')
    if not token:
        return None
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return int(payload['id_usuario'])
    except:
        return None

def gerar_codigo():
    return str(random.randint(100000, 999999))


def enviando_email(destinatario, assunto, html):
    user_email = 'webcar89@gmail.com'
    senha = 'dbgu pqdq htkb bcds'

    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = assunto
        msg['From'] = user_email
        msg['To'] = destinatario

        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10)
        server.login(user_email, senha)
        server.send_message(msg)
        server.quit()

        print("EMAIL ENVIADO")

    except Exception as e:
        print("ERRO:", e)
