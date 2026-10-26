"""Triggers curtas, texto legível e histórico intacto em bancos descartáveis."""
import datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fdb
import auditoria
from tests import test_log_simples_firebird as base
from scripts.aplicar_log_externo import comandos_sql
from scripts.aplicar_log_simples import aplicar_texto,conferir,conferir_log,salvar_rollback,texto_ativo
from scripts.gerar_migracao_log import CAMPOS,TABELAS_PRINCIPAIS


class LogTextoFirebird(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.LogSimplesFirebird.setUpClass()
        for nome in ('con','audit','schema','principal','arquivo','pasta','pasta_local','senha','app'):
            setattr(cls,nome,getattr(base.LogSimplesFirebird,nome))
        cls.antes,cls.origem = conferir(cls.con)
        aplicar_texto(cls.con,cls.audit)

    @classmethod
    def tearDownClass(cls):
        base.LogSimplesFirebird.tearDownClass()

    setUp = base.LogSimplesFirebird.setUp
    tearDown = base.LogSimplesFirebird.tearDown
    sql = base.LogSimplesFirebird.sql

    def eventos(self,tabela,registro):
        self.audit.rollback()
        return self.sql('SELECT ACAO,VALOR_ANTERIOR,VALOR_NOVO,USUARIO FROM LOG WHERE TABELA=? AND ID_REGISTRO=? ORDER BY ID_LOG',(tabela,registro),self.audit)

    def test_onze_triggers_sem_json_com_uma_gravacao_e_oito_campos(self):
        triggers,_ = conferir(self.con)
        self.assertTrue(texto_ativo(triggers))
        self.assertEqual(len(triggers),13)
        self.assertTrue(conferir_log(self.audit))
        for nome,*dados in triggers:
            if nome.endswith('_LOG'):
                corpo = dados[4].upper()
                self.assertEqual(corpo.count('EXECUTE STATEMENT'),1)
                self.assertEqual(corpo.count('IF ('),1)
                self.assertNotIn('JSON',corpo)
                self.assertNotIn('IS DISTINCT FROM',corpo)
                self.assertNotIn('V_ANTES',corpo)
        self.assertFalse(aplicar_texto(self.con,self.audit))

    def test_antes_e_depois_em_texto_incluem_resumo_fixo(self):
        self.sql('INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,ID_RECEBEDOR,VALOR,DATA_MOVIMENTACAO) VALUES (11001,9,10,25,CURRENT_TIMESTAMP)')
        self.con.commit()
        self.sql('UPDATE MOVIMENTACAO SET VALOR=30 WHERE ID_MOVIMENTACAO=11001')
        self.con.commit()
        self.sql('DELETE FROM MOVIMENTACAO WHERE ID_MOVIMENTACAO=11001')
        self.con.commit()
        linhas = self.eventos('MOVIMENTACAO',11001)
        self.assertEqual([r[0] for r in linhas],['INSERT','UPDATE','DELETE'])
        self.assertIsNone(linhas[0][1])
        self.assertIsNone(linhas[2][2])
        anterior = dict(p.split('=',1) for p in linhas[1][1].split('; '))
        novo = dict(p.split('=',1) for p in linhas[1][2].split('; '))
        self.assertEqual(Decimal(anterior['VALOR']),Decimal('25'))
        self.assertEqual(Decimal(novo['VALOR']),Decimal('30'))
        self.assertEqual(anterior['ID_PAGADOR'],novo['ID_PAGADOR'])
        self.assertEqual(novo['ID_PAGADOR'],'9')
        self.assertEqual(novo['ID_COBRANCA'],'NULL')
        self.assertTrue(all(r[3]=='44' for r in linhas))

    def test_insert_update_delete_nas_onze_tabelas(self):
        for indice,tabela in enumerate(TABELAS_PRINCIPAIS):
            with self.subTest(tabela=tabela):
                chave = CAMPOS[tabela].split()[0]
                registro = 12000+indice
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
                        valor = datetime.date(2026,10,26)
                    elif tipo==35:
                        valor = datetime.datetime(2026,10,26,12)
                    valores.append(valor)
                self.sql(f'INSERT INTO {tabela} ('+','.join(colunas)+') VALUES ('+','.join('?' for _ in valores)+')',tuple(valores))
                self.con.commit()
                self.sql(f'UPDATE {tabela} SET {chave}={chave} WHERE {chave}=?',(registro,))
                self.con.commit()
                self.sql(f'DELETE FROM {tabela} WHERE {chave}=?',(registro,))
                self.con.commit()
                linhas = self.eventos(tabela,registro)
                self.assertEqual([r[0] for r in linhas],['INSERT','UPDATE','DELETE'])
                self.assertTrue(all(isinstance(v,str) and '=' in v for r in linhas for v in r[1:3] if v is not None))

    def test_rollback_normal_e_falha_de_configuracao(self):
        sql = 'INSERT INTO MOVIMENTACAO (ID_MOVIMENTACAO,ID_PAGADOR,VALOR,DATA_MOVIMENTACAO) VALUES (11002,9,25,CURRENT_TIMESTAMP)'
        self.sql(sql)
        self.con.rollback()
        self.assertFalse(self.eventos('MOVIMENTACAO',11002))
        self.sql('DELETE FROM CONFIGURACAO_LOG WHERE ID_CONFIGURACAO=1')
        with self.assertRaises(fdb.DatabaseError):
            self.sql(sql)
        self.con.rollback()
        self.assertFalse(self.eventos('MOVIMENTACAO',11002))

    def test_tela_recebe_texto_sem_envelope_e_le_json_antigo(self):
        self.sql("INSERT INTO LOG (TABELA,ID_REGISTRO,ACAO,VALOR_NOVO) VALUES ('TESTE',11003,'UPDATE','STATUS=1; TIPO=0')",banco=self.audit)
        self.sql("INSERT INTO LOG (TABELA,ID_REGISTRO,ACAO,VALOR_NOVO) VALUES ('TESTE',11003,'UPDATE','{\"status\":0}')",banco=self.audit)
        self.audit.commit()
        with patch.object(auditoria,'_admin',return_value=(44,None)),self.app.test_request_context('/api/v1/admin/auditoria?simples=1&id_registro=11003'):
            resposta,status = auditoria.listar_eventos_admin()
        self.assertEqual(status,200)
        valores = [r['valor_novo'] for r in resposta.get_json()['eventos']]
        self.assertIn('STATUS=1; TIPO=0',valores)
        self.assertIn({'status':0},valores)

    def test_rollback_da_troca_preserva_logs_antigos_e_textos_novos(self):
        self.sql("INSERT INTO LOG (TABELA,ID_REGISTRO,ACAO,VALOR_NOVO) VALUES ('TESTE',11004,'UPDATE','STATUS=1')",banco=self.audit)
        self.audit.commit()
        try:
            with tempfile.TemporaryDirectory(prefix='arkhe-log-teste-texto-') as pasta:
                salvar_rollback(Path(pasta),self.antes,self.origem)
                for comando in comandos_sql((Path(pasta)/'rollback-log-simples.sql').read_text(encoding='utf-8')):
                    self.sql(comando)
                self.con.commit()
                self.assertFalse(texto_ativo(conferir(self.con)[0]))
                self.assertTrue(self.eventos('TESTE',11004))
                self.assertEqual(self.sql("SELECT COUNT(*) FROM AUDITORIA_EVENTO WHERE EVENTO='HISTORICO'",banco=self.audit),[(1,)])
        finally:
            self.con.rollback()
            aplicar_texto(self.con,self.audit)


if __name__ == '__main__':
    unittest.main()
