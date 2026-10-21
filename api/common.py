"""Shared helpers for the HTTP integration endpoints."""
import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import jsonify, request

from banco import con
from funcao import verificar_pin


def valor_monetario_api(valor):
    try:
        valor = Decimal(str(valor))
        if not valor.is_finite() or valor <= 0:
            return None
        valor = valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if valor <= 0 or valor > Decimal('9999999999999.99'):
            return None
        return valor
    except (InvalidOperation, TypeError, ValueError):
        return None


def autenticar_integracao():
    client_id = request.headers.get('X-Client-ID')
    client_secret = request.headers.get('X-Client-Secret')

    if not client_id or not client_secret:
        return None, (jsonify({'mensagem': 'Credenciais da API nao informadas'}), 401)

    cursor = con.cursor()

    try:
        cursor.execute("""SELECT ID_INTEGRACAO, ID_CONTA, CLIENT_SECRET_HASH, ATIVO FROM INTEGRACAO_API WHERE CLIENT_ID = ?""", (client_id,))
        integracao = cursor.fetchone()

        if not integracao:
            return None, (jsonify({'mensagem': 'Credenciais da API invalidas'}), 401)

        id_integracao = integracao[0]
        id_conta = integracao[1]
        client_secret_hash = integracao[2]
        ativo = integracao[3]

        if ativo != 1:
            return None, (jsonify({'mensagem': 'Integracao desativada'}), 403)

        if not verificar_pin(client_secret, client_secret_hash):
            return None, (jsonify({'mensagem': 'Credenciais da API invalidas'}), 401)

        cursor.execute("""UPDATE INTEGRACAO_API SET ULTIMO_USO = CURRENT_TIMESTAMP WHERE ID_INTEGRACAO = ?""", (id_integracao,))
        con.commit()

        return {
            'id_integracao': id_integracao,
            'id_conta': id_conta
        }, None

    except Exception as e:
        con.rollback()
        print('ERRO AUTENTICAR INTEGRACAO:', e)
        return None, (jsonify({'mensagem': 'Erro ao autenticar integracao'}), 500)

    finally:
        cursor.close()


def obter_periodo():
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    hoje = datetime.date.today()

    if not data_inicio and not data_fim:
        data_inicio = hoje.replace(day=1).isoformat()
        data_fim = hoje.isoformat()
        return data_inicio, data_fim, None

    if not data_inicio or not data_fim:
        return None, None, (jsonify({'mensagem': 'Informe data_inicio e data_fim juntas'}), 400)

    try:
        inicio = datetime.date.fromisoformat(data_inicio)
        fim = datetime.date.fromisoformat(data_fim)
    except ValueError:
        return None, None, (jsonify({'mensagem': 'Datas invalidas. Use o formato YYYY-MM-DD'}), 400)

    if inicio > fim:
        return None, None, (jsonify({'mensagem': 'data_inicio nao pode ser maior que data_fim'}), 400)

    return inicio.isoformat(), fim.isoformat(), None


def nome_cliente_api(nome, nome_fantasia, razao_social, tipo_conta):
    if tipo_conta == 1:
        return nome_fantasia or razao_social or nome or 'Conta Arkhe'

    return nome or 'Conta Arkhe'


def autenticar_requisicao(nivel_whatsapp=1, permitir_whatsapp=False):
    """Descobre a conta autorizada usando credenciais normais OU vínculo WhatsApp.

    Integrações de terceiros continuam usando X-Client-ID e X-Client-Secret.
    O WhatsApp exige a chave privada do n8n e um chatId previamente vinculado
    pelo site; o nível é sempre lido do Firebird, nunca recebido do cliente.

    IMPORTANTE: X-Arkhe-Chat-ID só pode vir do fluxo de mensagens WAHA
    autenticado no n8n. Nunca copie esse header do texto enviado pelo usuário.
    """
    tem_cliente = bool(request.headers.get("X-Client-ID") or request.headers.get("X-Client-Secret"))
    tem_canal = bool(request.headers.get("X-Arkhe-N8N-Key") or request.headers.get("X-Arkhe-Chat-ID"))
    if tem_cliente and tem_canal:
        return None, (jsonify({"mensagem": "Escolha apenas um tipo de autenticacao"}), 401)

    # As credenciais antigas continuam funcionando exatamente como antes.
    if tem_cliente or not permitir_whatsapp:
        return autenticar_integracao()

    if not tem_canal:
        return autenticar_integracao()

    from .whatsapp import _servico_valido, verificar_nivel_whatsapp
    if not _servico_valido():
        return None, (jsonify({"mensagem": "Servico nao autorizado"}), 401)
    chat_id = request.headers.get("X-Arkhe-Chat-ID", "")
    if not chat_id:
        return None, (jsonify({"mensagem": "Identificador WhatsApp nao informado"}), 400)
    conta, mensagem = verificar_nivel_whatsapp(chat_id, nivel_whatsapp)
    if not conta:
        return None, (jsonify({"mensagem": mensagem}), 403)
    return {"id_conta": conta["id_conta"], "id_usuario": conta["id_usuario"],
            "id_integracao": None, "origem": "whatsapp", "nivel": conta["nivel"]}, None
