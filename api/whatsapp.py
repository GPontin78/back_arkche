"""WhatsApp account linking, activation, identity, and permission routes."""
import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote

import redis
import requests
from flask import jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

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
    if not ((remetente.endswith("@c.us") or remetente.endswith("@lid")) and remetente.split("@")[0].isdigit()):
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
    if not registro or not registro[0] or not telefone or (remetente.endswith("@c.us") and _normalizar_telefone(telefone[0]) != numero):
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
    if not ((chat_id.endswith("@c.us") or chat_id.endswith("@lid")) and chat_id.split("@")[0].isdigit()):
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


PENDENCIA_TTL = 600


VINCULO_TTL = 30 * 24 * 60 * 60


def _chave_pendente(telefone):
    return "arkhe:wa:pendente:v2:" + hashlib.sha256(telefone.encode()).hexdigest()


def _chave_pendente_chat(chat_id):
    return "arkhe:wa:pendente-chat:v2:" + hashlib.sha256(chat_id.encode()).hexdigest()


def _telefone_do_jid(jid):
    if not isinstance(jid, str) or not re.fullmatch(r"55[0-9]{10,11}@c\.us", jid):
        return None
    return _normalizar_telefone(jid.split("@", 1)[0])


def _jid_valido(chat_id):
    return isinstance(chat_id, str) and bool(re.fullmatch(r"[0-9]{6,20}@(c\.us|lid)", chat_id))


def _credenciais_waha():
    url = os.getenv("WAHA_API_URL", "").rstrip("/")
    chave = os.getenv("WAHA_API_KEY", "")
    if not url.startswith("https://") or not chave:
        raise RuntimeError("WAHA_API_URL ou WAHA_API_KEY não configurada")
    return url, {"X-Api-Key": chave}


def _resolver_lid_pelo_waha(chat_id):
    """Só confia no número devolvido pela sessão WAHA, nunca em texto do usuário."""
    if chat_id.endswith("@c.us"):
        return _telefone_do_jid(chat_id)
    if not chat_id.endswith("@lid"):
        return None
    url, headers = _credenciais_waha()
    resposta = requests.get(url + "/api/arkhe/lids/" + quote(chat_id, safe=""),
                            headers=headers, timeout=8)
    if resposta.status_code != 200:
        app.logger.warning("WAHA não resolveu LID: HTTP %s", resposta.status_code)
        return None
    dados = resposta.json()
    return _telefone_do_jid(dados.get("pn")) if isinstance(dados, dict) else None


def _descobrir_chat_destino(telefone):
    """Consulta o WAHA para descobrir o JID real do telefone (incluindo @lid)."""
    url, headers = _credenciais_waha()
    try:
        resposta = requests.get(url + "/api/contacts/check-exists",
            params={"phone": "55" + telefone, "session": "arkhe"}, headers=headers, timeout=8)
        if resposta.ok:
            dados = resposta.json()
            encontrado = dados.get("chatId") if isinstance(dados, dict) else None
            if dados.get("numberExists") and _jid_valido(encontrado):
                return encontrado
    except Exception:
        app.logger.warning("WAHA check-exists indisponível; usando número cadastrado")
    return "55" + telefone + "@c.us"


@app.route("/whatsapp/ativar", methods=["POST"])
def whatsapp_ativar_sem_codigo():
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    if not conta["autorizado"]:
        return jsonify({"mensagem": "Autorize o WhatsApp nesta conta antes de continuar."}), 403

    usuario = descobre_id_usuario()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (usuario,))
        linha = cursor.fetchone()
    finally:
        cursor.close()
    telefone = _normalizar_telefone(linha[0] if linha else None)
    if not telefone:
        return jsonify({"mensagem": "Atualize o telefone cadastrado antes de ativar."}), 422
    try:
        _credenciais_waha()
    except RuntimeError:
        return jsonify({"mensagem": "O WhatsApp do Arkhé ainda não foi configurado no servidor."}), 503

    pendencia = {"id_usuario": int(usuario), "id_conta": int(conta["id_conta"]), "telefone": telefone}
    chave = _chave_pendente(telefone)
    chat_id = _descobrir_chat_destino(telefone)
    chave_chat = _chave_pendente_chat(chat_id)

    try:
        redis_cli = _redis_wa()
        with redis_cli.pipeline(transaction=True) as pipe:
            pipe.set(chave, json.dumps(pendencia), ex=PENDENCIA_TTL)
            pipe.set(chave_chat, json.dumps(pendencia), ex=PENDENCIA_TTL)
            pipe.execute()
    except Exception:
        app.logger.exception("Falha Redis ao iniciar ativação do WhatsApp")
        return jsonify({"mensagem": "Não foi possível preparar a ativação. Confira o Redis."}), 503

    try:
        url, headers = _credenciais_waha()
        resposta = requests.post(url + "/api/sendText",
            headers={**headers, "Content-Type": "application/json"},
            json={"session": "arkhe", "chatId": chat_id,
                  "text": ("Olá! Aqui é o assistente do Banco Arkhé. Você solicitou a ativação do WhatsApp pelo nosso site. "
                           "Para confirmar este número, responda ATIVAR. A solicitação expira em 10 minutos. "
                           "Se não foi você, ignore esta mensagem.")}, timeout=12)
        resposta.raise_for_status()
    except Exception:
        app.logger.exception("Falha no envio da mensagem de ativação pelo WAHA")
        try:
            redis_cli.delete(chave, chave_chat)
        except Exception:
            app.logger.warning("Não foi possível limpar ativação pendente após erro de envio")
        return jsonify({"mensagem": "Não foi possível enviar a mensagem de ativação agora."}), 503

    return jsonify({"enviado": True, "telefone_final": telefone[-4:],
                    "mensagem": "Mensagem enviada! Responda ATIVAR no seu WhatsApp em até 10 minutos."})


@app.route("/internal/whatsapp/confirmar", methods=["POST"])
def whatsapp_confirmar_sem_codigo():
    if not _servico_valido():
        return jsonify({"mensagem": "Serviço não autorizado."}), 401
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    if not _jid_valido(chat_id):
        return jsonify({"confirmado": False, "mensagem": "Não foi possível identificar a conversa do WhatsApp."}), 403

    try:
        vinculo_existente = _conta_vinculada(chat_id)
        if vinculo_existente:
            return jsonify({"confirmado": True, "ja_ativo": True,
                            "mensagem": "Seu WhatsApp já está vinculado ao Arkhé! Pode pedir seu saldo ou extrato."})
        redis_cli = _redis_wa()
        pendencia_chat = redis_cli.get(_chave_pendente_chat(chat_id))
        pendencia = json.loads(pendencia_chat) if pendencia_chat else None
        # Se o convite foi criado antes desta atualização, resolver @lid pelo WAHA.
        telefone = pendencia.get("telefone") if pendencia else _resolver_lid_pelo_waha(chat_id)
        if not telefone:
            return jsonify({"confirmado": False, "mensagem": "Não consegui identificar seu número pelo WhatsApp. Solicite um novo convite no site do Arkhé."}), 403

        chave = _chave_pendente(telefone)
        valor = redis_cli.get(chave)
        if not valor:
            return jsonify({"confirmado": False, "mensagem": "Sua ativação expirou ou já foi concluída. Se necessário, solicite outra pelo site do Arkhé."}), 404
        pendencia_atual = json.loads(valor)
        # Caso tenha sido iniciado outro convite, nunca aceitar um vínculo antigo.
        if pendencia and pendencia != pendencia_atual:
            return jsonify({"confirmado": False, "mensagem": "Há uma ativação mais recente. Solicite outra mensagem no site."}), 409

        cursor = con.cursor()
        try:
            cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL, U.TELEFONE
                FROM CONTA C INNER JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
                WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ?""",
                (pendencia_atual["id_conta"], pendencia_atual["id_usuario"]))
            conta = cursor.fetchone()
        finally:
            cursor.close()
        if not conta or not conta[0] or _normalizar_telefone(conta[2]) != telefone:
            return jsonify({"confirmado": False, "mensagem": "A autorização foi revogada ou o telefone cadastrado mudou."}), 403

        vinculo = {"id_usuario": pendencia_atual["id_usuario"],
                   "id_conta": pendencia_atual["id_conta"], "telefone": telefone,
                   "chat_id": chat_id}
        with redis_cli.pipeline(transaction=True) as pipe:
            pipe.set(_chave_remetente(chat_id), json.dumps(vinculo), ex=VINCULO_TTL)
            pipe.delete(chave, _chave_pendente_chat(chat_id))
            pipe.execute()
        return jsonify({"confirmado": True, "nivel": int(conta[1]),
                        "mensagem": "WhatsApp ativado com sucesso! Sua conta Arkhé foi vinculada. Você já pode consultar saldo e extrato."})
    except Exception:
        app.logger.exception("Falha ao confirmar ativação WhatsApp")
        return jsonify({"confirmado": False, "mensagem": "Não foi possível concluir a ativação agora. Tente novamente em instantes."}), 503
