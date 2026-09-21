from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from app.application.ports import InvoiceRepository, OriginalFileStore
from app.domain.file_policy import invoice_mime_type, sha256_file
from app.domain.models import IngestionResult


class IngestInvoice:
    """Coordinates ingestion without knowing whether storage is local or remote."""

    def __init__(
        self,
        repository: InvoiceRepository,
        file_store: OriginalFileStore,
        max_file_size_bytes: int,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.max_file_size_bytes = max_file_size_bytes
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, source_path: Path) -> IngestionResult:
        try:
            size = source_path.stat().st_size
            if size > self.max_file_size_bytes:
                return self._failure(source_path, f"File exceeds configured maximum of {self.max_file_size_bytes} bytes")

            checksum = sha256_file(source_path)
            existing_id = self.repository.find_by_checksum(checksum)
            if existing_id is not None:
                self.repository.record_duplicate(existing_id, source_path, checksum)
                self.file_store.archive(source_path, "duplicates")
                return IngestionResult(kind="duplicate", existing_invoice_id=existing_id)

            invoice_id = uuid4()
            stored_path = self.file_store.store(source_path, invoice_id)
            mime_type = invoice_mime_type(source_path.name)
            try:
                self.repository.create_queued_invoice(invoice_id, source_path.name, stored_path, checksum, mime_type, size)
            except Exception:
                self.file_store.remove(stored_path)
                existing_id = self.repository.find_by_checksum(checksum)
                if existing_id is None:
                    raise
                self.repository.record_duplicate(existing_id, source_path, checksum)
                self.file_store.archive(source_path, "duplicates")
                return IngestionResult(kind="duplicate", existing_invoice_id=existing_id)

            self.file_store.archive(source_path, "processed")
            self.logger.info("invoice_ingested", extra={"invoice_id": str(invoice_id), "checksum_sha256": checksum})
            return IngestionResult(kind="ingested", invoice_id=invoice_id)
        except Exception as exc:
            self.logger.exception("invoice_ingestion_failed", extra={"source_path": str(source_path)})
            return self._failure(source_path, str(exc))

    def _failure(self, source_path: Path, message: str) -> IngestionResult:
        try:
            self.repository.record_failure(source_path, message)
        except Exception:
            self.logger.exception("ingestion_failure_audit_write_failed", extra={"source_path": str(source_path)})
        self.logger.error("invoice_ingestion_failure_recorded", extra={"source_path": str(source_path), "error": message})
        return IngestionResult(kind="failed")
