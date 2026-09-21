from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from app.config import Settings
from app.extraction.documents import (
    DocumentExtractorDispatcher,
    DocxDocumentExtractor,
    ImageDocumentExtractor,
    OcrEngine,
    PdfDocumentExtractor,
)
from app.extraction.fields import DeterministicInvoiceFieldExtractor
from app.extraction.models import NormalizedInvoice, RawDocument
from app.worker_repository import ClaimedInvoice


@dataclass(frozen=True)
class ExtractionOutcome:
    raw_document: RawDocument
    normalized_invoice: NormalizedInvoice
    duration_seconds: float


class InvoiceExtractionProcessor:
    def __init__(self, dispatcher: DocumentExtractorDispatcher, field_extractor: DeterministicInvoiceFieldExtractor):
        self.dispatcher = dispatcher
        self.field_extractor = field_extractor

    def process(self, invoice: ClaimedInvoice) -> ExtractionOutcome:
        started = time.monotonic()
        raw = self.dispatcher.extract(invoice.id, invoice.mime_type, Path(invoice.stored_path))
        normalized = self.field_extractor.extract(raw)
        return ExtractionOutcome(raw, normalized, time.monotonic() - started)


def build_extraction_processor(settings: Settings) -> InvoiceExtractionProcessor:
    ocr = OcrEngine(settings.ocr_languages)
    dispatcher = DocumentExtractorDispatcher([
        PdfDocumentExtractor(ocr, settings.extraction_max_pages, settings.pdf_min_meaningful_characters, settings.pdf_min_printable_ratio, settings.ocr_dpi),
        DocxDocumentExtractor(),
        ImageDocumentExtractor(ocr),
    ])
    return InvoiceExtractionProcessor(dispatcher, DeterministicInvoiceFieldExtractor())
