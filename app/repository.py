from dataclasses import dataclass, replace
from threading import RLock
from uuid import UUID

from app.models import DeliveryRequest, IncomingEmail, ProcessingResult, Ticket, TicketStatus


class RepositoryError(Exception):
    """Base class for repository contract failures."""


class TicketNotFoundError(RepositoryError):
    pass


class MessageNotPreflightedError(RepositoryError):
    pass


class MessageBindingError(RepositoryError):
    pass


class ProcessingInProgressError(RepositoryError):
    pass


class DeliveryConflictError(RepositoryError):
    pass


@dataclass(frozen=True)
class MessageReservation:
    ticket_id: UUID
    original_ticket_id: UUID
    gmail_thread_id: str
    sender_email: str
    subject: str
    body_text: str

    @classmethod
    def from_email(cls, ticket_id: UUID, email: IncomingEmail) -> "MessageReservation":
        return cls(
            ticket_id=ticket_id,
            original_ticket_id=ticket_id,
            gmail_thread_id=email.gmail_thread_id,
            sender_email=email.sender_email.casefold().strip(),
            subject=email.subject,
            body_text=email.body_text,
        )

    def matches(self, email: IncomingEmail) -> bool:
        return (
            self.gmail_thread_id == email.gmail_thread_id
            and self.sender_email == email.sender_email.casefold().strip()
            and self.subject == email.subject
            and self.body_text == email.body_text
        )


class InMemoryTicketRepository:
    """Process-local demo storage. Replace with PostgreSQL before production use."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sequence = 0
        self._tickets: dict[UUID, Ticket] = {}
        self._thread_ticket_ids: dict[str, list[UUID]] = {}
        self._thread_message_ids: dict[str, list[str]] = {}
        self._reservations: dict[str, MessageReservation] = {}
        self._ticket_message_ids: dict[UUID, list[str]] = {}
        self._processing_message_ids: set[str] = set()
        self._processing_ticket_ids: set[UUID] = set()
        self._processing_results: dict[str, ProcessingResult] = {}
        self._deliveries: dict[tuple[UUID, str], DeliveryRequest] = {}

    def preflight(self, email: IncomingEmail) -> tuple[Ticket | None, bool, bool]:
        with self._lock:
            if email.gmail_message_id in self._reservations:
                return None, True, False

            ticket_ids = self._thread_ticket_ids.get(email.gmail_thread_id, [])
            previous = self._tickets[ticket_ids[-1]] if ticket_ids else None
            if previous and previous.status != TicketStatus.CLOSED:
                ticket = previous
                is_new = False
            else:
                self._sequence += 1
                ticket = Ticket(
                    ticket_number=f"TKT-{self._sequence:06d}",
                    gmail_thread_id=email.gmail_thread_id,
                    parent_ticket_id=previous.ticket_id if previous else None,
                )
                self._tickets[ticket.ticket_id] = ticket
                self._thread_ticket_ids.setdefault(email.gmail_thread_id, []).append(ticket.ticket_id)
                is_new = True

            self._reservations[email.gmail_message_id] = MessageReservation.from_email(ticket.ticket_id, email)
            self._thread_message_ids.setdefault(email.gmail_thread_id, []).append(email.gmail_message_id)
            self._ticket_message_ids.setdefault(ticket.ticket_id, []).append(email.gmail_message_id)
            return ticket, False, is_new

    def begin_processing(self, email: IncomingEmail, ticket_id: UUID, ticket_number: str) -> tuple[Ticket, ProcessingResult | None]:
        with self._lock:
            reservation = self._reservations.get(email.gmail_message_id)
            if reservation is None:
                raise MessageNotPreflightedError("message must pass preflight before processing")
            submitted_ticket = self._tickets.get(ticket_id)
            if submitted_ticket is None or submitted_ticket.ticket_number != ticket_number:
                raise TicketNotFoundError("ticket not found")
            if ticket_id not in {reservation.ticket_id, reservation.original_ticket_id} or not reservation.matches(email):
                raise MessageBindingError("message payload does not match its preflight reservation")

            cached = self._processing_results.get(email.gmail_message_id)
            if cached is not None:
                return self._tickets[cached.ticket_id], cached
            ticket = self._tickets[reservation.ticket_id]
            first_pending_message_id = next(
                (
                    message_id
                    for message_id in self._thread_message_ids[email.gmail_thread_id]
                    if message_id not in self._processing_results
                ),
                None,
            )
            if first_pending_message_id != email.gmail_message_id:
                raise ProcessingInProgressError("an earlier message for this thread must finish first")
            if ticket.status == TicketStatus.CLOSED:
                ticket = self._move_pending_messages_to_child(ticket, email.gmail_message_id)
            if email.gmail_message_id in self._processing_message_ids or ticket.ticket_id in self._processing_ticket_ids:
                raise ProcessingInProgressError("processing is already in progress for this message or thread")

            self._processing_message_ids.add(email.gmail_message_id)
            self._processing_ticket_ids.add(ticket.ticket_id)
            return ticket, None

    def _move_pending_messages_to_child(self, closed_ticket: Ticket, first_message_id: str) -> Ticket:
        message_ids = self._ticket_message_ids[closed_ticket.ticket_id]
        first_index = message_ids.index(first_message_id)
        pending_message_ids = [
            message_id for message_id in message_ids[first_index:] if message_id not in self._processing_results
        ]
        latest_ticket_id = self._thread_ticket_ids[closed_ticket.gmail_thread_id][-1]
        latest_ticket = self._tickets[latest_ticket_id]
        if latest_ticket.ticket_id != closed_ticket.ticket_id and latest_ticket.status != TicketStatus.CLOSED:
            child = latest_ticket
            existing_child_messages = self._ticket_message_ids[child.ticket_id]
            self._ticket_message_ids[child.ticket_id] = pending_message_ids + existing_child_messages
        else:
            self._sequence += 1
            child = Ticket(
                ticket_number=f"TKT-{self._sequence:06d}",
                gmail_thread_id=closed_ticket.gmail_thread_id,
                parent_ticket_id=closed_ticket.ticket_id,
            )
            self._tickets[child.ticket_id] = child
            self._thread_ticket_ids[closed_ticket.gmail_thread_id].append(child.ticket_id)
            self._ticket_message_ids[child.ticket_id] = pending_message_ids
        self._ticket_message_ids[closed_ticket.ticket_id] = [
            message_id for message_id in message_ids if message_id not in pending_message_ids
        ]
        for message_id in pending_message_ids:
            self._reservations[message_id] = replace(self._reservations[message_id], ticket_id=child.ticket_id)
        return child

    def finish_processing(self, gmail_message_id: str, result: ProcessingResult) -> None:
        with self._lock:
            self._processing_message_ids.discard(gmail_message_id)
            self._processing_ticket_ids.discard(result.ticket_id)
            self._processing_results[gmail_message_id] = result

    def abort_processing(self, gmail_message_id: str, ticket_id: UUID, previous_status: TicketStatus) -> None:
        with self._lock:
            self._processing_message_ids.discard(gmail_message_id)
            self._processing_ticket_ids.discard(ticket_id)
            ticket = self._tickets.get(ticket_id)
            if ticket is not None:
                ticket.status = previous_status

    def get(self, ticket_id: UUID) -> Ticket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def update_status(self, ticket_id: UUID, status: TicketStatus) -> Ticket:
        with self._lock:
            ticket = self._tickets[ticket_id]
            ticket.status = status
            return ticket

    def record_delivery(self, delivery: DeliveryRequest) -> bool:
        with self._lock:
            ticket = self._tickets.get(delivery.ticket_id)
            if ticket is None:
                raise TicketNotFoundError("ticket not found")
            reservation = self._reservations.get(delivery.gmail_inbound_message_id)
            if reservation is None or reservation.ticket_id != delivery.ticket_id:
                raise MessageBindingError("delivery does not match a preflighted ticket message")
            if delivery.gmail_inbound_message_id not in self._processing_results:
                raise DeliveryConflictError("delivery cannot be recorded before processing completes")

            key = (delivery.ticket_id, delivery.gmail_inbound_message_id)
            existing = self._deliveries.get(key)
            if existing is not None:
                if delivery.is_exact_repeat_of(existing):
                    return True
                if existing.delivery_status == "FAILED" and delivery.delivery_status == "SENT":
                    self._deliveries[key] = delivery.model_copy(deep=True)
                    return False
                raise DeliveryConflictError("delivery confirmation conflicts with the existing record")
            self._deliveries[key] = delivery.model_copy(deep=True)
            return False


repository = InMemoryTicketRepository()
