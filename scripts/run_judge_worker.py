"""Start the local judge worker with .env loaded (development only)."""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.env_loader import load_env  # noqa: E402

load_env()

from judge import heartbeat  # noqa: E402
from judge.celery_worker import celery_app  # noqa: E402

if __name__ == "__main__":
    # The heartbeat carries real active/completed metrics and the admin
    # "accepting" switch; without it, pausing a worker has no effect.
    threading.Thread(target=heartbeat.main, name="judge-heartbeat", daemon=True).start()
    celery_app.worker_main(argv=["worker", "-Q", "judge", "--pool=solo", "--loglevel=info", "--concurrency=1"])
