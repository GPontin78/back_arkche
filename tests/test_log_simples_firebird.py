"""Oito campos, EDS, histórico e identidade em dois bancos descartáveis."""
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, current_app, request
import auditoria
from tests import test_log_externo_firebird as legado
from scripts.aplicar_log_simples import CAMPOS_LOG, aplicar, conferir, conferir_log, salvar_rollback
from scripts.aplicar_log_externo import comandos_sql


class LogSimplesFirebird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        legado.LogExternoFirebird.setUpClass()
        for nome in ('con','audit','schema','principal','arquivo','pasta','pasta_local','senha','app'):
            setattr(cls,nome,getattr(legado.LogExternoFirebird,nome))
        cls.antes,cls.origem_antes = conferir(cls.con)
        aplicar(cls.con,cls.audit)

    @classmethod
    def tearDownClass(cls):
        legado.LogExternoFirebird.tearDownClass()

    def setUp(self):
        legado.LogExternoFirebird.setUp(self)
        self.sql("SELECT RDB$SET_CONTEXT('USER_SESSION','ARKHE_USUARIO_LOG',NULL) FROM RDB$DATABASE")

    tearDown = legado.LogExternoFirebird.tearDown
    sql = legado.LogExternoFirebird.sql

    def eventos(self,tabela,registro):
        self.audit.rollback()
        return self.sql('SELECT ACAO,VALOR_ANTERIOR,VALOR_NOVO FROM LOG WHERE TABELA=? AND ID_REGISTRO IS NOT DISTINCT FROM ? ORDER BY ID_LOG',(tabela,registro),self.audit)

    def test_exatamente_oito_campos_e_historico_original_intacto(self):
        self.assertTrue(conferir_log(self.audit))
        campos = self.sql("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME='LOG' ORDER BY RDB$FIELD_POSITION",banco=self.audit)
        self.assertEqual([r[0] for r in campos],CAMPOS_LOG)
        self.assertEqual(len(conferir(self.con)[0]),13)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM AUDITORIA_EVENTO WHERE EVENTO='HISTORICO'",banco=self.audit),[(1,)])
        self.assertFalse(aplicar(self.con,self.audit))

    def test_insert_update_delete_diretos_e_somente_campos_alterados(self):
        self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,ID_RECEBEDOR,VALOR,DATA_MOVIMENTACAO) VALUES (10001,9,10,25,CURRENT_TIMESTAMP)')
        self.con.commit()
        self.sql('UPDATE MOVIMENTACAO SET VALOR=30 WHERE ID_MOVIMENTACAO=10001')
        self.con.commit()
        self.sql('DELETE FROM MOVIMENTACAO WHERE ID_MOVIMENTACAO=10001')
        self.con.commit()
        linhas = self.eventos('MOVIMENTACAO',10001)
        self.assertEqual([r[0] for r in linhas],['INSERT','UPDATE','DELETE'])
        self.assertIsNone(linhas[0][1])
        self.assertEqual(json.loads(linhas[1][1]),{'valor':25})
        self.assertEqual(json.loads(linhas[1][2]),{'valor':30})
        self.assertIsNone(linhas[2][2])
        self.assertEqual(self.sql("SELECT DISTINCT USUARIO FROM LOG WHERE TABELA='MOVIMENTACAO' AND ID_REGISTRO=10001",banco=self.audit),[('44',)])

    def test_tres_operacoes_em_cada_tabela_principal(self):
        legado.LogExternoFirebird.test_todas_as_tabelas_tem_log_de_insert_update_delete_com_json_valido(self)

    def test_rollback_da_operacao_remove_log_externo(self):
        self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (10002,9,25,CURRENT_TIMESTAMP)')
        self.con.rollback()
        self.assertFalse(self.eventos('MOVIMENTACAO',10002))

    def test_rollback_da_migracao_preserva_ambos_os_historicos(self):
        self.sql("INSERT INTO LOG (TABELA,ACAO,ID_REGISTRO) VALUES ('TESTE','PRESERVADO',10003)",banco=self.audit)
        self.audit.commit()
        try:
            with tempfile.TemporaryDirectory(prefix='arkhe-log-teste-oito-') as pasta:
                salvar_rollback(Path(pasta),self.antes,self.origem_antes)
                for comando in comandos_sql((Path(pasta)/'rollback-log-simples.sql').read_text(encoding='utf-8')):
                    self.sql(comando)
                self.con.commit()
                self.assertFalse(conferir(self.con)[1].endswith('-simples'))
                self.assertTrue(self.eventos('TESTE',10003))
        finally:
            self.con.rollback()
            aplicar(self.con,self.audit)

    def test_api_identifica_integracao_validada_sem_copiar_credenciais(self):
        # Carrega apenas o helper, sem iniciar os schedulers do pacote api.
        spec = importlib.util.spec_from_file_location('common_log_teste',Path(__file__).resolve().parents[1]/'api/common.py')
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        self.sql("INSERT INTO INTEGRACAO_API (ID_INTEGRACAO,ID_CONTA,NOME,CLIENT_ID,CLIENT_SECRET_HASH,ATIVO) VALUES (10004,9,'Integracao ficticia','cliente-teste','hash-teste',1)")
        self.con.commit()
        app = Flask('log_api_oito')
        app.config.update(self.app.config)
        app.after_request(auditoria._registrar_resposta_relevante)

        @app.get('/api/v1/saldo-teste')
        def consultar():
            contexto,erro = common.autenticar_integracao()
            if erro:
                return erro
            self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (10004,9,25,CURRENT_TIMESTAMP)')
            self.con.commit()
            return {'conta':contexto['id_conta']}

        with patch.object(common,'con',self.con),patch.object(common,'verificar_pin',return_value=True), \
             patch.object(auditoria,'descobre_id_usuario',return_value=None),patch.object(auditoria,'descobre_id_conta',return_value=None):
            resposta = app.test_client().get('/api/v1/saldo-teste?segredo=nao-copiar',headers={'X-Client-ID':'cliente-teste','X-Client-Secret':'segredo-nao-copiar'})
        self.assertEqual(resposta.status_code,200)
        self.audit.rollback()
        linhas = self.sql("SELECT USUARIO,TABELA,ACAO,VALOR_NOVO FROM LOG WHERE USUARIO='INTEGRACAO_API:10004'",banco=self.audit)
        self.assertEqual({r[1] for r in linhas},{'API','MOVIMENTACAO'})
        registro_api = next(r for r in linhas if r[1]=='API')
        self.assertIn('METODO=GET; STATUS_HTTP=200',registro_api[3])
        self.assertFalse(registro_api[3].startswith('{'))
        self.assertNotIn('segredo-nao-copiar',str(linhas))
        self.assertNotIn('segredo=nao-copiar',str(linhas))

    def test_ia_grava_em_log_sem_conteudo_privado_e_sem_mensagens_parciais(self):
        from tests.test_assistente_mauro_intencoes import carregar_servico
        servico = carregar_servico()
        app = Flask('log_ia_oito')
        app.config.update(self.app.config)
        servico.registrar_rotas(app)
        app.after_request(auditoria._registrar_resposta_relevante)
        contexto = {'id_usuario':44,'id_conta':9,'tipo_conta':'PF','nome_conta':'Teste','conta_final':'0009'}
        original = auditoria._inserir_evento_simples

        def falhar(cursor,evento,resultado,*args):
            if evento == 'MAURO_CONSULTA' and resultado == 'SUCESSO':
                raise RuntimeError('Falha simulada no LOG')
            return original(cursor,evento,resultado,*args)

        with patch.object(servico,'con',self.con),patch.object(servico,'request',request),patch.object(servico,'current_app',current_app), \
             patch.object(servico,'registrar_evento_flask',auditoria.registrar_evento_flask), \
             patch.object(servico,'_contexto_atual',return_value=(contexto,None)),patch.object(servico,'_limitar_requisicoes',return_value=True), \
             patch.object(servico,'_responder_gemini',return_value=('Posso ajudar com sua conta.',None)), \
             patch.object(auditoria,'descobre_id_usuario',return_value=44),patch.object(auditoria,'descobre_id_conta',return_value=9), \
             patch.object(auditoria,'_redis',side_effect=RuntimeError('Redis dispensável')):
            cliente = app.test_client()
            conversa = cliente.post('/api/v1/assistente/conversas').get_json()['conversa']['id']
            url = f'/api/v1/assistente/conversas/{conversa}/mensagens'
            self.assertEqual(cliente.post(url,json={'mensagem':'Qual é meu saldo privado?'}).status_code,200)
            with patch.object(auditoria,'_inserir_evento_simples',side_effect=falhar),self.assertLogs(app.logger,level='ERROR'):
                self.assertEqual(cliente.post(url,json={'mensagem':'Meu saldo privado'}).status_code,503)
            self.assertEqual(self.sql('SELECT COUNT(*) FROM MAURO_MENSAGEM WHERE ID_CONVERSA=?',(conversa,))[0][0],2)
        self.audit.rollback()
        linhas = self.sql("SELECT USUARIO,ACAO,VALOR_NOVO FROM LOG WHERE TABELA='IA'",banco=self.audit)
        self.assertTrue(any(r[1]=='MAURO_CONSULTA / SUCESSO' for r in linhas))
        self.assertTrue(any(r[1]=='MAURO_CONSULTA / FALHA' for r in linhas))
        self.assertTrue(any('INTENCAO=SALDO' in r[2] for r in linhas))
        self.assertTrue(all(not r[2].startswith('{') for r in linhas))
        self.assertNotIn('saldo privado',str(linhas))

    def test_leitura_dos_oito_campos_e_acesso_ao_historico(self):
        self.sql("INSERT INTO LOG (USUARIO,TABELA,ACAO,ID_REGISTRO,VALOR_NOVO) VALUES ('44','TESTE','CONSULTA',10005,'{}')",banco=self.audit)
        self.audit.commit()
        with patch.object(auditoria,'_admin',return_value=(44,None)):
            with self.app.test_request_context('/api/v1/admin/auditoria?simples=1&tabela=TESTE'):
                resposta,status = auditoria.listar_eventos_admin()
                self.assertEqual(status,200)
                linha = resposta.get_json()['eventos'][0]
                self.assertEqual(set(linha),{n.lower() for n in CAMPOS_LOG})
            with self.app.test_request_context('/api/v1/admin/auditoria?simples=1&historico=1'):
                resposta,status = auditoria.listar_eventos_admin()
                self.assertEqual(status,200)
                self.assertTrue(any(r['acao'].startswith('HISTORICO') for r in resposta.get_json()['eventos']))


if __name__ == '__main__':
    unittest.main()
