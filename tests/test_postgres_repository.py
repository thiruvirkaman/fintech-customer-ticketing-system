import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.database import create_database_engine, create_session_factory
from app.db_models import ApplicationRecord, CustomerRecord, EmailMessageRecord
from app.models import DeliveryRequest, IncomingEmail, ProcessingResult, TicketStatus
from app.postgres_repository import PostgresTicketRepository
from app.seed_database import seed_database


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture()
def repository() -> PostgresTicketRepository:
    parsed = make_url(TEST_DATABASE_URL)
    if not (parsed.database or "").endswith("_test"):
        pytest.fail("integration tests require a database name ending in _test")
    engine = create_database_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE audit_events, ticket_summaries, email_messages, ticket_identities, "
            "applications, customers, spam_events, sender_blocklist RESTART IDENTITY CASCADE"
        )
        connection.exec_driver_sql("ALTER SEQUENCE ticket_number_seq RESTART WITH 1")
    yield PostgresTicketRepository.from_session_factory(create_session_factory(engine))
    engine.dispose()


def _email(message_id: str, thread_id: str = "thread-db") -> IncomingEmail:
    return IncomingEmail(
        gmail_message_id=message_id,
        gmail_thread_id=thread_id,
        sender_email="demo@example.com",
        subject="Bank statement",
        body_text="Why is a bank statement required?",
    )


def _result(ticket_id, ticket_number: str) -> ProcessingResult:
    return ProcessingResult(
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        action="SEND_REPLY",
        response_type="ANSWER",
        subject="Re: Bank statement",
        body="Synthetic grounded response",
        confidence=90,
        safe_to_send=True,
        evidence_ids=["SYN-TEST"],
        validation_decision="PASS",
        processing_time_ms=1,
    )


def test_postgres_repository_persists_idempotent_lifecycle(repository: PostgresTicketRepository) -> None:
    incoming = _email("db-message-1")
    ticket, duplicate, is_new = repository.preflight(incoming)
    assert ticket is not None and not duplicate and is_new
    assert ticket.ticket_number == "TKT-000001"
    assert repository.preflight(incoming) == (None, True, False)

    processing_ticket, cached = repository.begin_processing(
        incoming, ticket.ticket_id, ticket.ticket_number
    )
    assert processing_ticket.ticket_id == ticket.ticket_id
    assert cached is None
    repository.update_status(ticket.ticket_id, TicketStatus.PROCESSING)
    result = _result(ticket.ticket_id, ticket.ticket_number)
    repository.update_status(ticket.ticket_id, TicketStatus.WAITING_FOR_CUSTOMER)
    repository.finish_processing(incoming.gmail_message_id, result)

    _, cached = repository.begin_processing(incoming, ticket.ticket_id, ticket.ticket_number)
    assert cached == result
    delivery = DeliveryRequest(
        ticket_id=ticket.ticket_id,
        gmail_inbound_message_id=incoming.gmail_message_id,
        delivery_status="SENT",
        gmail_outbound_message_id="db-outbound-1",
    )
    assert repository.record_delivery(delivery) is False
    assert repository.record_delivery(delivery) is True

    with repository.session_factory() as session:
        directions = session.scalars(
            select(EmailMessageRecord.direction).order_by(EmailMessageRecord.created_at)
        ).all()
        assert directions == ["INBOUND", "OUTBOUND"]


def test_closed_thread_creates_linked_postgres_ticket(repository: PostgresTicketRepository) -> None:
    first, _, _ = repository.preflight(_email("db-close-1", "db-closed-thread"))
    repository.update_status(first.ticket_id, TicketStatus.CLOSED)
    second, duplicate, is_new = repository.preflight(_email("db-close-2", "db-closed-thread"))
    assert not duplicate and is_new
    assert second.ticket_id != first.ticket_id
    assert second.parent_ticket_id == first.ticket_id
    assert second.ticket_number == "TKT-000002"


def test_seed_database_is_transactional_and_idempotent(repository: PostgresTicketRepository) -> None:
    assert seed_database(TEST_DATABASE_URL, Path("data")) == {"customers": 20, "applications": 20}
    assert seed_database(TEST_DATABASE_URL, Path("data")) == {"customers": 20, "applications": 20}
    with repository.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CustomerRecord)) == 20
        assert session.scalar(select(func.count()).select_from(ApplicationRecord)) == 20
