from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from app.api import create_app, persist_upload
from app.config import Settings


def settings_for(tmp_path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://unused",
        data_root=tmp_path,
        poll_interval_seconds=2,
        stability_seconds=3,
        max_file_size_bytes=1024,
        log_level="INFO",
    )


def request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_successful_upload_is_atomically_published_with_unchanged_bytes(tmp_path) -> None:
    app = create_app(settings_for(tmp_path))
    contents = b"exact invoice bytes\x00\xff"

    response = request(
        app,
        "POST",
        "/api/v1/invoices",
        files={"file": ("invoice.pdf", contents, "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body == {
        "submission_id": body["submission_id"],
        "filename": "invoice.pdf",
        "status": "SUBMITTED",
    }
    final_path = tmp_path / "incoming" / f'{body["submission_id"]}-invoice.pdf'
    assert final_path.read_bytes() == contents
    assert not list((tmp_path / "incoming").glob(".upload-*.tmp"))


def test_filename_path_traversal_is_sanitized(tmp_path) -> None:
    app = create_app(settings_for(tmp_path))

    response = request(
        app,
        "POST",
        "/api/v1/invoices",
        files={"file": ("../../outside.pdf", b"invoice", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "outside.pdf"
    assert (tmp_path / "incoming" / f'{body["submission_id"]}-outside.pdf').is_file()
    assert not (tmp_path / "outside.pdf").exists()


def test_same_original_filename_does_not_overwrite(tmp_path) -> None:
    app = create_app(settings_for(tmp_path))

    first = request(app, "POST", "/api/v1/invoices", files={"file": ("invoice.pdf", b"first")})
    second = request(app, "POST", "/api/v1/invoices", files={"file": ("invoice.pdf", b"second")})

    assert first.status_code == second.status_code == 202
    first_id = first.json()["submission_id"]
    second_id = second.json()["submission_id"]
    assert first_id != second_id
    assert (tmp_path / "incoming" / f"{first_id}-invoice.pdf").read_bytes() == b"first"
    assert (tmp_path / "incoming" / f"{second_id}-invoice.pdf").read_bytes() == b"second"


class FailingUpload:
    filename = "invoice.pdf"

    def __init__(self) -> None:
        self.read_count = 0
        self.closed = False

    async def read(self, _size: int) -> bytes:
        self.read_count += 1
        if self.read_count == 1:
            return b"partial"
        raise OSError("simulated interrupted upload")

    async def close(self) -> None:
        self.closed = True


def test_failed_upload_removes_temporary_file_and_exposes_no_final_file(tmp_path) -> None:
    incoming_dir = tmp_path / "incoming"
    submission_id = uuid.uuid4()
    upload = FailingUpload()

    with pytest.raises(OSError, match="interrupted"):
        asyncio.run(persist_upload(upload, incoming_dir, submission_id))  # type: ignore[arg-type]

    assert upload.closed
    assert not (incoming_dir / f".upload-{submission_id}.tmp").exists()
    assert not list(incoming_dir.glob(f"{submission_id}-*"))


def test_health(tmp_path) -> None:
    response = request(create_app(settings_for(tmp_path)), "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
