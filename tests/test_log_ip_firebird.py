"""IP informado pelo componente local, em dois Firebirds descartáveis."""
import unittest
from unittest.mock import patch
from flask import Flask
import auditoria
from tests import test_log_modelo_firebird as modelo
from scripts.aplicar_log_ip import aplicar_ip, conferir_ip
from scripts.aplicar_log_simples import CAMPOS_LOG, conferir, ip_ativo


class LogIPFirebird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modelo.LogModeloFirebird.setUpClass()
        for nome in ('con','audit','schema','principal','arquivo','pasta','pasta_local','senha','app'):
            setattr(cls,nome,getattr(modelo.LogModeloFirebird,nome))
        cls.antes,_ = conferir(cls.con)
        cls.audit.execute_immediate('ALTER TABLE LOG DROP IP')
        cls.audit.cursor().execute("INSERT INTO LOG (ID_LOG,TABELA,ACAO,VALOR_NOVO) VALUES (17000,'TESTE','ANTIGO','Preservado')")
        cls.audit.commit()
        aplicar_ip(cls.con,cls.audit)

    @classmethod
    def tearDownClass(cls):
        modelo.LogModeloFirebird.tearDownClass()

    setUp = modelo.LogModeloFirebird.setUp
    tearDown = modelo.LogModeloFirebird.tearDown
    sql = modelo.LogModeloFirebird.sql

    def aplicativo(self):
        app = Flask('log_ip_teste')
        app.config.update(self.app.config)
        app.config.update(SECRET_KEY='segredo-apenas-do-teste',FRONTEND_URL='https://banco.test')
        auditoria.registrar_rotas(app)

        @app.post('/api/v1/teste-ip/<int:registro>')
        def executar(registro):
            self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (?,9,25,CURRENT_TIMESTAMP)',(registro,))
            self.con.commit()
            auditoria.registrar_log(44,'IA','TESTE_IP',registro,valor_novo='Operação fictícia')
            return {'id':registro}
        return app

    def test_migracao_acrescenta_nono_campo_e_preserva_triggers_financeiras_e_historico(self):
        self.assertTrue(conferir_ip(self.audit))
        campos = self.sql("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME='LOG' ORDER BY RDB$FIELD_POSITION",banco=self.audit)
        self.assertEqual([r[0] for r in campos],CAMPOS_LOG+['IP'])
        self.assertEqual(self.sql('SELECT VALOR_NOVO,IP FROM LOG WHERE ID_LOG=17000',banco=self.audit),[('Preservado',None)])
        atuais,_ = conferir(self.con)
        self.assertTrue(ip_ativo(atuais))
        self.assertEqual(len(atuais),35)
        self.assertEqual([r for r in atuais if not r[0].endswith('_LOG')],[r for r in self.antes if not r[0].endswith('_LOG')])
        self.assertFalse(aplicar_ip(self.con,self.audit))

    def test_ip_do_componente_chega_a_ia_api_e_trigger(self):
        app = self.aplicativo()
        with patch.object(auditoria,'con',self.con), \
             patch.object(auditoria,'descobre_id_usuario',return_value=44), \
             patch.object(auditoria,'descobre_id_conta',return_value=9), \
             patch.object(auditoria,'_redis',side_effect=RuntimeError('Redis dispensável')):
            cliente = app.test_client()
            resposta = cliente.post('/ip_computador',json={'ip':'192.168.10.27'},headers={'Origin':'https://banco.test'})
            self.assertEqual(resposta.status_code,200)
            self.assertIn('HttpOnly',resposta.headers['Set-Cookie'])
            self.assertEqual(cliente.post('/api/v1/teste-ip/17101',environ_overrides={'REMOTE_ADDR':'198.51.100.10'}).status_code,200)
        self.audit.rollback()
        linhas = self.sql("SELECT TABELA,IP FROM LOG WHERE ID_REGISTRO=17101 OR (TABELA='API' AND VALOR_NOVO CONTAINING 'REGISTRO=17101')",banco=self.audit)
        self.assertEqual({r[0] for r in linhas},{'IA','API','MOVIMENTACAO'})
        self.assertEqual({r[1] for r in linhas},{'192.168.10.27'})

    def test_sem_cookie_assinado_nao_usa_header_publico_servidor_ou_ip_anterior(self):
        app = self.aplicativo()
        with patch.object(auditoria,'con',self.con), \
             patch.object(auditoria,'descobre_id_usuario',return_value=44), \
             patch.object(auditoria,'descobre_id_conta',return_value=9), \
             patch.object(auditoria,'_redis',side_effect=RuntimeError('Redis dispensável')):
            primeiro = app.test_client()
            primeiro.post('/ip_computador',json={'ip':'192.168.10.28'},headers={'Origin':'https://banco.test'})
            primeiro.post('/api/v1/teste-ip/17102')
            outro = app.test_client()
            outro.set_cookie('session','cookie-alterado')
            resposta = outro.post('/api/v1/teste-ip/17103',headers={'X-Forwarded-For':'203.0.113.10','X-IP-Computador':'192.168.10.99'},environ_overrides={'REMOTE_ADDR':'198.51.100.10'})
            self.assertEqual(resposta.status_code,200)
            self.assertEqual(self.sql("SELECT RDB$GET_CONTEXT('USER_SESSION','ARKHE_IP_LOG') FROM RDB$DATABASE"),[(None,)])
        self.audit.rollback()
        self.assertEqual(self.sql('SELECT IP FROM LOG WHERE ID_REGISTRO=17103',banco=self.audit),[(None,),(None,)])

    def test_origem_e_ip_invalidos_sao_recusados(self):
        app = self.aplicativo()
        app.before_request_funcs[None] = []
        app.after_request_funcs[None] = []
        cliente = app.test_client()
        self.assertEqual(cliente.post('/ip_computador',json={'ip':'192.168.1.2'},headers={'Origin':'https://outro.test'}).status_code,403)
        for dados in ({'ip':'abc'},{'ip':'127.0.0.1'},{'ip':None},['192.168.1.2'],{'ip':'0.0.0.0'}):
            self.assertEqual(cliente.post('/ip_computador',json=dados,headers={'Origin':'https://banco.test'}).status_code,400)
        with cliente.session_transaction() as sessao:
            self.assertNotIn('ip_computador',sessao)

    def test_ipv6_e_consulta_de_historico_com_ip_nulo(self):
        app = self.aplicativo()
        app.before_request_funcs[None] = []
        app.after_request_funcs[None] = []
        cliente = app.test_client()
        self.assertEqual(cliente.post('/ip_computador',json={'ip':'fd12:3456:789a::1'},headers={'Origin':'https://banco.test'}).status_code,200)
        with cliente.session_transaction() as sessao:
            self.assertEqual(sessao['ip_computador'],'fd12:3456:789a::1')
        with patch.object(auditoria,'_admin',return_value=(44,None)):
            for query in ('?simples=1&historico=1','?simples=1&tabela=TESTE'):
                resposta = cliente.get('/api/v1/admin/auditoria'+query)
                self.assertEqual(resposta.status_code,200)
                self.assertTrue(all(r['ip'] is None for r in resposta.get_json()['eventos']))

    def test_ip_da_trigger_respeita_rollback(self):
        self.sql("SELECT RDB$SET_CONTEXT('USER_SESSION','ARKHE_IP_LOG','192.168.10.30') FROM RDB$DATABASE")
        self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (17104,9,25,CURRENT_TIMESTAMP)')
        self.con.rollback()
        self.audit.rollback()
        self.assertFalse(self.sql('SELECT ID_LOG FROM LOG WHERE ID_REGISTRO=17104',banco=self.audit))


if __name__ == '__main__':
    unittest.main()
