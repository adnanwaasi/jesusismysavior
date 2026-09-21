from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from app.extraction.models import ExtractedField, LineItem, NormalizedInvoice, RawDocument, RawPage


LABELS: dict[str, tuple[str, ...]] = {
    "invoice_number": (r"invoice\s*(?:number|no\.?|#)\s*[:#-]?\s*(.+)$",),
    "invoice_date": (r"invoice\s*date\s*[:#-]?\s*(.+)$", r"^date\s*[:#-]\s*(.+)$"),
    "vendor": (r"(?:vendor|supplier)\s*[:#-]?\s*(.+)$",),
    "currency": (r"currency\s*[:#-]?\s*([A-Za-z]{3})\b",),
    "subtotal": (r"^sub\s*total\s*[:#-]?\s*(.+)$",),
    "tax": (r"^(?:tax|vat)\s*[:#-]?\s*(.+)$",),
    "total": (r"^(?:grand\s+)?total\s*[:#-]?\s*(.+)$",),
}


class DeterministicInvoiceFieldExtractor:
    def extract(self, document: RawDocument) -> NormalizedInvoice:
        values: dict[str, object] = {}
        evidence: list[ExtractedField] = []
        errors: dict[str, str] = {}
        for field_name, patterns in LABELS.items():
            match = self._find(document, patterns)
            if match is None:
                continue
            original, page, source_line = match
            try:
                normalized = self._normalize(field_name, original)
            except ValueError as exc:
                errors[field_name] = str(exc)
                continue
            values[field_name] = normalized
            evidence.append(ExtractedField(
                field_name=field_name,
                normalized_value=str(normalized),
                original_value=original,
                page_number=page.page_number,
                source_text=source_line,
                extraction_method=page.extraction_method,
                confidence=page.confidence,
            ))
        if "currency" not in values:
            inferred = infer_currency(document.full_text)
            if inferred:
                values["currency"] = inferred
        line_items = self._line_items(document)
        return NormalizedInvoice(**values, line_items=line_items, evidence=evidence, field_errors=errors)

    @staticmethod
    def _find(document: RawDocument, patterns: tuple[str, ...]) -> tuple[str, RawPage, str] | None:
        for page in document.pages:
            for line in page.text.splitlines():
                stripped = line.strip()
                for pattern in patterns:
                    match = re.search(pattern, stripped, re.IGNORECASE)
                    if match:
                        return match.group(1).strip(), page, stripped
        return None

    @staticmethod
    def _normalize(field_name: str, original: str):
        if field_name in {"subtotal", "tax", "total"}:
            return parse_decimal(original)
        if field_name == "invoice_date":
            return parse_date(original)
        if field_name == "currency":
            code = original.upper()
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError(f"Invalid currency value: {original}")
            return code
        return original.strip()

    def _line_items(self, document: RawDocument) -> list[LineItem]:
        items: list[LineItem] = []
        for page in document.pages:
            for line in page.text.splitlines():
                stripped = line.strip()
                if not stripped or re.search(r"description.*quantity|description.*qty", stripped, re.IGNORECASE):
                    continue
                columns = [column.strip() for column in re.split(r"\s*\|\s*|\t+", stripped)]
                if len(columns) != 4:
                    match = re.match(r"^(.+?)\s{2,}(\S+)\s{2,}(\S+)\s{2,}(\S+)$", stripped)
                    columns = list(match.groups()) if match else []
                if len(columns) != 4:
                    continue
                description, quantity, unit_price, line_total = columns
                try:
                    items.append(LineItem(
                        description=description,
                        quantity=parse_decimal(quantity),
                        unit_price=parse_decimal(unit_price),
                        line_total=parse_decimal(line_total),
                        original_quantity=quantity,
                        original_unit_price=unit_price,
                        original_line_total=line_total,
                        page_number=page.page_number,
                        source_text=stripped,
                    ))
                except ValueError:
                    continue
        return items


def parse_decimal(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9,.-]", "", value.strip())
    if not cleaned or cleaned in {"-", ".", ","}:
        raise ValueError(f"Invalid monetary value: {value}")
    negative = cleaned.startswith("-")
    cleaned = cleaned.replace("-", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        suffix = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", ".") if len(suffix) in {1, 2} else cleaned.replace(",", "")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid monetary value: {value}") from exc
    return -result if negative else result


def parse_date(value: str) -> date:
    candidate = value.strip().split()[0]
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(candidate, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid invoice date: {value}")


def infer_currency(text: str) -> str | None:
    upper = text.upper()
    for code in ("USD", "EUR", "GBP", "INR"):
        if re.search(rf"\b{code}\b", upper):
            return code
    for symbol, code in (("€", "EUR"), ("£", "GBP"), ("₹", "INR"), ("$", "USD")):
        if symbol in text:
            return code
    return None
