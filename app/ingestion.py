from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import shutil
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.state_machine import InvoiceStatus, ensure_transition


AUDIT_FILE_DISCOVERED = "FILE_DISCOVERED"
AUDIT_CHECKSUM_CALCULATED = "CHECKSUM_CALCULATED"
AUDIT_FILE_INGESTED = "FILE_INGESTED"
AUDIT_DUPLICATE_DETECTED = "DUPLICATE_DETECTED"


@dataclass(frozen=True)
class FileObservation:
    size: int
    mtime_ns: int
    first_seen_at: datetime


@dataclass(frozen=True)
class IngestionResult:
    kind: str
    invoice_id: uuid.UUID | None = None
    existing_invoice_id: uuid.UUID | None = None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_is_stable(path: Path, observation: FileObservation, now: datetime, stability_seconds: float) -> bool:
    stat = path.stat()
    return (
        stat.st_size == observation.size
        and stat.st_mtime_ns == observation.mtime_ns
        and (now - observation.first_seen_at).total_seconds() >= stability_seconds
        and (now - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)).total_seconds() >= stability_seconds
    )


def safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"} else ""


class InvoiceIngestor:
    def __init__(self, engine: Engine, data_root: Path, max_file_size_bytes: int, logger: logging.Logger | None = None):
        self.engine = engine
        self.data_root = data_root
        self.incoming_dir = data_root / "incoming"
        self.invoices_dir = data_root / "invoices"
        self.max_file_size_bytes = max_file_size_bytes
        self.logger = logger or logging.getLogger(__name__)

    def ingest(self, source_path: Path) -> IngestionResult:
        try:
            size = source_path.stat().st_size
            if size > self.max_file_size_bytes:
                return self._record_failure(source_path, f"File exceeds configured maximum of {self.max_file_size_bytes} bytes")
            checksum = sha256_file(source_path)
            existing_id = self._find_invoice_id(checksum)
            if existing_id is not None:
                self._record_duplicate(existing_id, source_path, checksum)
                self._archive(source_path, "duplicates")
                return IngestionResult(kind="duplicate", existing_invoice_id=existing_id)

            invoice_id = uuid.uuid4()
            stored_path = self._store_immutable_copy(source_path, invoice_id)
            mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
            try:
                with self.engine.begin() as connection:
                    self._insert_invoice(connection, invoice_id, source_path.name, stored_path, checksum, mime_type, size)
                    self._insert_audit(connection, invoice_id, AUDIT_FILE_DISCOVERED, {"source_path": str(source_path)})
                    self._insert_audit(connection, invoice_id, AUDIT_CHECKSUM_CALCULATED, {"checksum_sha256": checksum})
                    ensure_transition(InvoiceStatus.DISCOVERED, InvoiceStatus.QUEUED)
                    connection.execute(text("UPDATE invoices SET status = :status WHERE id = :id"), {"status": InvoiceStatus.QUEUED.value, "id": invoice_id})
                    self._insert_audit(connection, invoice_id, AUDIT_FILE_INGESTED, {"stored_path": str(stored_path), "mime_type": mime_type, "file_size": size}, old_value=InvoiceStatus.DISCOVERED.value, new_value=InvoiceStatus.QUEUED.value)
            except IntegrityError:
                stored_path.unlink(missing_ok=True)
                existing_id = self._find_invoice_id(checksum)
                if existing_id is None:
                    raise
                self._record_duplicate(existing_id, source_path, checksum)
                self._archive(source_path, "duplicates")
                return IngestionResult(kind="duplicate", existing_invoice_id=existing_id)

            self._archive(source_path, "processed")
            self.logger.info("invoice_ingested", extra={"invoice_id": str(invoice_id), "checksum_sha256": checksum})
            return IngestionResult(kind="ingested", invoice_id=invoice_id)
        except Exception as exc:
            self.logger.exception("invoice_ingestion_failed", extra={"source_path": str(source_path)})
            return self._record_failure(source_path, str(exc))

    def _store_immutable_copy(self, source_path: Path, invoice_id: uuid.UUID) -> Path:
        now = datetime.now(timezone.utc)
        destination_dir = self.invoices_dir / f"{now:%Y}" / f"{now:%m}"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{invoice_id}{safe_extension(source_path.name)}"
        temporary = destination.with_suffix(destination.suffix + ".partial")
        with source_path.open("rb") as source, temporary.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o444)
        return destination

    def _find_invoice_id(self, checksum: str) -> uuid.UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT id FROM invoices WHERE checksum_sha256 = :checksum"), {"checksum": checksum}).scalar_one_or_none()

    def _insert_invoice(self, connection, invoice_id: uuid.UUID, original_filename: str, stored_path: Path, checksum: str, mime_type: str, size: int) -> None:
        connection.execute(text("""INSERT INTO invoices (id, original_filename, stored_path, checksum_sha256, mime_type, file_size, status) VALUES (:id, :original_filename, :stored_path, :checksum, :mime_type, :file_size, :status)"""), {"id": invoice_id, "original_filename": original_filename, "stored_path": str(stored_path), "checksum": checksum, "mime_type": mime_type, "file_size": size, "status": InvoiceStatus.DISCOVERED.value})

    def _record_duplicate(self, invoice_id: uuid.UUID, source_path: Path, checksum: str) -> None:
        with self.engine.begin() as connection:
            self._insert_audit(connection, invoice_id, AUDIT_DUPLICATE_DETECTED, {"source_filename": source_path.name, "source_path": str(source_path), "checksum_sha256": checksum})
        self.logger.warning("duplicate_invoice_detected", extra={"invoice_id": str(invoice_id), "source_path": str(source_path)})

    def _record_failure(self, source_path: Path, message: str) -> IngestionResult:
        try:
            with self.engine.begin() as connection:
                connection.execute(text("INSERT INTO ingestion_failures (source_path, error_message) VALUES (:source_path, :error_message)"), {"source_path": str(source_path), "error_message": message[:4000]})
        except Exception:
            self.logger.exception("ingestion_failure_audit_write_failed", extra={"source_path": str(source_path)})
        self.logger.error("invoice_ingestion_failure_recorded", extra={"source_path": str(source_path), "error": message})
        return IngestionResult(kind="failed")

    def _insert_audit(self, connection, invoice_id: uuid.UUID, event_type: str, metadata: dict, old_value: str | None = None, new_value: str | None = None) -> None:
        connection.execute(text("""INSERT INTO audit_events (invoice_id, event_type, actor, old_value, new_value, metadata) VALUES (:invoice_id, :event_type, 'monitor', :old_value, :new_value, CAST(:metadata AS jsonb))"""), {"invoice_id": invoice_id, "event_type": event_type, "old_value": old_value, "new_value": new_value, "metadata": json.dumps(metadata)})

    def _archive(self, source_path: Path, category: str) -> None:
        if not source_path.exists():
            return
        archive_dir = self.incoming_dir / category
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex}_{source_path.name}"
        os.replace(source_path, archive_dir / archive_name)
