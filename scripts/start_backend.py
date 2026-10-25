"""Run Gunicorn and the notification outbox worker under one container PID 1."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_COMMAND = [sys.executable, "-u", "scripts/notificacoes_worker.py"]
WEB_COMMAND = ["gunicorn", "--bind", "0.0.0.0:5000", "main:app"]
STOPPING = False


def request_shutdown(signum: int, _frame: object) -> None:
    global STOPPING
    logging.info("Received signal %s; stopping application processes", signum)
    STOPPING = True


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        logging.warning("Process %s did not stop gracefully; killing it", process.pid)
        process.kill()
        process.wait()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    worker = subprocess.Popen(WORKER_COMMAND, cwd=ROOT)
    web = subprocess.Popen(WEB_COMMAND, cwd=ROOT)
    logging.info("Started notification worker (pid=%s)", worker.pid)
    logging.info("Started Gunicorn (pid=%s)", web.pid)
    restart_delay = 2

    try:
        while not STOPPING:
            web_status = web.poll()
            if web_status is not None:
                logging.error("Gunicorn exited with status %s", web_status)
                return web_status or 1

            if worker.poll() is not None and not STOPPING:
                worker_status = worker.returncode
                logging.error(
                    "Notification worker exited with status %s; restarting in %ss",
                    worker_status,
                    restart_delay,
                )
                time.sleep(restart_delay)
                if not STOPPING and web.poll() is None:
                    worker = subprocess.Popen(WORKER_COMMAND, cwd=ROOT)
                    logging.info("Restarted notification worker (pid=%s)", worker.pid)
                    restart_delay = min(restart_delay * 2, 30)
            elif worker.poll() is None:
                restart_delay = 2

            time.sleep(1)
    finally:
        stop_process(worker)
        stop_process(web)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
