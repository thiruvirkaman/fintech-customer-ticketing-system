from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import transactional_session
from app.db_models import EmailMessageRecord, TicketIdentityRecord, TicketSummaryRecord


class ConversationMessage(BaseModel):
    direction: str
    subject: str
    body_text: str
    occurred_at: datetime | None


class TicketMemory(BaseModel):
    current_ticket_history: list[ConversationMessage]
    relevant_closed_summaries: list[str]


class MemoryRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def retrieve(
        self,
        ticket_id: UUID,
        *,
        customer_id: str | None,
        query: str,
        summary_limit: int = 3,
    ) -> TicketMemory:
        with self._session_factory() as session:
            messages = session.scalars(
                select(EmailMessageRecord)
                .where(EmailMessageRecord.ticket_id == ticket_id)
                .order_by(EmailMessageRecord.created_at.asc())
            ).all()
            summaries: list[str] = []
            if customer_id and query.strip():
                search_query = func.plainto_tsquery("english", query)
                summaries = list(
                    session.scalars(
                        select(TicketSummaryRecord.summary_text)
                        .join(
                            TicketIdentityRecord,
                            TicketIdentityRecord.ticket_id == TicketSummaryRecord.ticket_id,
                        )
                        .where(
                            TicketSummaryRecord.customer_id == customer_id,
                            TicketSummaryRecord.ticket_id != ticket_id,
                            TicketIdentityRecord.status == "CLOSED",
                            TicketSummaryRecord.search_vector.op("@@")(search_query),
                        )
                        .order_by(
                            func.ts_rank(TicketSummaryRecord.search_vector, search_query).desc(),
                            TicketSummaryRecord.updated_at.desc(),
                        )
                        .limit(summary_limit)
                    ).all()
                )
            return TicketMemory(
                current_ticket_history=[
                    ConversationMessage(
                        direction=message.direction,
                        subject=message.subject,
                        body_text=message.body_text,
                        occurred_at=message.received_at or message.sent_at or message.created_at,
                    )
                    for message in messages
                ],
                relevant_closed_summaries=summaries,
            )

    def upsert_summary(
        self,
        ticket_id: UUID,
        *,
        customer_id: str | None,
        category: str | None,
        summary_text: str,
        resolution_text: str | None = None,
    ) -> None:
        with transactional_session(self._session_factory) as session:
            summary = session.scalar(
                select(TicketSummaryRecord)
                .where(TicketSummaryRecord.ticket_id == ticket_id)
                .with_for_update()
            )
            if summary is None:
                summary = TicketSummaryRecord(
                    ticket_id=ticket_id,
                    customer_id=customer_id,
                    category=category,
                    summary_text=summary_text,
                    resolution_text=resolution_text,
                    search_vector=func.to_tsvector("english", summary_text),
                )
                session.add(summary)
            else:
                summary.customer_id = customer_id
                summary.category = category
                summary.summary_text = summary_text
                summary.resolution_text = resolution_text
                summary.search_vector = func.to_tsvector("english", summary_text)
                summary.updated_at = func.now()
