# AI Invoice Auditor — Project Architecture & Delivery Plan

## 1. Architectural principle

**PostgreSQL is the source of truth for workflow state. The filesystem is the source of truth for original invoice binaries.**

This keeps files immutable and independently recoverable while making processing, retries, auditability, and concurrency durable and queryable.

### Scope decisions

- Use PostgreSQL as the durable work queue; do **not** introduce RabbitMQ or Kafka for the initial system.
- Treat “agents” as deterministic services/workers where possible. Reserve LLM reasoning for reporting and answer generation, not arithmetic or workflow control.
- Process, validate, and persist an invoice before it is indexed for RAG.
- Preserve source extraction and translations separately; never lose the original-language evidence.
- Record changes as append-only audit events and corrections instead of overwriting AI output.

## 2. End-to-end architecture

```text
Vendor / User
     │
     ▼
incoming/ on persistent storage
     │
     ▼
Ingestion worker ──► checksum + duplicate check + immutable file storage
     │                         │
     │                         └────────► PostgreSQL: invoice + audit events
     ▼
PostgreSQL-backed work queue
     │
     ▼
Extraction → Translation → Validation → Completed / Needs review / Failed
     │                                      │
     └──────────────────► Indexing ─────────┘
                                             │
Auditor question → RAG/reporting service → Answer with evidence and invoice references
```

## 3. File storage design

```text
/data/
├── incoming/                         # Folder watched by ingestion
└── invoices/                         # Permanent, immutable originals
    └── 2026/
        └── 09/
            ├── <uuid>.pdf
            ├── <uuid>.png
            └── ...
```

### Ingestion lifecycle

```text
incoming/vendor_invoice.pdf
  → detect file
  → calculate SHA-256
  → check for duplicate
  → assign invoice UUID
  → copy/store as invoices/YYYY/MM/<uuid>.<extension>
  → create invoice record and audit events
```

Do not model the workflow by moving originals among `queued/`, `processing/`, or `completed/` folders. Once stored, the original file must never be modified. Its database status describes where it is in the processing lifecycle.

## 4. Workflow state machine

```text
DISCOVERED
    ↓
QUEUED
    ↓
EXTRACTING
    ↓
TRANSLATING
    ↓
VALIDATING
    ↓
COMPLETED

At any relevant stage:
  → NEEDS_REVIEW  → human correction → QUEUED (revalidation path)
  → FAILED        → retry or manual intervention
```

Recommended operational fields are `processing_started_at`, `completed_at`, `retry_count`, `last_error`, and an optional processing lease/worker identifier. Every state transition must emit an audit event.

## 5. PostgreSQL schema plan

### Core tables

| Table | Purpose |
| --- | --- |
| `invoices` | File identity, immutable storage location, checksum, state, and lifecycle timestamps. |
| `invoice_extractions` | Raw extracted fields, original language values, translated values, confidence, and source locations. |
| `invoice_lines` | Normalized line-item data used by validation and reporting. |
| `validation_results` | Validation run results and rules evaluated. |
| `discrepancies` | Actionable validation failures and their resolution state. |
| `corrections` | Human changes to effective values without changing AI output. |
| `audit_events` | Append-only event history for all material operations. |
| `rag_chunks` | Indexed text, metadata, and pgvector embeddings for read-only retrieval. |

### `invoices` (minimum fields)

```text
id UUID PRIMARY KEY
original_filename TEXT NOT NULL
stored_path TEXT NOT NULL
checksum_sha256 CHAR(64) NOT NULL UNIQUE
mime_type TEXT NOT NULL
file_size BIGINT NOT NULL
status TEXT/ENUM NOT NULL
language TEXT
created_at TIMESTAMPTZ NOT NULL
processing_started_at TIMESTAMPTZ
completed_at TIMESTAMPTZ
retry_count INT NOT NULL DEFAULT 0
error_message TEXT
```

The checksum `UNIQUE` constraint is the final duplicate-protection guarantee. An application-level lookup provides a friendly result; the database constraint protects against races.

### Queue claim pattern

```sql
SELECT *
FROM invoices
WHERE status = 'QUEUED'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Workers claim work in a transaction, update it to the appropriate in-progress state, and commit. Multiple workers can therefore safely pull from PostgreSQL without processing the same invoice.

### Audit event model

```text
audit_events
────────────────────────────
id
invoice_id
event_type
actor
occurred_at
old_value
new_value
metadata JSONB
```

Example history:

```text
14:03:01 FILE_DISCOVERED
14:03:01 CHECKSUM_VERIFIED
14:03:02 EXTRACTION_STARTED
14:03:05 EXTRACTION_COMPLETED
14:03:05 LANGUAGE_DETECTED (de)
14:03:07 TRANSLATION_COMPLETED
14:03:08 VALIDATION_FAILED
14:11:42 HUMAN_CORRECTION
14:11:43 REVALIDATION_STARTED
14:11:44 VALIDATION_PASSED
```

## 6. Processing services

| Specification term | Implementation role | Responsibility |
| --- | --- | --- |
| Monitor Agent | Ingestion worker | Detect files, checksum, deduplicate, store immutable original, create invoice record. |
| Extraction Agent | Extraction service | Extract text/fields from PDF, DOCX, image, or scanned PDF. |
| Translation Agent | Translation service | Detect language and produce English representation while retaining source values. |
| Validation Agent | Validation service | Deterministically check totals, currency, quantities, prices, and ERP data. |
| Indexing Agent | Embedding/index service | Index completed invoice evidence for retrieval. |
| Reporting Agent | RAG service | Retrieve evidence and generate answers with invoice references. |

### Normalized invoice contract

Every extractor produces the same internal model before subsequent processing:

```json
{
  "invoice_number": "INV-38291",
  "invoice_date": "2026-09-17",
  "vendor": "Example GmbH",
  "currency": "EUR",
  "subtotal": 1200.0,
  "tax": 228.0,
  "total": 1428.0,
  "line_items": [
    {
      "description": "Industrial valve",
      "quantity": 4,
      "unit_price": 300.0,
      "total": 1200.0
    }
  ]
}
```

Use a Python Pydantic model to enforce this contract.

### Extraction routes

```text
PDF          → PDF parser ──┐
DOCX         → DOCX parser ─┼──► NormalizedInvoice
Image        → OCR ─────────┤
Scanned PDF  → OCR ─────────┘
```

## 7. Translation, provenance, and human review

Store raw extraction independently from its translated and normalized values.

```text
Original invoice
  → raw extraction (source language)
  → translation
  → normalized English representation
```

Each extracted field should preserve at least:

```text
invoice_id, field_name, original_value, translated_value,
confidence, source_page
```

When a human corrects a value, create a correction record rather than updating the AI extraction.

```text
AI value: total = 1530
Human correction: total = 1580
Effective value for validation/reporting: 1580
Audit trail: field, old value, new value, auditor, timestamp, reason
```

The correction triggers revalidation and its own append-only audit events.

## 8. Validation rules

Validation is deterministic code, not an LLM task. Example:

```python
expected = quantity * unit_price
if abs(expected - line_total) > tolerance:
    record_discrepancy(...)
```

Initial rules:

- Line-item `quantity × unit_price` equals line total within tolerance.
- Sum of line totals, tax, subtotal, and grand total agree.
- Currency is valid and consistent.
- Required fields are present and have sufficient confidence.
- Where applicable, invoice fields match ERP records.

Outcomes are `COMPLETED`, `NEEDS_REVIEW`, or `FAILED`; discrepancies remain linked to the invoice and validation run.

## 9. RAG and reporting boundary

RAG is downstream and read-oriented. It must not be part of invoice ingestion, extraction, translation, or validation.

```text
Invoice → extract → translate → validate → persist → index

Auditor question
  → structured PostgreSQL filters + pgvector search
  → relevant invoice evidence
  → LLM answer with invoice references
```

Use PostgreSQL with `pgvector` for `rag_chunks` initially, avoiding a separate vector database. Retrieval metadata should include invoice ID, vendor, date, language, validation status, discrepancy type, and source-page pointers so every answer can cite evidence.

## 10. Container and persistence architecture

```text
Host
  ./data/invoices ── bind mount ──► application containers (/data/invoices)

Docker Compose
  monitor / ingestion worker
  processing worker(s): extraction, translation, validation, indexing
  FastAPI API
  Streamlit UI
  PostgreSQL + pgvector
      └── postgres_data Docker named volume
```

Persistence mechanisms:

| Data | Mechanism | Reason |
| --- | --- | --- |
| Original invoices | Host bind mount: `./data/invoices:/data/invoices` | Files are useful to inspect and back up directly. |
| PostgreSQL internals | Docker named volume: `postgres_data:/var/lib/postgresql/data` | Database files are managed implementation data. |

The Streamlit UI calls FastAPI; FastAPI and workers access PostgreSQL. The browser/UI should not access PostgreSQL directly.

## 11. Delivery roadmap: build vertically

Do not begin by creating six independent services. Deliver a complete, reliable path first, then extend it.

| Phase | Deliverable | Exit criteria |
| --- | --- | --- |
| 0 | State machine and schema | Migration creates all core state, audit, and invoice identity structures. |
| 1 | Durable ingestion vertical slice | A stable dropped file is checksummed, deduplicated, immutably stored, recorded with audit events, and ends in `QUEUED`. |
| 2 | Worker/state machine | Transactional PostgreSQL job claiming, bounded retries, stale-job recovery, and failure handling. |
| 3 | Structured extraction | Normalized fields and line items are persisted with provenance. |
| 4 | Language/translation | Language detection and English fields are stored without losing originals. |
| 5 | Validation | Deterministic rules create discrepancies and correct terminal states. |
| 6 | Human review | Corrections are append-only, calculate effective values, and trigger revalidation. |
| 7 | RAG/indexing | Completed invoices are indexed; answers include source evidence. |
| 8 | Streamlit dashboard | Users can view status, evidence, discrepancies, corrections, and reports. |
| 9 | Deployment refinement | Components are separated into required Compose containers and operational checks are documented. |

## 12. First implementation priority

Design and migrate the state machine plus PostgreSQL schema first. Every other component depends on the invoice identity, state transitions, audit semantics, and data contracts defined there. The first vertical slice must end at `QUEUED`; extraction begins only after durable queue processing is implemented.
