from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TicketStatus(str, Enum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER"
    CLOSED = "CLOSED"


class ExistingTicketReference(BaseModel):
    ticket_id: UUID
    ticket_number: str
    status: TicketStatus
    parent_ticket_id: UUID | None = None


class IncomingEmail(BaseModel):
    gmail_message_id: str = Field(min_length=1)
    gmail_thread_id: str = Field(min_length=1)
    sender_email: str = Field(min_length=3)
    subject: str = ""
    body_text: str = Field(min_length=1)
    received_at: datetime = Field(default_factory=utc_now)
    existing_ticket: ExistingTicketReference | None = None


class ProcessTicketRequest(IncomingEmail):
    ticket_id: UUID
    ticket_number: str


class DeliveryRequest(BaseModel):
    ticket_id: UUID
    gmail_inbound_message_id: str
    delivery_status: Literal["SENT", "FAILED"]
    gmail_outbound_message_id: str | None = None
    sent_at: datetime | None = None
    error_code: str | None = None

    def is_exact_repeat_of(self, other: "DeliveryRequest") -> bool:
        return self == other


class Ticket(BaseModel):
    ticket_id: UUID = Field(default_factory=uuid4)
    ticket_number: str
    gmail_thread_id: str
    parent_ticket_id: UUID | None = None
    status: TicketStatus = TicketStatus.NEW
    created_at: datetime = Field(default_factory=utc_now)


class GuardrailResult(BaseModel):
    safe_to_send: bool
    violations: list[str] = Field(default_factory=list)
    masked_fields: list[str] = Field(default_factory=list)
    text: str


class ProcessingResult(BaseModel):
    ticket_id: UUID
    ticket_number: str
    action: Literal["SEND_REPLY", "CLOSE_TICKET", "SAFE_FALLBACK", "NO_ACTION"]
    response_type: Literal["ANSWER", "NEED_MORE_INFO", "SAFE_FALLBACK"]
    subject: str
    body: str
    confidence: int = Field(ge=0, le=100)
    safe_to_send: bool
    duplicate: bool = False
    repeat_query: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    validation_decision: Literal["PASS", "NEED_MORE_INFORMATION", "SAFE_FALLBACK"]
    web_search_count: int = 0
    manager_used: bool = False
    fallback_model_used: bool = False
    processing_time_ms: int = Field(ge=0)
