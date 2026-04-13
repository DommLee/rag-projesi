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
    last_warmup = 0
    while True:
        ready = service.ready()
        now = time.time()
        
        # Her 15 dakikada (900 saniye) bir otomatik warmup (veri cekme)
        if now - last_warmup > 900:
            logger.info("Periyodik 15-dakikalik otomatik warmup basliyor...")
            try:
                service.warm_up_all_sources()
                last_warmup = now
                logger.info("Periyodik warmup tamamlandi.")
            except Exception as e:
                logger.error("Periyodik warmup sirasinda hata: %s", e)

        logger.info("Worker heartbeat %s | %s", datetime.now(UTC).isoformat(), ready)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_worker_loop()

