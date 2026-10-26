"""Testes isolados das barreiras de autorização dos estornos."""
import unittest
from unittest.mock import patch

from flask import Flask

import estornos
app = Flask(__name__)


class CursorFalso:
    def close(self):
        pass


class ConexaoFalsa:
    def cursor(self):
        return CursorFalso()

    def rollback(self):
        pass

    def commit(self):
        pass


class CursorCancelamentoFalso:
    def __init__(self, conexao, status=0):
        self.conexao = conexao
        self.status = status
        self.resultado = None

    def execute(self, sql, parametros=()):
        self.conexao.sql.append(' '.join(sql.upper().split()))
        consulta = self.conexao.sql[-1]
        self.resultado = None
        if 'FROM COBRANCA WHERE ID_COBRANCA' in consulta:
            self.resultado = (55, None, 20, 12, None, self.status, 0, 'boleto-ficticio')
        elif 'SELECT ID_CONTA FROM CONTA' in consulta:
            self.resultado = (20,)
        elif 'SELECT ID_ESTORNO, STATUS, ID_COBRANCA' in consulta:
            self.resultado = None
        elif 'UPDATE COBRANCA SET STATUS = 2' in consulta:
            self.resultado = (55,)
        elif 'RETURNING ID_ESTORNO' in consulta:
            self.resultado = (77,)
        return self

    def fetchone(self):
        resultado, self.resultado = self.resultado, None
        return resultado

    def close(self):
        pass


class ConexaoCancelamentoFalsa:
    def __init__(self, status=0):
        self.sql = []
        self.status = status
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return CursorCancelamentoFalso(self, self.status)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class TestRegrasEstorno(unittest.TestCase):
    def setUp(self):
        self.movimento = (900, 10, 20, 25, None, None, None, None, 0, None, None, None, None)

    def executar_devolucao(self, id_conta=20, admin=False, estorno_boleto=False):
        with app.test_request_context(json={
            'confirmacao': True,
            'motivo': 'Validação isolada',
            'chave_idempotencia': 'teste-estorno-0001',
        }):
            with patch.object(estornos, 'con', ConexaoFalsa()), \
                 patch.object(estornos, '_autenticacao', return_value=(7, id_conta)), \
                 patch.object(estornos, 'usuario_eh_admin_bancario', return_value=admin), \
                 patch.object(estornos, '_buscar_movimentacao', return_value=self.movimento), \
                 patch.object(estornos, '_conta_acessivel', return_value=True):
                return estornos.devolver_movimentacao(900, estorno_boleto)

    def test_historico_pessoal_bloqueia_conta_sem_permissao(self):
        with app.test_request_context('/api/v1/estornos/minha-conta'):
            with patch.object(estornos, 'descobre_id_usuario', return_value=13), \\
                 patch.object(estornos, 'descobre_id_conta', return_value=2), \\
                 patch.object(estornos, '_conta_acessivel', return_value=False):
                resposta, status = estornos.historico_estornos_conta()
        self.assertEqual(status, 403)
        self.assertIn('não autorizado', resposta.get_json()['mensagem'])

    def test_historico_pessoal_filtra_somente_conta_ativa(self):
        class Cursor:
            def __init__(self):
                self.parametros = []
                self.consulta = ''
            def execute(self, sql, parametros=()):
                self.consulta = sql.upper()
                self.parametros = parametros
            def fetchall(self):
                return [(4, 'DEVOLUCAO_PIX_TRANSFERENCIA', None, 40, 41,
                         10, 20, 38.50, 'CONCLUIDO', 'Devolução legítima',
                         '2026-10-26 09:30')]
            def close(self):
                pass
        class Conexao:
            def __init__(self):
                self.cursor_ativo = Cursor()
            def cursor(self):
                return self.cursor_ativo
        conexao = Conexao()
        with app.test_request_context('/api/v1/estornos/minha-conta'):
            with patch.object(estornos, 'con', conexao), \\
                 patch.object(estornos, 'descobre_id_usuario', return_value=7), \\
                 patch.object(estornos, 'descobre_id_conta', return_value=20), \\
                 patch.object(estornos, '_conta_acessivel', return_value=True), \\
                 patch.object(estornos, '_tem_estrutura_estornos', return_value=True):
                resposta, status = estornos.historico_estornos_conta()
        self.assertEqual(status, 200)
        self.assertEqual(conexao.cursor_ativo.parametros, (20, 20))
        self.assertIn('WHERE E.ID_CONTA_PAGADOR = ? OR E.ID_CONTA_RECEBEDOR = ?', conexao.cursor_ativo.consulta)
        self.assertNotIn('ID_USUARIO_RESPONSAVEL', str(resposta.get_json()))
        self.assertEqual(resposta.get_json()['historico'][0]['participacao'], 'recebedor_original')

    def test_movimentacao_de_cartao_e_recusada_sem_estorno(self):
        self.movimento = (*self.movimento[:8], 1, *self.movimento[9:])
        resposta, status = self.executar_devolucao()
        self.assertEqual(status, 409)
        self.assertIn('cartão ou folha', resposta.get_json()['mensagem'])

    def test_movimentacao_de_folha_e_recusada_sem_estorno(self):
        self.movimento = (*self.movimento[:7], 44, *self.movimento[8:])
        resposta, status = self.executar_devolucao()
        self.assertEqual(status, 409)
        self.assertIn('cartão ou folha', resposta.get_json()['mensagem'])

    def test_pagador_nao_pode_devolver_a_propria_transferencia(self):
        resposta, status = self.executar_devolucao(id_conta=10)
        self.assertEqual(status, 403)
        self.assertIn('recebedor', resposta.get_json()['mensagem'])

    def test_boleto_pago_exige_admin_bancario(self):
        self.movimento = (900, 10, 20, 25, None, 300, 0, None, 0, 1, 10, 20, 25)
        resposta, status = self.executar_devolucao(id_conta=20)
        self.assertEqual(status, 403)
        self.assertIn('estorno administrativo', resposta.get_json()['mensagem'])

    def test_confirmacao_explicita_e_obrigatoria(self):
        with app.test_request_context(json={
            'confirmacao': False,
            'motivo': 'Teste de validação',
            'chave_idempotencia': 'teste-estorno-0002',
        }):
            with self.assertRaises(estornos.ErroEstorno):
                estornos._dados_corpo()

    def test_cancelamento_pendente_preserva_lancamentos_financeiros(self):
        conexao = ConexaoCancelamentoFalsa()
        with app.test_request_context(json={
            'confirmacao': True,
            'motivo': 'Cobrança emitida por engano',
            'chave_idempotencia': 'teste-cancelamento-01',
        }):
            with patch.object(estornos, 'con', conexao), \
                 patch.object(estornos, '_autenticacao', return_value=(7, 20)), \
                 patch.object(estornos, '_conta_acessivel', return_value=True), \
                 patch.object(estornos, 'registrar_evento_bancario', return_value=[]), \
                 patch.object(estornos, 'tentar_publicar_eventos'):
                resposta, status = estornos.cancelar_cobranca(55)
        self.assertEqual(status, 200)
        self.assertEqual(resposta.get_json()['status'], 'CANCELADO')
        self.assertEqual(conexao.commits, 1)
        self.assertFalse(any('INSERT INTO MOVIMENTACAO' in sql for sql in conexao.sql))
        self.assertTrue(any('UPDATE COBRANCA SET STATUS = 2' in sql for sql in conexao.sql))

    def test_cobranca_paga_nao_e_cancelada(self):
        conexao = ConexaoCancelamentoFalsa(status=1)
        with app.test_request_context(json={
            'confirmacao': True,
            'motivo': 'Não se aplica',
            'chave_idempotencia': 'teste-cancelamento-02',
        }):
            with patch.object(estornos, 'con', conexao), \
                 patch.object(estornos, '_autenticacao', return_value=(7, 20)), \
                 patch.object(estornos, '_conta_acessivel', return_value=True):
                resposta, status = estornos.cancelar_cobranca(55)
        self.assertEqual(status, 409)
        self.assertFalse(any('UPDATE COBRANCA SET STATUS = 2' in sql for sql in conexao.sql))


if __name__ == '__main__':
    unittest.main()
