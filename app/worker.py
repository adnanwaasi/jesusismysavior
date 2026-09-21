from __future__ import annotations

import logging
import signal
import time

from app.config import Settings
from app.db import apply_migrations, create_db_engine
from app.logging import configure_logging
from app.extraction.pipeline import InvoiceExtractionProcessor, build_extraction_processor
from app.worker_repository import InvoiceJobRepository


class InvoiceWorker:
    def __init__(self, repository: InvoiceJobRepository, settings: Settings, processor: InvoiceExtractionProcessor, logger: logging.Logger | None = None):
        self.repository = repository
        self.settings = settings
        self.processor = processor
        self.logger = logger or logging.getLogger(__name__)
        self.running = True

    def stop(self, *_args) -> None:
        self.running = False

    def run_once(self) -> bool:
        self.repository.recover_stale(self.settings.stale_timeout_seconds, self.settings.max_attempts)
        job = self.repository.claim_next(self.settings.worker_id)
        if job is None:
            return False
        try:
            outcome = self.processor.process(job)
            self.repository.persist_extraction(job, outcome)
            self.logger.info("invoice_extracted", extra={"invoice_id": str(job.id), "worker_id": self.settings.worker_id, "document_type": job.mime_type, "extraction_method": outcome.raw_document.extraction_method, "page_count": len(outcome.raw_document.pages), "duration_seconds": outcome.duration_seconds})
        except Exception as exc:
            self.logger.exception("invoice_processing_failed", extra={"invoice_id": str(job.id), "worker_id": self.settings.worker_id})
            self.repository.record_failure(job, str(exc), self.settings.max_attempts)
        return True

    def run_forever(self) -> None:
        while self.running:
            if not self.run_once():
                time.sleep(self.settings.worker_poll_interval_seconds)


def main() -> None:
    settings = Settings.from_environment()
    logger = configure_logging(settings.log_level)
    engine = create_db_engine(settings.database_url)
    apply_migrations(engine)
    repository = InvoiceJobRepository(engine, logger)
    processor = build_extraction_processor(settings)
    worker = InvoiceWorker(repository, settings, processor, logger)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    logger.info("worker_started", extra={"worker_id": settings.worker_id, "max_attempts": settings.max_attempts})
    worker.run_forever()


if __name__ == "__main__":
    main()
