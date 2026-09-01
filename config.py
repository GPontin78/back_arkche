from pathlib import Path

SECRET_KEY = "Mariahsaudades"

DB_HOST = "127.0.0.1"
DB_PORT = 3050

DB_NAME = str(Path(__file__).with_name("ARKHE.FDB"))

DB_USER = "SYSDBA"
DB_PASSWORD = "sysdba"
