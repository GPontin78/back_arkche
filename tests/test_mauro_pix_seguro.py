"""Testes isolados das regras determinísticas e das transições de proposta do MAURO Pix."""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def carregar_servico():
    financeiros = types.SimpleNamespace(
        COLUNAS_PIX={
            'email': 'CHAVE_PIX_EMAIL', 'telefone': 'CHAVE_PIX_TELEFONE',
            'cpf': 'CHAVE_PIX_CPF', 'cnpj': 'CHAVE_PIX_CNPJ',
            'aleatoria': 'CHAVE_PIX_ALEATORIA',
        },
        ErroOperacaoFinanceira=type('ErroOperacaoFinanceira', (Exception,), {}),
        _normalizar_chave=lambda tipo, chave: ''.join(c for c in str(chave or '').strip() if c.isdigit()) if tipo in ('cpf', 'cnpj', 'telefone') else str(chave or '').strip(),
        _valor_monetario_api=lambda valor: Decimal(str(valor)).quantize(Decimal('0.01')) if Decimal(str(valor)) > 0 else None,
        executar_pix_para_conta=lambda *_args, **_kwargs: {},
        hash_chave_pix=lambda tipo, chave: f'{tipo}:{chave}',
    )
    substitutos = {
        'flask': types.SimpleNamespace(
            current_app=types.SimpleNamespace(logger=types.SimpleNamespace(exception=lambda *_: None)),
            jsonify=lambda dados: dados,
            request=types.SimpleNamespace(path='/test', get_json=lambda silent=True: {}),
        ),
        'auditoria': types.SimpleNamespace(registrar_log=lambda **_kwargs: True),
        'banco': types.SimpleNamespace(con=object()),
        'funcao': types.SimpleNamespace(
            data_atual=lambda: datetime(2026, 10, 25, 12),
            descobre_id_conta=lambda: 10,
            descobre_id_usuario=lambda: 7,
            usuario_pode_acessar_conta=lambda *_: True,
            verificar_pin_usuario=lambda *_: {'valido': True},
        ),
        'notificacoes': types.SimpleNamespace(tentar_publicar_eventos=lambda *_: None),
        'operacoes_financeiras': financeiros,
    }
    anteriores = {nome: sys.modules.get(nome) for nome in substitutos}
    sys.modules.update(substitutos)
    spec = importlib.util.spec_from_file_location('mauro_pix_seguro_teste', ROOT / 'mauro_pix.py')
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        for nome, anterior in anteriores.items():
            if anterior is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = anterior
    return modulo


mauro_pix = carregar_servico()


class TestInterpretacaoSeguraPix(unittest.TestCase):
    def test_valor_em_formatos_brasileiros_e_followup_curto(self):
        self.assertEqual(mauro_pix.extrair_valor('Transfira R$ 1.234,56 para esta chave')[0], Decimal('1234.56'))
        self.assertEqual(mauro_pix.extrair_valor('R$ 1.234')[0], Decimal('1234.00'))
        self.assertEqual(mauro_pix.extrair_valor('transfira 20 para esta chave')[0], Decimal('20.00'))
        self.assertEqual(mauro_pix.extrair_valor('15,50')[0], Decimal('15.50'))
        self.assertIsNone(mauro_pix.extrair_valor('R$ 20,999 para esta chave')[0])

    def test_valor_de_pix_com_erros_de_digitacao_e_sem_unidade(self):
        self.assertEqual(mauro_pix.extrair_valor('Quero um pix de 20')[0], Decimal('20.00'))
        self.assertEqual(mauro_pix.extrair_valor('Me envie um pix de 10')[0], Decimal('10.00'))
        self.assertEqual(mauro_pix.extrair_valor('quero fazer pix no valor de 20 reias')[0], Decimal('20.00'))
        self.assertIsNone(mauro_pix.extrair_valor('minha chave pix é 52998224725')[0])

    def test_chaves_sao_extraidas_e_redigidas_do_historico(self):
        texto = 'Pix de R$ 20,00 para 529.982.247-25'
        chave = mauro_pix.extrair_chave(texto, mauro_pix.extrair_valor(texto)[1])
        self.assertEqual(chave[0], 'cpf')
        redigido = mauro_pix.sanitizar_mensagem_operacao(texto)
        self.assertNotIn('529.982.247-25', redigido)
        self.assertIn('[chave Pix omitida]', redigido)

    def test_email_e_chave_aleatoria_nao_sao_enviados_ao_modelo(self):
        self.assertEqual(mauro_pix.extrair_chave('envia para cliente@exemplo.com')[0], 'email')
        self.assertEqual(mauro_pix.extrair_chave('chave 123e4567-e89b-42d3-a456-426614174000')[0], 'aleatoria')


class TestAutorizacaoEIdempotenciaPix(unittest.TestCase):
    def test_proposta_precisa_bater_com_conversa_usuario_e_conta(self):
        row = (55, 8, 12, 9)
        self.assertTrue(mauro_pix.validar_escopo_proposta(row, 8, 12, 9))
        self.assertFalse(mauro_pix.validar_escopo_proposta(row, 8, 13, 9))
        self.assertFalse(mauro_pix.validar_escopo_proposta(row, 8, 12, 10))
        self.assertFalse(mauro_pix.validar_escopo_proposta(row, 99, 12, 9))

    def test_proposta_expirada_cancelada_ou_executada_nao_pode_reexecutar(self):
        agora = datetime(2026, 10, 25, 12)
        self.assertEqual(mauro_pix.estado_confirmacao('PREPARADA', agora + timedelta(minutes=1), agora), 'PODE_CONFIRMAR')
        self.assertEqual(mauro_pix.estado_confirmacao('PREPARADA', agora, agora), 'EXPIRADA')
        self.assertEqual(mauro_pix.estado_confirmacao('EXECUTADA', agora + timedelta(minutes=1), agora), 'JA_EXECUTADA')
        self.assertEqual(mauro_pix.estado_confirmacao('CANCELADA', agora + timedelta(minutes=1), agora), 'INDISPONIVEL')

    def test_confirmacao_nao_aceita_alterar_valor_destinatario_ou_conta(self):
        self.assertTrue(mauro_pix.corpo_confirmacao_valido({'pin': '123456'}))
        self.assertFalse(mauro_pix.corpo_confirmacao_valido({'pin': '123456', 'valor': 0.01}))
        self.assertFalse(mauro_pix.corpo_confirmacao_valido({'pin': '123456', 'id_conta_destino': 999}))


if __name__ == '__main__':
    unittest.main()
