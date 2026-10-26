"""Idempotencia persistente para compras com cartao.

Os dados financeiros e a chave ficam na mesma transacao Firebird. Redis nao e
necessario para determinar se uma compra ja foi confirmada.
"""
import hashlib
import json
import re

from flask import current_app, jsonify


_CHAVE_VALIDADA = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")


def validar_chave_venda(chave):
    chave = str(chave or "")
    return chave if _CHAVE_VALIDADA.fullmatch(chave) else None


def assinatura_venda(**campos):
    serializado = json.dumps(
        campos, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def obter_resposta_venda(cursor, canal, escopo, chave, assinatura):
    """Retorna a resposta ja persistida ou None se a chave ainda nao existe."""
    cursor.execute(
        """SELECT ASSINATURA, RESPOSTA_JSON, HTTP_STATUS
           FROM IDEMPOTENCIA_VENDA
           WHERE CANAL = ? AND ESCOPO_ID = ? AND CHAVE = ?""",
        (canal, str(escopo), chave),
    )
    existente = cursor.fetchone()
    if not existente:
        return None
    if existente[0] != assinatura:
        return jsonify({
            "mensagem": "Esta chave de operacao ja foi usada com outros dados.",
            "codigo": "CHAVE_IDEMPOTENCIA_REUTILIZADA",
        }), 409
    return current_app.response_class(
        existente[1], status=int(existente[2]), mimetype="application/json"
    )


def registrar_venda_idempotente(
    cursor, canal, escopo, chave, assinatura, id_compra, id_movimentacao,
    resposta, status_http,
):
    """Grava o resultado antes do commit da compra e da movimentacao."""
    cursor.execute(
        """INSERT INTO IDEMPOTENCIA_VENDA
           (CANAL, ESCOPO_ID, CHAVE, ASSINATURA, ID_COMPRA,
            ID_MOVIMENTACAO, RESPOSTA_JSON, HTTP_STATUS)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canal, str(escopo), chave, assinatura, int(id_compra),
            int(id_movimentacao) if id_movimentacao is not None else None,
            json.dumps(resposta, ensure_ascii=False, separators=(",", ":")),
            int(status_http),
        ),
    )
