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


def gerar_token_usuario(id_usuario):
    payload = {
        'id_usuario': int(id_usuario),
        'escopo': 'usuario',
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=120)
    }

    return jwt.encode(
        payload,
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )


def gerar_token(id_usuario, id_conta):
    payload = {
        'id_usuario': int(id_usuario),
        'id_conta': int(id_conta),
        'escopo': 'conta',
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


def usuario_pode_acessar_conta(id_usuario, id_conta):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT 1 FROM CONTA WHERE ID_CONTA = ? AND ID_USUARIO = ?""",
            (id_conta, id_usuario)
        )

        if cursor.fetchone():
            return True

        cursor.execute(
            """SELECT 1
               FROM ACESSO_CONTA A
               INNER JOIN CONTA C ON C.ID_CONTA = A.ID_CONTA
               WHERE A.ID_CONTA = ? AND A.ID_USUARIO = ? AND A.STATUS = 1 AND C.TIPO_CONTA = 1""",
            (id_conta, id_usuario)
        )

        return cursor.fetchone() is not None

    finally:
        if cursor:
            cursor.close()


def listar_contas_usuario(id_usuario):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA,
                      C.CNPJ, C.NOME_FANTASIA, C.RAZAO_SOCIAL
               FROM CONTA C
               WHERE C.ID_USUARIO = ?
               ORDER BY C.TIPO_CONTA, C.ID_CONTA""",
            (id_usuario,)
        )

        contas_proprias = cursor.fetchall()

        cursor.execute(
            """SELECT C.ID_CONTA, C.NUMERO_CONTA, C.AGENCIA, C.BANCO, C.TIPO_CONTA,
                      C.CNPJ, C.NOME_FANTASIA, C.RAZAO_SOCIAL, A.CARGO
               FROM ACESSO_CONTA A
               INNER JOIN CONTA C ON C.ID_CONTA = A.ID_CONTA
               WHERE A.ID_USUARIO = ? AND A.STATUS = 1 AND C.TIPO_CONTA = 1 AND C.ID_USUARIO <> ?
               ORDER BY C.ID_CONTA""",
            (id_usuario, id_usuario)
        )

        contas_acesso = cursor.fetchall()

        resultado = []

        for conta in contas_proprias:
            resultado.append({
                'id_conta': conta[0],
                'numero_conta': conta[1],
                'agencia': conta[2],
                'banco': conta[3],
                'tipo_conta': conta[4],
                'cnpj': conta[5],
                'nome_fantasia': conta[6],
                'razao_social': conta[7],
                'vinculo': 'titular' if conta[4] == 0 else 'proprietario',
                'cargo': None
            })

        for conta in contas_acesso:
            resultado.append({
                'id_conta': conta[0],
                'numero_conta': conta[1],
                'agencia': conta[2],
                'banco': conta[3],
                'tipo_conta': conta[4],
                'cnpj': conta[5],
                'nome_fantasia': conta[6],
                'razao_social': conta[7],
                'vinculo': 'acesso',
                'cargo': conta[8]
            })

        return resultado

    finally:
        if cursor:
            cursor.close()


def dados_conta():
    id_usuario = descobre_id_usuario()
    id_conta = descobre_id_conta()

    if not id_usuario or not id_conta:
        return None

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None

    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT ID_CONTA, ID_USUARIO, NUMERO_CONTA, AGENCIA, BANCO, TIPO_CONTA,
                      CNPJ, NOME_FANTASIA, RAZAO_SOCIAL
               FROM CONTA
               WHERE ID_CONTA = ?""",
            (id_conta,)
        )

        conta = cursor.fetchone()

        if not conta:
            return None

        id_titular = conta[1]

        if id_titular == id_usuario:
            vinculo = 'titular' if conta[5] == 0 else 'proprietario'
            cargo = None

        else:
            vinculo = 'acesso'

            cursor.execute(
                """SELECT CARGO
                   FROM ACESSO_CONTA
                   WHERE ID_CONTA = ? AND ID_USUARIO = ? AND STATUS = 1""",
                (id_conta, id_usuario)
            )

            acesso = cursor.fetchone()
            cargo = acesso[0] if acesso else None

        return {
            'id_conta': conta[0],
            'id_usuario': id_usuario,
            'id_titular': id_titular,
            'numero_conta': conta[2],
            'agencia': conta[3],
            'banco': conta[4],
            'tipo_conta': conta[5],
            'cnpj': conta[6],
            'nome_fantasia': conta[7],
            'razao_social': conta[8],
            'vinculo': vinculo,
            'cargo': cargo
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


def verificar_pin_usuario(id_usuario, pin):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT PIN_HASH, PRIMEIRO_ACESSO, PIN_TEMPORARIO_EXPIRA_EM
               FROM USUARIO
               WHERE ID_USUARIO = ?""",
            (id_usuario,)
        )

        usuario = cursor.fetchone()

        if not usuario:
            return {
                'valido': False,
                'legado': False,
                'temporario': False,
                'temporario_expirado': False
            }

        pin_hash = usuario[0]
        primeiro_acesso = usuario[1]
        expiracao = usuario[2]

        if primeiro_acesso == 1 and expiracao is not None:
            if expiracao <= data_atual():
                return {
                    'valido': False,
                    'legado': False,
                    'temporario': True,
                    'temporario_expirado': True
                }

            if pin_hash and verificar_pin(pin, pin_hash):
                return {
                    'valido': True,
                    'legado': False,
                    'temporario': True,
                    'temporario_expirado': False
                }

            return {
                'valido': False,
                'legado': False,
                'temporario': True,
                'temporario_expirado': False
            }

        if pin_hash and verificar_pin(pin, pin_hash):
            return {
                'valido': True,
                'legado': False,
                'temporario': False,
                'temporario_expirado': False
            }

        if pin_hash is None or primeiro_acesso == 1:
            cursor.execute(
                """SELECT PIN_HASH
                   FROM CONTA
                   WHERE ID_USUARIO = ? AND PIN_HASH IS NOT NULL""",
                (id_usuario,)
            )

            contas = cursor.fetchall()

            for conta in contas:
                if verificar_pin(pin, conta[0]):
                    return {
                        'valido': True,
                        'legado': True,
                        'temporario': False,
                        'temporario_expirado': False
                    }

        return {
            'valido': False,
            'legado': False,
            'temporario': False,
            'temporario_expirado': False
        }

    finally:
        if cursor:
            cursor.close()


def gerar_codigo():
    return str(random.randint(100000, 999999))

def gerar_pin_temporario():
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

        cursor.execute(
            """SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
               FROM MOVIMENTACAO M
               WHERE M.ID_RECEBEDOR = ?""",
            (id_conta,)
        )

        receita = cursor.fetchone()[0]

        cursor.execute(
            """SELECT CAST(COALESCE(SUM(M.VALOR), 0) AS DECIMAL(18,2))
               FROM MOVIMENTACAO M
               WHERE M.ID_PAGADOR = ?""",
            (id_conta,)
        )

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
            cursor.execute(
                "SELECT 1 FROM CHAVE_PIX WHERE " + chave + " = ?",
                (chave_pix,)
            )

            resultado = cursor.fetchone()

            if resultado:
                return True

            return False

        elif acao == 2:
            cursor.execute(
                "UPDATE CHAVE_PIX SET " + chave + " = ? WHERE ID_CONTA = ?",
                (chave_pix, id_conta)
            )

        elif acao == 3:
            cursor.execute(
                "UPDATE CHAVE_PIX SET " + chave + " = NULL WHERE ID_CONTA = ?",
                (id_conta,)
            )

    except Exception as e:
        print("ERRO:", e)

    finally:
        if cursor:
            cursor.close()


def data_atual():
    fuso_brasilia = datetime.timezone(datetime.timedelta(hours=-3))

    return datetime.datetime.now(
        fuso_brasilia
    ).replace(tzinfo=None)


def gerar_numero_cartao():
    return str(
        random.randint(
            1000000000000000,
            9999999999999999
        )
    )


def gerar_cvv():
    return str(
        random.randint(
            100,
            999
        )
    )


def gerar_vencimento():
    data = datetime.datetime.now()

    mes = data.month
    ano = data.year + 5

    vencimento = datetime.datetime(
        ano,
        mes,
        1
    )

    return vencimento.date()


def calcular_limite_cartao(id_cartao):
    cursor = None

    try:
        cursor = con.cursor()

        cursor.execute(
            """SELECT CAST(COALESCE(SUM(FC.VALOR_PARCELA), 0) AS DECIMAL(18,2))
               FROM FATURA_COMPRA FC
               INNER JOIN COMPRA CM ON CM.ID_COMPRA = FC.ID_COMPRA
               WHERE FC.STATUS = 0 AND CM.ID_CARTAO = ?""",
            (id_cartao,)
        )

        resultado = cursor.fetchone()

        return float(resultado[0] or 0)

    finally:
        if cursor:
            cursor.close()