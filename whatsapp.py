"""Configuracao do WhatsApp por conta.

Acesso bancario pelo WhatsApp permanece bloqueado ate existir
vinculacao de identidade comprovada; um numero fornecido pelo n8n
nao autentica o titular.
"""
import os
import secrets
import re
from urllib.parse import quote
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from flask import jsonify, request

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta
from main import app


def _conta_configuravel():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return None, (jsonify({"mensagem": "Autenticacao necessaria"}), 401)
    cursor = con.cursor()
    try:
        cursor.execute("SELECT ID_USUARIO, WHATSAPP_AUTORIZADO, WHATSAPP_NIVEL FROM CONTA WHERE ID_CONTA = ?", (conta,))
        registro = cursor.fetchone()
    finally:
        cursor.close()
    if not registro:
        return None, (jsonify({"mensagem": "Conta nao encontrada"}), 404)
    # Configuracao de canal e gerenciada exclusivamente pelo titular.
    if int(registro[0]) != int(usuario):
        return None, (jsonify({"mensagem": "Somente o titular pode configurar o canal WhatsApp"}), 403)
    return {"id_conta": conta, "autorizado": int(registro[1]), "nivel": int(registro[2])}, None


@app.route("/whatsapp/configuracao", methods=["GET"])
def whatsapp_configuracao_get():
    conta, erro = _conta_configuravel()
    return erro if erro else jsonify(conta)


@app.route("/whatsapp/configuracao", methods=["PUT"])
def whatsapp_configuracao_put():
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or type(dados.get("autorizado")) is not bool or type(dados.get("nivel")) is not int:
        return jsonify({"mensagem": "Informe autorizado (booleano) e nivel (1, 2 ou 3)"}), 400
    nivel = dados["nivel"]
    if nivel not in (1, 2, 3):
        return jsonify({"mensagem": "Nivel invalido"}), 400
    autorizado = int(dados["autorizado"])
    cursor = con.cursor()
    try:
        cursor.execute("UPDATE CONTA SET WHATSAPP_AUTORIZADO = ?, WHATSAPP_NIVEL = ? WHERE ID_CONTA = ?", (autorizado, nivel, conta["id_conta"]))
        con.commit()
    except Exception:
        con.rollback()
        app.logger.exception("Falha ao atualizar configuracao WhatsApp")
        return jsonify({"mensagem": "Nao foi possivel atualizar a configuracao"}), 500
    finally:
        cursor.close()
    return jsonify({"id_conta": conta["id_conta"], "autorizado": autorizado, "nivel": nivel})


def _servico_valido():
    segredo = os.getenv("N8N_SERVICE_KEY")
    recebido = request.headers.get("X-Arkhe-N8N-Key")
    return bool(segredo and recebido and secrets.compare_digest(segredo, recebido))


@app.route("/internal/whatsapp/contexto", methods=["POST"])
def whatsapp_contexto():
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    # Nao identificar cliente apenas por telefone ou por JID.
    # A vinculacao autenticada sera implementada separadamente.
    return jsonify({"vinculado": False, "contas": [], "mensagem": "Vinculacao de identidade ainda nao habilitada"})


@app.route("/internal/whatsapp/iniciar", methods=["POST"])
def whatsapp_legado_iniciar():
    return jsonify({"mensagem": "Rota legada desativada ate vinculacao segura"}), 403


@app.route("/internal/whatsapp/selecionar-conta", methods=["POST"])
def whatsapp_legado_selecionar():
    return jsonify({"mensagem": "Rota legada desativada ate vinculacao segura"}), 403


def _normalizar_telefone(valor):
    digitos = re.sub(r"\D", "", str(valor or ""))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    return digitos if len(digitos) in (10, 11) else None


@app.route("/whatsapp/link", methods=["POST"])
def whatsapp_criar_link():
    """Cria um convite temporario; nao concede acesso financeiro por si so."""
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    if not conta["autorizado"]:
        return jsonify({"mensagem": "Autorize o WhatsApp antes de iniciar a vinculacao"}), 403
    destino = re.sub(r"\D", "", os.getenv("ARKHE_WHATSAPP_NUMBER", ""))
    if len(destino) not in (12, 13) or not destino.startswith("55"):
        return jsonify({"mensagem": "Numero oficial do WhatsApp ainda nao configurado no servidor"}), 503
    usuario = descobre_id_usuario()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (usuario,))
        registro = cursor.fetchone()
    finally:
        cursor.close()
    numero = _normalizar_telefone(registro[0] if registro else None)
    if not numero:
        return jsonify({"mensagem": "Cadastre um telefone valido no seu perfil antes de vincular"}), 422
    codigo = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="arkhe-wa-v1").dumps(
        {"usuario": usuario, "conta": conta["id_conta"], "telefone": numero})
    texto = "Ola Arkhe! Quero iniciar a vinculacao do meu WhatsApp. Codigo: " + codigo
    return jsonify({"url": "https://wa.me/" + destino + "?text=" + quote(texto),
                    "expira_em_segundos": 600, "mensagem": "Envie a mensagem pronta pelo WhatsApp"})


@app.route("/internal/whatsapp/validar-convite", methods=["POST"])
def whatsapp_validar_convite():
    """Valida convite e remetente para saudacao. NAO emite token bancario."""
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    remetente = str(dados.get("chatId", ""))
    if not remetente.endswith("@c.us") or not remetente.split("@")[0].isdigit():
        return jsonify({"vinculado": False, "mensagem": "Nao foi possivel validar automaticamente o identificador do WhatsApp"}), 403
    numero = _normalizar_telefone(remetente.split("@")[0])
    try:
        token = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="arkhe-wa-v1").loads(
            str(dados.get("codigo", "")), max_age=600)
    except (BadSignature, SignatureExpired):
        return jsonify({"vinculado": False, "mensagem": "Convite invalido ou expirado. Gere outro pelo site"}), 403
    if not numero or numero != token.get("telefone"):
        return jsonify({"vinculado": False, "mensagem": "Use o mesmo numero cadastrado no Arkhé"}), 403
    cursor = con.cursor()
    try:
        cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL
                          FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ? AND U.TELEFONE IS NOT NULL""",
                       (token.get("conta"), token.get("usuario")))
        registro = cursor.fetchone()
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (token.get("usuario"),))
        telefone = cursor.fetchone()
    finally:
        cursor.close()
    if not registro or not registro[0] or not telefone or _normalizar_telefone(telefone[0]) != numero:
        return jsonify({"vinculado": False, "mensagem": "Autorizacao desativada ou telefone alterado"}), 403
    return jsonify({"convite_validado": True, "vinculado": False, "nivel": int(registro[1]),
                    "mensagem": "Telefone e convite confirmados. O acesso bancario permanece indisponivel ate a vinculacao persistente segura."})
