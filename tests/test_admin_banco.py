"""Verificacoes de autorizacao e validacao para o painel administrativo."""
import unittest
from unittest.mock import patch

from flask import Flask

import admin_banco


class TestAdminBanco(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('admin_banco_test')
        admin_banco.registrar_rotas(cls.app)
        cls.client = cls.app.test_client()

    def test_rotas_administrativas_negam_usuario_autenticado_sem_permissao(self):
        with patch.object(admin_banco, 'descobre_id_usuario', return_value=99), \
             patch.object(admin_banco, 'usuario_eh_admin_bancario', return_value=False):
            respostas = [
                self.client.get('/api/v1/admin/banco/permissao'),
                self.client.get('/api/v1/admin/banco/resumo'),
                self.client.get('/api/v1/admin/banco/usuarios?q=lucas'),
                self.client.get('/api/v1/admin/banco/usuarios/12'),
                self.client.get('/api/v1/admin/banco/operacoes'),
            ]
        self.assertEqual([resposta.status_code for resposta in respostas], [403] * len(respostas))

    def test_rota_administrativa_exige_autenticacao(self):
        with patch.object(admin_banco, 'descobre_id_usuario', return_value=None):
            resposta = self.client.get('/api/v1/admin/banco/resumo')
        self.assertEqual(resposta.status_code, 401)

    def test_permissao_reutiliza_allowlist_do_admin_bancario(self):
        with patch.object(admin_banco, 'descobre_id_usuario', return_value=12), \
             patch.object(admin_banco, 'usuario_eh_admin_bancario', return_value=True):
            resposta = self.client.get('/api/v1/admin/banco/permissao')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json['autorizado'])
        self.assertEqual(resposta.json['id_usuario'], 12)

    def test_filtros_validam_datas_conta_tipo_e_status(self):
        with self.app.test_request_context('/?conta_id=9&data_inicio=2026-10-01&data_fim=2026-10-25&tipo=BOLETO&status=PENDENTE&limite=25'):
            self.assertEqual(admin_banco._filtros_operacoes(), (9, '2026-10-01', '2026-10-25', 'BOLETO', 'PENDENTE', 25))
        with self.app.test_request_context('/?data_inicio=2026-10-26&data_fim=2026-10-25'):
            with self.assertRaisesRegex(ValueError, 'data inicial'):
                admin_banco._filtros_operacoes()
        with self.app.test_request_context('/?tipo=DROP_TABLE'):
            with self.assertRaisesRegex(ValueError, 'Tipo de operacao'):
                admin_banco._filtros_operacoes()


if __name__ == '__main__':
    unittest.main()
