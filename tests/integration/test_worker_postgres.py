from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
from sqlalchemy import text

from app.db import apply_migrations, create_db_engine
from app.worker_repository import InvoiceJobRepository


DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration


@pytest.fixture()
def database():
    if not DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    engine = create_db_engine(DATABASE_URL)
    apply_migrations(engine)
    ids: list[uuid.UUID] = []
    yield engine, ids
    with engine.begin() as connection:
        if ids:
            connection.execute(text("DELETE FROM audit_events WHERE invoice_id = ANY(:ids)"), {"ids": ids})
            connection.execute(text("DELETE FROM invoices WHERE id = ANY(:ids)"), {"ids": ids})
    engine.dispose()


def add_queued(engine, ids: list[uuid.UUID], count: int = 1) -> None:
    with engine.begin() as connection:
        for _ in range(count):
            invoice_id = uuid.uuid4()
            ids.append(invoice_id)
            connection.execute(text("""
                INSERT INTO invoices (id, original_filename, stored_path, checksum_sha256, mime_type, file_size, status)
                VALUES (:id, :name, :path, :checksum, 'application/pdf', 1, 'QUEUED')
            """), {"id": invoice_id, "name": f"{invoice_id}.pdf", "path": f"/data/test/{invoice_id}.pdf", "checksum": uuid.uuid4().hex + uuid.uuid4().hex[:32]})


def test_two_workers_cannot_claim_same_invoice(database) -> None:
    engine, ids = database
    add_queued(engine, ids)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: InvoiceJobRepository(create_db_engine(DATABASE_URL)).claim_next(worker), ["worker-a", "worker-b"]))

    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1
    assert claimed[0].id == ids[0]


def test_multiple_workers_claim_different_invoices_and_audit(database) -> None:
    engine, ids = database
    add_queued(engine, ids, count=2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda worker: InvoiceJobRepository(create_db_engine(DATABASE_URL)).claim_next(worker), ["worker-a", "worker-b"]))

    assert {claim.id for claim in claims if claim} == set(ids)
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM audit_events WHERE event_type = 'JOB_CLAIMED' AND invoice_id = ANY(:ids)"), {"ids": ids}).scalar_one()
    assert count == 2


def test_stale_job_recovery_requeues_and_fresh_job_is_retained(database) -> None:
    engine, ids = database
    add_queued(engine, ids, count=2)
    repository = InvoiceJobRepository(engine)
    stale = repository.claim_next("dead-worker")
    fresh = repository.claim_next("live-worker")
    assert stale and fresh
    with engine.begin() as connection:
        connection.execute(text("UPDATE invoices SET claimed_at = :old WHERE id = :id"), {"old": datetime.now(timezone.utc) - timedelta(seconds=60), "id": stale.id})

    assert repository.recover_stale(10, 3) == 1
    with engine.connect() as connection:
        states = dict(connection.execute(text("SELECT id, status FROM invoices WHERE id = ANY(:ids)"), {"ids": ids}).all())
    assert states[stale.id] == "QUEUED"
    assert states[fresh.id] == "EXTRACTING"


def test_failure_retries_are_bounded_and_audited(database) -> None:
    engine, ids = database
    add_queued(engine, ids)
    repository = InvoiceJobRepository(engine)
    for attempt in range(3):
        job = repository.claim_next(f"failure-worker-{attempt}")
        assert job is not None
        final_status = repository.record_failure(job, "synthetic processor failure", max_attempts=3)

    assert final_status.value == "FAILED"
    with engine.connect() as connection:
        row = connection.execute(text("SELECT status, retry_count FROM invoices WHERE id = :id"), {"id": ids[0]}).one()
        events = connection.execute(text("SELECT event_type FROM audit_events WHERE invoice_id = :id ORDER BY id"), {"id": ids[0]}).scalars().all()
    assert row.status == "FAILED"
    assert row.retry_count == 3
    assert events.count("PROCESSING_FAILED") == 3
    assert events.count("RETRY_SCHEDULED") == 2
    assert events.count("RETRY_EXHAUSTED") == 1
