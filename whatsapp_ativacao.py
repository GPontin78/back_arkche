"""Ativação do WhatsApp: autorização no site, convite enviado pelo WAHA e confirmação ATIVAR.

O Firebird continua sendo a fonte de permissões por conta.
O Redis registra apenas a confirmação pendente e o identificador vinculado.
"""
import hashlib
import json
import os
import re
from urllib.parse import quote

import requests
from flask import jsonify, request

from banco import con
from main import app
from funcao import descobre_id_usuario
from whatsapp import _conta_configuravel, _normalizar_telefone, _redis_wa, _chave_remetente, _servico_valido

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
