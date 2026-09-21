from pathlib import Path
from uuid import uuid4

import pytest

from app.extraction.documents import DocumentExtractorDispatcher, ImageDocumentExtractor, OcrEngine, PdfDocumentExtractor
from tests.fixtures.factory import make_invoice_image, make_scanned_pdf


pytestmark = pytest.mark.integration


def test_real_image_ocr_recovers_invoice_text(tmp_path: Path) -> None:
    path = make_invoice_image(tmp_path / "invoice.png")
    extractor = ImageDocumentExtractor(OcrEngine("eng"))
    raw = extractor.extract(uuid4(), "image/png", path)
    assert raw.extraction_method == "ocr"
    assert "INV-1001" in raw.full_text
    assert "Example Supplier" in raw.full_text


def test_real_scanned_pdf_uses_ocr_fallback(tmp_path: Path) -> None:
    path = make_scanned_pdf(tmp_path / "scanned.pdf")
    extractor = PdfDocumentExtractor(OcrEngine("eng"), 10, 40, 0.8, 180)
    raw = extractor.extract(uuid4(), "application/pdf", path)
    assert raw.extraction_method == "ocr"
    assert raw.metadata["ocr_used"] is True
    assert "INV-1001" in raw.full_text
