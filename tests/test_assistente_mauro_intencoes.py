"""Testes focados da classificação e das consultas bancárias do MAURO."""
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConexaoSemBanco:
    def cursor(self):
        raise AssertionError('Este teste não deve abrir conexão financeira')


class AppStub:
    def add_url_rule(self, *args, **kwargs):
        pass


def carregar_servico():
    substitutos = {
        'flask': types.SimpleNamespace(
            current_app=types.SimpleNamespace(logger=logging.getLogger('mauro_test')),
            jsonify=lambda value: value,
            request=types.SimpleNamespace(path='/teste'),
        ),
        'auditoria': types.SimpleNamespace(registrar_evento_flask=lambda **kwargs: True),
        'banco': types.SimpleNamespace(con=ConexaoSemBanco()),
        'funcao': types.SimpleNamespace(
            calcular_saldo=lambda *_: 0,
            descobre_id_conta=lambda: 1,
            descobre_id_usuario=lambda: 1,
            usuario_pode_acessar_conta=lambda *_: True,
        ),
        'limites': types.SimpleNamespace(_resumo_conta=lambda *_: {}),
        'main': types.SimpleNamespace(app=AppStub()),
    }
    anteriores = {nome: sys.modules.get(nome) for nome in substitutos}
    sys.modules.update(substitutos)
    nome = 'assistente_mauro_teste_isolado'
    spec = importlib.util.spec_from_file_location(nome, ROOT / 'assistente_mauro.py')
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        for chave, anterior in anteriores.items():
            if anterior is None:
                sys.modules.pop(chave, None)
            else:
                sys.modules[chave] = anterior
    return modulo


mauro = carregar_servico()


class CursorFake:
    def __init__(self, falhar_em=None):
        self.sql = ''
        self.parametros = None
        self.falhar_em = falhar_em
        self.resultado = []
        self.todas_consultas = []

    def execute(self, sql, parametros=()):
        self.sql = sql
        self.parametros = parametros
        self.todas_consultas.append((sql, parametros))
        if self.falhar_em and self.falhar_em in sql:
            raise RuntimeError('consulta indisponível')
        if 'FROM AGENDAMENTO_FINANCEIRO' in sql:
            self.resultado = [('TRANSFERENCIA', 25, '2026-11-01 12:00:00', 'AGENDADO', None)]
        elif 'FROM RECORRENCIA_FINANCEIRA R' in sql:
            self.resultado = [('TRANSFERENCIA', 40, 'SEMANAL', '2026-11-01 12:00:00', 'ATIVA', 0, None, 'Conta destino')]
        elif 'FROM COBRANCA CB' in sql:
            self.resultado = [(1000, '2026-11-10', 'Beneficiário')]
        elif 'FROM NOTIFICACAO_DESTINATARIO' in sql:
            self.resultado = [(2,)]
        else:
            self.resultado = []
        return self

    def fetchall(self):
        return list(self.resultado)

    def fetchone(self):
        return self.resultado[0] if self.resultado else None


CONTEXTO = {'id_usuario': 12, 'id_conta': 9, 'tipo_conta': 'PF'}


class TestIntencoesMauro(unittest.TestCase):
    def test_variações_de_agendamento_e_plural(self):
        for pergunta in (
            'Tenho pagamentos agendados?',
            'Existe alguma transferência marcada para depois?',
            'Tem Pix agendado para amanhã?',
            'Quais são meus agendamentos?',
        ):
            with self.subTest(pergunta=pergunta):
                self.assertEqual(mauro._detectar_intencao(pergunta), 'AGENDAMENTOS')

    def test_consultas_de_recorrencia_pendencia_e_notificacao(self):
        self.assertEqual(mauro._detectar_intencao('Tenho alguma recorrência ativa?'), 'RECORRENCIAS')
        self.assertEqual(mauro._detectar_intencao('Quais pagamentos estão pendentes?'), 'PENDENCIAS')
        self.assertEqual(mauro._detectar_intencao('Quais boletos preciso pagar?'), 'PENDENCIAS')
        self.assertEqual(mauro._detectar_intencao('Tenho alguma notificação?'), 'NOTIFICACOES')

    def test_perguntas_financeiras_e_vocabulário_natural(self):
        self.assertEqual(mauro._detectar_intencao('Quanto tenho de saldo?'), 'SALDO')
        self.assertEqual(mauro._detectar_intencao('Quanto gastei esse mês?'), 'DESPESAS_MES')
        self.assertEqual(mauro._detectar_intencao('Quais foram minhas últimas movimentações?'), 'MOVIMENTACOES')
        self.assertEqual(mauro._detectar_intencao('Qual foi minha maior despesa?'), 'MAIORES_GASTOS')
        self.assertEqual(mauro._detectar_intencao('Quais são meus limites?'), 'LIMITES')

    def test_continuacao_herda_assunto_e_entende_semana_passada(self):
        historico = [{'papel': 'USUARIO', 'conteudo': 'Quanto gastei este mês?'}]
        self.assertEqual(mauro._detectar_intencao('E na semana passada?', historico), 'DESPESAS_SEMANA_PASSADA')
        self.assertEqual(mauro._detectar_intencao('E isso?', historico), 'DESPESAS_MES')

    def test_pedido_de_pix_nao_e_consulta_nem_operacao(self):
        self.assertEqual(mauro._detectar_intencao('Você consegue fazer um Pix?'), 'PEDIDO_PAGAMENTO')
        self.assertIn('ainda não consigo fazer pix', mauro._resposta_pedido_financeiro().lower())


class TestConsultasMauro(unittest.TestCase):
    def test_agendamentos_e_recorrencias_usam_usuario_e_conta_ativos(self):
        for intencao, nome in (('AGENDAMENTOS', 'AGENDAMENTO_FINANCEIRO'), ('RECORRENCIAS', 'RECORRENCIA_FINANCEIRA')):
            cursor = CursorFake()
            resultado = mauro._dados_financeiros(cursor, CONTEXTO, intencao)
            consulta = next(sql for sql, _ in cursor.todas_consultas if nome in sql)
            parametros = next(args for sql, args in cursor.todas_consultas if nome in sql)
            self.assertIn('ID_USUARIO = ? AND ID_CONTA = ?', consulta.replace('R.ID_USUARIO = ?', 'ID_USUARIO = ?').replace('R.ID_CONTA = ?', 'ID_CONTA = ?'))
            self.assertEqual(parametros, (12, 9))
            self.assertTrue(resultado['agendamentos'] if intencao == 'AGENDAMENTOS' else resultado['recorrencias'])

    def test_pendencias_consultam_dda_agendamentos_e_notificacoes_com_escopo(self):
        cursor = CursorFake()
        resultado = mauro._dados_financeiros(cursor, CONTEXTO, 'PENDENCIAS')
        self.assertEqual(len(resultado['boletos_pendentes']), 1)
        self.assertEqual(len(resultado['agendamentos_pendentes']), 1)
        self.assertEqual(resultado['notificacoes_nao_lidas'], 2)
        consulta_agendamentos = next((sql, args) for sql, args in cursor.todas_consultas if 'AGENDAMENTO_FINANCEIRO' in sql)
        self.assertEqual(consulta_agendamentos[1], (12, 9))

    def test_lista_vazia_e_resposta_de_indisponibilidade_sao_distintas(self):
        self.assertEqual(
            mauro._resposta_financeira_verificada('AGENDAMENTOS', {'agendamentos': []}),
            'Não encontrei agendamentos para esta conta.',
        )
        cursor = CursorFake(falhar_em='AGENDAMENTO_FINANCEIRO')
        with self.assertRaisesRegex(RuntimeError, 'consulta indisponível'):
            mauro._dados_financeiros(cursor, CONTEXTO, 'AGENDAMENTOS')


if __name__ == '__main__':
    unittest.main()
