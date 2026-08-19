import pytest

from app.models import IncomingEmail, ProcessTicketRequest, TicketStatus
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
