from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from uuid import UUID, uuid4

from app.domain.file_policy import safe_extension


class LocalOriginalFileStore:
    def __init__(self, data_root: Path) -> None:
        self.incoming_dir = data_root / "incoming"
        self.invoices_dir = data_root / "invoices"

    def store(self, source_path: Path, invoice_id: UUID) -> Path:
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

    def archive(self, source_path: Path, category: str) -> None:
        if not source_path.exists():
            return
        archive_dir = self.incoming_dir / category
        archive_dir.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}_{uuid4().hex}_{source_path.name}"
        os.replace(source_path, archive_dir / name)

    def remove(self, stored_path: Path) -> None:
        stored_path.unlink(missing_ok=True)
