"""Testes de Pix e DDA com Firebird e Redis simulados, sem movimentar dinheiro real."""
import datetime
import importlib.util
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]


class CursorPagamentoFalso:
    def __init__(self, banco):
        self.banco = banco
        self.linha, self.linhas = None, []

    def execute(self, sql, parametros=()):
        comando = " ".join(sql.upper().split())
        self.linha, self.linhas = None, []
        if "FROM CHAVE_PIX" in comando:
            self.linhas = [(20,)]
        elif "FROM CONTA" in comando and "WITH LOCK" in comando:
            self.linha = (parametros[0],)
        elif "FROM COBRANCA" in comando:
            if parametros[0] == 123 and parametros[1] == 10:
                if "WITH LOCK" in comando:
                    self.linha = (self.banco.valor_boleto, self.banco.status_boleto)
                else:
                    self.linha = (20, self.banco.valor_boleto, self.banco.status_boleto)
        elif "UPDATE COBRANCA SET STATUS" in comando:
            if parametros[0] == 123 and parametros[1] == 10 and self.banco.status_boleto == 0:
                self.banco.status_boleto = 1
                self.linha = (123,)
        elif "INSERT INTO MOVIMENTACAO" in comando:
            self.banco.movimentos.append(parametros)
            self.linha = (len(self.banco.movimentos),)
        else:
            raise AssertionError("SQL inesperado: " + comando[:100])

    def fetchone(self):
        return self.linha

    def fetchall(self):
        return self.linhas

    def close(self):
        pass


class BancoPagamentoFalso:
    def __init__(self):
        self.movimentos = []
        self.saldo = Decimal("1000")
        self.status_boleto = 0
        self.valor_boleto = Decimal("35")

    def cursor(self):
        return CursorPagamentoFalso(self)

    def commit(self):
        pass

    def rollback(self):
        pass


class PagamentosApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.banco = Flask("pagamentos_api_testes"), BancoPagamentoFalso()
        fake_main = types.ModuleType("main")
        fake_main.app = cls.app
        fake_banco = types.ModuleType("banco")
        fake_banco.con = cls.banco
        fake_funcao = types.ModuleType("funcao")
        fake_funcao.calcular_limite_cartao = lambda *_: 0
        fake_funcao.calcular_saldo = lambda *_: cls.banco.saldo
        fake_funcao.criptografar_pin = lambda *_: "hash-falso"
        fake_funcao.data_atual = lambda: datetime.datetime(2026, 10, 21, 12, 0)
        fake_funcao.descobre_id_conta = lambda: None
        fake_funcao.pode_debitar_saldo = lambda _, valor: cls.banco.saldo >= Decimal(str(valor))
        fake_funcao.verificar_pin = lambda *_: True
        fake_fdb = types.ModuleType("fdb")
        fake_fdb.TransactionConflict = type("TransactionConflict", (Exception,), {})
        pkg = types.ModuleType("api_pagamentos_teste")
        pkg.__path__ = [str(ROOT / "api")]
        fake_whatsapp = types.ModuleType("api_pagamentos_teste.whatsapp")
        fake_whatsapp._conta_vinculada = lambda *_: None
        fake_whatsapp._servico_valido = lambda: False
        cls.package = pkg
        mods = {"main": fake_main, "banco": fake_banco, "funcao": fake_funcao,
                "fdb": fake_fdb, "api_pagamentos_teste": pkg,
                "api_pagamentos_teste.whatsapp": fake_whatsapp}
        with patch.dict(sys.modules, mods):
            for suffix in ("common", "post"):
                spec = importlib.util.spec_from_file_location("api_pagamentos_teste." + suffix,
                                                              ROOT / "api" / (suffix + ".py"))
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                setattr(cls, suffix, module)

    def setUp(self):
        self.banco.movimentos = []
        self.banco.status_boleto = 0
        self.banco.valor_boleto = Decimal("35")
        self.banco.saldo = Decimal("1000")
        self.auth = patch.object(self.post, "autenticar_requisicao",
                                 return_value=({"id_conta": 10, "origem": "whatsapp", "nivel": 2}, None))
        self.auth.start()
        self.addCleanup(self.auth.stop)
        self.idempotencia = patch.object(self.post, "executar_operacao_idempotente",
                                         side_effect=lambda contexto, op, executar: executar())
        self.idempotencia.start()
        self.addCleanup(self.idempotencia.stop)
        self.client = self.app.test_client()

    def test_pix_nao_aceita_conta_pagadora_do_json(self):
        resp = self.client.post("/api/v1/pagamentos/pix",
                                json={"tipo_chave": "cpf", "chave_pix": "52998224725",
                                      "valor": "25.00", "id_conta": 999})
        self.assertEqual(resp.status_code, 201, resp.json)
        self.assertEqual(self.banco.movimentos[0][0], 10)
        self.assertEqual(self.banco.movimentos[0][1], 20)
        self.assertEqual(self.banco.movimentos[0][2], Decimal("25.00"))

    def test_pix_valor_invalido_nao_movimenta(self):
        for valor in ("-20", "0", "NaN", "infinito"):
            resp = self.client.post("/api/v1/pagamentos/pix",
                                    json={"tipo_chave": "cpf", "chave_pix": "52998224725",
                                          "valor": valor})
            self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.banco.movimentos, [])

    def test_whatsapp_nivel_insuficiente_bloqueia(self):
        with patch.object(self.post, "autenticar_requisicao",
                          return_value=(None, ({"mensagem": "Nivel insuficiente"}, 403))):
            resp = self.client.post("/api/v1/pagamentos/pix",
                                    json={"tipo_chave": "cpf", "chave_pix": "52998224725", "valor": 25})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.banco.movimentos, [])

    def test_dda_de_outra_conta_nao_pode_ser_pago(self):
        resp = self.client.post("/api/v1/pagamentos/dda/999", json={})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.banco.movimentos, [])

    def test_dda_paga_uma_vez_e_impede_repeticao(self):
        resp = self.client.post("/api/v1/pagamentos/dda/123", json={})
        self.assertEqual(resp.status_code, 200, resp.json)
        self.assertEqual(self.banco.movimentos[0][0], 10)
        self.assertEqual(self.banco.movimentos[0][1], 20)
        self.assertEqual(self.banco.movimentos[0][2], Decimal("35"))
        outro = self.client.post("/api/v1/pagamentos/dda/123", json={})
        self.assertEqual(outro.status_code, 409)
        self.assertEqual(len(self.banco.movimentos), 1)

    def test_dda_nao_aceita_mudar_pagador_ou_valor(self):
        resp = self.client.post("/api/v1/pagamentos/dda/123", json={"id_conta": 999})
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post("/api/v1/pagamentos/dda/123", json={"valor": 1})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.banco.movimentos, [])


if __name__ == "__main__":
    unittest.main()
