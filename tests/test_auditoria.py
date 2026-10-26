"""Testes rápidos da autorização e validação da Central de Auditoria."""
import unittest
from unittest.mock import patch

from flask import Flask

import auditoria


class TestAuditoriaAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('auditoria_admin_test')
        auditoria.registrar_rotas(cls.app)
        # A persistência dos hooks é coberta pela suíte de Firebirds descartáveis.
        cls.app.before_request_funcs[None] = []
        cls.app.after_request_funcs[None] = []
        cls.client = cls.app.test_client()

    def test_feed_stream_status_e_detalhe_negam_nao_administrador(self):
        with patch.object(auditoria, 'descobre_id_usuario', return_value=44), \
             patch.object(auditoria, 'usuario_eh_admin_bancario', return_value=False):
            respostas = [
                self.client.get('/api/v1/admin/auditoria'),
                self.client.get('/api/v1/admin/auditoria/stream'),
                self.client.get('/api/v1/admin/auditoria/status'),
                self.client.get('/api/v1/admin/auditoria/10'),
                self.client.get('/api/v1/admin/auditoria?simples=1'),
                self.client.get('/api/v1/admin/auditoria?simples=1&historico=1'),
                self.client.get('/api/v1/admin/auditoria/10?simples=1'),
            ]
        self.assertEqual([r.status_code for r in respostas], [403] * len(respostas))

    def test_feed_exige_autenticacao(self):
        with patch.object(auditoria, 'descobre_id_usuario', return_value=None):
            for query in ('','?simples=1','?simples=1&historico=1'):
                self.assertEqual(self.client.get('/api/v1/admin/auditoria'+query).status_code,401)

    def test_filtros_simples_rejeitam_data_e_registro_invalidos(self):
        with patch.object(auditoria,'_admin',return_value=(12,None)):
            for query in ('&id_registro=abc','&data_inicio=ontem','&data_inicio=2026-10-26&data_fim=2026-10-25'):
                self.assertEqual(self.client.get('/api/v1/admin/auditoria?simples=1'+query).status_code,400)

    def test_filtros_rejeitam_identificador_data_e_intervalo_invalidos(self):
        with patch.object(auditoria, '_admin', return_value=(12, None)):
            for query in (
                '?usuario_id=abc',
                '?data_inicio=ontem',
                '?data_inicio=2026-10-26&data_fim=2026-10-25',
                '?valor_min=20&valor_max=10',
            ):
                resposta = self.client.get('/api/v1/admin/auditoria' + query)
                self.assertEqual(resposta.status_code, 400, query)

    def test_mascaramento_de_email_e_snapshot_invalido(self):
        self.assertEqual(auditoria._mascarar_email('lucas@example.com'), 'l***@example.com')
        self.assertEqual(auditoria._mascarar_email('sem-email'), None)
        self.assertEqual(auditoria._json_data('{"status":1}'), {'status': 1})
        self.assertEqual(auditoria._json_data(None), None)


if __name__ == '__main__':
    unittest.main()
