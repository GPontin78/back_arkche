from flask import Flask, g
from flask_cors import CORS
from werkzeug.local import LocalProxy
import fdb

app = Flask(__name__)

CORS(
    app,
    origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173"
    ],
    supports_credentials=True
)

app.config.from_pyfile("config.py")

def get_db():
    """Retorna uma conexao Firebird exclusiva para a requisicao atual."""
    if "db_connection" not in g:
        g.db_connection = fdb.connect(
            host=app.config["DB_HOST"],
            port=app.config["DB_PORT"],
            database=app.config["DB_NAME"],
            user=app.config["DB_USER"],
            password=app.config["DB_PASSWORD"]
        )

    return g.db_connection


@app.teardown_appcontext
def close_db(_error=None):
    """Fecha a conexao mesmo quando a rota termina com erro."""
    connection = g.pop("db_connection", None)
    if connection is not None:
        connection.close()


# Mantem a interface usada pelas rotas, mas resolve a conexao por requisicao.
con = LocalProxy(get_db)

from usuario import *
from pagamento import *
from chave_pix import *

if __name__ == "__main__":
    app.run(debug=True)
