"""Configuracao do WhatsApp por conta.

Acesso bancario pelo WhatsApp permanece bloqueado ate existir
vinculacao de identidade comprovada; um numero fornecido pelo n8n
nao autentica o titular.
"""
import os
import secrets

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
