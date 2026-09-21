from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.extraction.fields import DeterministicInvoiceFieldExtractor, parse_date, parse_decimal
from app.extraction.models import LineItem, NormalizedInvoice, RawDocument, RawPage


def raw_invoice(text: str) -> RawDocument:
    return RawDocument(invoice_id=uuid4(), source_type="application/pdf", extraction_method="pdf_text", pages=[RawPage(page_number=1, text=text, extraction_method="pdf_text")])


def test_decimal_and_date_normalization_preserve_exact_values() -> None:
    assert parse_decimal("$1,530.25") == Decimal("1530.25")
    assert parse_decimal("€1.530,00") == Decimal("1530.00")
    assert parse_date("20/09/2026") == date(2026, 9, 20)


def test_structured_extraction_creates_line_items_and_provenance() -> None:
    document = raw_invoice("""Invoice Number: INV-1001
Invoice Date: 2026-09-20
Vendor: Example Supplier
Currency: USD
Description | Quantity | Unit Price | Line Total
Item A | 2 | 200.00 | 400.00
Item B | 3 | 200.00 | 600.00
Subtotal: 1000.00
Total: 1100.00""")
    invoice = DeterministicInvoiceFieldExtractor().extract(document)

    assert invoice.invoice_number == "INV-1001"
    assert invoice.total == Decimal("1100.00")
    assert invoice.tax is None
    assert len(invoice.line_items) == 2
    total_evidence = next(item for item in invoice.evidence if item.field_name == "total")
    assert total_evidence.original_value == "1100.00"
    assert total_evidence.source_text == "Total: 1100.00"


def test_pydantic_model_uses_decimal_and_rejects_invalid_currency() -> None:
    invoice = NormalizedInvoice(total=Decimal("0.10"), line_items=[LineItem(description="Item", quantity=Decimal("0.1"))])
    assert invoice.total + Decimal("0.20") == Decimal("0.30")
    with pytest.raises(ValidationError):
        NormalizedInvoice(currency="US")


def test_present_but_unparseable_field_is_distinct_from_absent() -> None:
    invoice = DeterministicInvoiceFieldExtractor().extract(raw_invoice("Invoice Date: unknown\nVendor: Example"))
    assert invoice.invoice_date is None
    assert "invoice_date" in invoice.field_errors
    assert invoice.tax is None
    assert "tax" not in invoice.field_errors
