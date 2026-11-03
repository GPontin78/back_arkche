"""Regressões de intenção, períodos, ambiguidades e contexto antigo."""
from datetime import date
import unittest
import test_assistente_mauro_intencoes as base
from mauro_conversa import contexto_para_modelo, periodo_solicitado


class ConversaCompleta(unittest.TestCase):
    def test_resumo_nunca_e_pagamento_ou_assunto_proibido(self):
        for texto in ('Faça um resumo financeiro da minha conta', 'Quero um resumo financeiro completo',
                      'Me dê um panorama financeiro', 'Gere meu balanço deste mês', 'Resuma minhas finanças'):
            with self.subTest(texto=texto):
                self.assertEqual(base.mauro._detectar_intencao(texto), 'RESUMO_FINANCEIRO')
                self.assertFalse(base.mauro._pedido_fora_escopo(texto))

    def test_cadastros_e_explicacoes_sao_intencoes_distintas(self):
        casos = {'Crie um favorito': 'CADASTRAR_FAVORITO',
                 'Cadastre um favorito': 'CADASTRAR_FAVORITO',
                 'Renomeie o favorito 15 para Escola': 'EDITAR_FAVORITO',
                 'Remova o favorito 15': 'EXCLUIR_FAVORITO',
                 'Gere uma chave Pix aleatória': 'CADASTRAR_CHAVE',
                 'Crie uma chave Pix': 'CADASTRAR_CHAVE',
                 'Liste minhas chaves Pix': 'CHAVES_PIX',
                 'Atualize meu nome para Nome de teste': 'EDITAR_PERFIL',
                 'Como cadastrar uma chave Pix?': 'AJUDA_CADASTROS',
                 'Como editar meu nome?': 'AJUDA_CADASTROS',
                 'Crie um favorito e exclua minha chave Pix': 'ESCLARECER'}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(base.mauro._detectar_intencao(texto), esperado)

    def test_contexto_recupera_assunto_com_mais_de_dez_mensagens(self):
        historico = [{'papel': 'USUARIO', 'conteudo': 'Quanto gastei no mês passado?'}]
        historico += [{'papel': 'USUARIO', 'conteudo': 'Obrigado'}] * 150
        self.assertEqual(base.mauro._detectar_intencao('Quais foram elas?', historico), 'LISTAR_DESPESAS')

    def test_mes_nomeado_ano_e_datas_invalidas(self):
        inicio, fim, _ = periodo_solicitado('Quero meu resumo de fevereiro de 2024', agora=date(2026, 11, 3))
        self.assertEqual((inicio, fim), (date(2024, 2, 1), date(2024, 3, 1)))
        for texto in ('de 31/02/2026 a 10/03/2026', 'de 10/03/2026 a 01/03/2026'):
            with self.assertRaises(ValueError):
                periodo_solicitado(texto, agora=date(2026, 11, 3))

    def test_recuperacao_de_contexto_longo_inclui_informacao_antiga_relevante(self):
        antiga = {'papel': 'USUARIO', 'conteudo': 'Meu favorito se chama Escola Jacarandá.'}
        historico = [antiga] + [{'papel': 'USUARIO', 'conteudo': 'Conversa bancária genérica ' * 100}] * 50
        selecionado = contexto_para_modelo('Retome o favorito Escola Jacarandá', historico)
        self.assertIn(antiga, selecionado)
        self.assertIn(historico[-1], selecionado)
        self.assertLessEqual(sum(len(m['conteudo']) for m in selecionado), 60000)


if __name__ == '__main__':
    unittest.main()
