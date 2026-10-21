"""Testes isolados de vinculacao WhatsApp: sem WAHA, Redis ou Firebird reais.

Executar com: python -m unittest discover -s tests -p 'test_whatsapp_vinculos.py'
"""
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
CHAT = "5511999999999@c.us"
FONE = "11999999999"


class RedisFalso:
    """Simula somente os comandos Redis usados nos vinculos."""

    def __init__(self):
        self.dados, self.prazos = {}, {}

    def get(self, chave):
        return self.dados.get(chave)

    def set(self, chave, valor, ex=None, nx=False):
        if nx and chave in self.dados:
            return False
        self.dados[chave] = valor
        self.prazos[chave] = ex or 2592000
        return True

    def ttl(self, chave):
        return self.prazos.get(chave, -2)

    def delete(self, *chaves):
        for chave in chaves:
            self.dados.pop(chave, None)
            self.prazos.pop(chave, None)

    def pipeline(self, transaction=True):
        return PipelineFalso(self)


class PipelineFalso:
    def __init__(self, redis_cli):
        self.redis, self.operacoes = redis_cli, []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def watch(self, *_):
        pass

    def get(self, chave):
        return self.redis.get(chave)

    def ttl(self, chave):
        return self.redis.ttl(chave)

    def multi(self):
        self.operacoes = []

    def set(self, *args, **kwargs):
        self.operacoes.append(("set", args, kwargs))

    def delete(self, *args):
        self.operacoes.append(("delete", args, {}))

    def execute(self):
        for nome, args, kwargs in self.operacoes:
            getattr(self.redis, nome)(*args, **kwargs)
        return True


class CursorFalso:
    def __init__(self, contas):
        self.contas = contas
        self.linhas = []

    def execute(self, comando, parametros=()):
        if "ID_CONTA IN (" not in comando:
            raise AssertionError("SQL inesperado: " + comando[:80])
        id_usuario, *ids = parametros
        self.linhas = [(id_conta, autorizado, nivel, tipo, telefone,
                        "Empresa ficticia" if tipo == 1 else None, None,
                        "0000" + str(id_conta))
                       for id_conta, (usuario, autorizado, nivel, tipo, telefone)
                       in self.contas.items() if id_conta in ids and usuario == id_usuario]

    def fetchall(self):
        return self.linhas

    def close(self):
        pass


class BancoFalso:
    def __init__(self):
        # ID_CONTA => (ID_USUARIO, AUTORIZADO, NIVEL, TIPO, TELEFONE)
        self.contas = {10: (7, 1, 2, 0, FONE), 20: (7, 1, 3, 1, FONE),
                       30: (8, 1, 3, 1, FONE)}

    def cursor(self):
        return CursorFalso(self.contas)


class WhatsAppVinculosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.banco = Flask("whatsapp_vinculos_testes"), BancoFalso()
        cls.app.config["SECRET_KEY"] = "secret-somente-de-teste"

        fake_main = types.ModuleType("main")
        fake_main.app = cls.app
        fake_banco = types.ModuleType("banco")
        fake_banco.con = cls.banco
        fake_funcao = types.ModuleType("funcao")
        fake_funcao.descobre_id_conta = lambda: None
        fake_funcao.descobre_id_usuario = lambda: None
        fake_funcao.usuario_pode_acessar_conta = lambda *_: False
        fake_funcao.verificar_pin = lambda *_: True

        pkg = types.ModuleType("api_whatsapp_testes")
        pkg.__path__ = [str(ROOT / "api")]
        cls.pkg = pkg
        with patch.dict(sys.modules, {"main": fake_main, "banco": fake_banco,
                                      "funcao": fake_funcao, "api_whatsapp_testes": pkg}):
            spec = importlib.util.spec_from_file_location("api_whatsapp_testes.whatsapp",
                                                          ROOT / "api" / "whatsapp.py")
            cls.wa = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = cls.wa
            spec.loader.exec_module(cls.wa)
            spec2 = importlib.util.spec_from_file_location("api_whatsapp_testes.common",
                                                           ROOT / "api" / "common.py")
            cls.common = importlib.util.module_from_spec(spec2)
            sys.modules[spec2.name] = cls.common
            spec2.loader.exec_module(cls.common)

    def setUp(self):
        self.redis = RedisFalso()
        self.banco.contas[10] = (7, 1, 2, 0, FONE)
        self.banco.contas[20] = (7, 1, 3, 1, FONE)
        self.banco.contas[30] = (8, 1, 3, 1, FONE)
        self.mock_redis = patch.object(self.wa, "_redis_wa", return_value=self.redis)
        self.mock_redis.start()
        self.addCleanup(self.mock_redis.stop)
        self.mock_env = patch.dict(os.environ, {"N8N_SERVICE_KEY": "segredo-exclusivo-de-teste"})
        self.mock_env.start()
        self.addCleanup(self.mock_env.stop)

    def vincular(self, conta):
        self.wa._guardar_vinculo(CHAT, 7, conta, FONE, self.redis)

    def test_duas_contas_mesmo_whatsapp(self):
        self.vincular(10)
        self.vincular(20)
        identidade, contas = self.wa._listar_contas_autorizadas(CHAT)
        self.assertEqual([c["id_conta"] for c in contas], [10, 20])
        self.assertEqual(identidade["id_conta"], 20)
        self.assertEqual(self.wa._conta_vinculada(CHAT)["nivel"], 3)

    def test_vinculo_antigo_nao_e_apagado(self):
        chave = self.wa._chave_remetente(CHAT)
        self.redis.set(chave, json.dumps({"id_usuario": 7, "id_conta": 10,
                                         "telefone": FONE, "chat_id": CHAT}), ex=2592000)
        self.vincular(20)
        self.assertEqual(self.wa._ids_vinculados(self.wa._ler_vinculo(CHAT)), [10, 20])

    def test_whatsapp_de_outro_usuario_nao_pode_ser_reaproveitado(self):
        self.vincular(10)
        with self.assertRaises(ValueError):
            self.wa._guardar_vinculo(CHAT, 8, 30, FONE, self.redis)

    def test_desativacao_no_firebird_revoga_acesso_imediatamente(self):
        self.vincular(10)
        self.banco.contas[10] = (7, 0, 2, 0, FONE)
        self.assertIsNone(self.wa._conta_vinculada(CHAT))

    def test_nivel_tres_na_pf_e_limitado_a_dois(self):
        self.banco.contas[10] = (7, 1, 3, 0, FONE)
        self.vincular(10)
        self.assertEqual(self.wa._conta_vinculada(CHAT)["nivel"], 2)
        self.assertIsNone(self.wa.verificar_nivel_whatsapp(CHAT, 3)[0])

    def test_contexto_e_selecao_entre_contas(self):
        self.vincular(10)
        self.vincular(20)
        client = self.app.test_client()
        headers = {"X-Arkhe-N8N-Key": "segredo-exclusivo-de-teste"}
        resposta = client.post("/internal/whatsapp/contexto", json={"chatId": CHAT}, headers=headers)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.json["contas"]), 2)
        selecionar = client.post("/internal/whatsapp/selecionar-conta",
                               json={"chatId": CHAT, "id_conta": 10}, headers=headers)
        self.assertEqual(selecionar.status_code, 200)
        self.assertEqual(self.wa._conta_vinculada(CHAT)["id_conta"], 10)

    def test_conta_nao_vinculada_e_chave_ausente(self):
        self.vincular(10)
        client = self.app.test_client()
        headers = {"X-Arkhe-N8N-Key": "segredo-exclusivo-de-teste"}
        resposta = client.post("/internal/whatsapp/selecionar-conta",
                               json={"chatId": CHAT, "id_conta": 20}, headers=headers)
        self.assertEqual(resposta.status_code, 403)
        resposta = client.post("/internal/whatsapp/contexto", json={"chatId": CHAT})
        self.assertEqual(resposta.status_code, 401)

    def test_autenticacao_universal_nivel_e_integracao_antiga(self):
        self.vincular(10)
        headers = {"X-Arkhe-N8N-Key": "segredo-exclusivo-de-teste", "X-Arkhe-Chat-ID": CHAT}
        with patch.dict(sys.modules, {"api_whatsapp_testes": self.pkg,
                                      "api_whatsapp_testes.whatsapp": self.wa}):
            with self.app.test_request_context("/api/v1/saldo", headers=headers):
                contexto, erro = self.common.autenticar_requisicao(permitir_whatsapp=True)
                self.assertIsNone(erro)
                self.assertEqual(contexto["id_conta"], 10)
                contexto, erro = self.common.autenticar_requisicao(permitir_whatsapp=True, nivel_whatsapp=3)
                self.assertIsNone(contexto)
                self.assertEqual(erro[1], 403)
        with self.app.test_request_context("/api/v1/saldo", headers={"X-Client-ID": "integracao"}):
            with patch.object(self.common, "autenticar_integracao",
                              return_value=({"id_conta": 123}, None)) as legado:
                contexto, erro = self.common.autenticar_requisicao(permitir_whatsapp=True)
                legado.assert_called_once()
                self.assertEqual(contexto["id_conta"], 123)


    def test_pagamento_repetido_nao_executa_duas_vezes(self):
        self.vincular(10)
        with self.app.test_request_context("/api/v1/pagamentos/pix", method="POST",
                                           json={"valor": "20.00", "chave_pix": "teste"},
                                           headers={"X-Idempotency-Key": "teste-pagamento-001"}):
            with patch.object(self.common, "conectar_redis_operacoes", return_value=self.redis), patch.dict(
                    os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
                contador = [0]

                def executar():
                    contador[0] += 1
                    return {"id_movimentacao": 99}, 201

                contexto = {"id_conta": 10, "origem": "whatsapp"}
                primeira = self.common.executar_operacao_idempotente(contexto, "pix", executar)
                segunda = self.common.executar_operacao_idempotente(contexto, "pix", executar)
                self.assertEqual((primeira.status_code, segunda.status_code), (201, 201))
                self.assertEqual(contador[0], 1)

    def test_mesma_chave_outros_dados_rejeita_repeticao(self):
        with patch.object(self.common, "conectar_redis_operacoes", return_value=self.redis), patch.dict(
                os.environ, {"REDIS_URL": "redis://localhost:6379/0"}):
            contexto = {"id_conta": 10, "origem": "whatsapp"}
            headers = {"X-Idempotency-Key": "teste-pagamento-002"}
            with self.app.test_request_context("/api/v1/pagamentos/pix", method="POST",
                                               json={"valor": 10}, headers=headers):
                resp = self.common.executar_operacao_idempotente(
                    contexto, "pix", lambda: ({"resultado": "feito"}, 201))
                self.assertEqual(resp.status_code, 201)
            with self.app.test_request_context("/api/v1/pagamentos/pix", method="POST",
                                               json={"valor": 20}, headers=headers):
                resp = self.common.executar_operacao_idempotente(
                    contexto, "pix", lambda: self.fail("Nao deve executar"))
                self.assertEqual(resp[1], 409)

    def test_integracao_antiga_nao_recebe_permissao_de_saida_automaticamente(self):
        with self.app.test_request_context("/api/v1/pagamentos/pix",
                                           headers={"X-Client-ID": "cliente-antigo"}):
            with patch.dict(os.environ, {"ARKHE_API_PAGAMENTOS_CLIENT_IDS": ""}):
                resposta = self.common.autorizar_pagamento_externo({"id_conta": 10})
                self.assertEqual(resposta[1], 403)
            with patch.dict(os.environ, {"ARKHE_API_PAGAMENTOS_CLIENT_IDS": "cliente-antigo"}):
                self.assertIsNone(self.common.autorizar_pagamento_externo({"id_conta": 10}))


if __name__ == "__main__":
    unittest.main()
