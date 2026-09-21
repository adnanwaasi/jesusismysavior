from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.state_machine import InvoiceStatus, ensure_transition

if TYPE_CHECKING:
    from app.extraction.pipeline import ExtractionOutcome


PROCESSING_STATUSES = (InvoiceStatus.EXTRACTING, InvoiceStatus.TRANSLATING, InvoiceStatus.VALIDATING)


@dataclass(frozen=True)
class ClaimedInvoice:
    id: uuid.UUID
    original_filename: str
    stored_path: str
    status: InvoiceStatus
    retry_count: int
    worker_id: str
    mime_type: str


class InvoiceJobRepository:
    def __init__(self, engine: Engine, logger: logging.Logger | None = None):
        self.engine = engine
        self.logger = logger or logging.getLogger(__name__)

    def claim_next(self, worker_id: str) -> ClaimedInvoice | None:
        with self.engine.begin() as connection:
            row = connection.execute(text("""
                SELECT id, original_filename, stored_path, status, retry_count, mime_type
                FROM invoices
                WHERE status = 'QUEUED'
                ORDER BY created_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            """)).mappings().first()
            if row is None:
                return None
            invoice_id = row["id"]
            ensure_transition(InvoiceStatus.QUEUED, InvoiceStatus.EXTRACTING)
            connection.execute(text("""
                UPDATE invoices
                SET status = :status, worker_id = :worker_id, claimed_at = NOW(),
                    processing_started_at = COALESCE(processing_started_at, NOW()), updated_at = NOW(),
                    error_message = NULL
                WHERE id = :id AND status = 'QUEUED'
            """), {"status": InvoiceStatus.EXTRACTING.value, "worker_id": worker_id, "id": invoice_id})
            self._audit(connection, invoice_id, "JOB_CLAIMED", {"worker_id": worker_id})
            self._audit(connection, invoice_id, "STATE_TRANSITION", {"worker_id": worker_id}, "QUEUED", "EXTRACTING")
            self._audit(connection, invoice_id, "PROCESSING_STARTED", {"worker_id": worker_id})
            self._audit(connection, invoice_id, "EXTRACTION_STARTED", {"worker_id": worker_id, "mime_type": row["mime_type"]})
            return ClaimedInvoice(invoice_id, row["original_filename"], row["stored_path"], InvoiceStatus.EXTRACTING, row["retry_count"], worker_id, row["mime_type"])

    def persist_extraction(self, job: ClaimedInvoice, outcome: "ExtractionOutcome") -> None:
        target = InvoiceStatus.TRANSLATING
        ensure_transition(job.status, target)
        raw = outcome.raw_document
        invoice = outcome.normalized_invoice
        with self.engine.begin() as connection:
            owned = connection.execute(text("""
                SELECT 1 FROM invoices
                WHERE id = :id AND worker_id = :worker_id AND status = :status
                FOR UPDATE
            """), {"id": job.id, "worker_id": job.worker_id, "status": job.status.value}).scalar_one_or_none()
            if owned is None:
                raise RuntimeError(f"Worker {job.worker_id} no longer owns invoice {job.id}")
            connection.execute(text("""
                INSERT INTO document_extractions (invoice_id, source_type, extraction_method, full_text, pages, metadata, extracted_at)
                VALUES (:invoice_id, :source_type, :method, :full_text, CAST(:pages AS jsonb), CAST(:metadata AS jsonb), NOW())
                ON CONFLICT (invoice_id) DO UPDATE SET source_type = EXCLUDED.source_type,
                    extraction_method = EXCLUDED.extraction_method, full_text = EXCLUDED.full_text,
                    pages = EXCLUDED.pages, metadata = EXCLUDED.metadata, extracted_at = NOW()
            """), {"invoice_id": job.id, "source_type": raw.source_type, "method": raw.extraction_method,
                    "full_text": raw.full_text, "pages": json.dumps([page.model_dump(mode="json") for page in raw.pages]),
                    "metadata": json.dumps({**raw.metadata, "duration_seconds": outcome.duration_seconds})})
            connection.execute(text("""
                INSERT INTO extracted_invoices (invoice_id, invoice_number, invoice_date, vendor, currency, subtotal, tax, total, field_errors, extracted_at)
                VALUES (:invoice_id, :invoice_number, :invoice_date, :vendor, :currency, :subtotal, :tax, :total, CAST(:field_errors AS jsonb), NOW())
                ON CONFLICT (invoice_id) DO UPDATE SET invoice_number = EXCLUDED.invoice_number,
                    invoice_date = EXCLUDED.invoice_date, vendor = EXCLUDED.vendor, currency = EXCLUDED.currency,
                    subtotal = EXCLUDED.subtotal, tax = EXCLUDED.tax, total = EXCLUDED.total,
                    field_errors = EXCLUDED.field_errors, extracted_at = NOW()
            """), {"invoice_id": job.id, "invoice_number": invoice.invoice_number, "invoice_date": invoice.invoice_date,
                    "vendor": invoice.vendor, "currency": invoice.currency, "subtotal": invoice.subtotal,
                    "tax": invoice.tax, "total": invoice.total, "field_errors": json.dumps(invoice.field_errors)})
            connection.execute(text("DELETE FROM invoice_line_items WHERE invoice_id = :id"), {"id": job.id})
            for position, item in enumerate(invoice.line_items, 1):
                connection.execute(text("""
                    INSERT INTO invoice_line_items (id, invoice_id, position, description, quantity, unit_price, line_total,
                        original_quantity, original_unit_price, original_line_total, source_page, source_text)
                    VALUES (:id, :invoice_id, :position, :description, :quantity, :unit_price, :line_total,
                        :original_quantity, :original_unit_price, :original_line_total, :source_page, :source_text)
                """), {"id": uuid.uuid4(), "invoice_id": job.id, "position": position,
                        "description": item.description, "quantity": item.quantity, "unit_price": item.unit_price,
                        "line_total": item.line_total, "original_quantity": item.original_quantity,
                        "original_unit_price": item.original_unit_price, "original_line_total": item.original_line_total,
                        "source_page": item.page_number, "source_text": item.source_text})
            connection.execute(text("DELETE FROM extracted_fields WHERE invoice_id = :id"), {"id": job.id})
            for evidence in invoice.evidence:
                connection.execute(text("""
                    INSERT INTO extracted_fields (id, invoice_id, field_name, normalized_value, original_value,
                        source_page, source_text, extraction_method, confidence)
                    VALUES (:id, :invoice_id, :field_name, :normalized_value, :original_value,
                        :page_number, :source_text, :extraction_method, :confidence)
                """), {"id": uuid.uuid4(), "invoice_id": job.id, **evidence.model_dump()})
            connection.execute(text("""
                UPDATE invoices SET status = :target, worker_id = NULL, claimed_at = NULL,
                    error_message = NULL, updated_at = NOW()
                WHERE id = :id AND worker_id = :worker_id AND status = :current
            """), {"target": target.value, "id": job.id, "worker_id": job.worker_id, "current": job.status.value})
            self._audit(connection, job.id, "DOCUMENT_TYPE_DETECTED", {"mime_type": raw.source_type, "worker_id": job.worker_id})
            method_event = {"pdf_text": "PDF_TEXT_EXTRACTION_USED", "ocr": "OCR_EXTRACTION_USED", "docx": "DOCX_EXTRACTION_USED"}[raw.extraction_method]
            self._audit(connection, job.id, method_event, {"page_count": len(raw.pages), "worker_id": job.worker_id})
            self._audit(connection, job.id, "EXTRACTION_COMPLETED", {"worker_id": job.worker_id, "method": raw.extraction_method, "page_count": len(raw.pages), "line_item_count": len(invoice.line_items), "duration_seconds": outcome.duration_seconds})
            self._audit(connection, job.id, "STATE_TRANSITION", {"worker_id": job.worker_id}, job.status.value, target.value)

    def record_failure(self, job: ClaimedInvoice, error: str, max_attempts: int) -> InvoiceStatus:
        next_retry_count = job.retry_count + 1
        terminal = next_retry_count >= max_attempts
        target = InvoiceStatus.FAILED if terminal else InvoiceStatus.QUEUED
        ensure_transition(job.status, target)
        with self.engine.begin() as connection:
            updated = connection.execute(text("""
                UPDATE invoices
                SET status = :status, retry_count = :retry_count, error_message = :error_message,
                    worker_id = NULL, claimed_at = NULL, updated_at = NOW()
                WHERE id = :id AND worker_id = :worker_id AND status = :current_status
            """), {"status": target.value, "retry_count": next_retry_count, "error_message": error[:4000], "id": job.id, "worker_id": job.worker_id, "current_status": job.status.value})
            if updated.rowcount != 1:
                raise RuntimeError(f"Worker {job.worker_id} no longer owns invoice {job.id}")
            self._audit(connection, job.id, "PROCESSING_FAILED", {"worker_id": job.worker_id, "error": error})
            self._audit(connection, job.id, "EXTRACTION_FAILED", {"worker_id": job.worker_id, "error": error})
            self._audit(connection, job.id, "STATE_TRANSITION", {"worker_id": job.worker_id}, job.status.value, target.value)
            self._audit(connection, job.id, "RETRY_EXHAUSTED" if terminal else "RETRY_SCHEDULED", {"worker_id": job.worker_id, "retry_count": next_retry_count, "max_attempts": max_attempts})
        return target

    def recover_stale(self, stale_timeout_seconds: float, max_attempts: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_timeout_seconds)
        recovered = 0
        with self.engine.begin() as connection:
            rows = connection.execute(text("""
                SELECT id, status, worker_id, retry_count
                FROM invoices
                WHERE status IN ('EXTRACTING', 'TRANSLATING', 'VALIDATING')
                  AND claimed_at IS NOT NULL AND claimed_at < :cutoff
                FOR UPDATE SKIP LOCKED
            """), {"cutoff": cutoff}).mappings().all()
            for row in rows:
                current = InvoiceStatus(row["status"])
                next_retry_count = row["retry_count"] + 1
                target = InvoiceStatus.FAILED if next_retry_count >= max_attempts else InvoiceStatus.QUEUED
                ensure_transition(current, target)
                connection.execute(text("""
                    UPDATE invoices SET status = :status, retry_count = :retry_count,
                        worker_id = NULL, claimed_at = NULL, error_message = :error_message, updated_at = NOW()
                    WHERE id = :id AND status = :current_status AND claimed_at < :cutoff
                """), {"status": target.value, "retry_count": next_retry_count, "error_message": "stale processing lease recovered", "id": row["id"], "current_status": current.value, "cutoff": cutoff})
                self._audit(connection, row["id"], "STALE_JOB_RECOVERED", {"previous_worker_id": row["worker_id"], "retry_count": next_retry_count})
                self._audit(connection, row["id"], "RETRY_EXHAUSTED" if target == InvoiceStatus.FAILED else "RETRY_SCHEDULED", {"retry_count": next_retry_count, "max_attempts": max_attempts})
                recovered += 1
        return recovered

    @staticmethod
    def _audit(connection, invoice_id: uuid.UUID, event_type: str, metadata: dict, old_value: str | None = None, new_value: str | None = None) -> None:
        connection.execute(text("""
            INSERT INTO audit_events (invoice_id, event_type, actor, old_value, new_value, metadata)
            VALUES (:invoice_id, :event_type, 'worker', :old_value, :new_value, CAST(:metadata AS jsonb))
        """), {"invoice_id": invoice_id, "event_type": event_type, "old_value": old_value, "new_value": new_value, "metadata": json.dumps(metadata)})
