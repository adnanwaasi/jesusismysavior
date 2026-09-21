from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import socket


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_root: Path
    poll_interval_seconds: float
    stability_seconds: float
    max_file_size_bytes: int
    log_level: str
    worker_id: str = "worker-local"
    max_attempts: int = 3
    stale_timeout_seconds: float = 300.0
    worker_poll_interval_seconds: float = 2.0
    ocr_languages: str = "eng"
    extraction_max_pages: int = 25
    pdf_min_meaningful_characters: int = 40
    pdf_min_printable_ratio: float = 0.8
    ocr_dpi: int = 200

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
            worker_id=os.environ.get("WORKER_ID") or socket.gethostname(),
            max_attempts=int(os.environ.get("MAX_PROCESSING_ATTEMPTS", "3")),
            stale_timeout_seconds=float(os.environ.get("STALE_JOB_TIMEOUT_SECONDS", "300")),
            worker_poll_interval_seconds=float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "2")),
            ocr_languages=os.environ.get("OCR_LANGUAGES", "eng"),
            extraction_max_pages=int(os.environ.get("EXTRACTION_MAX_PAGES", "25")),
            pdf_min_meaningful_characters=int(os.environ.get("PDF_MIN_MEANINGFUL_CHARACTERS", "40")),
            pdf_min_printable_ratio=float(os.environ.get("PDF_MIN_PRINTABLE_RATIO", "0.8")),
            ocr_dpi=int(os.environ.get("OCR_DPI", "200")),
        )
