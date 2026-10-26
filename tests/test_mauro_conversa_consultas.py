"""Teste SQL puro do MAURO conversacional sem Firebird/Redis/Gemini."""
import unittest
from datetime import date
from decimal import Decimal

import test_assistente_mauro_intencoes as base


class CursorConsulta:
    def __init__(self, tipo):
        self.tipo = tipo
        self.executados = []

    def execute(self, sql, params=()):
        self.executados.append((sql, tuple(params)))

    def fetchone(self):
        return (6,)

    def fetchall(self):
        if self.tipo == 'destinatarios':
            return [('Pessoa de teste', Decimal('130.50'), 3),
                    ('Outra pessoa', Decimal('20.00'), 1)]
        if self.tipo == 'despesas':
            return [(Decimal('40.00'), '2026-10-26 08:40:51', 'Pessoa de teste')] * 6
        if self.tipo == 'extrato':
            return [(Decimal('25.10'), '2026-10-26 08:00:00', 'saida', 'Pessoa de teste')]
        return []


class ConsultasMauroV4(unittest.TestCase):
    def test_destinatarios_agrupados_usam_apenas_conta_ativa(self):
        cursor = CursorConsulta('destinatarios')
        dados = base.mauro._dados_financeiros(
            cursor, base.CONTEXTO, 'DESTINATARIOS_FREQUENTES',
            'Para quem eu mais enviei dinheiro?')
        self.assertEqual(cursor.executados[0][1], (base.CONTEXTO['id_conta'],))
        self.assertIn('M.ID_PAGADOR = ?', cursor.executados[0][0])
        self.assertIn('GROUP BY', cursor.executados[0][0])
        self.assertEqual(dados['destinatarios'][0]['total'], '130.50')
        resposta = base.mauro._resposta_financeira_verificada('DESTINATARIOS_FREQUENTES', dados)
        self.assertIn('Pessoa de teste', resposta)
        self.assertIn('130,50', resposta)

    def test_lista_relembra_mes_e_inclui_as_seis_despesas(self):
        cursor = CursorConsulta('despesas')
        historico = [{'papel': 'USUARIO', 'conteudo': 'Quanto gastei neste mês?'}]
        dados = base.mauro._dados_financeiros(
            cursor, base.CONTEXTO, 'LISTAR_DESPESAS', 'Quais foram elas?', historico)
        self.assertEqual(dados['quantidade'], 6)
        self.assertEqual(len(dados['movimentacoes']), 6)
        self.assertEqual(len(cursor.executados), 2)
        self.assertEqual(cursor.executados[0][1][0], base.CONTEXTO['id_conta'])
        self.assertEqual(cursor.executados[1][1][0:2], (base.CONTEXTO['id_conta'], base.CONTEXTO['id_conta']))
        self.assertIn('FIRST 25', cursor.executados[1][0])
        self.assertIn('M.ID_PAGADOR = ?', cursor.executados[1][0])
        self.assertIn('40,00', base.mauro._resposta_financeira_verificada('LISTAR_DESPESAS', dados))

    def test_extrato_consulta_somente_conta_autorizada(self):
        cursor = CursorConsulta('extrato')
        dados = base.mauro._dados_financeiros(
            cursor, base.CONTEXTO, 'MOVIMENTACOES', 'Liste minhas movimentações')
        self.assertEqual(cursor.executados[0][1], (9, 9, 9, 9))
        self.assertIn('M.ID_PAGADOR = ? OR M.ID_RECEBEDOR = ?', cursor.executados[0][0])
        self.assertIn('FIRST 15', cursor.executados[0][0])
        resposta = base.mauro._resposta_financeira_verificada('MOVIMENTACOES', dados)
        self.assertIn('25,10', resposta)

    def test_periodo_personalizado_nao_inclui_dias_anteriores(self):
        from mauro_conversa import periodo_solicitado
        inicio, fim, _ = periodo_solicitado('de 01/10/2026 até 26/10/2026', agora=date(2026, 10, 26))
        self.assertEqual(inicio, date(2026, 10, 1))
        self.assertEqual(fim, date(2026, 10, 27))


if __name__ == '__main__':
    unittest.main()
