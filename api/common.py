"""Shared helpers for the HTTP integration endpoints."""
import datetime
import hashlib
import json
import os
import re

import redis
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import current_app, jsonify, make_response, request

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
    try:
        conta, mensagem = verificar_nivel_whatsapp(chat_id, nivel_whatsapp)
    except Exception:
        current_app.logger.exception("Falha na autorizacao WhatsApp")
        return None, (jsonify({"mensagem": "Autenticacao WhatsApp indisponivel"}), 503)
    if not conta:
        return None, (jsonify({"mensagem": mensagem}), 403)
    return {"id_conta": conta["id_conta"], "id_usuario": conta["id_usuario"],
            "id_integracao": None, "origem": "whatsapp", "nivel": conta["nivel"]}, None

def conectar_redis_operacoes(endereco):
    """Conecta o Redis usado na prevencao de pagamentos duplicados."""
    return redis.Redis.from_url(endereco, decode_responses=True, socket_timeout=3,
                               socket_connect_timeout=3)


def executar_operacao_idempotente(contexto, operacao, executar):
    """Executa POST bancario uma vez por chave e devolve a resposta em repeticoes.

    A chave deve ser aleatoria e unica por operacao, enviada por um servidor
    confiavel no header X-Idempotency-Key. O Redis bloqueia repeticoes entre
    workers, inclusive enquanto a primeira requisicao ainda esta em andamento.
    Falha de Redis antes da operacao: NAO realiza pagamento.
    Falha depois do COMMIT: NAO tenta realizar outro pagamento.
    """
    chave_cliente = request.headers.get("X-Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", chave_cliente):
        return jsonify({"mensagem": "Envie X-Idempotency-Key unica (8 a 128 caracteres)"}), 400

    endereco = os.getenv("ARKHE_WHATSAPP_REDIS_URL") or os.getenv("REDIS_URL")
    if not endereco:
        return jsonify({"mensagem": "Protecao de duplicidade indisponivel"}), 503
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"mensagem": "Envie um objeto JSON"}), 400

    identidade = f'{contexto["id_conta"]}:{operacao}:{chave_cliente}'
    chave = "arkhe:api:pagamento:v1:" + hashlib.sha256(identidade.encode()).hexdigest()
    assinatura = hashlib.sha256(json.dumps(dados, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode()).hexdigest()
    redis_cli = conectar_redis_operacoes(endereco)
    pendente = json.dumps({"assinatura": assinatura, "estado": "processando"})
    try:
        reservado = redis_cli.set(chave, pendente, nx=True, ex=7 * 24 * 60 * 60)
        if not reservado:
            anterior = json.loads(redis_cli.get(chave) or "{}")
            if anterior.get("assinatura") != assinatura:
                return jsonify({"mensagem": "Chave reutilizada com dados diferentes"}), 409
            if anterior.get("estado") == "concluido":
                return current_app.response_class(anterior["corpo"], status=anterior["status"],
                                                  mimetype="application/json")
            return jsonify({"mensagem": "Operacao ja recebida; consulte seu extrato antes de repetir",
                            "codigo": "OPERACAO_EM_PROCESSAMENTO"}), 409
    except Exception:
        current_app.logger.exception("Redis indisponivel na protecao de pagamento")
        return jsonify({"mensagem": "Pagamento temporariamente indisponivel"}), 503

    # Nao libera a chave em erro inesperado: pode ter ocorrido COMMIT antes da falha.
    # Assim a repeticao nao movimenta dinheiro novamente sem verificacao humana.
    resposta = make_response(executar())
    final = {"assinatura": assinatura, "estado": "concluido",
             "status": resposta.status_code, "corpo": resposta.get_data(as_text=True)}
    try:
        redis_cli.set(chave, json.dumps(final, ensure_ascii=False), ex=7 * 24 * 60 * 60)
    except Exception:
        current_app.logger.exception("Falha ao registrar resposta de pagamento; conferir extrato")
        return jsonify({"mensagem": "Resultado indeterminado; confira o extrato antes de tentar novamente",
                        "codigo": "RESULTADO_INDETERMINADO"}), 503
    return resposta


def limitar_pagamento_whatsapp(contexto, valor):
    """Limite preventivo por operacao no canal, sem PIN repetido.

    Este limite NAO substitui auditoria nem protecao contra sequestro do WhatsApp.
    O titular pode desativar o canal no site a qualquer momento.
    """
    if contexto.get("origem") != "whatsapp":
        return None
    try:
        teto = Decimal(os.getenv("ARKHE_WHATSAPP_LIMITE_PAGAMENTO", "1000.00"))
    except (InvalidOperation, ValueError):
        return jsonify({"mensagem": "Limite WhatsApp mal configurado"}), 503
    if teto <= 0 or valor > teto:
        return jsonify({"mensagem": "Valor excede o limite por operacao do WhatsApp"}), 403
    return None


def autorizar_pagamento_externo(contexto):
    """Pagamentos por Client ID exigem opt-in, para nao ampliar chaves antigas.

    Defina ARKHE_API_PAGAMENTOS_CLIENT_IDS como lista de Client IDs permitidos.
    Nao confundir esse controle de integracao com o nivel do WhatsApp.
    """
    if contexto.get("origem") == "whatsapp":
        return None
    identificador = request.headers.get("X-Client-ID", "")
    permitidos = {valor.strip() for valor in os.getenv("ARKHE_API_PAGAMENTOS_CLIENT_IDS", "").split(",")
                  if valor.strip()}
    if identificador not in permitidos:
        return jsonify({"mensagem": "Esta integracao nao esta habilitada para pagamentos de saida"}), 403
    return None
