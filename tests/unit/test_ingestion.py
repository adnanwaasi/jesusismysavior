from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from app.ingestion import FileObservation, file_is_stable, safe_extension, sha256_file


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice contents")

    assert sha256_file(source) == "d45a8e7b8c63f414a774b17dfd1a8096ab2441653e8afc1cd3ac177dfe1c6565"


def test_file_is_stable_only_after_observation_and_age(tmp_path: Path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"stable")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp()
    os.utime(source, (old_timestamp, old_timestamp))
    stat = source.stat()
    first_seen = datetime.now(timezone.utc) - timedelta(seconds=5)
    observation = FileObservation(stat.st_size, stat.st_mtime_ns, first_seen)

    assert file_is_stable(source, observation, datetime.now(timezone.utc), stability_seconds=1)
    assert not file_is_stable(source, observation, first_seen + timedelta(milliseconds=500), stability_seconds=1)


def test_safe_extension_only_preserves_supported_invoice_extensions() -> None:
    assert safe_extension("INVOICE.PDF") == ".pdf"
    assert safe_extension("invoice.docx") == ".docx"
    assert safe_extension("invoice.exe") == ""
