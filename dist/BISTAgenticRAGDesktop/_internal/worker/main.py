from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.service import BISTAgentService
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger("worker")


def run_worker_loop(interval_seconds: int = 60) -> None:
    service = BISTAgentService()
    logger.info("Worker started. interval=%ss", interval_seconds)
    while True:
        ready = service.ready()
        logger.info("Worker heartbeat %s | %s", datetime.now(UTC).isoformat(), ready)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_worker_loop()

