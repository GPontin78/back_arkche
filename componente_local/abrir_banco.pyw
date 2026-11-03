"""Atalho local: identifica o IP do adaptador e abre o banco no navegador."""
import socket
import sys
import webbrowser
from urllib.parse import urlsplit


def obter_ip_computador(host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
        conexao.connect((host, 443))
        return conexao.getsockname()[0]


def abrir_banco(url):
    host = urlsplit(url).hostname
    ip = obter_ip_computador(host)
    webbrowser.open(url.rstrip('/') + '/#ip_computador=' + ip)


if __name__ == '__main__':
    try:
        abrir_banco(sys.argv[1])
    except Exception:
        from tkinter import messagebox
        messagebox.showerror('Banco Arkhé', 'Não foi possível identificar o IP deste computador. Confira a conexão de rede e tente novamente.')
