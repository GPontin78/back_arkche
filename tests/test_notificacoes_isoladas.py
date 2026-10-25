"""Testes unitarios das notificacoes: Firebird e Redis sao simulados."""
import importlib.util
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self.resultado = None
        self.resultados = []
        self.rowcount = 0

    def execute(self, sql, parametros=()):
        self.conexao.chamadas.append((sql, parametros))
        normalizado = ' '.join(sql.upper().split())
        self.resultado = None
        self.resultados = []

        if 'SELECT ID_USUARIO FROM CONTA WHERE ID_CONTA' in normalizado:
            self.resultado = self.conexao.dono_conta
        elif 'SELECT ID_EVENTO FROM EVENTO_NOTIFICACAO_OUTBOX WHERE CHAVE_IDEMPOTENCIA' in normalizado:
            self.resultado = self.conexao.evento_existente
        elif 'SELECT ATIVO FROM PREFERENCIA_NOTIFICACAO' in normalizado:
            self.resultado = self.conexao.preferencia
        elif 'RETURNING ID_EVENTO, CHAVE_IDEMPOTENCIA' in normalizado:
            self.resultado = self.conexao.evento_publicacao
        elif 'RETURNING ID_EVENTO' in normalizado and 'INSERT INTO EVENTO_NOTIFICACAO_OUTBOX' in normalizado:
            self.resultado = (self.conexao.novo_id_evento,)
        elif 'RETURNING ID_NOTIFICACAO' in normalizado:
            self.resultado = (self.conexao.novo_id_notificacao,)
        elif 'FROM CONTA WHERE ID_CONTA = ?' in normalizado and 'ID_USUARIO, TIPO_CONTA' in normalizado:
            self.resultado = self.conexao.conta_autenticada
        elif 'FROM ACESSO_CONTA' in normalizado:
            self.resultado = self.conexao.acesso_ativo
        elif 'SELECT FIRST' in normalizado and 'FROM NOTIFICACAO_DESTINATARIO' in normalizado:
            self.resultados = self.conexao.notificacoes
        return self

    def fetchone(self):
        resultado, self.resultado = self.resultado, None
        return resultado

    def fetchall(self):
        resultado, self.resultados = self.resultados, []
        return resultado

    def close(self):
        pass


class ConexaoFalsa:
    def __init__(self):
        self.chamadas = []
        self.commits = 0
        self.rollbacks = 0
        self.dono_conta = (10,)
        self.evento_existente = None
        self.preferencia = None
        self.novo_id_evento = 41
        self.novo_id_notificacao = 71
        self.evento_publicacao = (55, 'chave-55', 'PIX', 12, 100, '{}')
        self.conta_autenticada = (20, 1)
        self.acesso_ativo = None
        self.notificacoes = []

    def cursor(self):
        return CursorFalso(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


CONEXAO = ConexaoFalsa()
fake_banco = types.ModuleType('banco')
fake_banco.con = CONEXAO
fake_funcao = types.ModuleType('funcao')
fake_funcao.data_atual = lambda: datetime(2026, 10, 25, 12, 0, 0)
fake_redis = types.ModuleType('redis')
fake_redis.Redis = object

with patch.dict(sys.modules, {'banco': fake_banco, 'funcao': fake_funcao, 'redis': fake_redis}):
    service_spec = importlib.util.spec_from_file_location('notificacoes_isoladas_servico', ROOT / 'notificacoes.py')
    service = importlib.util.module_from_spec(service_spec)
    sys.modules[service_spec.name] = service
    service_spec.loader.exec_module(service)

app = Flask('notificacoes_isoladas')
fake_main = types.ModuleType('main')
fake_main.app = app
fake_funcao.descobre_id_conta = lambda: 12
fake_funcao.descobre_id_usuario = lambda: 20
fake_funcao.usuario_pode_acessar_conta = lambda _usuario, _conta: True
with patch.dict(sys.modules, {'main': fake_main, 'banco': fake_banco, 'funcao': fake_funcao,
                              'notificacoes': service}):
    route_spec = importlib.util.spec_from_file_location(
        'api_notificacoes_isoladas', ROOT / 'api' / 'notificacoes.py'
    )
    routes = importlib.util.module_from_spec(route_spec)
    sys.modules[route_spec.name] = routes
    route_spec.loader.exec_module(routes)


class RedisIndisponivel:
    def publish(self, _canal, _mensagem):
        raise ConnectionError('redis indisponivel no teste')


class NotificacoesIsoladasTests(unittest.TestCase):
    def setUp(self):
        CONEXAO.chamadas.clear()
        CONEXAO.commits = 0
        CONEXAO.rollbacks = 0
        CONEXAO.dono_conta = (10,)
        CONEXAO.evento_existente = None
        CONEXAO.preferencia = None
        CONEXAO.novo_id_evento = 41
        CONEXAO.novo_id_notificacao = 71
        CONEXAO.evento_publicacao = (55, 'chave-55', 'PIX', 12, 100, '{}')
        CONEXAO.conta_autenticada = (20, 1)
        CONEXAO.acesso_ativo = None
        CONEXAO.notificacoes = []
        service.con = CONEXAO
        routes.con = CONEXAO

    def test_evento_e_notificacao_sao_persistidos_no_cursor_da_operacao(self):
        cursor = CONEXAO.cursor()
        ids = service.registrar_evento_bancario(
            cursor,
            chave_operacao='movimentacao:900',
            categoria='PIX',
            id_contas=[12],
            referencia_tipo='MOVIMENTACAO',
            referencia_id=900,
            valor='25.00',
            id_pagador=12,
        )
        sql = [consulta.upper() for consulta, _ in CONEXAO.chamadas]
        self.assertEqual(ids, [41])
        self.assertTrue(any('INSERT INTO EVENTO_NOTIFICACAO_OUTBOX' in consulta for consulta in sql))
        self.assertTrue(any('INSERT INTO NOTIFICACAO' in consulta and 'DESTINATARIO' not in consulta for consulta in sql))
        self.assertTrue(any('INSERT INTO NOTIFICACAO_DESTINATARIO' in consulta for consulta in sql))
        self.assertEqual(CONEXAO.commits, 0, 'o servico nao pode confirmar a transacao bancaria')

    def test_chave_idempotente_existente_nao_cria_segunda_notificacao(self):
        CONEXAO.evento_existente = (77,)
        ids = service.registrar_evento_bancario(
            CONEXAO.cursor(), chave_operacao='movimentacao:900', categoria='PIX',
            id_contas=[12], referencia_tipo='MOVIMENTACAO', referencia_id=900,
            valor='25.00', id_pagador=12,
        )
        sql = [consulta.upper() for consulta, _ in CONEXAO.chamadas]
        self.assertEqual(ids, [77])
        self.assertFalse(any('INSERT INTO EVENTO_NOTIFICACAO_OUTBOX' in consulta for consulta in sql))
        self.assertFalse(any('INSERT INTO NOTIFICACAO' in consulta and 'DESTINATARIO' not in consulta for consulta in sql))

    def test_preferencia_desativada_suprime_sem_marcar_como_lida(self):
        CONEXAO.preferencia = (0,)
        service.registrar_evento_bancario(
            CONEXAO.cursor(), chave_operacao='movimentacao:901', categoria='PIX',
            id_contas=[12], referencia_tipo='MOVIMENTACAO', referencia_id=901,
            valor='25.00', id_pagador=12,
        )
        inserir_outbox = next(p for sql, p in CONEXAO.chamadas if 'INSERT INTO EVENTO_NOTIFICACAO_OUTBOX' in sql)
        inserir_destinatario = next(p for sql, p in CONEXAO.chamadas if 'INSERT INTO NOTIFICACAO_DESTINATARIO' in sql)
        self.assertEqual(inserir_outbox[-1], 0, 'eventos suprimidos nao sao publicados no Redis')
        self.assertIsNotNone(inserir_destinatario[-1], 'SUPRIMIDA_EM registra a preferencia')
        self.assertEqual(CONEXAO.commits, 0)

    def test_seguranca_critica_ignora_preferencias_e_e_pessoal(self):
        CONEXAO.preferencia = (0,)
        service.registrar_evento_seguranca(
            CONEXAO.cursor(), chave='login-bloqueado:20:2026102512', id_usuario=20,
            titulo='Bloqueio', mensagem='Tentativas incorretas',
        )
        consultas = [sql.upper() for sql, _ in CONEXAO.chamadas]
        outbox = next(p for sql, p in CONEXAO.chamadas if 'INSERT INTO EVENTO_NOTIFICACAO_OUTBOX' in sql)
        destinatario = next(p for sql, p in CONEXAO.chamadas if 'INSERT INTO NOTIFICACAO_DESTINATARIO' in sql)
        self.assertFalse(any('PREFERENCIA_NOTIFICACAO' in sql for sql in consultas))
        self.assertEqual(outbox[1], 'SEGURANCA_CRITICA')
        self.assertEqual(outbox[2], None)
        self.assertEqual(outbox[-1], 1)
        self.assertEqual(destinatario[1:3], (20, None))
        self.assertIsNone(destinatario[-1])

    def test_redis_indisponivel_mantem_outbox_pendente_e_agendado_para_retry(self):
        resultado = service.tentar_publicar_evento(55, cliente_redis=RedisIndisponivel())
        self.assertFalse(resultado)
        sql = [consulta.upper() for consulta, _ in CONEXAO.chamadas]
        self.assertEqual(CONEXAO.commits, 2, 'claim e registro de retry sao commits do outbox')
        self.assertEqual(CONEXAO.rollbacks, 1, 'erro Redis nao confirma o evento como publicado')
        self.assertTrue(any('PROXIMA_TENTATIVA = DATEADD(30 SECOND' in consulta for consulta in sql))
        self.assertTrue(any('ERRO_ULTIMO = ?' in consulta for consulta in sql))

    def test_vinculo_pj_revogado_bloqueia_a_central(self):
        routes.usuario_pode_acessar_conta = lambda _usuario, _conta: False
        with app.test_request_context('/api/v1/notificacoes'):
            contexto, erro = routes._contexto_autenticado()
        self.assertIsNone(contexto)
        self.assertEqual(erro[1], 403)

    def test_acesso_pj_exige_status_ativo_antes_de_consultar_notificacoes(self):
        routes.usuario_pode_acessar_conta = lambda _usuario, _conta: True
        CONEXAO.conta_autenticada = (10, 1)
        CONEXAO.acesso_ativo = None
        with app.test_request_context('/api/v1/notificacoes'):
            contexto, erro = routes._contexto_autenticado()
        self.assertIsNone(contexto)
        self.assertEqual(erro[1], 403)
        self.assertTrue(any('STATUS = 1' in sql for sql, _ in CONEXAO.chamadas))

    def test_consulta_filtra_por_usuario_mesmo_em_conta_compartilhada(self):
        routes.usuario_pode_acessar_conta = lambda _usuario, _conta: True
        CONEXAO.conta_autenticada = (20, 1)
        CONEXAO.acesso_ativo = (1,)
        CONEXAO.notificacoes = [(1, 'SEGURANCA_CRITICA', 'Alerta', 'Pessoal', '{}', None, None,
                                 datetime(2026, 10, 25, 12, 0), None, 20)]
        with app.test_request_context('/api/v1/notificacoes'):
            resposta, status = routes.listar_notificacoes()
        self.assertEqual(status, 200)
        self.assertEqual(resposta.get_json()['notificacoes'][0]['estado_leitura'], 'nao_lida')
        consulta, parametros = next(
            (sql, p) for sql, p in CONEXAO.chamadas
            if 'FROM NOTIFICACAO_DESTINATARIO D' in sql and 'SELECT FIRST' in sql
        )
        self.assertIn('D.ID_USUARIO = ?', consulta)
        self.assertEqual(parametros[0], 20)

    def test_migracao_separa_evento_outbox_notificacao_preferencia_e_destinatario(self):
        sql = (ROOT / 'migrations' / '001_notificacoes_outbox.sql').read_text(encoding='utf-8').upper()
        for tabela in ('EVENTO_NOTIFICACAO_OUTBOX', 'NOTIFICACAO',
                       'NOTIFICACAO_DESTINATARIO', 'PREFERENCIA_NOTIFICACAO'):
            with self.subTest(tabela=tabela):
                self.assertIn(f'CREATE TABLE {tabela}', sql)


if __name__ == '__main__':
    unittest.main(verbosity=2)
