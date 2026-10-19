import os

SECRET_KEY = os.environ.get('SECRET_KEY')

DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
DB_PORT = int(os.environ.get('DB_PORT', 3050))
DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER', 'SYSDBA')
DB_PASSWORD = os.environ.get('DB_PASSWORD','sysdba')

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'true' if FRONTEND_URL.startswith('https://') else 'false').lower() == 'true'
# Conta do banco que antecipa vendas a credito; segue a conta 9 do sistema atual.
CONTA_LIQUIDACAO_CARTAO = int(os.environ.get('CONTA_LIQUIDACAO_CARTAO', '9'))
