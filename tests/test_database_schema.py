from app.db_models import Base


def test_required_postgresql_tables_are_declared() -> None:
    assert {
        "customers",
        "applications",
        "ticket_identities",
        "email_messages",
        "ticket_summaries",
        "spam_events",
        "sender_blocklist",
        "audit_events",
    }.issubset(Base.metadata.tables)


def test_message_and_ticket_identifiers_are_unique() -> None:
    email_constraints = Base.metadata.tables["email_messages"].constraints
    ticket_constraints = Base.metadata.tables["ticket_identities"].constraints
    assert any(
        constraint.name == "uq_email_messages_gmail_message_id"
        for constraint in email_constraints
    )
    assert Base.metadata.tables["ticket_identities"].c.ticket_number.unique is True
    assert any(
        foreign_key.target_fullname == "ticket_identities.ticket_id"
        for foreign_key in Base.metadata.tables["email_messages"].c.original_ticket_id.foreign_keys
    )
    assert any(
        foreign_key.target_fullname == "ticket_identities.ticket_id"
        for foreign_key in Base.metadata.tables["ticket_identities"].c.parent_ticket_id.foreign_keys
    )
