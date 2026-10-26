"""Rate limiting distribuido para as rotas de integracao /api/v1.

Executado antes de acessar Firebird. Nao confia em X-Forwarded-For enviado
pelo cliente; o IP vem de REMOTE_ADDR (proxy deve ser configurado com cuidado).
"""
import hashlib
import os

import redis
from flask import current_app, jsonify, request

_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1])) end
return {n, redis.call('TTL', KEYS[1])}
"""


def _inteiro_env(nome, padrao):
    try:
        valor = int(os.getenv(nome, str(padrao)))
        return valor if valor > 0 else padrao
    except (TypeError, ValueError):
        return padrao


def _faixa_rota():
    caminho = request.path
    if caminho == '/api/v1/contas/verificar-cpf':
        return 'cpf', _inteiro_env('ARKHE_API_RATE_CPF_MIN', 10)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return 'escrita', _inteiro_env('ARKHE_API_RATE_ESCRITA_MIN', 30)
    return 'leitura', _inteiro_env('ARKHE_API_RATE_LEITURA_MIN', 120)


def limitar_api():
    """Restringe /api/v1 para integracoes HTTP, nao rotas web autenticadas."""
    if not request.path.startswith('/api/v1/'):
        return None
    # Nao interferir em rotas de sessao, MAURO ou administracao do proprio site.
    if request.path.startswith(('/api/v1/admin/', '/api/v1/limites/', '/api/v1/mauro/',
                                '/api/v1/assistente/', '/api/v1/agendamentos/',
                                '/api/v1/recorrencias/', '/api/v1/estornos/',
                                '/api/v1/notificacoes/')):
        return None
    # Apenas integracoes por Client ID: chamadas autenticadas pelo WhatsApp
    # mantem o controle especifico de seu canal.
    client_id = request.headers.get('X-Client-ID', '').strip()
    if not client_id:
        return None
    url = os.getenv('ARKHE_WHATSAPP_REDIS_URL') or os.getenv('REDIS_URL')
    if not url:
        return jsonify({'mensagem': 'Protecao de limite da API indisponivel'}), 503

    categoria, limite = _faixa_rota()
    ip = request.remote_addr or 'indefinido'
    identidade = hashlib.sha256((client_id + ':' + ip).encode()).hexdigest()
    chave = 'arkhe:api:rate:v1:' + categoria + ':' + identidade
    cliente = None
    try:
        cliente = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        contagem, restante = cliente.eval(_SCRIPT, 1, chave, 60)
    except (redis.RedisError, OSError, ValueError, TypeError):
        current_app.logger.warning('Rate limiting da API indisponivel')
        return jsonify({'mensagem': 'Protecao de limite da API indisponivel'}), 503
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except (redis.RedisError, OSError):
                pass
    if int(contagem) > limite:
        resposta = jsonify({'mensagem': 'Limite de requisicoes excedido', 'codigo': 'RATE_LIMIT_EXCEDIDO'})
        resposta.headers['Retry-After'] = str(max(1, int(restante)))
        resposta.headers['Cache-Control'] = 'no-store'
        return resposta, 429
    return None
