from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ExtractionMethod = Literal["pdf_text", "ocr", "docx"]


class RawPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    extraction_method: ExtractionMethod
    confidence: Decimal | None = Field(default=None, ge=0, le=100)


class RawDocument(BaseModel):
    invoice_id: UUID
    source_type: str
    extraction_method: ExtractionMethod
    pages: list[RawPage]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)


class ExtractedField(BaseModel):
    field_name: str
    normalized_value: str
    original_value: str
    page_number: int | None = Field(default=None, ge=1)
    source_text: str
    extraction_method: ExtractionMethod
    confidence: Decimal | None = Field(default=None, ge=0, le=100)


class LineItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    original_quantity: str | None = None
    original_unit_price: str | None = None
    original_line_total: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    source_text: str | None = None


class NormalizedInvoice(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_number: str | None = None
    invoice_date: date | None = None
    vendor: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    evidence: list[ExtractedField] = Field(default_factory=list)
    field_errors: dict[str, str] = Field(default_factory=dict)
