DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invoice_status') THEN
        CREATE TYPE invoice_status AS ENUM (
            'DISCOVERED', 'QUEUED', 'EXTRACTING', 'TRANSLATING', 'VALIDATING',
            'NEEDS_REVIEW', 'COMPLETED', 'INDEXING', 'INDEXED', 'FAILED'
        );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL UNIQUE,
    checksum_sha256 CHAR(64) NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    file_size BIGINT NOT NULL CHECK (file_size >= 0),
    status invoice_status NOT NULL,
    detected_language TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS invoices_queue_index ON invoices (created_at) WHERE status = 'QUEUED';
CREATE INDEX IF NOT EXISTS invoices_status_created_index ON invoices (status, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_value TEXT,
    new_value TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_events_invoice_occurred_index ON audit_events (invoice_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS ingestion_failures (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_path TEXT NOT NULL,
    error_message TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
