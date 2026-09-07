import fdb
from flask import g, current_app
from werkzeug.local import LocalProxy

def get_db():
    if 'db_connection' not in g:
        g.db_connection = fdb.connect(
            host=current_app.config['DB_HOST'],
            port=current_app.config['DB_PORT'],
            database=current_app.config['DB_NAME'],
            user=current_app.config['DB_USER'],
            password=current_app.config['DB_PASSWORD']
        )

    return g.db_connection

def close_db(_error=None):
    connection = g.pop('db_connection', None)

    if connection is not None:
        connection.close()

def init_db(app):
    app.teardown_appcontext(close_db)

con = LocalProxy(get_db)