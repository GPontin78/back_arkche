"""Autorizacao do canal WhatsApp no Redis, isolada da memoria de conversa.
Nao executa transacoes. Requer REDIS_URL e N8N_SERVICE_KEY no backend.
"""
import hashlib
import json
import os
import re
import secrets

import redis
from flask import jsonify, request

from main import app
from funcao import descobre_id_usuario, descobre_id_conta, usuario_pode_acessar_conta, listar_contas_usuario

PREFIX = "arkhe:wa:auth:v1"
JID_RE = re.compile(r"^[0-9]{5,24}@(lid|c\.us)$")


def store():
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL nao configurada")
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)


def jid_valido(valor):
    jid = str(valor or "").strip()
    return jid if JID_RE.fullmatch(jid) else None


def autenticar_servico():
    esperado = os.environ.get("N8N_SERVICE_KEY")
    recebido = request.headers.get("X-Arkhe-N8N-Key")
    return bool(esperado and recebido and secrets.compare_digest(esperado, recebido))


def grant_key(usuario, conta):
    return f"{PREFIX}:grant:{usuario}:{conta}"


def chat_key(jid):
    return f"{PREFIX}:chat:{jid}"


def resposta_erro(mensagem, status):
    return jsonify({"mensagem": mensagem}), status


@app.route("/whatsapp/autorizacao", methods=["POST"])
def whatsapp_autorizar_conta():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return resposta_erro("Conta nao autenticada", 401)
    dados = request.get_json(silent=True) or {}
    nivel = dados.get("nivel")
    if type(nivel) is not int or nivel not in (1, 2, 3):
        return resposta_erro("Nivel deve ser 1, 2 ou 3", 400)
    # O nivel e apenas teto: o cargo e validado a cada ferramenta no backend.
    try:
        store().set(grant_key(usuario, conta), str(nivel))
    except redis.RedisError:
        app.logger.exception("Redis indisponivel na autorizacao WhatsApp")
        return resposta_erro("Autorizacao temporariamente indisponivel", 503)
    return jsonify({"autorizada": True, "id_conta": conta, "nivel": nivel})


@app.route("/whatsapp/autorizacao", methods=["DELETE"])
def whatsapp_revogar_conta():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return resposta_erro("Conta nao autenticada", 401)
    try:
        store().delete(grant_key(usuario, conta))
    except redis.RedisError:
        return resposta_erro("Revogacao temporariamente indisponivel", 503)
    return jsonify({"revogada": True})


@app.route("/whatsapp/vinculo", methods=["POST"])
def whatsapp_gerar_vinculo():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return resposta_erro("Conta nao autenticada", 401)
    try:
        r = store()
        if not r.get(grant_key(usuario, conta)):
            return resposta_erro("Autorize primeiro o WhatsApp nesta conta", 403)
        codigo = secrets.token_urlsafe(32)
        digest = hashlib.sha256(codigo.encode()).hexdigest()
        r.set(f"{PREFIX}:pending:{digest}", str(usuario), ex=600, nx=True)
    except redis.RedisError:
        return resposta_erro("Vinculo temporariamente indisponivel", 503)
    # Mostrar apenas ao usuario autenticado. Nunca registrar em logs.
    return jsonify({"codigo": codigo, "expira_em_segundos": 600})


@app.route("/internal/whatsapp/vincular", methods=["POST"])
def whatsapp_confirmar_vinculo():
    if not autenticar_servico():
        return resposta_erro("Nao autorizado", 401)
    dados = request.get_json(silent=True) or {}
    jid = jid_valido(dados.get("chat_id"))
    codigo = str(dados.get("codigo") or "")
    if not jid or not (32 <= len(codigo) <= 128):
        return resposta_erro("Vinculo invalido", 400)
    digest = hashlib.sha256(codigo.encode()).hexdigest()
    try:
        r = store()
        # GETDEL consome o token uma unica vez, inclusive sob concorrencia.
        usuario = r.execute_command("GETDEL", f"{PREFIX}:pending:{digest}")
        if not usuario:
            return resposta_erro("Codigo invalido ou expirado", 403)
        if not any(r.get(grant_key(usuario, c["id_conta"])) for c in listar_contas_usuario(int(usuario))):
            return resposta_erro("Nenhuma conta autorizada", 403)
        r.set(chat_key(jid), str(usuario))
    except redis.RedisError:
        return resposta_erro("Vinculo temporariamente indisponivel", 503)
    return jsonify({"vinculado": True})


@app.route("/internal/whatsapp/contexto", methods=["POST"])
def whatsapp_contexto_autorizado():
    if not autenticar_servico():
        return resposta_erro("Nao autorizado", 401)
    jid = jid_valido((request.get_json(silent=True) or {}).get("chat_id"))
    if not jid:
        return resposta_erro("Identificador invalido", 400)
    try:
        r = store()
        usuario = r.get(chat_key(jid))
        if not usuario:
            return jsonify({"vinculado": False, "contas": []})
        usuario = int(usuario)
        contas = []
        for conta in listar_contas_usuario(usuario):
            nivel = r.get(grant_key(usuario, conta["id_conta"]))
            if not nivel or not usuario_pode_acessar_conta(usuario, conta["id_conta"]):
                continue
            contas.append({
                "id_conta": conta["id_conta"],
                "tipo_conta": conta["tipo_conta"],
                "nome_fantasia": conta.get("nome_fantasia"),
                "vinculo": conta.get("vinculo"),
                "cargo": conta.get("cargo"),
                "nivel": int(nivel)
            })
    except redis.RedisError:
        return resposta_erro("Contexto temporariamente indisponivel", 503)
    # Nunca disponibilizar credenciais de MCP para o modelo.
    return jsonify({"vinculado": True, "contas": contas})
