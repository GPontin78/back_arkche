import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

arquivo = Path(__file__).resolve().parents[1]/'componente_local/abrir_banco.pyw'
loader = importlib.machinery.SourceFileLoader('componente_ip_teste',str(arquivo))
componente = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader))
loader.exec_module(componente)


class ComponenteIP(unittest.TestCase):
    def test_obtem_ip_do_adaptador_usado_para_acessar_o_banco(self):
        with patch.object(componente.socket,'socket') as criar:
            conexao = criar.return_value.__enter__.return_value
            conexao.getsockname.return_value = ('192.168.10.27',50000)
            self.assertEqual(componente.obter_ip_computador('banco.test'),'192.168.10.27')
            conexao.connect.assert_called_once_with(('banco.test',443))

    def test_abre_banco_com_ip_no_fragmento_sem_colocar_no_query(self):
        with patch.object(componente,'obter_ip_computador',return_value='192.168.10.27'), \
             patch.object(componente.webbrowser,'open') as abrir:
            componente.abrir_banco('https://banco.test/')
            abrir.assert_called_once_with('https://banco.test/#ip_computador=192.168.10.27')
