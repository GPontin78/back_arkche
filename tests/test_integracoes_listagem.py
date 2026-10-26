"""Regressao da listagem PJ: nenhuma conexao a banco de producao."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

from flask import Flask, jsonify


ARQUIVO = Path(__file__).resolve().parents[1] / 'api' / 'get.py'


def carregar_listagem_isolada(descobrir, conexao):
    arvore = ast.parse(ARQUIVO.read_text(encoding='utf-8'))
    funcao = next(n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == 'listar_integracoes_api')
    funcao.decorator_list = []
    modulo = ast.fix_missing_locations(ast.Module(body=[funcao], type_ignores=[]))
    namespace = {'descobre_id_conta': descobrir, 'con': conexao, 'jsonify': jsonify}
    exec(compile(modulo, str(ARQUIVO), 'exec'), namespace)
    return namespace['listar_integracoes_api']


class ListagemIntegracoesTests(unittest.TestCase):
    def test_rota_importa_resolvedor_de_conta(self):
        arvore = ast.parse(ARQUIVO.read_text(encoding='utf-8'))
        importados = {
            alias.name for item in arvore.body
            if isinstance(item, ast.ImportFrom) and item.module == 'funcao'
            for alias in item.names
        }
        self.assertIn('descobre_id_conta', importados,
                      'A rota GET /integracoes/api usa descobre_id_conta; nao omitir import.')

    def test_conta_logada_lista_apenas_proprias_integracoes(self):
        cursor = Mock()
        cursor.fetchall.return_value = [
            (101, 'Sistema do salao', 'client-publico-1', 1, None, None),
            (102, 'ERP empresarial', 'client-publico-2', 1, None, None),
        ]
        conexao = Mock()
        conexao.cursor.return_value = cursor
        endpoint = carregar_listagem_isolada(lambda: 55, conexao)
        app = Flask(__name__)
        with app.test_request_context('/integracoes/api'):
            resposta, status = endpoint()
        self.assertEqual(status, 200)
        self.assertEqual(len(resposta.get_json()), 2)
        self.assertEqual(resposta.get_json()[0]['nome'], 'Sistema do salao')
        self.assertNotIn('client_secret', str(resposta.get_json()))
        self.assertEqual(cursor.execute.call_args.args[1], (55,))
        self.assertIn('WHERE ID_CONTA = ?', cursor.execute.call_args.args[0])
        cursor.close.assert_called_once()

    def test_sem_conta_nao_expõe_registros(self):
        conexao = Mock()
        endpoint = carregar_listagem_isolada(lambda: None, conexao)
        app = Flask(__name__)
        with app.test_request_context('/integracoes/api'):
            resposta, status = endpoint()
        self.assertEqual(status, 403)
        self.assertEqual(resposta.get_json()['mensagem'], 'Usuario nao logado')
        conexao.cursor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
