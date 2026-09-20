from __future__ import annotations

from datetime import datetime, timezone
import time

from app.config import Settings
from app.db import apply_migrations, create_db_engine
from app.ingestion import FileObservation, InvoiceIngestor, file_is_stable


class IncomingDirectoryMonitor:
    def __init__(self, ingestor: InvoiceIngestor, settings: Settings):
        self.ingestor = ingestor
        self.settings = settings
        self.observations: dict[object, FileObservation] = {}

    def scan_once(self) -> None:
        self.settings.incoming_dir.mkdir(parents=True, exist_ok=True)
        # Repository/operator marker files (for example .gitkeep) are not invoice arrivals.
        current_paths = {path for path in self.settings.incoming_dir.iterdir() if path.is_file() and not path.name.startswith(".")}
        self.observations = {path: observation for path, observation in self.observations.items() if path in current_paths}
        now = datetime.now(timezone.utc)
        for path in sorted(current_paths):
            try:
                stat = path.stat()
                observation = self.observations.get(path)
                if observation is None or observation.size != stat.st_size or observation.mtime_ns != stat.st_mtime_ns:
                    self.observations[path] = FileObservation(stat.st_size, stat.st_mtime_ns, now)
                    continue
                if file_is_stable(path, observation, now, self.settings.stability_seconds):
                    self.ingestor.ingest(path)
                    self.observations.pop(path, None)
            except FileNotFoundError:
                self.observations.pop(path, None)
            except Exception:
                self.ingestor.logger.exception("incoming_file_scan_failed", extra={"source_path": str(path)})

    def run_forever(self) -> None:
        while True:
            self.scan_once()
            time.sleep(self.settings.poll_interval_seconds)


def main() -> None:
    from app.logging import configure_logging

    settings = Settings.from_environment()
    logger = configure_logging(settings.log_level)
    settings.incoming_dir.mkdir(parents=True, exist_ok=True)
    settings.invoices_dir.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(settings.database_url)
    apply_migrations(engine)
    monitor = IncomingDirectoryMonitor(InvoiceIngestor(engine, settings.data_root, settings.max_file_size_bytes, logger), settings)
    logger.info("monitor_started", extra={"incoming_dir": str(settings.incoming_dir)})
    monitor.run_forever()


if __name__ == "__main__":
    main()
