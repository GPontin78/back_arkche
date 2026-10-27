"""Modelo solicitado: variáveis, parâmetros posicionais e valores com separador."""
import datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fdb
import auditoria
from tests import test_log_tres_firebird as base
from scripts.aplicar_log_externo import comandos_sql
from scripts.aplicar_log_simples import aplicar_modelo,conferir,conferir_log,modelo_ativo,salvar_rollback
from scripts.gerar_migracao_log import CAMPOS,TABELAS_PRINCIPAIS


class LogModeloFirebird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.LogTresFirebird.setUpClass()
        for nome in ('con','audit','schema','principal','arquivo','pasta','pasta_local','senha','app'):
            setattr(cls,nome,getattr(base.LogTresFirebird,nome))
        cls.antes,cls.origem = conferir(cls.con)
        aplicar_modelo(cls.con,cls.audit)

    @classmethod
    def tearDownClass(cls):
        base.LogTresFirebird.tearDownClass()

    setUp = base.LogTresFirebird.setUp
    tearDown = base.LogTresFirebird.tearDown
    sql = base.LogTresFirebird.sql
    eventos = base.LogTresFirebird.eventos
    test_texto_e_json_antigo_na_tela = base.LogTresFirebird.test_texto_e_json_antigo_na_tela
    test_api_identifica_integracao_sem_credenciais = base.LogTresFirebird.test_api_identifica_integracao_sem_credenciais
    test_ia_grava_resumo_sem_conteudo_privado = base.LogTresFirebird.test_ia_grava_resumo_sem_conteudo_privado

    def test_python_grava_antes_depois_sem_converter_para_json(self):
        cursor = self.con.cursor()
        try:
            auditoria.registrar_log(
                usuario=44, tabela='IA', acao='MAURO_TESTE_EDICAO / SUCESSO',
                id_registro=14004, valor_anterior='Nome anterior - 0',
                valor_novo='Nome novo - 1', cursor=cursor,
            )
            self.con.commit()
            self.assertEqual(self.eventos('IA',14004),[
                ('MAURO_TESTE_EDICAO / SUCESSO','Nome anterior - 0','Nome novo - 1','44'),
            ])
            cursor.execute('SELECT 1 FROM RDB$DATABASE')
            self.assertEqual(cursor.fetchone(),(1,))
        finally:
            cursor.close()

    def test_python_preserva_rollback_e_recusa_texto_maior_que_o_campo(self):
        cursor = self.con.cursor()
        try:
            auditoria.registrar_log(usuario=44,tabela='API',acao='TESTE_ROLLBACK',
                                  id_registro=14005,valor_novo='STATUS=1',cursor=cursor)
            self.con.rollback()
            self.assertFalse(self.eventos('API',14005))
            with self.assertRaises((ValueError,fdb.DatabaseError)):
                auditoria.registrar_log(usuario=44,tabela='API',acao='TESTE_TAMANHO',
                                      id_registro=14005,valor_novo='x'*4001,cursor=cursor)
            self.con.rollback()
            self.assertFalse(self.eventos('API',14005))
        finally:
            cursor.close()

    def test_contexto_da_trigger_limpa_o_usuario_da_requisicao_anterior(self):
        with patch.object(auditoria,'con',self.con):
            with self.app.test_request_context('/api/v1/assistente/conversas'):
                with patch.object(auditoria,'descobre_id_usuario',return_value=44):
                    auditoria._preparar_contexto_trigger()
            self.assertEqual(self.sql("SELECT RDB$GET_CONTEXT('USER_SESSION','ARKHE_USUARIO_LOG') FROM RDB$DATABASE"),[('44',)])
            with self.app.test_request_context('/api/v1/saldo'):
                with patch.object(auditoria,'descobre_id_usuario',return_value=None):
                    auditoria._preparar_contexto_trigger()
            self.assertEqual(self.sql("SELECT RDB$GET_CONTEXT('USER_SESSION','ARKHE_USUARIO_LOG'), RDB$GET_CONTEXT('USER_SESSION','ARKHE_ID_USUARIO') FROM RDB$DATABASE"),[(None,None)])

    def test_tres_por_tabela_no_modelo_solicitado(self):
        triggers,_ = conferir(self.con)
        self.assertTrue(modelo_ativo(triggers))
        self.assertTrue(conferir_log(self.audit))
        self.assertEqual(len(triggers),35)
        for nome,tabela,tipo,_,_,corpo in triggers:
            if nome.endswith('_LOG'):
                self.assertEqual(corpo.count('EXECUTE STATEMENT'),1)
                self.assertNotIn('IF (',corpo)
                self.assertNotIn('CASE',corpo)
                self.assertNotIn('JSON',corpo)
                self.assertNotIn('CONFIGURACAO_LOG',corpo)
                self.assertNotIn('__LOG_',corpo)
                self.assertIn('VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)',corpo)
                self.assertIn('V_USUARIO =',corpo)
                if tipo == 2:
                    self.assertNotIn('OLD.',corpo)
                    self.assertIn('V_NOVO =',corpo)
                if tipo == 6:
                    self.assertNotIn('NEW.',corpo)
                    self.assertIn('V_ANTIGO =',corpo)
        self.assertEqual([r for r in triggers if not r[0].endswith('_LOG')],
                         [r for r in self.antes if not r[0].endswith('_LOG')])
        self.assertFalse(aplicar_modelo(self.con,self.audit))

    def test_update_preserva_valores_sem_truncar_e_insert_delete_usam_nulo(self):
        self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,ID_RECEBEDOR,VALOR,DATA_MOVIMENTACAO) VALUES (14001,9,10,25,CURRENT_TIMESTAMP)')
        self.con.commit()
        self.sql('UPDATE MOVIMENTACAO SET VALOR=30 WHERE ID_MOVIMENTACAO=14001')
        self.con.commit()
        self.sql('DELETE FROM MOVIMENTACAO WHERE ID_MOVIMENTACAO=14001')
        self.con.commit()
        linhas = self.eventos('MOVIMENTACAO',14001)
        self.assertEqual([r[0] for r in linhas],['INSERT','UPDATE','DELETE'])
        self.assertIsNone(linhas[0][1])
        self.assertIsNone(linhas[2][2])
        anterior = dict(zip(CAMPOS['MOVIMENTACAO'].split(),linhas[1][1].split(' - ')))
        novo = dict(zip(CAMPOS['MOVIMENTACAO'].split(),linhas[1][2].split(' - ')))
        self.assertEqual(Decimal(anterior['VALOR']),Decimal('25'))
        self.assertEqual(Decimal(novo['VALOR']),Decimal('30'))
        self.assertEqual(anterior['ID_PAGADOR'],novo['ID_PAGADOR'])
        self.assertEqual(novo['ID_MOVIMENTACAO'],'14001')
        self.assertEqual(novo['ID_COBRANCA'],'')
        self.assertGreater(len(linhas[1][2]),50)
        self.assertTrue(all(r[3]=='44' for r in linhas))

    def test_insert_update_delete_nas_onze_tabelas_sem_duplicacao(self):
        for indice,tabela in enumerate(TABELAS_PRINCIPAIS):
            with self.subTest(tabela=tabela):
                chave = CAMPOS[tabela].split()[0]
                registro = 15000+indice
                colunas,valores = [],[]
                for _,nome,tipo,subtipo,tamanho,escala,padrao,obrigatorio in (r for r in self.schema['fields'] if r[0]==tabela):
                    if nome not in CAMPOS[tabela].split() and not (obrigatorio and not padrao):
                        continue
                    colunas.append(nome)
                    valor = 1
                    if nome==chave:
                        valor = registro
                    elif tipo in (14,37):
                        valor = 'PF' if nome=='TIPO_CONTA' else 'ATIVO'
                    elif tipo==12:
                        valor = datetime.date(2026,10,27)
                    elif tipo==35:
                        valor = datetime.datetime(2026,10,27,12)
                    valores.append(valor)
                self.sql(f'INSERT INTO {tabela} ('+','.join(colunas)+') VALUES ('+','.join('?' for _ in valores)+')',tuple(valores))
                self.con.commit()
                self.sql(f'UPDATE {tabela} SET {chave}={chave} WHERE {chave}=?',(registro,))
                self.con.commit()
                self.sql(f'DELETE FROM {tabela} WHERE {chave}=?',(registro,))
                self.con.commit()
                linhas = self.eventos(tabela,registro)
                self.assertEqual([r[0] for r in linhas],['INSERT','UPDATE','DELETE'])
                self.assertTrue(all(len(v.split(' - '))==len(CAMPOS[tabela].split()) for r in linhas for v in r[1:3] if v is not None))

    def test_rollback_da_operacao_e_falha_na_gravacao_externa(self):
        sql = 'INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (14002,9,25,CURRENT_TIMESTAMP)'
        self.sql(sql)
        self.con.rollback()
        self.assertFalse(self.eventos('MOVIMENTACAO',14002))
        self.sql('ALTER TABLE LOG ADD CONSTRAINT CK_TESTE_LOG CHECK (ID_REGISTRO <> 14002)',banco=self.audit)
        self.audit.commit()
        try:
            with self.assertRaises(fdb.DatabaseError):
                self.sql(sql)
            self.con.rollback()
            self.assertFalse(self.sql('SELECT ID_MOVIMENTACAO FROM MOVIMENTACAO WHERE ID_MOVIMENTACAO=14002'))
            self.assertFalse(self.eventos('MOVIMENTACAO',14002))
        finally:
            self.sql('ALTER TABLE LOG DROP CONSTRAINT CK_TESTE_LOG',banco=self.audit)
            self.audit.commit()

    def test_rollback_e_falha_da_migracao_preservam_historico(self):
        self.sql("INSERT INTO LOG (TABELA,ID_REGISTRO,ACAO,VALOR_NOVO) VALUES ('TESTE',14003,'UPDATE','STATUS=1')",banco=self.audit)
        self.audit.commit()
        try:
            with tempfile.TemporaryDirectory(prefix='arkhe-log-teste-modelo-') as pasta:
                salvar_rollback(Path(pasta),self.antes,self.origem)
                for sql in comandos_sql((Path(pasta)/'rollback-log-simples.sql').read_text(encoding='utf-8')):
                    self.sql(sql)
                self.con.commit()
            with patch('scripts.aplicar_log_simples.testar_eds',side_effect=RuntimeError('Falha EDS simulada')):
                with self.assertRaisesRegex(RuntimeError,'Falha EDS simulada'):
                    aplicar_modelo(self.con,self.audit)
            self.assertEqual(conferir(self.con)[0],self.antes)
            self.assertTrue(self.eventos('TESTE',14003))
            self.assertEqual(self.sql("SELECT COUNT(*) FROM AUDITORIA_EVENTO WHERE EVENTO='HISTORICO'",banco=self.audit),[(1,)])
        finally:
            self.con.rollback()
            aplicar_modelo(self.con,self.audit)


if __name__ == '__main__':
    unittest.main()
