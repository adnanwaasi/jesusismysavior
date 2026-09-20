from __future__ import annotations

from enum import StrEnum


class InvoiceStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    TRANSLATING = "TRANSLATING"
    VALIDATING = "VALIDATING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    COMPLETED = "COMPLETED"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[InvoiceStatus, frozenset[InvoiceStatus]] = {
    InvoiceStatus.DISCOVERED: frozenset({InvoiceStatus.QUEUED, InvoiceStatus.FAILED}),
    InvoiceStatus.QUEUED: frozenset({InvoiceStatus.EXTRACTING, InvoiceStatus.FAILED}),
    InvoiceStatus.EXTRACTING: frozenset({InvoiceStatus.TRANSLATING, InvoiceStatus.FAILED, InvoiceStatus.QUEUED}),
    InvoiceStatus.TRANSLATING: frozenset({InvoiceStatus.VALIDATING, InvoiceStatus.FAILED, InvoiceStatus.QUEUED}),
    InvoiceStatus.VALIDATING: frozenset({InvoiceStatus.COMPLETED, InvoiceStatus.NEEDS_REVIEW, InvoiceStatus.FAILED, InvoiceStatus.QUEUED}),
    InvoiceStatus.NEEDS_REVIEW: frozenset({InvoiceStatus.VALIDATING, InvoiceStatus.FAILED}),
    InvoiceStatus.COMPLETED: frozenset({InvoiceStatus.INDEXING}),
    InvoiceStatus.INDEXING: frozenset({InvoiceStatus.INDEXED, InvoiceStatus.FAILED, InvoiceStatus.COMPLETED}),
    InvoiceStatus.INDEXED: frozenset(),
    InvoiceStatus.FAILED: frozenset({InvoiceStatus.QUEUED}),
}


class InvalidStateTransition(ValueError):
    pass


def ensure_transition(current: InvoiceStatus, target: InvoiceStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"Cannot transition invoice from {current} to {target}")
