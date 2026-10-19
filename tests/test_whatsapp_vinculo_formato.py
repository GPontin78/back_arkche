"""Testes puros da validacao de identidade da conversa, sem abrir conexao Firebird."""
import ast
import pathlib
import re
import unittest

ARQUIVO = pathlib.Path(__file__).resolve().parents[1] / 'whatsapp_vinculo.py'
ARVORE = ast.parse(ARQUIVO.read_text(encoding='utf-8'))
REGEX = next(node.value.args[0].value for node in ARVORE.body
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'JID_RE' for t in node.targets))
JID_RE = re.compile(REGEX)


class TesteFormatoIdentidadeWhatsApp(unittest.TestCase):
    def test_aceita_lid(self):
        self.assertIsNotNone(JID_RE.fullmatch('123456789012345@lid'))

    def test_aceita_numero_classico(self):
        self.assertIsNotNone(JID_RE.fullmatch('5511999999999@c.us'))

    def test_rejeita_grupo(self):
        self.assertIsNone(JID_RE.fullmatch('120363000@g.us'))

    def test_rejeita_injecao_de_sufixo(self):
        self.assertIsNone(JID_RE.fullmatch('5511999999999@c.us@lid'))

    def test_rejeita_texto_livre(self):
        self.assertIsNone(JID_RE.fullmatch('saldo'))

    def test_token_usa_hash_e_validade(self):
        origem = ARQUIVO.read_text(encoding='utf-8')
        self.assertIn('secrets.token_urlsafe(32)', origem)
        self.assertIn('hashlib.sha256', origem)
        self.assertIn('VALIDADE_MINUTOS = 10', origem)


if __name__ == '__main__':
    unittest.main()
