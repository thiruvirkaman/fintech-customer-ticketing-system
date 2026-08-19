from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory, transactional_session
from app.ai.contracts import StageExecution
from app.db_models import (
    AuditEventRecord,
    CustomerRecord,
    EmailMessageRecord,
    TicketIdentityRecord,
    TicketSummaryRecord,
)
from app.models import DeliveryRequest, IncomingEmail, ProcessingResult, Ticket, TicketStatus
from app.repository import (
    DeliveryConflictError,
    MessageBindingError,
    MessageNotPreflightedError,
    ProcessingInProgressError,
    TicketNotFoundError,
    normalize_message_body,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ticket(record: TicketIdentityRecord) -> Ticket:
    return Ticket(
        ticket_id=record.ticket_id,
        ticket_number=record.ticket_number,
        gmail_thread_id=record.gmail_thread_id,
        parent_ticket_id=record.parent_ticket_id,
        status=TicketStatus(record.status),
        created_at=record.created_at,
    )


class PostgresTicketRepository:
    """Transactional PostgreSQL implementation of the ticket repository contract."""

    def __init__(self, database_url: str, *, processing_lock_seconds: int = 120) -> None:
        if processing_lock_seconds < 1:
            raise ValueError("processing_lock_seconds must be positive")
        self.engine = create_database_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.processing_lock_seconds = processing_lock_seconds

    def healthcheck(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    @classmethod
    def from_session_factory(
        cls, factory: sessionmaker[Session], *, processing_lock_seconds: int = 120
    ) -> "PostgresTicketRepository":
        repository = cls.__new__(cls)
        repository.session_factory = factory
        repository.engine = factory.kw["bind"]
        repository.processing_lock_seconds = processing_lock_seconds
        return repository

    @staticmethod
    def _lock(session: Session, namespace: str, value: str) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"{namespace}:{value}"},
        )

    @staticmethod
    def _next_ticket_number(session: Session) -> str:
        return session.execute(
            text("SELECT 'TKT-' || lpad(nextval('ticket_number_seq')::text, 6, '0')")
        ).scalar_one()

    @staticmethod
    def _latest_ticket_query(thread_id: str) -> Select[tuple[TicketIdentityRecord]]:
        return (
            select(TicketIdentityRecord)
            .where(TicketIdentityRecord.gmail_thread_id == thread_id)
            .order_by(TicketIdentityRecord.created_at.desc(), TicketIdentityRecord.ticket_number.desc())
            .limit(1)
            .with_for_update()
        )

    def _create_ticket(
        self, session: Session, thread_id: str, parent_ticket_id: UUID | None = None
    ) -> TicketIdentityRecord:
        record = TicketIdentityRecord(
            ticket_id=uuid4(),
            ticket_number=self._next_ticket_number(session),
            gmail_thread_id=thread_id,
            parent_ticket_id=parent_ticket_id,
            status=TicketStatus.NEW.value,
        )
        session.add(record)
        session.flush()
        self._audit(session, record.ticket_id, "TICKET_CREATED", {"parent_ticket_id": str(parent_ticket_id) if parent_ticket_id else None})
        return record

    @staticmethod
    def _audit(session: Session, ticket_id: UUID | None, event_type: str, payload: dict) -> None:
        session.add(
            AuditEventRecord(
                ticket_id=ticket_id,
                step=event_type,
                event_type=event_type,
                event_payload=payload,
            )
        )

    def preflight(self, email: IncomingEmail) -> tuple[Ticket | None, bool, bool]:
        with transactional_session(self.session_factory) as session:
            self._lock(session, "message", email.gmail_message_id)
            existing_message = session.scalar(
                select(EmailMessageRecord.message_id).where(
                    EmailMessageRecord.gmail_message_id == email.gmail_message_id
                )
            )
            if existing_message is not None:
                return None, True, False

            self._lock(session, "thread", email.gmail_thread_id)
            previous = session.scalar(self._latest_ticket_query(email.gmail_thread_id))
            if previous is not None and previous.status != TicketStatus.CLOSED.value:
                ticket_record = previous
                is_new = False
            else:
                ticket_record = self._create_ticket(
                    session,
                    email.gmail_thread_id,
                    previous.ticket_id if previous is not None else None,
                )
                is_new = True

            customer_id = session.scalar(
                select(CustomerRecord.customer_id).where(
                    func.lower(CustomerRecord.email) == email.sender_email.casefold().strip()
                )
            )
            if customer_id and ticket_record.customer_id is None:
                ticket_record.customer_id = customer_id
            if email.existing_ticket is not None:
                sheet = email.existing_ticket
                expected_parent = str(ticket_record.parent_ticket_id) if ticket_record.parent_ticket_id else None
                if (
                    sheet.ticket_id != ticket_record.ticket_id
                    or sheet.ticket_number != ticket_record.ticket_number
                    or sheet.status.value != ticket_record.status
                    or (str(sheet.parent_ticket_id) if sheet.parent_ticket_id else None) != expected_parent
                ):
                    self._audit(
                        session,
                        ticket_record.ticket_id,
                        "SHEET_RECONCILIATION_REQUIRED",
                        {
                            "sheet_ticket_id": str(sheet.ticket_id),
                            "canonical_ticket_id": str(ticket_record.ticket_id),
                        },
                    )

            session.add(
                EmailMessageRecord(
                    ticket_id=ticket_record.ticket_id,
                    original_ticket_id=ticket_record.ticket_id,
                    gmail_message_id=email.gmail_message_id,
                    gmail_thread_id=email.gmail_thread_id,
                    direction="INBOUND",
                    sender_email=email.sender_email.casefold().strip(),
                    subject=email.subject,
                    body_text=email.body_text,
                    received_at=email.received_at,
                )
            )
            self._audit(
                session,
                ticket_record.ticket_id,
                "INBOUND_MESSAGE_RESERVED",
                {"gmail_message_id": email.gmail_message_id},
            )
            return _ticket(ticket_record), False, is_new

    def begin_processing(
        self, email: IncomingEmail, ticket_id: UUID, ticket_number: str
    ) -> tuple[Ticket, ProcessingResult | None]:
        with transactional_session(self.session_factory) as session:
            reservation = session.scalar(
                select(EmailMessageRecord)
                .where(
                    EmailMessageRecord.gmail_message_id == email.gmail_message_id,
                    EmailMessageRecord.direction == "INBOUND",
                )
                .with_for_update()
            )
            if reservation is None:
                raise MessageNotPreflightedError("message must pass preflight before processing")
            self._lock(session, "thread", reservation.gmail_thread_id)

            submitted_ticket = session.get(TicketIdentityRecord, ticket_id)
            if submitted_ticket is None or submitted_ticket.ticket_number != ticket_number:
                raise TicketNotFoundError("ticket not found")
            if ticket_id not in {reservation.ticket_id, reservation.original_ticket_id} or not self._matches(
                reservation, email
            ):
                raise MessageBindingError("message payload does not match its preflight reservation")

            if reservation.processing_result is not None:
                return _ticket(session.get(TicketIdentityRecord, reservation.ticket_id)), ProcessingResult.model_validate(
                    reservation.processing_result
                )

            first_pending = session.scalar(
                select(EmailMessageRecord)
                .where(
                    EmailMessageRecord.gmail_thread_id == reservation.gmail_thread_id,
                    EmailMessageRecord.direction == "INBOUND",
                    EmailMessageRecord.processing_result.is_(None),
                )
                .order_by(EmailMessageRecord.received_at.asc(), EmailMessageRecord.created_at.asc())
                .limit(1)
                .with_for_update()
            )
            if first_pending is None or first_pending.message_id != reservation.message_id:
                raise ProcessingInProgressError("an earlier message for this thread must finish first")

            ticket_record = session.get(TicketIdentityRecord, reservation.ticket_id)
            if ticket_record.status == TicketStatus.CLOSED.value:
                ticket_record = self._move_pending_messages_to_child(session, ticket_record, reservation)

            now = _utc_now()
            active_processing = session.scalar(
                select(EmailMessageRecord.message_id)
                .where(
                    EmailMessageRecord.gmail_thread_id == reservation.gmail_thread_id,
                    EmailMessageRecord.direction == "INBOUND",
                    EmailMessageRecord.processing_result.is_(None),
                    EmailMessageRecord.processing_lock_expires_at > now,
                )
                .limit(1)
            )
            if active_processing is not None:
                raise ProcessingInProgressError("processing is already in progress for this message or thread")

            reservation.processing_started_at = now
            reservation.processing_lock_expires_at = now + timedelta(seconds=self.processing_lock_seconds)
            self._audit(
                session,
                ticket_record.ticket_id,
                "PROCESSING_STARTED",
                {"gmail_message_id": email.gmail_message_id},
            )
            return _ticket(ticket_record), None

    @staticmethod
    def _matches(record: EmailMessageRecord, email: IncomingEmail) -> bool:
        return (
            record.gmail_thread_id == email.gmail_thread_id
            and record.sender_email == email.sender_email.casefold().strip()
            and record.subject == email.subject
            and record.body_text == email.body_text
        )

    def _move_pending_messages_to_child(
        self,
        session: Session,
        closed_ticket: TicketIdentityRecord,
        first_message: EmailMessageRecord,
    ) -> TicketIdentityRecord:
        latest = session.scalar(self._latest_ticket_query(closed_ticket.gmail_thread_id))
        if latest is not None and latest.ticket_id != closed_ticket.ticket_id and latest.status != TicketStatus.CLOSED.value:
            child = latest
        else:
            child = self._create_ticket(session, closed_ticket.gmail_thread_id, closed_ticket.ticket_id)

        session.execute(
            update(EmailMessageRecord)
            .where(
                EmailMessageRecord.ticket_id == closed_ticket.ticket_id,
                EmailMessageRecord.direction == "INBOUND",
                EmailMessageRecord.processing_result.is_(None),
                EmailMessageRecord.received_at >= first_message.received_at,
            )
            .values(ticket_id=child.ticket_id)
        )
        first_message.ticket_id = child.ticket_id
        self._audit(
            session,
            child.ticket_id,
            "PENDING_MESSAGES_MOVED_TO_CHILD",
            {"parent_ticket_id": str(closed_ticket.ticket_id)},
        )
        return child

    def finish_processing(self, gmail_message_id: str, result: ProcessingResult) -> None:
        with transactional_session(self.session_factory) as session:
            message = session.scalar(
                select(EmailMessageRecord)
                .where(EmailMessageRecord.gmail_message_id == gmail_message_id)
                .with_for_update()
            )
            if message is None or message.ticket_id != result.ticket_id:
                raise MessageBindingError("processing result does not match the reserved message")
            message.processing_result = result.model_dump(mode="json")
            message.processing_started_at = None
            message.processing_lock_expires_at = None
            self._audit(
                session,
                result.ticket_id,
                "PROCESSING_FINISHED",
                {"gmail_message_id": gmail_message_id, "action": result.action},
            )

    def has_delivered_matching_message(self, email: IncomingEmail) -> bool:
        """Return true only for a new message matching a previously delivered request."""
        with self.session_factory() as session:
            candidates = session.scalars(
                select(EmailMessageRecord).where(
                    EmailMessageRecord.gmail_thread_id == email.gmail_thread_id,
                    EmailMessageRecord.gmail_message_id != email.gmail_message_id,
                    EmailMessageRecord.direction == "INBOUND",
                    EmailMessageRecord.sender_email == email.sender_email.casefold().strip(),
                    EmailMessageRecord.delivery_status == "SENT",
                )
            )
            normalized_body = normalize_message_body(email.body_text)
            return any(
                normalize_message_body(candidate.body_text) == normalized_body
                for candidate in candidates
            )

    def record_agent_audit(
        self,
        ticket_id: UUID,
        executions: list[StageExecution],
        result: ProcessingResult,
    ) -> None:
        """Persist safe per-stage metadata without prompts, PII, or raw model output."""
        with transactional_session(self.session_factory) as session:
            for execution in executions:
                session.add(
                    AuditEventRecord(
                        ticket_id=ticket_id,
                        step=execution.stage.value,
                        agent=execution.stage.value,
                        model_provider=execution.provider,
                        model=execution.model,
                        fallback_used=execution.fallback_used,
                        latency_ms=execution.latency_ms,
                        confidence=result.confidence if execution.stage.value == "VALIDATION" else None,
                        decision=result.validation_decision if execution.stage.value == "VALIDATION" else None,
                        evidence_ids=result.evidence_ids if execution.stage.value == "VALIDATION" else None,
                        web_search_attempt=result.web_search_count,
                        manager_used=result.manager_used,
                        event_type="AGENT_STAGE_COMPLETED",
                        event_payload={
                            "attempts": [attempt.model_dump(mode="json") for attempt in execution.attempts]
                        },
                    )
                )

    def record_guardrail_audit(self, execution: StageExecution, result: dict) -> None:
        with transactional_session(self.session_factory) as session:
            session.add(
                AuditEventRecord(
                    ticket_id=None,
                    step=execution.stage.value,
                    agent=execution.stage.value,
                    model_provider=execution.provider,
                    model=execution.model,
                    fallback_used=execution.fallback_used,
                    latency_ms=execution.latency_ms,
                    guardrail_result={
                        "allowed": result.get("allowed"),
                        "reason_codes": result.get("reason_codes", []),
                    },
                    event_type="INPUT_GUARDRAIL_COMPLETED",
                    event_payload={
                        "attempts": [attempt.model_dump(mode="json") for attempt in execution.attempts]
                    },
                )
            )

    def abort_processing(
        self, gmail_message_id: str, ticket_id: UUID, previous_status: TicketStatus
    ) -> None:
        with transactional_session(self.session_factory) as session:
            message = session.scalar(
                select(EmailMessageRecord)
                .where(EmailMessageRecord.gmail_message_id == gmail_message_id)
                .with_for_update()
            )
            if message is not None:
                message.processing_started_at = None
                message.processing_lock_expires_at = None
            ticket = session.get(TicketIdentityRecord, ticket_id, with_for_update=True)
            if ticket is not None:
                ticket.status = previous_status.value
                ticket.updated_at = _utc_now()
            self._audit(
                session,
                ticket_id,
                "PROCESSING_ABORTED",
                {"gmail_message_id": gmail_message_id},
            )

    def get(self, ticket_id: UUID) -> Ticket | None:
        with self.session_factory() as session:
            record = session.get(TicketIdentityRecord, ticket_id)
            return _ticket(record) if record is not None else None

    def update_status(self, ticket_id: UUID, status: TicketStatus) -> Ticket:
        with transactional_session(self.session_factory) as session:
            record = session.get(TicketIdentityRecord, ticket_id, with_for_update=True)
            if record is None:
                raise TicketNotFoundError("ticket not found")
            old_status = record.status
            record.status = status.value
            record.updated_at = _utc_now()
            record.closed_at = _utc_now() if status == TicketStatus.CLOSED else None
            if old_status != status.value:
                self._audit(
                    session,
                    ticket_id,
                    "TICKET_STATUS_CHANGED",
                    {"from": old_status, "to": status.value},
                )
            session.flush()
            return _ticket(record)

    def record_delivery(self, delivery: DeliveryRequest) -> bool:
        payload = delivery.model_dump(mode="json")
        with transactional_session(self.session_factory) as session:
            self._lock(session, "message", delivery.gmail_inbound_message_id)
            ticket = session.get(TicketIdentityRecord, delivery.ticket_id)
            if ticket is None:
                raise TicketNotFoundError("ticket not found")
            inbound = session.scalar(
                select(EmailMessageRecord)
                .where(
                    EmailMessageRecord.gmail_message_id == delivery.gmail_inbound_message_id,
                    EmailMessageRecord.direction == "INBOUND",
                )
                .with_for_update()
            )
            if inbound is None or inbound.ticket_id != delivery.ticket_id:
                raise MessageBindingError("delivery does not match a preflighted ticket message")
            if inbound.processing_result is None:
                raise DeliveryConflictError("delivery cannot be recorded before processing completes")

            if inbound.delivery_payload is not None:
                if inbound.delivery_payload == payload:
                    return True
                if not (
                    inbound.delivery_status == "FAILED" and delivery.delivery_status == "SENT"
                ):
                    raise DeliveryConflictError("delivery confirmation conflicts with the existing record")

            if delivery.delivery_status == "SENT":
                if not delivery.gmail_outbound_message_id:
                    raise DeliveryConflictError("gmail_outbound_message_id is required for SENT")
                existing_outbound = session.scalar(
                    select(EmailMessageRecord.message_id).where(
                        EmailMessageRecord.gmail_message_id == delivery.gmail_outbound_message_id
                    )
                )
                if existing_outbound is not None:
                    raise DeliveryConflictError("outbound Gmail message ID is already recorded")
                result = ProcessingResult.model_validate(inbound.processing_result)
                session.add(
                    EmailMessageRecord(
                        ticket_id=delivery.ticket_id,
                        original_ticket_id=delivery.ticket_id,
                        gmail_message_id=delivery.gmail_outbound_message_id,
                        gmail_thread_id=inbound.gmail_thread_id,
                        direction="OUTBOUND",
                        recipient_email=inbound.sender_email,
                        subject=result.subject,
                        body_text=result.body,
                        sent_at=delivery.sent_at or _utc_now(),
                    )
                )
                self._upsert_ticket_summary(session, ticket, inbound, result)
            inbound.delivery_payload = payload
            inbound.delivery_status = delivery.delivery_status
            inbound.delivery_error_code = delivery.error_code
            self._audit(
                session,
                delivery.ticket_id,
                "DELIVERY_CONFIRMED",
                {
                    "gmail_inbound_message_id": delivery.gmail_inbound_message_id,
                    "delivery_status": delivery.delivery_status,
                },
            )
            try:
                session.flush()
            except IntegrityError as exc:
                raise DeliveryConflictError("delivery violates message idempotency") from exc
            return False

    @staticmethod
    def _upsert_ticket_summary(
        session: Session,
        ticket: TicketIdentityRecord,
        inbound: EmailMessageRecord,
        result: ProcessingResult,
    ) -> None:
        resolution = result.body if ticket.status == TicketStatus.CLOSED.value else None
        summary_text = (
            f"Issue: {inbound.subject or 'customer support request'}\n"
            f"Customer intent: {result.response_type}\n"
            "Relevant LOS stage: determined from the current ticket conversation\n"
            f"Actions or advice already given: {result.body}\n"
            f"Unresolved items: {'none' if resolution else 'awaiting customer confirmation'}\n"
            f"Resolution: {resolution or 'not yet confirmed'}"
        )
        summary = session.scalar(
            select(TicketSummaryRecord)
            .where(TicketSummaryRecord.ticket_id == ticket.ticket_id)
            .with_for_update()
        )
        if summary is None:
            session.add(
                TicketSummaryRecord(
                    ticket_id=ticket.ticket_id,
                    customer_id=ticket.customer_id,
                    category=result.response_type,
                    summary_text=summary_text,
                    resolution_text=resolution,
                    search_vector=func.to_tsvector("english", summary_text),
                )
            )
        else:
            summary.customer_id = ticket.customer_id
            summary.category = result.response_type
            summary.summary_text = summary_text
            summary.resolution_text = resolution
            summary.search_vector = func.to_tsvector("english", summary_text)
            summary.updated_at = func.now()
