"""Configuracao do WhatsApp por conta.

Acesso bancario pelo WhatsApp permanece bloqueado ate existir
vinculacao de identidade comprovada; um numero fornecido pelo n8n
nao autentica o titular.
"""
import os
import secrets
import re
import json
import hashlib
import redis
from urllib.parse import quote
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from flask import jsonify, request

from banco import con
from funcao import descobre_id_conta, descobre_id_usuario, usuario_pode_acessar_conta, calcular_saldo
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
    return {"id_conta": conta, "autorizado": int(registro[1]), "nivel": int(registro[2]), "tipo_conta": int(_tipo_conta(conta))}, None


def _tipo_conta(id_conta):
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TIPO_CONTA FROM CONTA WHERE ID_CONTA = ?", (id_conta,))
        linha = cursor.fetchone()
        return int(linha[0]) if linha else 0
    finally:
        cursor.close()


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
    if nivel not in ((1, 2) if conta["tipo_conta"] == 0 else (1, 2, 3)):
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
    return jsonify({"id_conta": conta["id_conta"], "autorizado": autorizado, "nivel": nivel, "tipo_conta": conta["tipo_conta"]})


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
    if not re.fullmatch(r"[0-9]{6,20}@(c\\.us|lid)", remetente):
        return jsonify({"vinculado": False, "mensagem": "Nao foi possivel validar automaticamente o identificador do WhatsApp"}), 403
    numero = _normalizar_telefone(remetente.split("@")[0])
    try:
        token = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="arkhe-wa-v1").loads(
            str(dados.get("codigo", "")), max_age=600)
    except (BadSignature, SignatureExpired):
        return jsonify({"vinculado": False, "mensagem": "Convite invalido ou expirado. Gere outro pelo site"}), 403
    if remetente.endswith("@c.us") and (not numero or numero != token.get("telefone")):
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
    return _salvar_vinculo_whatsapp(remetente, token, registro)


# Redis de autorizacao, separado da memoria conversacional do agente.
# Nunca utilizar texto do Gemini ou historico como prova de autenticacao.
def _redis_wa():
    endereco = os.getenv("ARKHE_WHATSAPP_REDIS_URL") or os.getenv("REDIS_URL")
    if not endereco:
        raise RuntimeError("ARKHE_WHATSAPP_REDIS_URL nao configurada")
    return redis.Redis.from_url(endereco, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)


def _chave_remetente(chat_id):
    return "arkhe:wa:binding:v1:" + hashlib.sha256(chat_id.encode("utf-8")).hexdigest()


def _salvar_vinculo_whatsapp(remetente, token, registro):
    """O convite do site autoriza exclusivamente a conta nele especificada."""
    try:
        redis_cli = _redis_wa()
        convite_hash = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        # Distinguir vinculos de contas PF e PJ. O ultimo pareamento seleciona a conta.
        # Prova de posse do numero ocorre para @c.us; @lid usa o segredo temporario
        # de uso unico emitido no site autenticado.
        codigo_hash = hashlib.sha256(str(request.get_json(silent=True).get("codigo", "")).encode("utf-8")).hexdigest()
        if not redis_cli.set("arkhe:wa:convite-usado:" + codigo_hash, "1", nx=True, ex=600):
            return jsonify({"vinculado": False, "mensagem": "Convite ja utilizado. Gere outro no site"}), 409
        redis_cli.set(_chave_remetente(remetente), json.dumps({
            "id_usuario": int(token["usuario"]), "id_conta": int(token["conta"]),
            "telefone": str(token["telefone"]), "chat_id": remetente
        }), ex=60*60*24*30)
    except Exception:
        app.logger.exception("Falha Redis vinculo WhatsApp")
        return jsonify({"vinculado": False, "mensagem": "Nao foi possivel vincular o WhatsApp. Verifique Redis"}), 503
    return jsonify({"convite_validado": True, "vinculado": True, "nivel": int(registro[1]),
                    "mensagem": "WhatsApp vinculado com a conta Arkhé. Saldo e extrato disponiveis."})


def _conta_vinculada(chat_id):
    if not re.fullmatch(r"[0-9]{6,20}@(c\\.us|lid)", chat_id):
        return None
    valor = _redis_wa().get(_chave_remetente(chat_id))
    if not valor:
        return None
    identidade = json.loads(valor)
    if identidade.get("chat_id") != chat_id:
        return None
    cursor = con.cursor()
    try:
        cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL, C.TIPO_CONTA, U.TELEFONE
                          FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                          WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ?""",
                       (identidade["id_conta"], identidade["id_usuario"]))
        conta = cursor.fetchone()
    finally:
        cursor.close()
    if not conta or int(conta[0]) != 1 or _normalizar_telefone(conta[3]) != identidade["telefone"]:
        return None
    identidade["nivel"] = min(int(conta[1]), 2) if int(conta[2]) == 0 else int(conta[1])
    return identidade


@app.route("/internal/whatsapp/consulta", methods=["POST"])
def whatsapp_consulta():
    """Consultas reais, isoladas pela conta vinculada e autorizacao atual do Firebird."""
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    acao = str(dados.get("acao", "")).lower()
    if acao not in ("saldo", "extrato"):
        return jsonify({"mensagem": "Consulta nao disponivel"}), 400
    try:
        conta = _conta_vinculada(chat_id)
        if not conta:
            return jsonify({"vinculado": False, "mensagem": "Vincule sua conta pelo site Arkhé para consultar dados bancarios"}), 403
        id_conta = conta["id_conta"]
        if acao == "saldo":
            saldo = calcular_saldo(id_conta)
            return jsonify({"vinculado": True, "acao": "saldo", "id_conta": id_conta,
                            "nivel": conta["nivel"], "saldo": float(saldo)})
        cursor = con.cursor()
        try:
            cursor.execute("""SELECT FIRST 10 ID_MOVIMENTACAO, VALOR, DATA_MOVIMENTACAO,
                              ID_PAGADOR, ID_RECEBEDOR FROM MOVIMENTACAO
                              WHERE ID_PAGADOR = ? OR ID_RECEBEDOR = ?
                              ORDER BY DATA_MOVIMENTACAO DESC, ID_MOVIMENTACAO DESC""",
                           (id_conta, id_conta))
            linhas = cursor.fetchall()
        finally:
            cursor.close()
        movimentos = [{"id": int(r[0]), "valor": float(r[1]),
                        "data": r[2].isoformat() if r[2] else None,
                        "tipo": "saida" if int(r[3] or 0) == id_conta else "entrada"}
                       for r in linhas]
        return jsonify({"vinculado": True, "acao": "extrato", "id_conta": id_conta,
                        "nivel": conta["nivel"], "movimentacoes": movimentos})
    except Exception:
        app.logger.exception("Falha na consulta bancaria do WhatsApp")
        return jsonify({"mensagem": "Consulta indisponivel no momento"}), 503
