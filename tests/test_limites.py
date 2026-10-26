"""Testes isolados das janelas e da guarda transacional dos limites."""
import datetime
import importlib.util
import pathlib
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import patch

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CursorFake:
    def __init__(self, utilizado=Decimal('0'), limite_operacao=Decimal('100'),
                 limite_acumulado=Decimal('500'), ativo_operacao=1, ativo_periodo=1):
        self.utilizado = utilizado
        self.limite_operacao = limite_operacao
        self.limite_acumulado = limite_acumulado
        self.ativo_operacao = ativo_operacao
        self.ativo_periodo = ativo_periodo
        self.resultado = None
        self.queries = []

    def execute(self, sql, parametros=()):
        self.queries.append((sql, parametros))
        comando = ' '.join(sql.upper().split())
        if 'SELECT TIPO_CONTA FROM CONTA' in comando:
            self.resultado = (0,)
        elif 'FROM POLITICA_LIMITE_OPERACAO' in comando:
            self.resultado = (self.ativo_operacao, self.limite_operacao)
        elif 'FROM POLITICA_LIMITE_PERIODO' in comando:
            self.resultado = (self.ativo_periodo, self.limite_acumulado)
        elif 'UPDATE CONTROLE_LIMITE_CONTA' in comando:
            self.resultado = (17,)
        elif 'SUM(M.VALOR)' in comando:
            self.resultado = (self.utilizado,)
        elif 'SUM(C.VALOR_COMPRA)' in comando:
            self.resultado = (Decimal('0'),)
        else:
            self.resultado = None

    def fetchone(self):
        return self.resultado


class LimitesIsoladosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('limites_isolados')
        cls.mod_banco = types.ModuleType('banco')
        cls.mod_banco.con = types.SimpleNamespace(rollback=lambda: None)
        cls.mod_funcao = types.ModuleType('funcao')
        cls.mod_funcao.data_atual = lambda: datetime.datetime(2026, 10, 25, 12, 0)
        cls.mod_funcao.dados_conta = lambda: None
        cls.mod_funcao.dados_usuario = lambda: None
        cls.mod_main = types.ModuleType('main')
        cls.mod_main.app = cls.app
        cls.mod_notificacoes = types.ModuleType('notificacoes')
        cls.mod_notificacoes.registrar_evento_bancario = lambda *a, **k: []
        cls.mod_notificacoes.tentar_publicar_eventos = lambda *a, **k: None
        cls.mod_fdb = types.ModuleType('fdb')
        anteriores = {nome: sys.modules.get(nome) for nome in ('banco', 'funcao', 'main', 'notificacoes', 'fdb')}
        sys.modules.update({'banco': cls.mod_banco, 'funcao': cls.mod_funcao,
                            'main': cls.mod_main, 'notificacoes': cls.mod_notificacoes,
                            'fdb': cls.mod_fdb})
        spec = importlib.util.spec_from_file_location('limites_isolados_servico', ROOT / 'limites.py')
        cls.service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.service)
        for nome, anterior in anteriores.items():
            if anterior is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = anterior

    def test_janelas_incluem_os_limites_de_horario_sao_paulo(self):
        service = self.service
        self.assertEqual(service._periodo_agora(datetime.datetime(2026, 10, 25, 5, 59))[0], 'NOTURNO')
        self.assertEqual(service._periodo_agora(datetime.datetime(2026, 10, 25, 6, 0))[0], 'DIURNO')
        self.assertEqual(service._periodo_agora(datetime.datetime(2026, 10, 25, 21, 59))[0], 'DIURNO')
        self.assertEqual(service._periodo_agora(datetime.datetime(2026, 10, 25, 22, 0))[0], 'NOTURNO')

    def _avaliar(self, cursor, valor, por_operacao=None):
        with self.app.test_request_context('/adicionar_pix'):
            with patch.object(self.service, 'data_atual', return_value=datetime.datetime(2026, 10, 25, 12, 0)), \
                 patch.object(self.service, '_registrar_recusa', return_value=True) as auditoria:
                resultado = self.service.aplicar_limite(
                    cursor, 12, 'TRANSFERENCIA', valor,
                    valor_por_operacao=por_operacao, id_usuario=7,
                )
        return resultado, auditoria

    def test_recusa_limite_por_operacao_registra_auditoria_e_serializa_antes_do_somatorio(self):
        cursor = CursorFake(limite_operacao=Decimal('100'))
        resultado, auditoria = self._avaliar(cursor, Decimal('101'))
        self.assertEqual(resultado[1], 403)
        self.assertEqual(resultado[0].get_json()['codigo'], 'LIMITE_ATINGIDO')
        auditoria.assert_called_once()
        comandos = [' '.join(sql.upper().split()) for sql, _ in cursor.queries]
        self.assertLess(next(i for i, sql in enumerate(comandos) if 'UPDATE CONTROLE_LIMITE_CONTA' in sql),
                        next(i for i, sql in enumerate(comandos) if 'SUM(M.VALOR)' in sql))

    def test_recusa_limite_acumulado_considera_o_total_de_movimentacoes_do_periodo(self):
        cursor = CursorFake(utilizado=Decimal('450'), limite_acumulado=Decimal('500'))
        resultado, _auditoria = self._avaliar(cursor, Decimal('60'), por_operacao=Decimal('60'))
        self.assertEqual(resultado[1], 403)
        self.assertEqual(resultado[0].get_json()['codigo'], 'LIMITE_ATINGIDO')
        self.assertIn('acumulado', resultado[0].get_json()['mensagem'])

    def test_politica_inativa_usa_teto_de_segurança_e_recusa_excesso(self):
        cursor = CursorFake(ativo_operacao=0, ativo_periodo=0)
        resultado, auditoria = self._avaliar(cursor, Decimal('5000.01'))
        self.assertEqual(resultado[1], 403)
        self.assertEqual(resultado[0].get_json()['codigo'], 'LIMITE_ATINGIDO')
        auditoria.assert_called_once()
        self.assertTrue(any('UPDATE CONTROLE_LIMITE_CONTA' in sql.upper() for sql, _ in cursor.queries))

    def test_politica_inativa_permite_valores_ate_5000(self):
        cursor = CursorFake(ativo_operacao=0, ativo_periodo=0)
        resultado, auditoria = self._avaliar(cursor, Decimal('5000'))
        self.assertIsNone(resultado)
        auditoria.assert_not_called()

    def test_politica_explicita_do_admin_pode_definir_valores_menores(self):
        cursor = CursorFake(limite_operacao=Decimal('250'), limite_acumulado=Decimal('800'))
        resultado, _ = self._avaliar(cursor, Decimal('251'))
        self.assertEqual(resultado[1], 403)
        self.assertIn('250.00', resultado[0].get_json()['mensagem'])

    def test_migracao_e_aditiva_e_prepara_o_controle_concorrente(self):
        sql = (ROOT / 'migrations' / '002_limites_diurnos_noturnos.sql').read_text(encoding='utf-8').upper()
        for esperado in ('SET BAIL ON', 'POLITICA_LIMITE_OPERACAO', 'POLITICA_LIMITE_PERIODO',
                         'CONTROLE_LIMITE_CONTA', 'AUDITORIA_LIMITE', 'TG_AI_CONTA_LIMITE_CTRL'):
            self.assertIn(esperado, sql)
        self.assertNotIn('DROP TABLE', sql)
        self.assertNotIn('CREATE TABLE MOVIMENTACAO', sql)

        nova = (ROOT / 'migrations' / '010_limites_conta_credito_cartao.sql').read_text(encoding='utf-8').upper()
        for esperado in ('LIMITE_CONTA_OPERACAO', 'LIMITE_CONTA_PERIODO',
                         'AUDITORIA_LIMITE_CARTAO', 'ALTER TABLE MOVIMENTACAO ADD ID_COMPRA',
                         'FK_MOV_COMPRA_LIMITE', 'LIMITE_CONTA_ATUALIZADO'):
            self.assertIn(esperado, nova)
        self.assertNotIn('DROP TABLE', nova)


if __name__ == '__main__':
    unittest.main(verbosity=2)
