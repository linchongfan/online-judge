"""Periodic judge maintenance: Outbox redispatch + expired-task sweeping.

Runs as a standalone long-lived process next to the result consumer so that
transient Redis/database failures cannot leave submissions stuck forever.
"""

import logging
import time

from app.tasks.dispatcher import process_outbox
from app.tasks.sweeper import sweep_expired_tasks

logger = logging.getLogger(__name__)


def run_maintenance(interval_seconds: int = 5) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("Judge maintenance started (interval=%ss)", interval_seconds)
    while True:
        try:
            stats = process_outbox()
            if stats["failed"]:
                logger.warning("Outbox sweep: %s", stats)
        except Exception:
            logger.exception("Outbox sweep failed")
        try:
            stats = sweep_expired_tasks()
            if stats["recovered"] or stats["failed"]:
                logger.info("Expired-task sweep: %s", stats)
        except Exception:
            logger.exception("Expired-task sweep failed")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_maintenance()
