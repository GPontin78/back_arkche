"""Ativacao WhatsApp sem codigo visivel: site autenticado -> WAHA -> resposta ATIVAR.
Redis guarda desafio pendente e vinculacao, Firebird e fonte das permissoes.
"""
import hashlib
import json
import os
import re

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


def _telefone_do_jid(jid):
    if not re.fullmatch(r"55[0-9]{10,11}@c\.us", jid):
        return None
    return _normalizar_telefone(jid.split("@", 1)[0])


@app.route("/whatsapp/ativar", methods=["POST"])
def whatsapp_ativar_sem_codigo():
    conta, erro = _conta_configuravel()
    if erro:
        return erro
    if not conta["autorizado"]:
        return jsonify({"mensagem": "Autorize o WhatsApp nesta conta antes de continuar"}), 403
    usuario = descobre_id_usuario()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (usuario,))
        linha = cursor.fetchone()
    finally:
        cursor.close()
    telefone = _normalizar_telefone(linha[0] if linha else None)
    if not telefone:
        return jsonify({"mensagem": "Atualize o telefone cadastrado antes de ativar"}), 422
    destino = "55" + telefone + "@c.us"
    waha_url = os.getenv("WAHA_API_URL", "").rstrip("/")
    waha_chave = os.getenv("WAHA_API_KEY", "")
    if not waha_url.startswith("https://") or not waha_chave:
        return jsonify({"mensagem": "WAHA nao configurado no backend"}), 503

    pendencia = {"id_usuario": int(usuario), "id_conta": int(conta["id_conta"]),
                 "telefone": telefone}
    redis_cli = None
    chave = _chave_pendente(telefone)
    try:
        redis_cli = _redis_wa()
        redis_cli.set(chave, json.dumps(pendencia), ex=PENDENCIA_TTL)
        resposta = requests.post(waha_url + "/api/sendText",
            headers={"X-Api-Key": waha_chave, "Content-Type": "application/json"},
            json={"session": "arkhe", "chatId": destino,
                  "text": "Ola! Aqui e o assistente do Banco Arkhe. Voce solicitou a ativacao do WhatsApp pelo site. Para confirmar este numero, responda ATIVAR. A solicitacao expira em 10 minutos. Se nao foi voce, ignore esta mensagem."},
            timeout=12)
        resposta.raise_for_status()
    except Exception:
        if redis_cli:
            redis_cli.delete(chave)
        app.logger.exception("Falha ao iniciar ativacao WhatsApp via WAHA")
        return jsonify({"mensagem": "Nao foi possivel enviar a mensagem de ativacao agora"}), 503
    return jsonify({"enviado": True, "telefone_final": telefone[-4:],
                    "mensagem": "Mensagem enviada ao seu WhatsApp. Responda ATIVAR em ate 10 minutos."})


@app.route("/internal/whatsapp/confirmar", methods=["POST"])
def whatsapp_confirmar_sem_codigo():
    if not _servico_valido():
        return jsonify({"mensagem": "Servico nao autorizado"}), 401
    dados = request.get_json(silent=True) or {}
    chat_id = str(dados.get("chatId", ""))
    numero_jid = str(dados.get("senderPhoneJid", "")).strip()
    if not re.fullmatch(r"[0-9]{6,20}@(c\.us|lid)", chat_id):
        return jsonify({"confirmado": False, "mensagem": "Identificador do WhatsApp invalido"}), 403
    # Para @lid so aceitar um JID telefonico alternativo fornecido pelo WAHA,
    # nunca inferido pelo Gemini ou pelo proprio texto da mensagem.
    telefone = _telefone_do_jid(chat_id if chat_id.endswith("@c.us") else numero_jid)
    if not telefone:
        return jsonify({"confirmado": False, "mensagem": "Nao consegui confirmar seu numero. Abra a integracao no site Arkhé para tentar novamente."}), 403
    redis_cli = _redis_wa()
    chave = _chave_pendente(telefone)
    valor = redis_cli.get(chave)
    if not valor:
        return jsonify({"confirmado": False, "mensagem": "Nao encontrei ativacao pendente. Solicite novamente pelo site Arkhé."}), 404
    pendencia = json.loads(valor)
    cursor = con.cursor()
    try:
        cursor.execute("""SELECT C.WHATSAPP_AUTORIZADO, C.WHATSAPP_NIVEL, U.TELEFONE
            FROM CONTA C JOIN USUARIO U ON U.ID_USUARIO = C.ID_USUARIO
            WHERE C.ID_CONTA = ? AND C.ID_USUARIO = ?""",
            (pendencia["id_conta"], pendencia["id_usuario"]))
        conta = cursor.fetchone()
    finally:
        cursor.close()
    if not conta or not conta[0] or _normalizar_telefone(conta[2]) != telefone:
        redis_cli.delete(chave)
        return jsonify({"confirmado": False, "mensagem": "Autorizacao nao encontrada ou revogada"}), 403
    # A chave de remetente isola a conta e e substituida quando o usuario ativa outra.
    redis_cli.set(_chave_remetente(chat_id), json.dumps({
        "id_usuario": pendencia["id_usuario"], "id_conta": pendencia["id_conta"],
        "telefone": telefone, "chat_id": chat_id}), ex=VINCULO_TTL)
    redis_cli.delete(chave)
    return jsonify({"confirmado": True, "nivel": int(conta[1]),
                    "mensagem": "WhatsApp ativado com sucesso! Sua conta foi vinculada. Agora voce pode consultar saldo e extrato. Outros servicos serao disponibilizados gradualmente."})
