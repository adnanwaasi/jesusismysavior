from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID


class InvoiceRepository(Protocol):
    def find_by_checksum(self, checksum: str) -> UUID | None: ...

    def create_queued_invoice(
        self,
        invoice_id: UUID,
        original_filename: str,
        stored_path: Path,
        checksum: str,
        mime_type: str,
        file_size: int,
    ) -> None: ...

    def record_duplicate(self, invoice_id: UUID, source_path: Path, checksum: str) -> None: ...

    def record_failure(self, source_path: Path, message: str) -> None: ...


class OriginalFileStore(Protocol):
    def store(self, source_path: Path, invoice_id: UUID) -> Path: ...

    def archive(self, source_path: Path, category: str) -> None: ...

    def remove(self, stored_path: Path) -> None: ...
