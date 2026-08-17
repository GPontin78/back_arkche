from flask import Flask
from flask_cors import CORS
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

con = fdb.connect(
    host=app.config["DB_HOST"],
    port=app.config["DB_PORT"],
    database=app.config["DB_NAME"],
    user=app.config["DB_USER"],
    password=app.config["DB_PASSWORD"]
)

from usuario import *


if __name__ == "__main__":
    app.run(debug=True)