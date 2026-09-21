from pathlib import Path
from uuid import uuid4

import pytest

from app.extraction.documents import (
    DocumentExtractorDispatcher,
    DocxDocumentExtractor,
    ImageDocumentExtractor,
    OcrEngine,
    PdfDocumentExtractor,
    text_is_usable,
)
from app.extraction.errors import CorruptDocument, UnsupportedDocumentType
from tests.fixtures.factory import make_digital_pdf, make_docx


def dispatcher() -> DocumentExtractorDispatcher:
    ocr = OcrEngine("eng")
    return DocumentExtractorDispatcher([PdfDocumentExtractor(ocr, 10, 40, 0.8, 150), DocxDocumentExtractor(), ImageDocumentExtractor(ocr)])


def test_pdf_text_usability_heuristic() -> None:
    assert not text_is_usable("total", 40, 0.8)
    assert text_is_usable("Invoice number INV-1001 vendor Example total 1100.00", 40, 0.8)


def test_digital_pdf_uses_embedded_text_without_ocr(tmp_path: Path) -> None:
    path = make_digital_pdf(tmp_path / "invoice.pdf")
    raw = dispatcher().extract(uuid4(), "application/pdf", path)
    assert raw.extraction_method == "pdf_text"
    assert raw.metadata["ocr_used"] is False
    assert "INV-1001" in raw.full_text


def test_docx_extracts_paragraphs_and_tables(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "invoice.docx")
    raw = dispatcher().extract(uuid4(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", path)
    assert raw.extraction_method == "docx"
    assert "Example Supplier" in raw.full_text
    assert "Item A | 2 | 200.00 | 400.00" in raw.full_text


def test_unsupported_and_corrupt_documents_fail_cleanly(tmp_path: Path) -> None:
    unsupported = tmp_path / "invoice.exe"
    unsupported.write_bytes(b"MZ-not-an-invoice")
    with pytest.raises(UnsupportedDocumentType):
        dispatcher().select("application/octet-stream", unsupported)
    corrupt = tmp_path / "invoice.pdf"
    corrupt.write_bytes(b"not a pdf")
    with pytest.raises(UnsupportedDocumentType):
        dispatcher().select("application/pdf", corrupt)
