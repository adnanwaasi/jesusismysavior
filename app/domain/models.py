from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class FileObservation:
    size: int
    mtime_ns: int
    first_seen_at: datetime


@dataclass(frozen=True)
class IngestionResult:
    kind: str
    invoice_id: UUID | None = None
    existing_invoice_id: UUID | None = None
