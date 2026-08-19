import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CustomerRecord(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    mobile: Mapped[str] = mapped_column(String(32), nullable=False)
    pan: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ApplicationRecord(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("pan_status IN ('PENDING','SUCCESS','FAILURE')", name="ck_applications_pan_status"),
        CheckConstraint(
            "bureau_status IN ('NOT_STARTED','PENDING','SUCCESS','FAILURE')",
            name="ck_applications_bureau_status",
        ),
        CheckConstraint(
            "underwriting_status IN ('NOT_STARTED','PENDING','APPROVED','REJECTED')",
            name="ck_applications_underwriting_status",
        ),
        CheckConstraint(
            "initial_offer_status IN ('NOT_STARTED','AVAILABLE','ACCEPTED','DECLINED')",
            name="ck_applications_initial_offer_status",
        ),
        CheckConstraint(
            "bank_statement_status IN ('NOT_STARTED','PENDING','PROCESSING','FAILURE','SUCCESS')",
            name="ck_applications_bank_statement_status",
        ),
        CheckConstraint(
            "final_offer_status IN ('NOT_STARTED','AVAILABLE','ACCEPTED','DECLINED')",
            name="ck_applications_final_offer_status",
        ),
        CheckConstraint(
            "offer_selection IN ('UNDECIDED','INITIAL','FINAL')",
            name="ck_applications_offer_selection",
        ),
        CheckConstraint(
            "bank_account_status IN ('NOT_STARTED','PENDING','FAILURE','SUCCESS')",
            name="ck_applications_bank_account_status",
        ),
        CheckConstraint(
            "mandate_status IN ('NOT_STARTED','PENDING','FAILURE','SUCCESS')",
            name="ck_applications_mandate_status",
        ),
        CheckConstraint(
            "disbursal_status IN ('NOT_STARTED','PENDING','SUCCESS')",
            name="ck_applications_disbursal_status",
        ),
        Index("ix_applications_customer_id", "customer_id"),
    )

    application_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="RESTRICT"), nullable=False
    )
    pan_status: Mapped[str] = mapped_column(String(32), nullable=False)
    bureau_status: Mapped[str] = mapped_column(String(32), nullable=False)
    underwriting_status: Mapped[str] = mapped_column(String(32), nullable=False)
    initial_offer_status: Mapped[str] = mapped_column(String(32), nullable=False)
    bank_statement_status: Mapped[str] = mapped_column(String(32), nullable=False)
    final_offer_status: Mapped[str] = mapped_column(String(32), nullable=False)
    offer_selection: Mapped[str] = mapped_column(String(32), nullable=False)
    bank_account_status: Mapped[str] = mapped_column(String(32), nullable=False)
    mandate_status: Mapped[str] = mapped_column(String(32), nullable=False)
    disbursal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TicketIdentityRecord(Base):
    __tablename__ = "ticket_identities"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW','PROCESSING','WAITING_FOR_CUSTOMER','CLOSED')",
            name="ck_ticket_identities_status",
        ),
        Index("ix_ticket_identities_thread_created", "gmail_thread_id", "created_at"),
        Index(
            "uq_ticket_identities_open_thread",
            "gmail_thread_id",
            unique=True,
            postgresql_where=text("status <> 'CLOSED'"),
        ),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT")
    )
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW", server_default="NEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessageRecord(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        CheckConstraint("direction IN ('INBOUND','OUTBOUND')", name="ck_email_messages_direction"),
        UniqueConstraint("gmail_message_id", name="uq_email_messages_gmail_message_id"),
        Index("ix_email_messages_ticket_received", "ticket_id", "received_at", "created_at"),
        Index("ix_email_messages_thread_received", "gmail_thread_id", "received_at", "created_at"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT"), nullable=False
    )
    original_ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_email: Mapped[str | None] = mapped_column(String(320))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_result: Mapped[dict | None] = mapped_column(JSONB)
    delivery_payload: Mapped[dict | None] = mapped_column(JSONB)
    delivery_status: Mapped[str | None] = mapped_column(String(32))
    delivery_error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TicketSummaryRecord(Base):
    __tablename__ = "ticket_summaries"
    __table_args__ = (Index("ix_ticket_summaries_search_vector", "search_vector", postgresql_using="gin"),)

    summary_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ticket_identities.ticket_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id", ondelete="SET NULL"))
    category: Mapped[str | None] = mapped_column(String(128))
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_text: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SpamEventRecord(Base):
    __tablename__ = "spam_events"
    __table_args__ = (Index("ix_spam_events_sender_created", "sender_email", "created_at"),)

    spam_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SenderBlocklistRecord(Base):
    __tablename__ = "sender_blocklist"

    sender_email: Mapped[str] = mapped_column(String(320), primary_key=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_ticket_occurred", "ticket_id", "occurred_at"),)

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket_identities.ticket_id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    step: Mapped[str | None] = mapped_column(String(128))
    agent: Mapped[str | None] = mapped_column(String(128))
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    fallback_used: Mapped[bool | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(128))
    evidence_ids: Mapped[list | None] = mapped_column(JSONB)
    web_search_attempt: Mapped[int | None] = mapped_column(Integer)
    manager_used: Mapped[bool | None]
    guardrail_result: Mapped[dict | None] = mapped_column(JSONB)
    delivery_status: Mapped[str | None] = mapped_column(String(32))
    sanitized_error_code: Mapped[str | None] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
