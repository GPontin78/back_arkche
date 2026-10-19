import unittest

from whatsapp_permissoes import capacidades_whatsapp


class TestPermissoesWhatsApp(unittest.TestCase):
    def test_titular_pf_pode_consultar_financeiro(self):
        self.assertEqual(capacidades_whatsapp({'tipo_conta': 0, 'vinculo': 'titular'}), {'financeiro': True, 'rh': False})

    def test_pj_proprietario_pode_consultar_financeiro_e_rh(self):
        self.assertEqual(capacidades_whatsapp({'tipo_conta': 1, 'vinculo': 'proprietario'}), {'financeiro': True, 'rh': True})

    def test_financeiro_administrativo_contador(self):
        for cargo in (0, 1, 2):
            with self.subTest(cargo=cargo):
                self.assertEqual(capacidades_whatsapp({'tipo_conta': 1, 'vinculo': 'acesso', 'cargo': cargo}), {'financeiro': True, 'rh': False})

    def test_rh_nao_consulta_dados_financeiros(self):
        self.assertEqual(capacidades_whatsapp({'tipo_conta': 1, 'vinculo': 'acesso', 'cargo': 3}), {'financeiro': False, 'rh': True})

    def test_compras_e_outro_nao_tem_consultas_habilitadas(self):
        for cargo in (4, 5, None):
            with self.subTest(cargo=cargo):
                self.assertEqual(capacidades_whatsapp({'tipo_conta': 1, 'vinculo': 'acesso', 'cargo': cargo}), {'financeiro': False, 'rh': False})

    def test_tipos_e_vinculos_invalidos_sao_bloqueados(self):
        self.assertEqual(capacidades_whatsapp({'tipo_conta': 0, 'vinculo': 'acesso'}), {'financeiro': False, 'rh': False})
        self.assertEqual(capacidades_whatsapp({'tipo_conta': 7, 'vinculo': 'titular'}), {'financeiro': False, 'rh': False})


if __name__ == '__main__':
    unittest.main()
