import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('arkhe_api_common_rate_test', ROOT / 'api' / 'common.py')
common = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = common
SPEC.loader.exec_module(common)


class RedisContadorFake:
    def __init__(self):
        self.contagens = {}

    def eval(self, script, quantidade_chaves, chave, janela):
        self.contagens[chave] = self.contagens.get(chave, 0) + 1
        return self.contagens[chave]


class CursorIntegracaoFake:
    def execute(self, _sql, _params=()):
        pass

    def fetchone(self):
        return (7, 2, 'hash-teste', 1)

    def close(self):
        pass


class ConexaoIntegracaoFake:
    def cursor(self):
        return CursorIntegracaoFake()

    def commit(self):
        pass

    def rollback(self):
        pass


class RateLimitApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.redis_fake = RedisContadorFake()

    def limitar(self, id_integracao, *, testing=False):
        self.app.config['TESTING'] = testing
        with self.app.app_context():
            return common.limitar_api_integracao(id_integracao)

    def test_mesma_integracao_recebe_429_apos_a_cota(self):
        with patch.dict(os.environ, {
            'REDIS_URL': 'redis://redis-teste/0',
            'ARKHE_API_RATE_LIMIT': '2',
            'ARKHE_API_RATE_WINDOW_SECONDS': '60',
        }), patch.object(common.redis.Redis, 'from_url', return_value=self.redis_fake):
            self.assertIsNone(self.limitar(7))
            self.assertIsNone(self.limitar(7))
            resposta = self.limitar(7)

        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(resposta.headers['Retry-After'], '60')
        self.assertEqual(resposta.get_json()['codigo'], 'RATE_LIMIT_EXCEEDED')

    def test_integracoes_possuem_cotas_independentes(self):
        with patch.dict(os.environ, {
            'REDIS_URL': 'redis://redis-teste/0',
            'ARKHE_API_RATE_LIMIT': '1',
            'ARKHE_API_RATE_WINDOW_SECONDS': '30',
        }), patch.object(common.redis.Redis, 'from_url', return_value=self.redis_fake):
            self.assertIsNone(self.limitar(7))
            self.assertIsNone(self.limitar(8))
            resposta = self.limitar(7)

        self.assertEqual(resposta.status_code, 429)

    def test_autenticacao_api_aplica_a_cota_depois_da_credencial(self):
        self.app.config['TESTING'] = False
        with patch.dict(os.environ, {
            'REDIS_URL': 'redis://redis-teste/0',
            'ARKHE_API_RATE_LIMIT': '1',
            'ARKHE_API_RATE_WINDOW_SECONDS': '60',
        }), patch.object(common.redis.Redis, 'from_url', return_value=self.redis_fake), \
             patch.object(common, 'con', ConexaoIntegracaoFake()), \
             patch.object(common, 'verificar_pin', return_value=True):
            with self.app.test_request_context(
                '/api/v1/saldo', headers={'X-Client-ID': 'cliente', 'X-Client-Secret': 'segredo'}
            ):
                integracao, erro = common.autenticar_integracao()
            with self.app.test_request_context(
                '/api/v1/saldo', headers={'X-Client-ID': 'cliente', 'X-Client-Secret': 'segredo'}
            ):
                bloqueada, resposta = common.autenticar_integracao()

        self.assertEqual(integracao['id_integracao'], 7)
        self.assertIsNone(erro)
        self.assertIsNone(bloqueada)
        self.assertEqual(resposta.status_code, 429)

    def test_redis_indisponivel_falha_fechado_com_503(self):
        with patch.dict(os.environ, {
            'REDIS_URL': 'redis://redis-teste/0',
            'ARKHE_API_RATE_LIMIT': '10',
            'ARKHE_API_RATE_WINDOW_SECONDS': '60',
        }), patch.object(common.redis.Redis, 'from_url', side_effect=OSError('redis offline')):
            resposta = self.limitar(7)

        self.assertEqual(resposta[1], 503)

    def test_configuracao_invalida_e_recusada(self):
        with patch.dict(os.environ, {
            'REDIS_URL': 'redis://redis-teste/0',
            'ARKHE_API_RATE_LIMIT': '0',
            'ARKHE_API_RATE_WINDOW_SECONDS': '60',
        }), patch.object(common.redis.Redis, 'from_url', return_value=self.redis_fake):
            resposta = self.limitar(7)

        self.assertEqual(resposta[1], 503)

    def test_modo_testing_nao_precisa_de_redis(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(common.redis.Redis, 'from_url') as factory:
            self.assertIsNone(self.limitar(7, testing=True))
        factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
