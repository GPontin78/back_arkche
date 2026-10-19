"""Configuracao WhatsApp da conta, validada pela sessao bancaria existente.
Nao identifica remetente WAHA; nao libera MCP nem movimentacoes.
"""
from flask import jsonify, request
from main import app
from banco import con
from funcao import descobre_id_usuario, descobre_id_conta, usuario_pode_acessar_conta


def _conta_autenticada():
    usuario, conta = descobre_id_usuario(), descobre_id_conta()
    if not usuario or not conta or not usuario_pode_acessar_conta(usuario, conta):
        return None, None
    return usuario, conta


@app.route("/whatsapp/configuracao", methods=["GET"])
def whatsapp_configuracao_consultar():
    usuario, conta = _conta_autenticada()
    if not usuario:
        return jsonify({"mensagem": "Nao autenticado"}), 401
    cursor = con.cursor()
    try:
        cursor.execute("SELECT WHATSAPP_AUTORIZADO, WHATSAPP_NIVEL FROM CONTA WHERE ID_CONTA = ?", (conta,))
        registro = cursor.fetchone()
        if not registro:
            return jsonify({"mensagem": "Conta nao encontrada"}), 404
        return jsonify({"id_conta": conta, "autorizado": bool(registro[0]), "nivel": int(registro[1])})
    finally:
        cursor.close()


@app.route("/whatsapp/configuracao", methods=["PUT"])
def whatsapp_configuracao_alterar():
    usuario, conta = _conta_autenticada()
    if not usuario:
        return jsonify({"mensagem": "Nao autenticado"}), 401
    dados = request.get_json(silent=True) or {}
    autorizado, nivel = dados.get("autorizado"), dados.get("nivel")
    if type(autorizado) is not bool or type(nivel) is not int or nivel not in (1, 2, 3):
        return jsonify({"mensagem": "Informe autorizado booleano e nivel 1, 2 ou 3"}), 400
    cursor = con.cursor()
    try:
        # Somente titular/proprietario; funcionarios nao podem alterar a politica global.
        cursor.execute("SELECT ID_USUARIO FROM CONTA WHERE ID_CONTA = ?", (conta,))
        dono = cursor.fetchone()
        if not dono or int(dono[0]) != usuario:
            return jsonify({"mensagem": "Somente o titular pode configurar o WhatsApp"}), 403
        cursor.execute("UPDATE CONTA SET WHATSAPP_AUTORIZADO = ?, WHATSAPP_NIVEL = ? WHERE ID_CONTA = ?", (int(autorizado), nivel, conta))
        con.commit()
        return jsonify({"id_conta": conta, "autorizado": autorizado, "nivel": nivel})
    except Exception:
        con.rollback()
        app.logger.exception("Falha ao alterar configuracao WhatsApp")
        return jsonify({"mensagem": "Nao foi possivel salvar a configuracao"}), 500
    finally:
        cursor.close()
