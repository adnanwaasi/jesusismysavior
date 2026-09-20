import pytest

from app.state_machine import InvoiceStatus, InvalidStateTransition, ensure_transition


def test_discovered_can_be_queued() -> None:
    ensure_transition(InvoiceStatus.DISCOVERED, InvoiceStatus.QUEUED)


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(InvalidStateTransition):
        ensure_transition(InvoiceStatus.QUEUED, InvoiceStatus.COMPLETED)
