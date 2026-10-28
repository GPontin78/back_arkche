"""Consulta de existencia de conta por CPF para integracoes API autenticadas.

Exige credenciais ativas da API, CPF valido, limites Redis por integracao
e por documento e responde somente a existencia da conta, sem dados pessoais.
"""
import hashlib
import os

import redis
from flask import current_app, jsonify, request

from banco import con
from funcao import normalizar_cpf, validar_cpf
from main import app
from .common import autenticar_integracao


_LUA_LIMITE_CPF = """
local count1 = redis.call('INCR', KEYS[1])
if count1 == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1])) end
local count2 = redis.call('INCR', KEYS[2])
if count2 == 1 then redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3])) end
local count3 = redis.call('INCR', KEYS[3])
if count3 == 1 then redis.call('EXPIRE', KEYS[3], tonumber(ARGV[5])) end
if count1 > tonumber(ARGV[2]) or count2 > tonumber(ARGV[4]) or count3 > tonumber(ARGV[6]) then return 0 end
return 1
"""


def _limitar_consulta_cpf(id_integracao, cpf):
    """Redis e obrigatorio: sem rate limiting nao ha consulta de CPFs de terceiros."""
    url = os.getenv('ARKHE_WHATSAPP_REDIS_URL') or os.getenv('REDIS_URL')
    if not url:
        return None
    cliente = None
    try:
        cliente = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        cliente_hash = hashlib.sha256(str(id_integracao).encode('utf-8')).hexdigest()
        cpf_hash = hashlib.sha256(cpf.encode('ascii')).hexdigest()
        permitido = cliente.eval(
            _LUA_LIMITE_CPF, 3,
            'arkhe:cpf:integracao:' + cliente_hash,
            'arkhe:cpf:documento:' + cpf_hash,
            'arkhe:cpf:integracao:dia:' + cliente_hash,
            60, 10, 86400, 20, 86400, 100,
        )
        return bool(permitido)
    except (redis.RedisError, OSError, ValueError):
        current_app.logger.warning('Rate limiter da consulta CPF indisponivel')
        return None
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except (redis.RedisError, OSError):
                pass


@app.route('/api/v1/contas/verificar-cpf', methods=['POST'])
def api_verificar_cpf():
    contexto, erro = autenticar_integracao()
    if erro:
        return erro

    # A autenticacao convencional ja valida Client ID, Secret e status ATIVO.
    dados = request.get_json(silent=True)
    cpf_informado = dados.get('cpf') if isinstance(dados, dict) else None
    if not isinstance(cpf_informado, str) or len(cpf_informado) > 32 or not validar_cpf(cpf_informado):
        return jsonify({'mensagem': 'CPF invalido'}), 400
    cpf = normalizar_cpf(cpf_informado)

    permitido = _limitar_consulta_cpf(contexto['id_integracao'], cpf)
    if permitido is None:
        return jsonify({'mensagem': 'Consulta temporariamente indisponivel'}), 503
    if not permitido:
        return jsonify({'mensagem': 'Limite de consultas excedido'}), 429

    cursor = None
    try:
        cursor = con.cursor()
        cursor.execute(
            """SELECT FIRST 1 1 FROM USUARIO U
               INNER JOIN CONTA C ON C.ID_USUARIO = U.ID_USUARIO
               WHERE REPLACE(REPLACE(TRIM(U.CPF), '.', ''), '-', '') = ?""",
            (cpf,),
        )
        existe = cursor.fetchone() is not None
        # Sem CPF no payload, na URL ou nos logs de erro. Sem dados de terceiros.
        resposta = jsonify({'possui_conta': existe})
        resposta.headers['Cache-Control'] = 'no-store'
        return resposta, 200
    except Exception:
        current_app.logger.exception('Falha na consulta restrita de existencia de conta')
        return jsonify({'mensagem': 'Consulta indisponivel'}), 503
    finally:
        if cursor:
            cursor.close()
