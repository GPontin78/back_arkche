"""Três triggers por tabela, sem duplicar logs nem perder o histórico."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_log_texto_firebird as texto
from tests import test_log_simples_firebird as base
from scripts.aplicar_log_externo import comandos_sql
from scripts.aplicar_log_simples import aplicar_tres,conferir,conferir_log,salvar_rollback,tres_ativas
from scripts.gerar_migracao_log import TABELAS_PRINCIPAIS


class LogTresFirebird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        texto.LogTextoFirebird.setUpClass()
        for nome in ('con','audit','schema','principal','arquivo','pasta','pasta_local','senha','app'):
            setattr(cls,nome,getattr(texto.LogTextoFirebird,nome))
        cls.antes,cls.origem = conferir(cls.con)
        aplicar_tres(cls.con,cls.audit)

    @classmethod
    def tearDownClass(cls):
        texto.LogTextoFirebird.tearDownClass()

    setUp = texto.LogTextoFirebird.setUp
    tearDown = texto.LogTextoFirebird.tearDown
    sql = texto.LogTextoFirebird.sql
    eventos = texto.LogTextoFirebird.eventos

    test_insert_update_delete_nas_onze_tabelas = texto.LogTextoFirebird.test_insert_update_delete_nas_onze_tabelas
    test_antes_e_depois_em_texto = texto.LogTextoFirebird.test_antes_e_depois_em_texto_incluem_resumo_fixo
    test_rollback_da_operacao_e_falha_de_configuracao = texto.LogTextoFirebird.test_rollback_normal_e_falha_de_configuracao
    test_texto_e_json_antigo_na_tela = texto.LogTextoFirebird.test_tela_recebe_texto_sem_envelope_e_le_json_antigo
    test_api_identifica_integracao_sem_credenciais = base.LogSimplesFirebird.test_api_identifica_integracao_validada_sem_copiar_credenciais
    test_ia_grava_resumo_sem_conteudo_privado = base.LogSimplesFirebird.test_ia_grava_em_log_sem_conteudo_privado_e_sem_mensagens_parciais

    def test_tres_por_tabela_sem_case_e_sem_duplicacao(self):
        triggers,_ = conferir(self.con)
        self.assertTrue(tres_ativas(triggers))
        self.assertTrue(conferir_log(self.audit))
        self.assertEqual(len(triggers),35)
        for tabela in TABELAS_PRINCIPAIS:
            logs = [r for r in triggers if r[1]==tabela and r[0].endswith('_LOG')]
            self.assertEqual({r[2] for r in logs},{2,4,6})
            self.assertEqual(len(logs),3)
            for nome,_,tipo,_,_,corpo in logs:
                self.assertEqual(corpo.count('EXECUTE STATEMENT'),1)
                self.assertEqual(corpo.count('IF ('),1)
                self.assertNotIn('CASE',corpo)
                self.assertNotIn('JSON',corpo)
                if tipo == 2:
                    self.assertNotIn('OLD.',corpo)
                if tipo == 6:
                    self.assertNotIn('NEW.',corpo)
        self.assertEqual([r for r in triggers if not r[0].endswith('_LOG')],
                         [r for r in self.antes if not r[0].endswith('_LOG')])
        self.assertFalse(aplicar_tres(self.con,self.audit))

    def test_recusa_trigger_modificada(self):
        self.sql('ALTER TRIGGER TG_AU_USUARIO_LOG INACTIVE')
        with self.assertRaisesRegex(RuntimeError,'mudou'):
            aplicar_tres(self.con,self.audit)
        self.con.rollback()
        self.assertTrue(tres_ativas(conferir(self.con)[0]))

    def test_rollback_e_falha_da_migracao_preservam_historico(self):
        self.sql("INSERT INTO LOG (TABELA,ID_REGISTRO,ACAO,VALOR_NOVO) VALUES ('TESTE',13001,'UPDATE','STATUS=1')",banco=self.audit)
        self.audit.commit()
        try:
            with tempfile.TemporaryDirectory(prefix='arkhe-log-teste-tres-') as pasta:
                salvar_rollback(Path(pasta),self.antes,self.origem,remover_tres=True)
                for sql in comandos_sql((Path(pasta)/'rollback-log-simples.sql').read_text(encoding='utf-8')):
                    self.sql(sql)
                self.con.commit()
            with patch('scripts.aplicar_log_simples.testar_eds',side_effect=RuntimeError('Falha EDS simulada')):
                with self.assertRaisesRegex(RuntimeError,'Falha EDS simulada'):
                    aplicar_tres(self.con,self.audit)
            self.assertEqual(conferir(self.con)[0],self.antes)
            self.assertTrue(self.eventos('TESTE',13001))
            self.assertEqual(self.sql("SELECT COUNT(*) FROM AUDITORIA_EVENTO WHERE EVENTO='HISTORICO'",banco=self.audit),[(1,)])
        finally:
            self.con.rollback()
            aplicar_tres(self.con,self.audit)


if __name__ == '__main__':
    unittest.main()
