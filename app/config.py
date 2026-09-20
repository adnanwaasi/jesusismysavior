from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_root: Path
    poll_interval_seconds: float
    stability_seconds: float
    max_file_size_bytes: int
    log_level: str

    @property
    def incoming_dir(self) -> Path:
        return self.data_root / "incoming"

    @property
    def invoices_dir(self) -> Path:
        return self.data_root / "invoices"

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://invoice_auditor:change-me-for-local-use@localhost:5432/invoice_auditor",
            ),
            data_root=Path(os.environ.get("DATA_ROOT", "/data")),
            poll_interval_seconds=float(os.environ.get("MONITOR_POLL_INTERVAL_SECONDS", "2")),
            stability_seconds=float(os.environ.get("FILE_STABILITY_SECONDS", "3")),
            max_file_size_bytes=int(os.environ.get("MAX_FILE_SIZE_BYTES", str(50 * 1024 * 1024))),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
