# AI Invoice Auditor — File-wise Explanation

This document explains the project file by file, including each file’s purpose, the logic it contains, and how it fits into the invoice-auditing architecture.

## 1. Project overview

The project is the foundation of an invoice-auditing system.

The currently implemented workflow is:

```text
Invoice file
    ↓
data/incoming/
    ↓
Monitor detects a stable file
    ↓
Calculate checksum and check duplicates
    ↓
Store an immutable copy
    ↓
Create a PostgreSQL invoice record
    ↓
Set status to QUEUED
    ↓
Move the incoming file to processed/ or duplicates/
```

The future system will add extraction, translation, validation, human review, search, reporting, and an API. Those features are described in the architecture plan but are not implemented yet.

## 2. Root-level files

### `README.md`

The project’s quick-start and architecture guide.

It explains:

- What the current milestone implements.
- How to run the project with Docker.
- Where incoming and permanent invoice files are stored.
- The current state machine.
- How to run the tests.
- The clean-architecture layer structure.
- Which features are deliberately postponed.

This is the best file for someone who wants to run the project quickly.

### `requirements.txt`

Contains the Python runtime dependencies:

- `SQLAlchemy` — database engine and SQL execution.
- `psycopg` — PostgreSQL driver.
- `python-json-logger` — structured JSON logging.

FastAPI and Uvicorn are not currently included because the API layer has not been implemented.

### `requirements-dev.txt`

Contains development and testing dependencies. It is used when installing the project locally for test execution.

### `Dockerfile`

Builds the monitor container.

Its main responsibilities are:

1. Start from a small Python image.
2. Set `/app` as the working directory.
3. Install runtime dependencies.
4. Copy the application and migration files into the image.
5. Run as a non-root `app` user.
6. Start `python -m app.monitor`.

The container currently runs the directory monitor, not a web server.

### `docker-compose.yml`

Defines the local services:

```text
postgres
monitor
```

The `postgres` service runs PostgreSQL and stores database data in a named Docker volume.

The `monitor` service runs the invoice-ingestion worker and mounts:

```text
./data:/data
```

This makes incoming and stored invoice files available on the host machine.

The monitor waits for PostgreSQL to pass its health check before starting.

### `.env.example`

Provides example environment variables for local configuration, when present.

The real `.env` file should not be committed because it can contain passwords or environment-specific settings.

## 3. Planning files

### `plan/ai-invoice-auditor-project-architecture-and-delivery-plan.md`

The main architecture and delivery plan.

It defines the intended system, including:

- PostgreSQL as the workflow-state source of truth.
- The filesystem as the source of truth for original invoice binaries.
- The planned workflow states.
- The future database tables.
- Extraction, translation, validation, indexing, and reporting responsibilities.
- The future FastAPI and UI boundary.

This document is broader than the current implementation. It describes the target architecture, while the current code mainly implements the ingestion milestone.

### `plan/project-file-wise-explanation.md`

This document.

It explains the repository at file level and connects individual files to the broader architecture.

## 4. Application package

### `app/__init__.py`

Marks `app` as the Python application package.

It currently contains only a package description and no runtime logic.

## 5. Domain layer

The domain layer contains rules and data structures that should not depend on PostgreSQL, Docker, or a specific storage provider.

### `app/domain/__init__.py`

Marks the domain directory as a Python package.

### `app/domain/models.py`

Contains small domain data objects.

#### `FileObservation`

Stores the file information captured during monitoring:

- File size.
- Modification timestamp in nanoseconds.
- First time the monitor saw the file.

The monitor uses this information to decide whether a file is stable enough to process.

#### `IngestionResult`

Describes the result of an ingestion attempt.

Possible result types include:

- `ingested` — a new invoice was stored.
- `duplicate` — the file matched an existing invoice.
- `failed` — processing failed and the failure was recorded.

It can also contain the new or existing invoice UUID.

### `app/domain/file_policy.py`

Contains file-related domain rules.

#### `SUPPORTED_EXTENSIONS`

Defines the invoice formats accepted by the current system:

```text
.pdf, .docx, .png, .jpg, .jpeg, .tif, .tiff, .bmp
```

#### `sha256_file`

Reads a file in chunks and calculates its SHA-256 checksum.

Reading in chunks avoids loading a potentially large invoice entirely into memory.

#### `safe_extension`

Normalizes a filename extension to lowercase and returns it only if it is supported.

For example:

```text
INVOICE.PDF → .pdf
invoice.exe → ""
```

#### `file_is_stable`

Checks that:

- The size has not changed.
- The modification time has not changed.
- The file has been observed for the required stability duration.
- The file’s own modification time is old enough.

This prevents the worker from processing a file while it is still being copied.

## 6. Application layer

The application layer contains use cases. It coordinates business operations while depending on abstract interfaces instead of concrete infrastructure.

### `app/application/__init__.py`

Marks the application directory as a Python package.

### `app/application/ports.py`

Defines the interfaces required by the ingestion use case.

#### `InvoiceRepository`

Describes database operations needed by ingestion:

- Find an invoice by checksum.
- Create a queued invoice.
- Record a duplicate event.
- Record an ingestion failure.

The use case does not need to know that PostgreSQL is being used.

#### `OriginalFileStore`

Describes file-storage operations:

- Store an immutable original.
- Archive an incoming file.
- Remove a temporary stored file when persistence fails.

The current implementation uses the local filesystem, but this contract could later be implemented by object storage such as S3.

### `app/application/ingest_invoice.py`

Contains the main ingestion use case: `IngestInvoice`.

Its `execute` method coordinates the complete ingestion flow:

1. Read the incoming file size.
2. Reject files larger than the configured maximum.
3. Calculate the SHA-256 checksum.
4. Ask the repository whether that checksum already exists.
5. Archive duplicates without creating a second invoice.
6. Generate a new invoice UUID for new files.
7. Store an immutable copy.
8. Create the PostgreSQL invoice record with status `QUEUED`.
9. Archive the original incoming file as processed.
10. Record and return failures if anything goes wrong.

This is the central business workflow for the current milestone.

The use case is intentionally independent of concrete database and filesystem implementations.

## 7. Infrastructure layer

The infrastructure layer implements the interfaces used by the application layer.

### `app/infrastructure/__init__.py`

Marks the infrastructure directory as a Python package.

### `app/infrastructure/files.py`

Contains the local filesystem adapter: `LocalOriginalFileStore`.

#### `store`

Copies the incoming file to:

```text
data/invoices/YYYY/MM/<uuid>.<extension>
```

It writes to a temporary `.partial` file first, flushes the data, calls `fsync`, and then atomically renames the temporary file.

This reduces the risk of leaving a partially written permanent invoice file.

The completed file is marked read-only with permission `0444`.

#### `archive`

Moves the original incoming file into a category directory such as:

```text
data/incoming/processed/
data/incoming/duplicates/
```

The archived name includes a timestamp and random UUID to avoid collisions.

#### `remove`

Deletes a stored file if database persistence fails after the file was copied.

### `app/infrastructure/postgres.py`

Contains the PostgreSQL adapter: `PostgresInvoiceRepository`.

#### `find_by_checksum`

Searches the `invoices` table for an existing checksum.

#### `create_queued_invoice`

Creates the invoice record initially as `DISCOVERED`, then validates the state transition to `QUEUED` and updates the record.

It also records audit events for:

- `FILE_DISCOVERED`
- `CHECKSUM_CALCULATED`
- `FILE_INGESTED`

The operation runs in a database transaction.

#### `record_duplicate`

Adds a `DUPLICATE_DETECTED` audit event to the existing invoice.

#### `record_failure`

Stores an ingestion failure in the `ingestion_failures` table.

## 8. Compatibility facade

### `app/ingestion.py`

This file preserves the older public import path while the codebase moves to the cleaner architecture.

It re-exports commonly used functions and classes:

- `FileObservation`
- `IngestionResult`
- `file_is_stable`
- `safe_extension`
- `sha256_file`

It also defines `InvoiceIngestor`, which wires together:

- `IngestInvoice`
- `PostgresInvoiceRepository`
- `LocalOriginalFileStore`

New code should preferably depend directly on the application and infrastructure packages. Existing callers can continue importing from `app.ingestion`.

## 9. Runtime monitor

### `app/monitor.py`

Contains the directory-monitoring process and the executable entrypoint.

### `IncomingDirectoryMonitor`

The monitor:

1. Ensures `data/incoming/` exists.
2. Lists visible files in that directory.
3. Tracks observations in memory.
4. Detects files whose size or modification time has changed.
5. Waits until a file is stable.
6. Passes the stable file to the ingestion use case.

### `run_forever`

Runs the scan repeatedly with the configured polling interval.

### `main`

Builds the runtime dependencies:

1. Load settings.
2. Configure logging.
3. Create the database engine.
4. Apply database migrations.
5. Create the PostgreSQL adapter.
6. Create the local file-storage adapter.
7. Create the ingestion use case.
8. Start monitoring.

This is the current Docker entrypoint.

## 10. Configuration and database support

### `app/config.py`

Defines the immutable `Settings` configuration object.

Configuration comes from environment variables, including:

- `DATABASE_URL`
- `DATA_ROOT`
- `MONITOR_POLL_INTERVAL_SECONDS`
- `FILE_STABILITY_SECONDS`
- `MAX_FILE_SIZE_BYTES`
- `LOG_LEVEL`

It also exposes calculated paths:

- `incoming_dir`
- `invoices_dir`

### `app/db.py`

Contains database setup helpers.

#### `create_db_engine`

Creates a SQLAlchemy engine with connection health checking enabled.

#### `apply_migrations`

Creates a `schema_migrations` table, checks which SQL migrations were already applied, and executes new migration files in sorted order.

This allows the application to initialize or upgrade the database automatically at startup.

### `app/state_machine.py`

Defines invoice statuses and valid transitions.

Statuses include:

```text
DISCOVERED
QUEUED
EXTRACTING
TRANSLATING
VALIDATING
NEEDS_REVIEW
COMPLETED
INDEXING
INDEXED
FAILED
```

`ensure_transition` raises `InvalidStateTransition` when code attempts an invalid workflow change.

For example:

```text
DISCOVERED → QUEUED       valid
QUEUED → COMPLETED        invalid
```

### `app/logging.py`

Configures structured JSON logging.

Logs include fields such as:

- Timestamp.
- Log level.
- Logger name.
- Message.
- Contextual fields such as invoice ID or source path.

Structured logs are useful when the application is running inside Docker or a log aggregation system.

## 11. Database migrations

### `migrations/0001_phase0_phase1.sql`

Creates the initial database schema.

### `invoices`

Stores invoice identity, file metadata, state, timestamps, retry information, and errors.

Important constraints include:

- UUID primary key.
- Unique stored file path.
- Unique SHA-256 checksum.
- Non-negative file size.
- Valid PostgreSQL invoice status.

### `audit_events`

Stores append-only invoice history.

Each event references an invoice and includes event type, actor, timestamp, old value, new value, and JSON metadata.

### `ingestion_failures`

Stores failures that happen before a usable invoice record exists, such as an oversized or unreadable incoming file.

## 12. Tests

### `tests/unit/test_ingestion.py`

Tests pure ingestion-related rules:

- SHA-256 calculation.
- File stability behavior.
- Supported extension normalization.

### `tests/unit/test_monitor.py`

Checks that hidden marker files such as `.gitkeep` are ignored by the directory monitor.

### `tests/unit/test_state_machine.py`

Checks valid and invalid invoice state transitions.

The current test suite focuses on unit-level behavior. Integration tests for PostgreSQL persistence, queue claiming, extraction, validation, review, and RAG are planned for later phases.

## 13. End-to-end example

Suppose a user copies this file into the incoming directory:

```text
data/incoming/acme-invoice.pdf
```

The monitor sees it and records its size and modification time.

After the file remains unchanged long enough, the monitor calls `IngestInvoice.execute`.

The use case calculates the checksum and checks PostgreSQL.

If it is new, the file is copied to something like:

```text
data/invoices/2026/09/550e8400-e29b-41d4-a716-446655440000.pdf
```

PostgreSQL receives a record with status `QUEUED`, and audit events are written.

Finally, the original incoming file is moved to:

```text
data/incoming/processed/<timestamp>_<random-id>_acme-invoice.pdf
```

The original permanent invoice copy remains untouched and is ready for a future extraction worker.

## 14. Current versus future responsibility

### Implemented now

- Directory monitoring.
- Stable-file detection.
- File-size limits.
- Supported file checking.
- SHA-256 checksums.
- Duplicate detection.
- Immutable local storage.
- PostgreSQL invoice registration.
- State initialization at `QUEUED`.
- Audit events.
- Failure recording.
- Docker runtime.

### Planned later

- PostgreSQL-backed worker queue claiming.
- PDF, image, DOCX, and OCR extraction.
- Translation with original-value preservation.
- Normalized invoice and line-item models.
- Deterministic financial validation.
- Human corrections and review workflows.
- Embeddings and RAG search.
- Reporting service.
- FastAPI backend.
- User interface.

## 15. Short summary

The project is currently a reliable invoice intake service. `app/monitor.py` finds files, the domain layer applies file rules, `app/application/ingest_invoice.py` coordinates ingestion, and the infrastructure adapters store the file and database record. The rest of the planned AI-auditing platform will build on invoices that have safely reached the `QUEUED` state.
