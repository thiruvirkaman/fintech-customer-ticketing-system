import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import transactional_session
from app.db_models import AuditEventRecord, SenderBlocklistRecord, SpamEventRecord
from app.models import IncomingEmail


HIGH_CONFIDENCE_PATTERNS = {
    "CRYPTO_PROMOTION": re.compile(r"\b(?:guaranteed crypto|crypto giveaway|double your bitcoin)\b", re.I),
    "UNSOLICITED_SEO": re.compile(r"\b(?:buy backlinks|first page of google guaranteed|seo guest posts? for sale)\b", re.I),
    "CREDENTIAL_PHISHING": re.compile(r"\bverify your (?:password|login credentials?)\b", re.I),
}
URL_PATTERN = re.compile(r"https?://", re.I)


class SpamDecision(BaseModel):
    spam: bool
    blocked: bool
    reason_codes: list[str] = Field(default_factory=list)


def classify_high_confidence_spam(subject: str, body_text: str) -> list[str]:
    text = f"{subject}\n{body_text}"
    reasons = [reason for reason, pattern in HIGH_CONFIDENCE_PATTERNS.items() if pattern.search(text)]
    if len(URL_PATTERN.findall(text)) >= 5:
        reasons.append("EXCESSIVE_LINKS")
    return reasons


class SpamService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        threshold: int = 3,
        window_hours: int = 24,
    ) -> None:
        if threshold < 1 or window_hours < 1:
            raise ValueError("spam threshold and window must be positive")
        self._session_factory = session_factory
        self._threshold = threshold
        self._window = timedelta(hours=window_hours)

    def evaluate(self, email: IncomingEmail, *, now: datetime | None = None) -> SpamDecision:
        checked_at = now or datetime.now(timezone.utc)
        sender = email.sender_email.casefold().strip()
        with transactional_session(self._session_factory) as session:
            block = session.get(SenderBlocklistRecord, sender, with_for_update=True)
            if block and block.active and (block.expires_at is None or block.expires_at > checked_at):
                return SpamDecision(spam=True, blocked=True, reason_codes=["SENDER_BLOCKED"])

            reasons = classify_high_confidence_spam(email.subject, email.body_text)
            if not reasons:
                return SpamDecision(spam=False, blocked=False)

            previous_event = session.scalar(
                select(SpamEventRecord).where(
                    SpamEventRecord.gmail_message_id == email.gmail_message_id
                )
            )
            if previous_event is not None:
                return SpamDecision(
                    spam=True,
                    blocked=bool(block and block.active),
                    reason_codes=list(previous_event.reason_codes),
                )

            session.add(
                SpamEventRecord(
                    gmail_message_id=email.gmail_message_id,
                    sender_email=sender,
                    reason_codes=reasons,
                    created_at=checked_at,
                )
            )
            recent_count = session.scalar(
                select(func.count(SpamEventRecord.spam_event_id)).where(
                    SpamEventRecord.sender_email == sender,
                    SpamEventRecord.created_at >= checked_at - self._window,
                )
            ) or 0
            # The pending event is not visible to the count until autoflush; include it explicitly.
            should_block = recent_count + 1 >= self._threshold
            if should_block:
                if block is None:
                    block = SenderBlocklistRecord(
                        sender_email=sender,
                        reason="HIGH_CONFIDENCE_SPAM_THRESHOLD",
                        active=True,
                        blocked_at=checked_at,
                    )
                    session.add(block)
                else:
                    block.active = True
                    block.reason = "HIGH_CONFIDENCE_SPAM_THRESHOLD"
                    block.blocked_at = checked_at
                    block.expires_at = None
                session.add(
                    AuditEventRecord(
                        ticket_id=None,
                        event_type="SENDER_BLOCKED",
                        event_payload={"reason": block.reason},
                    )
                )
            return SpamDecision(spam=True, blocked=should_block, reason_codes=reasons)

    def unblock(self, sender_email: str) -> bool:
        sender = sender_email.casefold().strip()
        with transactional_session(self._session_factory) as session:
            block = session.get(SenderBlocklistRecord, sender, with_for_update=True)
            if block is None or not block.active:
                return False
            block.active = False
            session.add(
                AuditEventRecord(
                    ticket_id=None,
                    event_type="SENDER_UNBLOCKED",
                    event_payload={"reason": "MANUAL_REVERSAL"},
                )
            )
            return True
