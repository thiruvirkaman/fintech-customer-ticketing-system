"""Create durable LOS and ticketing schema.

Revision ID: 20260819_0001
Revises:
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260819_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSequence(sa.Sequence("ticket_number_seq", start=1)))

    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(32), primary_key=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("mobile", sa.String(32), nullable=False),
        sa.Column("pan", sa.String(10), nullable=False, unique=True),
        sa.Column("data_classification", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "applications",
        sa.Column("application_id", sa.String(32), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(32),
            sa.ForeignKey("customers.customer_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pan_status", sa.String(32), nullable=False),
        sa.Column("bureau_status", sa.String(32), nullable=False),
        sa.Column("underwriting_status", sa.String(32), nullable=False),
        sa.Column("initial_offer_status", sa.String(32), nullable=False),
        sa.Column("bank_statement_status", sa.String(32), nullable=False),
        sa.Column("final_offer_status", sa.String(32), nullable=False),
        sa.Column("offer_selection", sa.String(32), nullable=False),
        sa.Column("bank_account_status", sa.String(32), nullable=False),
        sa.Column("mandate_status", sa.String(32), nullable=False),
        sa.Column("disbursal_status", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("data_classification", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pan_status IN ('PENDING','SUCCESS','FAILURE')", name="ck_applications_pan_status"),
        sa.CheckConstraint(
            "bureau_status IN ('NOT_STARTED','PENDING','SUCCESS','FAILURE')",
            name="ck_applications_bureau_status",
        ),
        sa.CheckConstraint(
            "underwriting_status IN ('NOT_STARTED','PENDING','APPROVED','REJECTED')",
            name="ck_applications_underwriting_status",
        ),
        sa.CheckConstraint(
            "initial_offer_status IN ('NOT_STARTED','AVAILABLE','ACCEPTED','DECLINED')",
            name="ck_applications_initial_offer_status",
        ),
        sa.CheckConstraint(
            "bank_statement_status IN ('NOT_STARTED','PENDING','PROCESSING','FAILURE','SUCCESS')",
            name="ck_applications_bank_statement_status",
        ),
        sa.CheckConstraint(
            "final_offer_status IN ('NOT_STARTED','AVAILABLE','ACCEPTED','DECLINED')",
            name="ck_applications_final_offer_status",
        ),
        sa.CheckConstraint(
            "offer_selection IN ('UNDECIDED','INITIAL','FINAL')",
            name="ck_applications_offer_selection",
        ),
        sa.CheckConstraint(
            "bank_account_status IN ('NOT_STARTED','PENDING','FAILURE','SUCCESS')",
            name="ck_applications_bank_account_status",
        ),
        sa.CheckConstraint(
            "mandate_status IN ('NOT_STARTED','PENDING','FAILURE','SUCCESS')",
            name="ck_applications_mandate_status",
        ),
        sa.CheckConstraint(
            "disbursal_status IN ('NOT_STARTED','PENDING','SUCCESS')",
            name="ck_applications_disbursal_status",
        ),
    )
    op.create_index("ix_applications_customer_id", "applications", ["customer_id"])

    op.create_table(
        "ticket_identities",
        sa.Column("ticket_id", sa.Uuid(), primary_key=True),
        sa.Column("ticket_number", sa.String(32), nullable=False, unique=True),
        sa.Column("gmail_thread_id", sa.String(255), nullable=False),
        sa.Column(
            "parent_ticket_id",
            sa.Uuid(),
            sa.ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT"),
        ),
        sa.Column("customer_id", sa.String(32), sa.ForeignKey("customers.customer_id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="NEW"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('NEW','PROCESSING','WAITING_FOR_CUSTOMER','CLOSED')",
            name="ck_ticket_identities_status",
        ),
    )
    op.create_index(
        "ix_ticket_identities_thread_created",
        "ticket_identities",
        ["gmail_thread_id", "created_at"],
    )
    op.create_index(
        "uq_ticket_identities_open_thread",
        "ticket_identities",
        ["gmail_thread_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'CLOSED'"),
    )

    op.create_table(
        "email_messages",
        sa.Column("message_id", sa.Uuid(), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_ticket_id", sa.Uuid(), sa.ForeignKey("ticket_identities.ticket_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column("gmail_thread_id", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("sender_email", sa.String(320)),
        sa.Column("recipient_email", sa.String(320)),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_lock_expires_at", sa.DateTime(timezone=True)),
        sa.Column("processing_result", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("delivery_payload", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("delivery_status", sa.String(32)),
        sa.Column("delivery_error_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("direction IN ('INBOUND','OUTBOUND')", name="ck_email_messages_direction"),
        sa.UniqueConstraint("gmail_message_id", name="uq_email_messages_gmail_message_id"),
    )
    op.create_index("ix_email_messages_ticket_received", "email_messages", ["ticket_id", "received_at", "created_at"])
    op.create_index("ix_email_messages_thread_received", "email_messages", ["gmail_thread_id", "received_at", "created_at"])

    op.create_table(
        "ticket_summaries",
        sa.Column("summary_id", sa.Uuid(), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket_identities.ticket_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("customer_id", sa.String(32), sa.ForeignKey("customers.customer_id", ondelete="SET NULL")),
        sa.Column("category", sa.String(128)),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("resolution_text", sa.Text()),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_summaries_search_vector", "ticket_summaries", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "spam_events",
        sa.Column("spam_event_id", sa.Uuid(), primary_key=True),
        sa.Column("gmail_message_id", sa.String(255), unique=True),
        sa.Column("sender_email", sa.String(320), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_spam_events_sender_created", "spam_events", ["sender_email", "created_at"])

    op.create_table(
        "sender_blocklist",
        sa.Column("sender_email", sa.String(320), primary_key=True),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket_identities.ticket_id", ondelete="SET NULL")),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("step", sa.String(128)),
        sa.Column("agent", sa.String(128)),
        sa.Column("model_provider", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("fallback_used", sa.Boolean()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("confidence", sa.Integer()),
        sa.Column("decision", sa.String(128)),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("web_search_attempt", sa.Integer()),
        sa.Column("manager_used", sa.Boolean()),
        sa.Column("guardrail_result", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("delivery_status", sa.String(32)),
        sa.Column("sanitized_error_code", sa.String(128)),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_ticket_occurred", "audit_events", ["ticket_id", "occurred_at"])

    op.execute(
        """
        CREATE FUNCTION prevent_audit_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation")
    op.drop_index("ix_audit_events_ticket_occurred", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("sender_blocklist")
    op.drop_index("ix_spam_events_sender_created", table_name="spam_events")
    op.drop_table("spam_events")
    op.drop_index("ix_ticket_summaries_search_vector", table_name="ticket_summaries", postgresql_using="gin")
    op.drop_table("ticket_summaries")
    op.drop_index("ix_email_messages_thread_received", table_name="email_messages")
    op.drop_index("ix_email_messages_ticket_received", table_name="email_messages")
    op.drop_table("email_messages")
    op.drop_index("ix_ticket_identities_thread_created", table_name="ticket_identities")
    op.drop_index("uq_ticket_identities_open_thread", table_name="ticket_identities")
    op.drop_table("ticket_identities")
    op.drop_index("ix_applications_customer_id", table_name="applications")
    op.drop_table("applications")
    op.drop_table("customers")
    op.execute(sa.schema.DropSequence(sa.Sequence("ticket_number_seq")))
