from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib

from app.domain.models import FileObservation

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
MIME_TYPES_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in SUPPORTED_EXTENSIONS else ""


def invoice_mime_type(filename: str) -> str:
    """Return a stable MIME mapping independent of the host OS MIME database."""
    return MIME_TYPES_BY_EXTENSION.get(Path(filename).suffix.lower(), "application/octet-stream")


def file_is_stable(path: Path, observation: FileObservation, now: datetime, stability_seconds: float) -> bool:
    stat = path.stat()
    return (
        stat.st_size == observation.size
        and stat.st_mtime_ns == observation.mtime_ns
        and (now - observation.first_seen_at).total_seconds() >= stability_seconds
        and (now - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)).total_seconds() >= stability_seconds
    )
