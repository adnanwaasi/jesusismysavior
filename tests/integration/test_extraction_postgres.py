from __future__ import annotations

import hashlib
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import apply_migrations, create_db_engine
from app.extraction.pipeline import build_extraction_processor
from app.worker_repository import InvoiceJobRepository
from tests.fixtures.factory import make_digital_pdf


DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration


def test_worker_extracts_and_atomically_persists_normalized_invoice(tmp_path: Path) -> None:
    if not DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    engine = create_db_engine(DATABASE_URL)
    apply_migrations(engine)
    invoice_id = uuid.uuid4()
    path = make_digital_pdf(tmp_path / "invoice.pdf")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO invoices (id, original_filename, stored_path, checksum_sha256, mime_type, file_size, status)
            VALUES (:id, 'invoice.pdf', :path, :checksum, 'application/pdf', :size, 'QUEUED')
        """), {"id": invoice_id, "path": str(path), "checksum": checksum, "size": path.stat().st_size})
    try:
        repository = InvoiceJobRepository(engine)
        job = repository.claim_next("extraction-test-worker")
        assert job and job.id == invoice_id
        settings = Settings(DATABASE_URL, tmp_path, 1, 0, 50_000_000, "INFO")
        outcome = build_extraction_processor(settings).process(job)
        repository.persist_extraction(job, outcome)

        with engine.connect() as connection:
            invoice = connection.execute(text("""
                SELECT i.status, e.invoice_number, e.invoice_date, e.vendor, e.currency, e.subtotal, e.tax, e.total
                FROM invoices i JOIN extracted_invoices e ON e.invoice_id = i.id WHERE i.id = :id
            """), {"id": invoice_id}).mappings().one()
            line_count = connection.execute(text("SELECT count(*) FROM invoice_line_items WHERE invoice_id = :id"), {"id": invoice_id}).scalar_one()
            evidence_count = connection.execute(text("SELECT count(*) FROM extracted_fields WHERE invoice_id = :id"), {"id": invoice_id}).scalar_one()
            methods = connection.execute(text("SELECT extraction_method FROM document_extractions WHERE invoice_id = :id"), {"id": invoice_id}).scalar_one()
        assert invoice.status == "TRANSLATING"
        assert invoice.invoice_number == "INV-1001"
        assert str(invoice.total) == "1100.0000"
        assert line_count == 2
        assert evidence_count >= 6
        assert methods == "pdf_text"
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audit_events WHERE invoice_id = :id"), {"id": invoice_id})
            connection.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": invoice_id})
        engine.dispose()
