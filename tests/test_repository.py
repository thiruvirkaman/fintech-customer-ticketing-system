import pytest

from app.models import (
    DeliveryRequest,
    IncomingEmail,
    ProcessingResult,
    ProcessTicketRequest,
    TicketStatus,
)
from app.repository import InMemoryTicketRepository, ProcessingInProgressError


def email(message_id: str, thread_id: str = "thread-1") -> IncomingEmail:
    return IncomingEmail(gmail_message_id=message_id, gmail_thread_id=thread_id, sender_email="demo@example.com", body_text="question")


def test_duplicate_message_is_rejected_and_open_thread_is_reused() -> None:
    repo = InMemoryTicketRepository()
    first, duplicate, is_new = repo.preflight(email("message-1"))
    assert first is not None and not duplicate and is_new
    _, duplicate, is_new = repo.preflight(email("message-1"))
    assert duplicate
    second, duplicate, is_new = repo.preflight(email("message-2"))
    assert second == first and not duplicate and not is_new


def test_only_new_messages_matching_a_delivered_request_are_repeat_queries() -> None:
    repo = InMemoryTicketRepository()
    first_email = email("repeat-message-1", "repeat-thread")
    ticket, _, _ = repo.preflight(first_email)
    request = ProcessTicketRequest(
        **first_email.model_dump(),
        ticket_id=ticket.ticket_id,
        ticket_number=ticket.ticket_number,
    )
    repo.begin_processing(request, ticket.ticket_id, ticket.ticket_number)
    repo.finish_processing(
        first_email.gmail_message_id,
        ProcessingResult(
            ticket_id=ticket.ticket_id,
            ticket_number=ticket.ticket_number,
            action="SEND_REPLY",
            response_type="ANSWER",
            subject="Re: Question",
            body="Answer",
            confidence=90,
            safe_to_send=True,
            validation_decision="PASS",
            processing_time_ms=1,
        ),
    )
    repo.record_delivery(
        DeliveryRequest(
            ticket_id=ticket.ticket_id,
            gmail_inbound_message_id=first_email.gmail_message_id,
            delivery_status="SENT",
            gmail_outbound_message_id="repeat-outbound-1",
        )
    )

    repeated = email("repeat-message-2", "repeat-thread").model_copy(
        update={
            "body_text": (
                "  QUESTION  \n\n"
                "On Wed, 20 Aug 2026 at 12:00, Support wrote:\n"
                "> Answer"
            )
        }
    )
    repo.preflight(repeated)
    assert repo.has_delivered_matching_message(repeated) is True

    different = email("repeat-message-3", "repeat-thread").model_copy(
        update={"body_text": "different question"}
    )
    repo.preflight(different)
    assert repo.has_delivered_matching_message(different) is False


def test_closed_thread_creates_linked_ticket() -> None:
    repo = InMemoryTicketRepository()
    first, _, _ = repo.preflight(email("message-1"))
    repo.update_status(first.ticket_id, TicketStatus.CLOSED)
    second, _, is_new = repo.preflight(email("message-2"))
    assert second.ticket_id != first.ticket_id
    assert second.parent_ticket_id == first.ticket_id
    assert is_new


def test_same_thread_cannot_process_concurrently() -> None:
    repo = InMemoryTicketRepository()
    first_email = email("message-1")
    second_email = email("message-2")
    ticket, _, _ = repo.preflight(first_email)
    reused, _, _ = repo.preflight(second_email)
    assert reused.ticket_id == ticket.ticket_id

    first_request = ProcessTicketRequest(**first_email.model_dump(), ticket_id=ticket.ticket_id, ticket_number=ticket.ticket_number)
    second_request = ProcessTicketRequest(**second_email.model_dump(), ticket_id=ticket.ticket_id, ticket_number=ticket.ticket_number)
    repo.begin_processing(first_request, ticket.ticket_id, ticket.ticket_number)
    with pytest.raises(ProcessingInProgressError):
        repo.begin_processing(second_request, ticket.ticket_id, ticket.ticket_number)


def test_same_thread_messages_cannot_process_out_of_order() -> None:
    repo = InMemoryTicketRepository()
    first_email = email("ordered-message-1")
    second_email = email("ordered-message-2")
    ticket, _, _ = repo.preflight(first_email)
    repo.preflight(second_email)
    second_request = ProcessTicketRequest(**second_email.model_dump(), ticket_id=ticket.ticket_id, ticket_number=ticket.ticket_number)
    with pytest.raises(ProcessingInProgressError, match="earlier message"):
        repo.begin_processing(second_request, ticket.ticket_id, ticket.ticket_number)
