from pathlib import Path

from app.config import Settings
from app.monitor import IncomingDirectoryMonitor


class FakeIngestor:
    def __init__(self) -> None:
        self.ingested: list[Path] = []

    def execute(self, path: Path) -> None:
        self.ingested.append(path)


def test_hidden_marker_files_are_not_considered_invoice_arrivals(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / ".gitkeep").touch()
    settings = Settings("postgresql://unused", tmp_path, 1, 0, 1024, "INFO")
    ingestor = FakeIngestor()

    IncomingDirectoryMonitor(ingestor, settings).scan_once()

    assert ingestor.ingested == []
