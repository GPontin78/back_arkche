"""Testes isolados do bloqueio temporario de login, sem Redis ou Firebird reais."""
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
CPF = '52998224725'


class RedisFalso:
    def __init__(self):
        self.dados = {}
        self.expiracoes = {}

    def exists(self, chave):
        return int(chave in self.dados)

    def incr(self, chave):
        self.dados[chave] = int(self.dados.get(chave, 0)) + 1
        return self.dados[chave]

    def expire(self, chave, segundos):
        self.expiracoes[chave] = segundos
        return True

    def set(self, chave, valor, ex=None):
        self.dados[chave] = valor
        self.expiracoes[chave] = ex
        return True

    def delete(self, *chaves):
        removidas = 0
        for chave in chaves:
            removidas += int(chave in self.dados)
            self.dados.pop(chave, None)
            self.expiracoes.pop(chave, None)
        return removidas

    def eval(self, _script, _quantidade_chaves, tentativas_chave, bloqueio_chave,
             janela, maximo, duracao_bloqueio):
        tentativas = self.incr(tentativas_chave)
        if tentativas == 1:
            self.expire(tentativas_chave, int(janela))
        if tentativas >= int(maximo):
            self.set(bloqueio_chave, '1', ex=int(duracao_bloqueio))
            self.delete(tentativas_chave)
            return 1
        return 0


class LoginBloqueioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('login_bloqueio_testes')
        cls.app.config['COOKIE_SECURE'] = False
        fake_main = types.ModuleType('main')
        fake_main.app = cls.app
        fake_banco = types.ModuleType('banco')
        fake_banco.con = object()
        fake_funcao = types.ModuleType('funcao')
        nomes = (
            'gerar_token', 'gerar_token_usuario', 'descobre_id_usuario',
            'descobre_id_conta', 'criptografar_pin', 'verificar_pin',
            'verificar_pin_usuario', 'usuario_pode_acessar_conta',
            'listar_contas_usuario', 'dados_usuario', 'dados_conta',
            'enviando_email', 'montar_email_arkhe', 'data_atual',
        )
        for nome in nomes:
            setattr(fake_funcao, nome, lambda *args, **kwargs: None)

        cls.modulo = types.ModuleType('conta_login_bloqueio_testes')
        cls.modulo.__file__ = str(ROOT / 'conta.py')
        spec = importlib.util.spec_from_file_location(
            cls.modulo.__name__, ROOT / 'conta.py'
        )
        with patch.dict(sys.modules, {
            'main': fake_main,
            'banco': fake_banco,
            'funcao': fake_funcao,
        }):
            cls.modulo = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = cls.modulo
            spec.loader.exec_module(cls.modulo)

    def setUp(self):
        self.redis = RedisFalso()
        self.patch_redis = patch.object(
            self.modulo, '_redis_login', return_value=self.redis
        )
        self.patch_redis.start()
        self.addCleanup(self.patch_redis.stop)
        self.patch_env = patch.dict(os.environ, {
            'ARKHE_LOGIN_MAX_TENTATIVAS': '5',
            'ARKHE_LOGIN_JANELA_SEGUNDOS': '900',
            'ARKHE_LOGIN_BLOQUEIO_SEGUNDOS': '900',
        })
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def test_bloqueia_apos_cinco_falhas_e_normaliza_cpf(self):
        for _ in range(4):
            self.assertFalse(self.modulo.registrar_falha_login(CPF))

        self.assertTrue(self.modulo.registrar_falha_login('529.982.247-25'))
        self.assertTrue(self.modulo.login_temporariamente_bloqueado(CPF))
        self.assertEqual(list(self.redis.dados.values()), ['1'])
        self.assertEqual(list(self.redis.expiracoes.values()), [900])
        self.assertNotIn(CPF, next(iter(self.redis.dados)))

    def test_login_e_login_usuario_recusam_conta_bloqueada(self):
        for rota, payload in (
            (self.modulo.login, {'cpf': CPF, 'pin': '111111', 'tipo_conta': 0}),
            (self.modulo.login_usuario, {'cpf': CPF, 'pin': '111111'}),
        ):
            with self.app.test_request_context('/', method='POST', json=payload):
                with patch.object(self.modulo, 'login_temporariamente_bloqueado', return_value=True):
                    resposta, status = rota()
            self.assertEqual(status, 429)
            self.assertIn('temporariamente', resposta.get_json()['mensagem'])

    def test_login_valido_limpa_contador_e_bloqueio(self):
        self.modulo.registrar_falha_login(CPF)
        tentativas, bloqueio = self.modulo._chaves_bloqueio_login(CPF)
        self.redis.set(bloqueio, '1', ex=900)

        self.modulo.limpar_falhas_login(CPF)

        self.assertFalse(self.modulo.login_temporariamente_bloqueado(CPF))
        self.assertNotIn(tentativas, self.redis.dados)


if __name__ == '__main__':
    unittest.main()
