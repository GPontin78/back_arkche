import datetime
import hashlib
import hmac
import os
import secrets

import jwt
from flask import jsonify, request

from banco import con
from funcao import gerar_token_mcp, listar_contas_usuario, usuario_pode_acessar_conta
from main import app


CARGOS_WHATSAPP = {0: 'Administrativo', 1: 'Financeiro', 2: 'Contador', 3: 'RH', 4: 'Compras', 5: 'Outro'}
CARGOS_FINANCEIROS = (0, 1, 2)
DURACAO_CODIGO_MINUTOS = 10
DURACAO_SESSAO_MINUTOS = 30


def normalizar_telefone_whatsapp(valor):
    texto = str(valor or '').split('@')[0]
    numeros = ''.join(caractere for caractere in texto if caractere.isdigit())
    if len(numeros) in (10, 11):
        numeros = '55' + numeros
    return numeros if len(numeros) in (12, 13) and numeros.startswith('55') else ''


def autenticar_n8n():
    esperada = os.getenv('N8N_SERVICE_KEY')
    recebida = request.headers.get('X-Arkhe-N8N-Key')
    if not esperada:
        return jsonify({'mensagem': 'Integração n8n não configurada'}), 503
    if not recebida or not secrets.compare_digest(recebida, esperada):
        return jsonify({'mensagem': 'Serviço não autorizado'}), 401
    return None


def buscar_usuario_por_telefone(telefone):
    cursor = con.cursor()
    try:
        cursor.execute("SELECT ID_USUARIO, NOME, TELEFONE FROM USUARIO WHERE TELEFONE IS NOT NULL")
        encontrados = [u for u in cursor.fetchall() if normalizar_telefone_whatsapp(u[2]) == telefone]
        if len(encontrados) != 1:
            return None
        return {'id_usuario': encontrados[0][0], 'nome': encontrados[0][1], 'telefone': telefone}
    finally:
        cursor.close()


def obter_contexto_web():
    token = request.cookies.get('access_token')
    if not token:
        return None, (jsonify({'mensagem': 'Entre na sua conta para continuar'}), 401)
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        if payload.get('escopo') != 'conta':
            raise ValueError('Escopo inválido')
        id_usuario, id_conta = int(payload['id_usuario']), int(payload['id_conta'])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        return None, (jsonify({'mensagem': 'Sessão inválida ou expirada'}), 401)

    if not usuario_pode_acessar_conta(id_usuario, id_conta):
        return None, (jsonify({'mensagem': 'Acesso à conta não autorizado'}), 403)

    contas = listar_contas_usuario(id_usuario)
    conta = next((item for item in contas if int(item['id_conta']) == id_conta), None)
    if not conta:
        return None, (jsonify({'mensagem': 'Conta não encontrada'}), 404)

    cursor = con.cursor()
    try:
        cursor.execute("SELECT TELEFONE FROM USUARIO WHERE ID_USUARIO = ?", (id_usuario,))
        usuario = cursor.fetchone()
    finally:
        cursor.close()
    telefone = normalizar_telefone_whatsapp(usuario[0] if usuario else None)
    if not telefone:
        return None, (jsonify({'mensagem': 'Atualize seu telefone cadastrado antes de utilizar o WhatsApp'}), 422)
    return {'id_usuario': id_usuario, 'id_conta': id_conta, 'conta': conta, 'telefone': telefone}, None


def validar_origem_web():
    origem = (request.headers.get('Origin') or '').rstrip('/')
    permitida = app.config['FRONTEND_URL'].rstrip('/')
    if origem != permitida:
        return jsonify({'mensagem': 'Origem da solicitação não autorizada'}), 403
    return None


def capacidades_whatsapp(conta):
    if conta['tipo_conta'] == 0:
        return {'financeiro': conta['vinculo'] == 'titular', 'rh': False}
    if conta['vinculo'] == 'proprietario':
        return {'financeiro': True, 'rh': True}
    return {'financeiro': conta.get('cargo') in CARGOS_FINANCEIROS, 'rh': conta.get('cargo') == 3}


def obter_configuracao(cursor, id_usuario, id_conta):
    cursor.execute(
        """SELECT TELEFONE, NIVEL, CODIGO_HASH, CODIGO_EXPIRA, TENTATIVAS, CODIGO_GERADO_EM
           FROM WHATSAPP_CONFIG WHERE ID_USUARIO = ? AND ID_CONTA = ?""",
        (id_usuario, id_conta)
    )
    return cursor.fetchone()


def resumo_whatsapp(contexto, config=None):
    conta = contexto['conta']
    capacidades = capacidades_whatsapp(conta)
    nivel = int(config[1]) if config else 0
    return {
        'telefone': contexto['telefone'],
        'tipo_conta': 'PJ' if conta['tipo_conta'] == 1 else 'PF',
        'vinculo': conta['vinculo'],
        'cargo': CARGOS_WHATSAPP.get(conta.get('cargo')),
        'nivel': nivel,
        'habilitado': nivel == 1,
        'capacidades': capacidades,
        'niveis': [{'numero': 1, 'nome': 'Consultas', 'disponivel': True},
                   {'numero': 2, 'nome': 'Solicitações', 'disponivel': False},
                   {'numero': 3, 'nome': 'Movimentações', 'disponivel': False}]
    }


def hash_codigo(id_usuario, id_conta, telefone, codigo):
    texto = f'{id_usuario}:{id_conta}:{telefone}:{codigo}'.encode('utf-8')
    segredo = str(app.config['SECRET_KEY']).encode('utf-8')
    return hmac.new(segredo, texto, hashlib.sha256).hexdigest()


@app.route('/whatsapp/configuracao', methods=['GET', 'PUT'])
def whatsapp_configuracao():
    contexto, erro = obter_contexto_web()
    if erro:
        return erro
    if request.method == 'PUT':
        erro = validar_origem_web()
        if erro:
            return erro
        dados = request.get_json(silent=True) or {}
        nivel = dados.get('nivel')
        if type(nivel) is not int or nivel not in (0, 1):
            return jsonify({'mensagem': 'Apenas o nível 1 de consultas está disponível'}), 400
        if nivel == 1 and not any(capacidades_whatsapp(contexto['conta']).values()):
            return jsonify({'mensagem': 'Seu cargo não possui consultas autorizadas pelo WhatsApp'}), 403

    cursor = con.cursor()
    try:
        config = obter_configuracao(cursor, contexto['id_usuario'], contexto['id_conta'])
        if request.method == 'PUT':
            if config:
                cursor.execute(
                    """UPDATE WHATSAPP_CONFIG SET TELEFONE = ?, NIVEL = ?, CODIGO_HASH = NULL,
                       CODIGO_EXPIRA = NULL, TENTATIVAS = 0, CODIGO_GERADO_EM = NULL
                       WHERE ID_USUARIO = ? AND ID_CONTA = ?""",
                    (contexto['telefone'], nivel, contexto['id_usuario'], contexto['id_conta'])
                )
            else:
                cursor.execute(
                    """INSERT INTO WHATSAPP_CONFIG (ID_USUARIO, ID_CONTA, TELEFONE, NIVEL, TENTATIVAS)
                       VALUES (?, ?, ?, ?, 0)""",
                    (contexto['id_usuario'], contexto['id_conta'], contexto['telefone'], nivel)
                )
            cursor.execute("DELETE FROM WHATSAPP_SESSAO WHERE ID_USUARIO = ? AND ID_CONTA = ?", (contexto['id_usuario'], contexto['id_conta']))
            con.commit()
            config = obter_configuracao(cursor, contexto['id_usuario'], contexto['id_conta'])
        return jsonify(resumo_whatsapp(contexto, config)), 200
    except Exception as e:
        if request.method == 'PUT':
            con.rollback()
        print('ERRO CONFIGURAÇÃO WHATSAPP:', type(e).__name__)
        return jsonify({'mensagem': 'Não foi possível acessar a configuração do WhatsApp'}), 500
    finally:
        cursor.close()


@app.route('/whatsapp/codigo', methods=['POST'])
def whatsapp_gerar_codigo():
    erro = validar_origem_web()
    if erro:
        return erro
    contexto, erro = obter_contexto_web()
    if erro:
        return erro
    cursor = con.cursor()
    try:
        config = obter_configuracao(cursor, contexto['id_usuario'], contexto['id_conta'])
        if not config or int(config[1]) != 1 or config[0] != contexto['telefone']:
            return jsonify({'mensagem': 'Ative o WhatsApp para esta conta primeiro'}), 403
        if not any(capacidades_whatsapp(contexto['conta']).values()):
            return jsonify({'mensagem': 'Seu acesso não permite usar o WhatsApp nesta conta'}), 403

        agora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        if config[5] and (agora - config[5]).total_seconds() < 60:
            return jsonify({'mensagem': 'Aguarde um minuto antes de gerar outro código'}), 429

        codigo = f'{secrets.randbelow(100000000):08d}'
        validade = agora + datetime.timedelta(minutes=DURACAO_CODIGO_MINUTOS)
        cursor.execute(
            """UPDATE WHATSAPP_CONFIG SET CODIGO_HASH = ?, CODIGO_EXPIRA = ?, TENTATIVAS = 0,
               CODIGO_GERADO_EM = ? WHERE ID_USUARIO = ? AND ID_CONTA = ?""",
            (hash_codigo(contexto['id_usuario'], contexto['id_conta'], contexto['telefone'], codigo),
             validade, agora, contexto['id_usuario'], contexto['id_conta'])
        )
        con.commit()
        return jsonify({'codigo': codigo, 'expira_em_minutos': DURACAO_CODIGO_MINUTOS, 'telefone': contexto['telefone']}), 200
    except Exception as e:
        con.rollback()
        print('ERRO CÓDIGO WHATSAPP:', type(e).__name__)
        return jsonify({'mensagem': 'Não foi possível gerar o código de acesso'}), 500
    finally:
        cursor.close()


@app.route('/internal/whatsapp/iniciar', methods=['POST'])
def whatsapp_iniciar():
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    telefone = normalizar_telefone_whatsapp(dados.get('telefone') or dados.get('chat_id'))
    if not telefone:
        return jsonify({'mensagem': 'Telefone inválido'}), 400
    # Não revela se existe cliente ou quais contas ele possui sem autenticação.
    return jsonify({'autenticado': False, 'mensagem': 'Entre no Arkhé, abra WhatsApp na conta desejada e envie aqui o código temporário gerado no site.'}), 200


@app.route('/internal/whatsapp/selecionar-conta', methods=['POST'])
def whatsapp_selecionar_conta():
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    telefone = normalizar_telefone_whatsapp(dados.get('telefone') or dados.get('chat_id'))
    codigo = str(dados.get('codigo') or '').strip()
    if not telefone or len(codigo) != 8 or not codigo.isdigit():
        return jsonify({'mensagem': 'Código inválido ou expirado'}), 401

    usuario = buscar_usuario_por_telefone(telefone)
    if not usuario:
        return jsonify({'mensagem': 'Código inválido ou expirado'}), 401

    cursor = con.cursor()
    try:
        cursor.execute(
            """SELECT ID_CONTA, CODIGO_HASH, CODIGO_EXPIRA, TENTATIVAS FROM WHATSAPP_CONFIG
               WHERE ID_USUARIO = ? AND TELEFONE = ? AND NIVEL = 1 AND CODIGO_HASH IS NOT NULL""",
            (usuario['id_usuario'], telefone)
        )
        agora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        for id_conta, codigo_hash, expiracao, tentativas in cursor.fetchall():
            if not expiracao or expiracao <= agora or int(tentativas) >= 5:
                continue
            esperado = hash_codigo(usuario['id_usuario'], id_conta, telefone, codigo)
            if not hmac.compare_digest(esperado, codigo_hash):
                cursor.execute(
                    """UPDATE WHATSAPP_CONFIG SET TENTATIVAS = TENTATIVAS + 1
                       WHERE ID_USUARIO = ? AND ID_CONTA = ? AND CODIGO_HASH = ?""",
                    (usuario['id_usuario'], id_conta, codigo_hash)
                )
                continue

            contas = listar_contas_usuario(usuario['id_usuario'])
            conta = next((c for c in contas if c['id_conta'] == id_conta), None)
            if not conta or not any(capacidades_whatsapp(conta).values()):
                con.commit()
                return jsonify({'mensagem': 'Acesso à conta não autorizado'}), 403

            cursor.execute(
                """UPDATE WHATSAPP_CONFIG SET CODIGO_HASH = NULL, CODIGO_EXPIRA = NULL,
                   TENTATIVAS = 0 WHERE ID_USUARIO = ? AND ID_CONTA = ? AND CODIGO_HASH = ?""",
                (usuario['id_usuario'], id_conta, codigo_hash)
            )
            if cursor.rowcount != 1:
                con.rollback()
                return jsonify({'mensagem': 'Código já utilizado'}), 401
            validade_sessao = agora + datetime.timedelta(minutes=DURACAO_SESSAO_MINUTOS)
            cursor.execute(
                """UPDATE OR INSERT INTO WHATSAPP_SESSAO (ID_USUARIO, ID_CONTA, TELEFONE, VALIDA_ATE)
                   VALUES (?, ?, ?, ?) MATCHING (ID_USUARIO)""",
                (usuario['id_usuario'], id_conta, telefone, validade_sessao)
            )
            con.commit()
            sessao = gerar_token_mcp(usuario['id_usuario'], id_conta, canal='whatsapp',
                                    minutos=DURACAO_SESSAO_MINUTOS, telefone=telefone)
            return jsonify({
                'mcp_session': sessao, 'expira_em_minutos': DURACAO_SESSAO_MINUTOS,
                'conta': {'tipo_conta': 'PJ' if conta['tipo_conta'] == 1 else 'PF',
                          'nome': conta.get('nome_fantasia') or conta.get('razao_social') or usuario['nome'],
                          'vinculo': conta.get('vinculo'),
                          'cargo': CARGOS_WHATSAPP.get(conta.get('cargo')),
                          'capacidades': capacidades_whatsapp(conta)}
            }), 200

        con.commit()
        return jsonify({'mensagem': 'Código inválido ou expirado'}), 401
    except Exception as e:
        con.rollback()
        print('ERRO AUTENTICAÇÃO WHATSAPP:', type(e).__name__)
        return jsonify({'mensagem': 'Erro ao autenticar pelo WhatsApp'}), 500
    finally:
        cursor.close()


def autorizar_sessao_whatsapp(id_usuario, id_conta, telefone, caminho):
    """Revalida a configuração e o cargo em toda consulta feita via MCP."""
    contas = listar_contas_usuario(id_usuario)
    conta = next((c for c in contas if c['id_conta'] == id_conta), None)
    if not conta:
        return False

    cursor = con.cursor()
    try:
        config = obter_configuracao(cursor, id_usuario, id_conta)
    finally:
        cursor.close()
    if not config or int(config[1]) != 1 or config[0] != telefone:
        return False
    cursor = con.cursor()
    try:
        cursor.execute(
            """SELECT VALIDA_ATE FROM WHATSAPP_SESSAO
               WHERE ID_USUARIO = ? AND ID_CONTA = ? AND TELEFONE = ?""",
            (id_usuario, id_conta, telefone)
        )
        sessao = cursor.fetchone()
    finally:
        cursor.close()
    agora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if not sessao or sessao[0] <= agora:
        return False
    usuario = buscar_usuario_por_telefone(telefone)
    if not usuario or usuario['id_usuario'] != id_usuario:
        return False

    capacidades = capacidades_whatsapp(conta)
    if caminho == '/internal/mcp/conta':
        return any(capacidades.values())
    if caminho.startswith(('/internal/mcp/funcionarios', '/internal/mcp/folhas',
                           '/internal/mcp/relatorios/funcionarios')):
        return capacidades['rh']
    return capacidades['financeiro'] and caminho in (
        '/internal/mcp/saldo', '/internal/mcp/extrato', '/internal/mcp/dda',
        '/internal/mcp/boletos', '/internal/mcp/faturas',
        '/internal/mcp/limites', '/internal/mcp/chaves-pix')


@app.route('/internal/whatsapp/sessao', methods=['POST'])
def whatsapp_obter_sessao():
    """O n8n obtém um token MCP curto; não armazena o token em workflows."""
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    telefone = normalizar_telefone_whatsapp(dados.get('telefone') or dados.get('chat_id'))
    if not telefone:
        return jsonify({'mensagem': 'Telefone inválido'}), 400

    usuario = buscar_usuario_por_telefone(telefone)
    if not usuario:
        return jsonify({'autenticado': False, 'mensagem': 'É necessário autenticar pelo site'}), 401

    cursor = con.cursor()
    try:
        cursor.execute(
            """SELECT ID_CONTA, VALIDA_ATE FROM WHATSAPP_SESSAO
               WHERE ID_USUARIO = ? AND TELEFONE = ?""",
            (usuario['id_usuario'], telefone)
        )
        sessao = cursor.fetchone()
    finally:
        cursor.close()
    agora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if not sessao or sessao[1] <= agora:
        return jsonify({'autenticado': False, 'mensagem': 'Sessão expirada. Gere outro código no site'}), 401
    if not autorizar_sessao_whatsapp(usuario['id_usuario'], sessao[0], telefone, '/internal/mcp/conta'):
        return jsonify({'autenticado': False, 'mensagem': 'Acesso revogado ou não permitido'}), 403

    segundos = int((sessao[1] - agora).total_seconds())
    token = gerar_token_mcp(usuario['id_usuario'], sessao[0], canal='whatsapp',
                            minutos=1, telefone=telefone)
    return jsonify({'autenticado': True, 'mcp_session': token,
                    'expira_em_segundos': min(segundos, 60)}), 200


@app.route('/internal/whatsapp/encerrar', methods=['POST'])
def whatsapp_encerrar_sessao():
    erro = autenticar_n8n()
    if erro:
        return erro
    dados = request.get_json(silent=True) or {}
    telefone = normalizar_telefone_whatsapp(dados.get('telefone') or dados.get('chat_id'))
    if not telefone:
        return jsonify({'mensagem': 'Telefone inválido'}), 400
    cursor = con.cursor()
    try:
        cursor.execute("DELETE FROM WHATSAPP_SESSAO WHERE TELEFONE = ?", (telefone,))
        con.commit()
        return jsonify({'mensagem': 'Sessão encerrada'}), 200
    except Exception:
        con.rollback()
        return jsonify({'mensagem': 'Não foi possível encerrar a sessão'}), 500
    finally:
        cursor.close()
