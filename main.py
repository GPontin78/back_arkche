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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)