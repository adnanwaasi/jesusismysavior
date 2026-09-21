CREATE TABLE IF NOT EXISTS document_extractions (
    invoice_id UUID PRIMARY KEY REFERENCES invoices(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('pdf_text', 'ocr', 'docx')),
    full_text TEXT NOT NULL,
    pages JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS extracted_invoices (
    invoice_id UUID PRIMARY KEY REFERENCES invoices(id) ON DELETE CASCADE,
    invoice_number TEXT,
    invoice_date DATE,
    vendor TEXT,
    currency CHAR(3),
    subtotal NUMERIC(20, 4),
    tax NUMERIC(20, 4),
    total NUMERIC(20, 4),
    field_errors JSONB NOT NULL DEFAULT '{}'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoice_line_items (
    id UUID PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 1),
    description TEXT NOT NULL,
    quantity NUMERIC(20, 6),
    unit_price NUMERIC(20, 4),
    line_total NUMERIC(20, 4),
    original_quantity TEXT,
    original_unit_price TEXT,
    original_line_total TEXT,
    source_page INTEGER,
    source_text TEXT,
    UNIQUE (invoice_id, position)
);

CREATE INDEX IF NOT EXISTS invoice_line_items_invoice_index ON invoice_line_items (invoice_id, position);

CREATE TABLE IF NOT EXISTS extracted_fields (
    id UUID PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    original_value TEXT NOT NULL,
    source_page INTEGER,
    source_text TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence NUMERIC(6, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS extracted_fields_invoice_field_index ON extracted_fields (invoice_id, field_name);
