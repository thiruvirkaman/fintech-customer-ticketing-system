import re
import logging
from hashlib import sha256
from time import monotonic

from app.config import settings
from app.ai.pipeline import AgentPipeline
from app.guardrails import inspect_input, inspect_output
from app.knowledge import BANK_STATEMENT_EVIDENCE, Evidence, is_registered_evidence
from app.models import ProcessTicketRequest, ProcessingResult, TicketStatus
from app.repository import InMemoryTicketRepository


COURTESY_WORDS = r"(?:thanks?|thank you|please|okay|ok)"
RESOLUTION_PATTERNS = (
    re.compile(rf"^(?:{COURTESY_WORDS}[, ]+)*(?:resolved|fixed|sorted)(?:[, ]+{COURTESY_WORDS})*$"),
    re.compile(r"\bthat (?:worked|fixed it)\b"),
    re.compile(r"\b(?:the )?(?:issue|problem|it|everything|this) (?:is|has been) (?:now )?(?:resolved|fixed|sorted|working)\b"),
    re.compile(r"\beverything works now\b"),
)
UNRESOLVED_PATTERN = re.compile(
    r"\b(?:not|never|isn't|is not|wasn't|was not|hasn't|has not|haven't|have not|unresolved)\b.{0,40}\b(?:resolved|fixed|sorted|working)\b"
)
RENEWED_FAILURE_PATTERN = re.compile(
    r"\b(?:but|however|although|yet|again|still)\b.{0,60}\b(?:fail(?:s|ed|ing)?|broke|broken|error|issue|problem|not working)\b"
)
logger = logging.getLogger(__name__)


def is_explicit_resolution(text: str) -> bool:
    normalized = " ".join(text.casefold().strip(" .!\n\t").split())
    if "?" in text or UNRESOLVED_PATTERN.search(normalized) or RENEWED_FAILURE_PATTERN.search(normalized):
        return False
    if re.search(r"\b(?:resolved|fixed|worked|working|sorted)\b.{0,30}\b(?:but|however|although|yet)\b", normalized):
        return False
    return any(pattern.search(normalized) for pattern in RESOLUTION_PATTERNS)


def validate_grounded_answer(question: str, answer: str, evidence: list[Evidence], *, complete: bool) -> int:
    """Validate the demo answer against immutable, registered evidence."""
    if not evidence or not complete:
        return 0
    if any(not is_registered_evidence(item) for item in evidence):
        return 0
    normalized_question = question.casefold()
    if not any(term in normalized_question for item in evidence for term in item.supported_question_terms):
        return 0
    if len(evidence) != 1 or answer != evidence[0].customer_answer:
        return 0
    evidence_relevance = 30
    groundedness = 30
    question_coverage = 20
    source_consistency = 10
    ambiguity = 0 if all(item.source_type == "SYNTHETIC_INTERNAL" for item in evidence) else 10
    return evidence_relevance + groundedness + question_coverage + source_consistency + ambiguity


class TicketOrchestrator:
    def __init__(self, repository: InMemoryTicketRepository, agent_pipeline: AgentPipeline | None = None) -> None:
        self.repository = repository
        self.agent_pipeline = agent_pipeline

    def process(self, request: ProcessTicketRequest) -> ProcessingResult:
        started = monotonic()
        ticket, cached = self.repository.begin_processing(request, request.ticket_id, request.ticket_number)
        if cached is not None:
            return cached.model_copy(
                update={
                    "action": "NO_ACTION",
                    "subject": "",
                    "body": "",
                    "safe_to_send": False,
                    "duplicate": True,
                    "processing_time_ms": max(0, round((monotonic() - started) * 1000)),
                }
            )

        effective_request = request.model_copy(
            update={"ticket_id": ticket.ticket_id, "ticket_number": ticket.ticket_number}
        )
        previous_status = ticket.status
        try:
            self.repository.update_status(ticket.ticket_id, TicketStatus.PROCESSING)
            allowed, _ = inspect_input(f"{effective_request.subject}\n{effective_request.body_text}")
            if not allowed:
                result = self._result(
                    effective_request,
                    "SAFE_FALLBACK",
                    "SAFE_FALLBACK",
                    "We cannot process instructions that request protected system information. Please describe your loan application support question.",
                    settings.confidence_threshold - 1,
                    "SAFE_FALLBACK",
                    [],
                    started,
                )
                return self._finish(effective_request, result, TicketStatus.WAITING_FOR_CUSTOMER)

            normalized = effective_request.body_text.casefold().strip(" .!\n\t")
            if is_explicit_resolution(effective_request.body_text):
                result = self._result(
                    effective_request,
                    "CLOSE_TICKET",
                    "ANSWER",
                    f"Thank you for confirming that the issue is resolved. Ticket {ticket.ticket_number} is now closed.",
                    100,
                    "PASS",
                    [f"CUSTOMER-MESSAGE-{sha256(effective_request.gmail_message_id.encode()).hexdigest()[:12]}"],
                    started,
                )
                return self._finish(effective_request, result, TicketStatus.CLOSED)

            if self.agent_pipeline is not None:
                try:
                    pipeline_result = self.agent_pipeline.process(
                        ticket_id=effective_request.ticket_id,
                        ticket_number=effective_request.ticket_number,
                        sender_email=effective_request.sender_email,
                        subject=effective_request.subject,
                        customer_question=effective_request.body_text,
                    )
                    action = (
                        "SAFE_FALLBACK"
                        if pipeline_result.response_type == "SAFE_FALLBACK"
                        else "SEND_REPLY"
                    )
                    validation_decision = (
                        pipeline_result.validation_decision
                        if pipeline_result.validation_decision in {"PASS", "NEED_MORE_INFORMATION", "SAFE_FALLBACK"}
                        else "SAFE_FALLBACK"
                    )
                    result = self._result(
                        effective_request,
                        action,
                        pipeline_result.response_type,
                        pipeline_result.answer,
                        pipeline_result.confidence,
                        validation_decision,
                        pipeline_result.evidence_ids,
                        started,
                        web_search_count=pipeline_result.web_search_count,
                        manager_used=pipeline_result.manager_used,
                        fallback_model_used=pipeline_result.fallback_model_used,
                    )
                    record_audit = getattr(self.repository, "record_agent_audit", None)
                    if record_audit is not None:
                        record_audit(
                            effective_request.ticket_id,
                            pipeline_result.stage_executions,
                            result,
                        )
                    return self._finish(
                        effective_request,
                        result,
                        TicketStatus.WAITING_FOR_CUSTOMER,
                    )
                except Exception:
                    logger.error(
                        "agent pipeline failed safely",
                        extra={"ticket_id": str(effective_request.ticket_id)},
                    )
                    result = self._result(
                        effective_request,
                        "SAFE_FALLBACK",
                        "SAFE_FALLBACK",
                        "We could not safely complete the requested research. Please try again later or contact support through the official channel.",
                        settings.confidence_threshold - 1,
                        "SAFE_FALLBACK",
                        [],
                        started,
                    )
                    return self._finish(
                        effective_request,
                        result,
                        TicketStatus.WAITING_FOR_CUSTOMER,
                    )

            if "bank statement" in normalized:
                evidence = [BANK_STATEMENT_EVIDENCE]
                body = BANK_STATEMENT_EVIDENCE.customer_answer
                confidence = validate_grounded_answer(
                    effective_request.body_text, body, evidence, complete=True
                )
                evidence_ids = [item.evidence_id for item in evidence]
                result = self._result(effective_request, "SEND_REPLY", "ANSWER", body, confidence, "PASS", evidence_ids, started)
                return self._finish(effective_request, result, TicketStatus.WAITING_FOR_CUSTOMER)

            if "pending" in normalized or "application status" in normalized:
                body = (
                    "I need to verify the current demo application record before explaining the pending stage. "
                    "Please provide your application ID if it was not included in your message."
                )
                result = self._result(
                    effective_request,
                    "SEND_REPLY",
                    "NEED_MORE_INFO",
                    body,
                    settings.confidence_threshold - 1,
                    "NEED_MORE_INFORMATION",
                    [],
                    started,
                )
                return self._finish(effective_request, result, TicketStatus.WAITING_FOR_CUSTOMER)

            body = "We do not currently have enough verified information to answer this accurately. Please provide the application stage or error shown."
            result = self._result(
                effective_request,
                "SAFE_FALLBACK",
                "SAFE_FALLBACK",
                body,
                settings.confidence_threshold - 1,
                "SAFE_FALLBACK",
                [],
                started,
            )
            return self._finish(effective_request, result, TicketStatus.WAITING_FOR_CUSTOMER)
        except Exception:
            self.repository.abort_processing(effective_request.gmail_message_id, effective_request.ticket_id, previous_status)
            raise

    def _finish(
        self,
        request: ProcessTicketRequest,
        result: ProcessingResult,
        intended_status: TicketStatus,
    ) -> ProcessingResult:
        final_status = intended_status
        if intended_status == TicketStatus.CLOSED and result.action != "CLOSE_TICKET":
            final_status = TicketStatus.WAITING_FOR_CUSTOMER
        self.repository.update_status(result.ticket_id, final_status)
        self.repository.finish_processing(request.gmail_message_id, result)
        return result

    @staticmethod
    def _result(
        request: ProcessTicketRequest,
        action: str,
        response_type: str,
        body: str,
        confidence: int,
        validation_decision: str,
        evidence_ids: list[str],
        started: float,
        *,
        web_search_count: int = 0,
        manager_used: bool = False,
        fallback_model_used: bool = False,
    ) -> ProcessingResult:
        subject = f"Re: {request.subject}" if request.subject else f"Ticket {request.ticket_number}"
        guarded_subject = inspect_output(subject)
        guarded_body = inspect_output(body)
        safe_to_send = guarded_subject.safe_to_send and guarded_body.safe_to_send
        if not safe_to_send:
            action = "SAFE_FALLBACK"
            response_type = "SAFE_FALLBACK"
            confidence = settings.confidence_threshold - 1
            validation_decision = "SAFE_FALLBACK"
            evidence_ids = []
            guarded_subject = inspect_output(f"Ticket {request.ticket_number}")
            guarded_body = inspect_output("We could not safely prepare a response. Please contact support through the official channel.")

        return ProcessingResult(
            ticket_id=request.ticket_id,
            ticket_number=request.ticket_number,
            action=action,
            response_type=response_type,
            subject=guarded_subject.text,
            body=guarded_body.text,
            confidence=confidence,
            safe_to_send=guarded_subject.safe_to_send and guarded_body.safe_to_send,
            evidence_ids=evidence_ids,
            validation_decision=validation_decision,
            web_search_count=web_search_count,
            manager_used=manager_used,
            fallback_model_used=fallback_model_used,
            processing_time_ms=max(0, round((monotonic() - started) * 1000)),
        )
