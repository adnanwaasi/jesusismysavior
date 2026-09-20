"""Compatibility facade for the ingestion bounded context.

New code should depend on ``app.application`` and ``app.infrastructure`` directly.
"""

from app.application.ingest_invoice import IngestInvoice
from app.domain.file_policy import file_is_stable, safe_extension, sha256_file
from app.domain.models import FileObservation, IngestionResult
from app.infrastructure.files import LocalOriginalFileStore
from app.infrastructure.postgres import PostgresInvoiceRepository


class InvoiceIngestor(IngestInvoice):
    def __init__(self, engine, data_root, max_file_size_bytes, logger=None):
        super().__init__(PostgresInvoiceRepository(engine), LocalOriginalFileStore(data_root), max_file_size_bytes, logger)

    def ingest(self, source_path):
        return self.execute(source_path)


__all__ = ["FileObservation", "IngestionResult", "InvoiceIngestor", "file_is_stable", "safe_extension", "sha256_file"]
