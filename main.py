from flask import Flask
from flask_cors import CORS
from banco import init_db

app = Flask(__name__)
app.config.from_pyfile('config.py')

CORS(app, origins=[app.config['FRONTEND_URL']], supports_credentials=True)

init_db(app)

import usuario
import conta
import transferencia
import pix
import pdf 
import api
import cartao
import acesso
import folha
import folha_csv
import maquininha
import fatura
import limites
import favoritos
import agendamentos
import recorrencias
import estornos
import admin_banco
import auditoria
import assistente_mauro

limites.registrar_rotas(app)
agendamentos.registrar_rotas(app)
recorrencias.registrar_rotas(app)
estornos.registrar_rotas(app)
admin_banco.registrar_rotas(app)
auditoria.registrar_rotas(app)
assistente_mauro.registrar_rotas(app)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
