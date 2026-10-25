"""Worker persistente do outbox. Executar como processo separado no EasyPanel."""
import logging
import os
import sys
import time
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from banco import init_db
from agendamentos import processar_agendamentos_pendentes
from recorrencias import processar_recorrencias_pendentes
from notificacoes import processar_outbox_pendente


def criar_app_worker():
    app = Flask('arkhe_notificacoes_worker')
    app.config.from_object(config)
    init_db(app)
    return app


def main():
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
    app = criar_app_worker()
    espera = max(1, int(os.getenv('ARKHE_NOTIFICACOES_INTERVALO_SEGUNDOS', '3')))
    lote = max(1, min(500, int(os.getenv('ARKHE_NOTIFICACOES_LOTE', '100'))))
    logging.info('Worker de notificacoes iniciado; intervalo=%ss lote=%s', espera, lote)

    while True:
        try:
            with app.app_context():
                enviados = processar_outbox_pendente(limite=lote)
                recorrencias = processar_recorrencias_pendentes(limite=20)
                executados = processar_agendamentos_pendentes(limite=20)
            if enviados:
                logging.info('Eventos publicados no Redis: %s', enviados)
            if recorrencias:
                logging.info('Parcelas recorrentes materializadas: %s', recorrencias)
            if executados:
                logging.info('Agendamentos executados: %s', executados)
        except Exception:
            logging.exception('Falha ao processar outbox de notificacoes')
        time.sleep(espera)


if __name__ == '__main__':
    main()
