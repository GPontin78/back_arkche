"""Saldo e identidade da mesma conta; Firebird e autenticacao simulados."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


class TestSaldoConta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('saldo_conta_teste')
        pacote = types.ModuleType('api_saldo_teste')
        pacote.__path__ = [str(Path(__file__).resolve().parents[1] / 'api')]
        comum = types.ModuleType('api_saldo_teste.common')
        comum.autenticar_requisicao = lambda **kwargs: ({'id_conta': 10}, None)
        comum.nome_cliente_api = lambda nome, fantasia, razao, tipo: (fantasia or razao or nome) if tipo == 1 else nome
        comum.obter_periodo = lambda: (None, None, None)
        substitutos = {
            'main': types.SimpleNamespace(app=cls.app),
            'banco': types.SimpleNamespace(con=None),
            'funcao': types.SimpleNamespace(calcular_saldo=lambda *_: None, calcular_limite_cartao=lambda *_: None,
                                            descobre_id_conta=lambda: None),
            'pdf': types.SimpleNamespace(gerar_boleto_pdf=lambda *_: None),
            'api_saldo_teste': pacote, 'api_saldo_teste.common': comum,
        }
        with patch.dict(sys.modules, substitutos):
            spec = importlib.util.spec_from_file_location('api_saldo_teste.get', Path(pacote.__path__[0]) / 'get.py')
            cls.modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.modulo)

    def test_nome_id_e_saldo_da_conta_autorizada(self):
        consultas = []
        class Cursor:
            def execute(self, sql, parametros):
                consultas.append(parametros)
                self.conta = parametros[0]
            def fetchone(self):
                return (0, 'Titular dez', None, None, '0010') if self.conta == 10 else (1, 'Titular vinte', 'Empresa vinte', None, '0020')
            def close(self):
                pass
        for id_conta, valor, nome in ((10, 123.45, 'Titular dez'), (20, -789.01, 'Empresa vinte')):
            with self.subTest(id_conta=id_conta), \
                 patch.object(self.modulo, 'con', types.SimpleNamespace(cursor=Cursor)), \
                 patch.object(self.modulo, 'autenticar_requisicao', return_value=({'id_conta': id_conta}, None)), \
                 patch.object(self.modulo, 'calcular_saldo', return_value=valor) as saldo:
                resposta = self.app.test_client().get('/api/v1/saldo?nome=Lais&id_conta=99')
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.json['id_conta'], id_conta)
                self.assertEqual(resposta.json['nome_conta'], nome)
                self.assertEqual(resposta.json['saldo'], valor)
                self.assertEqual(consultas[-1], (id_conta,))
                saldo.assert_called_once_with(id_conta)

    def test_indisponibilidade_nao_vira_saldo_zero(self):
        with patch.object(self.modulo, 'calcular_saldo', return_value=None):
            resposta = self.app.test_client().get('/api/v1/saldo')
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn('saldo', resposta.json)

    def test_sem_autorizacao_nao_consulta_saldo(self):
        with patch.object(self.modulo, 'autenticar_requisicao', return_value=(None, ({'mensagem': 'Sem acesso'}, 403))), \
             patch.object(self.modulo, 'calcular_saldo') as saldo:
            resposta = self.app.test_client().get('/api/v1/saldo')
        self.assertEqual(resposta.status_code, 403)
        saldo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
