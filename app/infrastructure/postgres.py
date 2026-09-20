from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.state_machine import InvoiceStatus, ensure_transition


class PostgresInvoiceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def find_by_checksum(self, checksum: str) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT id FROM invoices WHERE checksum_sha256 = :checksum"), {"checksum": checksum}).scalar_one_or_none()

    def create_queued_invoice(self, invoice_id: UUID, original_filename: str, stored_path: Path, checksum: str, mime_type: str, file_size: int) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(text("""INSERT INTO invoices (id, original_filename, stored_path, checksum_sha256, mime_type, file_size, status)
                    VALUES (:id, :original_filename, :stored_path, :checksum, :mime_type, :file_size, :status)"""), {
                    "id": invoice_id, "original_filename": original_filename, "stored_path": str(stored_path),
                    "checksum": checksum, "mime_type": mime_type, "file_size": file_size,
                    "status": InvoiceStatus.DISCOVERED.value,
                })
                self._audit(connection, invoice_id, "FILE_DISCOVERED", {"source_filename": original_filename})
                self._audit(connection, invoice_id, "CHECKSUM_CALCULATED", {"checksum_sha256": checksum})
                ensure_transition(InvoiceStatus.DISCOVERED, InvoiceStatus.QUEUED)
                connection.execute(text("UPDATE invoices SET status = :status WHERE id = :id"), {"status": InvoiceStatus.QUEUED.value, "id": invoice_id})
                self._audit(connection, invoice_id, "FILE_INGESTED", {"stored_path": str(stored_path), "mime_type": mime_type, "file_size": file_size}, InvoiceStatus.DISCOVERED.value, InvoiceStatus.QUEUED.value)
        except IntegrityError:
            raise

    def record_duplicate(self, invoice_id: UUID, source_path: Path, checksum: str) -> None:
        with self.engine.begin() as connection:
            self._audit(connection, invoice_id, "DUPLICATE_DETECTED", {"source_filename": source_path.name, "source_path": str(source_path), "checksum_sha256": checksum})

    def record_failure(self, source_path: Path, message: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO ingestion_failures (source_path, error_message) VALUES (:source_path, :error_message)"), {"source_path": str(source_path), "error_message": message[:4000]})

    @staticmethod
    def _audit(connection, invoice_id: UUID, event_type: str, metadata: dict, old_value: str | None = None, new_value: str | None = None) -> None:
        connection.execute(text("""INSERT INTO audit_events (invoice_id, event_type, actor, old_value, new_value, metadata)
            VALUES (:invoice_id, :event_type, 'monitor', :old_value, :new_value, CAST(:metadata AS jsonb))"""), {
            "invoice_id": invoice_id, "event_type": event_type, "old_value": old_value,
            "new_value": new_value, "metadata": json.dumps(metadata),
        })
