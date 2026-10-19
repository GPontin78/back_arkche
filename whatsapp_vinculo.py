"""Vinculo explicito entre uma sessao WhatsApp (@lid/@c.us) e um usuario Arkhé.

Piloto somente de vinculacao e consulta de contexto. Nao concede acesso MCP nem
executa transacoes. A identidade do remetente vem do webhook WAHA autenticado.
"""
import datetime
import hashlib
import os
import re
import secrets

from flask import jsonify, request
from banco import con
from main import app
from funcao import listar_contas_usuario, usuario_pode_acessar_conta
from whatsapp import autenticar_n8n, obter_contexto_web
from whatsapp_permissoes import capacidades_whatsapp

VALIDADE_MINUTOS = 10
JID_RE = re.compile(r'^[0-9]{5,24}@(lid|c\\.us)$')


def normalizar_chat_id(valor):
    texto = str(valor or '').strip().lower()
    return texto if JID_RE.fullmatch(texto) else ''


def resumo_vinculo(conta):
    return {'id_conta': conta['id_conta'], 'tipo_conta': 'PJ' if conta['tipo_conta'] == 1 else 'PF',
            'nome': conta.get('nome_fantasia') or conta.get('razao_social') or 'Conta pessoal',
            'capacidades': capacidades_whatsapp(conta)}


def instante():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


@app.route('/whatsapp/vinculo/criar', methods=['POST'])
def criar_vinculo_whatsapp():
    """Autorizacao nasce na sessao WEB da conta, nunca no telefone declarado."""
    from whatsapp import validar_origem_web
    erro = validar_origem_web()
    if erro:
        return erro
    contexto, erro = obter_contexto_web()
    if erro:
        return erro

    cursor = con.cursor()
    try:
        cursor.execute('SELECT NIVEL FROM WHATSAPP_CONFIG WHERE ID_USUARIO = ? AND ID_CONTA = ?',
                       (contexto['id_usuario'], contexto['id_conta']))
        config = cursor.fetchone()
        if not config or int(config[0]) != 1 or not any(capacidades_whatsapp(contexto['conta']).values()):
            return jsonify({'mensagem': 'Ative as consultas WhatsApp nesta conta antes de vincular'}), 403

        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode('ascii')).hexdigest()
        agora = instante()
        cursor.execute('DELETE FROM WHATSAPP_VINCULO_PENDENTE WHERE ID_USUARIO = ? AND ID_CONTA = ?',
                       (contexto['id_usuario'], contexto['id_conta']))
        cursor.execute(
            """INSERT INTO WHATSAPP_VINCULO_PENDENTE
               (TOKEN_HASH, ID_USUARIO, ID_CONTA, EXPIRA_EM, CRIADO_EM)
               VALUES (?, ?, ?, ?, ?)""",
            (digest, contexto['id_usuario'], contexto['id_conta'],
             agora + datetime.timedelta(minutes=VALIDADE_MINUTOS), agora))
        con.commit()
        # O frontend cria wa.me com texto inicial "ARKHE VINCULAR <token>".
        return jsonify({'mensagem_inicial': 'ARKHE VINCULAR ' + token,
                        'expira_em_minutos': VALIDADE_MINUTOS}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Erro ao criar vinculo WhatsApp')
        return jsonify({'mensagem': 'Nao foi possivel iniciar o vinculo'}), 500
    finally:
        cursor.close()


@app.route('/internal/whatsapp/vinculo/confirmar', methods=['POST'])
def confirmar_vinculo_whatsapp():
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    chat_id = normalizar_chat_id(dados.get('chat_id'))
    token = str(dados.get('token') or '')
    if not chat_id or len(token) < 35 or len(token) > 100:
        return jsonify({'mensagem': 'Vinculo invalido'}), 400

    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    cursor = con.cursor()
    try:
        cursor.execute(
            """SELECT ID_USUARIO, ID_CONTA, EXPIRA_EM FROM WHATSAPP_VINCULO_PENDENTE
               WHERE TOKEN_HASH = ? WITH LOCK""", (digest,))
        pendente = cursor.fetchone()
        if not pendente or pendente[2] <= instante():
            con.rollback()
            return jsonify({'mensagem': 'Vinculo invalido ou expirado'}), 401

        id_usuario, id_conta = pendente[:2]
        if not usuario_pode_acessar_conta(id_usuario, id_conta):
            con.rollback()
            return jsonify({'mensagem': 'Vinculo nao autorizado'}), 403
        cursor.execute('SELECT NIVEL FROM WHATSAPP_CONFIG WHERE ID_USUARIO = ? AND ID_CONTA = ?',
                       (id_usuario, id_conta))
        config = cursor.fetchone()
        if not config or int(config[0]) != 1:
            con.rollback()
            return jsonify({'mensagem': 'WhatsApp desativado para esta conta'}), 403

        # Um chat nao pode alternar silenciosamente entre dois usuarios diferentes.
        cursor.execute('SELECT ID_USUARIO FROM WHATSAPP_IDENTIDADE WHERE CHAT_ID = ?', (chat_id,))
        identidade = cursor.fetchone()
        if identidade and identidade[0] != id_usuario:
            con.rollback()
            return jsonify({'mensagem': 'Esta conversa ja esta vinculada. Revogue o vinculo anterior no Arkhé.'}), 409
        if not identidade:
            cursor.execute('INSERT INTO WHATSAPP_IDENTIDADE (CHAT_ID, ID_USUARIO, VINCULADO_EM) VALUES (?, ?, ?)',
                           (chat_id, id_usuario, instante()))
        cursor.execute('DELETE FROM WHATSAPP_VINCULO_PENDENTE WHERE TOKEN_HASH = ?', (digest,))
        con.commit()
        return jsonify({'vinculado': True, 'mensagem': 'Conversa autorizada. Escolha a conta para atendimento.'}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Erro ao confirmar vinculo WhatsApp')
        return jsonify({'mensagem': 'Nao foi possivel confirmar o vinculo'}), 500
    finally:
        cursor.close()


@app.route('/internal/whatsapp/vinculo/contas', methods=['POST'])
def contas_whatsapp_vinculadas():
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    chat_id = normalizar_chat_id(dados.get('chat_id'))
    if not chat_id:
        return jsonify({'mensagem': 'Identificador invalido'}), 400
    cursor = con.cursor()
    try:
        cursor.execute('SELECT ID_USUARIO FROM WHATSAPP_IDENTIDADE WHERE CHAT_ID = ?', (chat_id,))
        identidade = cursor.fetchone()
        if not identidade:
            return jsonify({'vinculado': False, 'contas': []}), 200
        id_usuario = identidade[0]
        contas = listar_contas_usuario(id_usuario)
        cursor.execute('SELECT ID_CONTA FROM WHATSAPP_CONFIG WHERE ID_USUARIO = ? AND NIVEL = 1', (id_usuario,))
        permitidas = {r[0] for r in cursor.fetchall()}
        autorizadas = [resumo_vinculo(c) for c in contas if c['id_conta'] in permitidas
                       and any(capacidades_whatsapp(c).values())]
        return jsonify({'vinculado': True, 'contas': autorizadas}), 200
    except Exception:
        app.logger.exception('Erro ao consultar contas vinculadas')
        return jsonify({'mensagem': 'Erro ao consultar contas'}), 500
    finally:
        cursor.close()


@app.route('/whatsapp/vinculo/revogar', methods=['POST'])
def revogar_vinculo_whatsapp():
    from whatsapp import validar_origem_web
    erro = validar_origem_web()
    if erro:
        return erro
    contexto, erro = obter_contexto_web()
    if erro:
        return erro
    cursor = con.cursor()
    try:
        # Revoga a identidade WhatsApp inteira do usuario e todas as sessoes antigas.
        cursor.execute('DELETE FROM WHATSAPP_IDENTIDADE WHERE ID_USUARIO = ?', (contexto['id_usuario'],))
        cursor.execute('DELETE FROM WHATSAPP_VINCULO_PENDENTE WHERE ID_USUARIO = ?', (contexto['id_usuario'],))
        cursor.execute('DELETE FROM WHATSAPP_SESSAO WHERE ID_USUARIO = ?', (contexto['id_usuario'],))
        con.commit()
        return jsonify({'revogado': True}), 200
    except Exception:
        con.rollback()
        app.logger.exception('Erro ao revogar vinculo WhatsApp')
        return jsonify({'mensagem': 'Nao foi possivel revogar'}), 500
    finally:
        cursor.close()
