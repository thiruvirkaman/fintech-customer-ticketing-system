import re
from collections.abc import Callable
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.contracts import (
    AgentStage,
    DBAnalysisOutput,
    EmailOutput,
    EvidenceItem,
    InputSemanticGuardrailOutput,
    ManagerOutput,
    OutputSemanticGuardrailOutput,
    ResearchOutput,
    StageExecution,
    ValidationOutput,
    WebSynthesisOutput,
)
from app.memory.repository import MemoryRepository, TicketMemory
from app.rag.index import FaissKnowledgeIndex
from app.tools.los_db import ApplicationFacts, CustomerFacts, LosDataTools
from app.tools.serper import BoundedSerperSearch, SerperClient


APPLICATION_ID = re.compile(r"\bAPP-DEMO-\d{4}\b", re.IGNORECASE)
SAFE_FALLBACK_BODY = (
    "We do not currently have enough verified information to answer this accurately. "
    "Please provide the application stage or error shown."
)


class StageExecutor(Protocol):
    def execute(self, stage: AgentStage, inputs: dict[str, Any]) -> StageExecution: ...


class AgentPipelineResult(BaseModel):
    answer: str
    response_type: str
    confidence: int = Field(ge=0, le=100)
    validation_decision: str
    evidence_ids: list[str] = Field(default_factory=list)
    web_search_count: int = 0
    manager_used: bool = False
    fallback_model_used: bool = False
    customer_name: str | None = None
    semantic_output_safe: bool = False
    stage_executions: list[StageExecution] = Field(default_factory=list)


class AgentPipeline:
    """Deterministic state machine around bounded specialist CrewAI stages."""

    def __init__(
        self,
        *,
        executor: StageExecutor,
        rag_index: FaissKnowledgeIndex | None,
        los_tools: LosDataTools | None,
        memory_repository: MemoryRepository | None,
        serper_factory: Callable[[], BoundedSerperSearch | None],
        confidence_threshold: int = 70,
        max_web_search_attempts: int = 2,
        processing_budget_seconds: float = 50.0,
        rag_top_k: int = 4,
    ) -> None:
        if not 1 <= confidence_threshold <= 100:
            raise ValueError("confidence_threshold must be between 1 and 100")
        if not 0 <= max_web_search_attempts <= 2:
            raise ValueError("max_web_search_attempts must be between 0 and 2")
        self._executor = executor
        self._rag = rag_index
        self._los = los_tools
        self._memory = memory_repository
        self._serper_factory = serper_factory
        self._threshold = confidence_threshold
        self._max_searches = max_web_search_attempts
        self._budget = processing_budget_seconds
        self._rag_top_k = rag_top_k

    def semantic_input_guardrail(self, email_data: dict[str, Any]) -> tuple[InputSemanticGuardrailOutput, StageExecution]:
        execution = self._executor.execute(AgentStage.INPUT_GUARDRAIL, {"email": email_data})
        return InputSemanticGuardrailOutput.model_validate(execution.output), execution

    def process(
        self,
        *,
        ticket_id: UUID,
        ticket_number: str,
        sender_email: str,
        subject: str,
        customer_question: str,
    ) -> AgentPipelineResult:
        started = monotonic()
        executions: list[StageExecution] = []
        rag_evidence = self._retrieve_rag(customer_question)
        memory = self._retrieve_memory(ticket_id, None, customer_question)

        research = self._run(
            AgentStage.RESEARCH,
            {
                "customer_question": customer_question,
                "ticket_context": {"ticket_id": str(ticket_id), "ticket_number": ticket_number},
                "db_evidence": [],
                "rag_evidence": self._dump(rag_evidence),
                "memory": memory.model_dump(mode="json"),
            },
            ResearchOutput,
            executions,
        )

        customer: CustomerFacts | None = None
        application: ApplicationFacts | None = None
        db_evidence: list[EvidenceItem] = []
        if research.intent == "CUSTOMER_SPECIFIC":
            customer, application = self._lookup_customer_application(sender_email, customer_question)
            if application is not None:
                db_evidence = [application.as_evidence()]
            db_analysis = self._run(
                AgentStage.DB,
                {
                    "customer_question": customer_question,
                    "db_tool_results": self._dump(db_evidence),
                },
                DBAnalysisOutput,
                executions,
            )
            allowed_db_ids = {item.evidence_id for item in db_evidence}
            if not set(db_analysis.evidence_ids) <= allowed_db_ids:
                db_evidence = []
            memory = self._retrieve_memory(
                ticket_id,
                customer.customer_id if customer else application.customer_id if application else None,
                customer_question,
            )
            research = self._run(
                AgentStage.RESEARCH,
                {
                    "customer_question": customer_question,
                    "ticket_context": {"ticket_id": str(ticket_id), "ticket_number": ticket_number},
                    "db_evidence": self._dump(db_evidence),
                    "rag_evidence": self._dump(rag_evidence),
                    "memory": memory.model_dump(mode="json"),
                },
                ResearchOutput,
                executions,
            )

        all_evidence = [*db_evidence, *rag_evidence]
        validation = self._validate(
            customer_question,
            research,
            db_evidence,
            rag_evidence,
            [],
            memory,
            executions,
        )
        validation = self._apply_hard_rules(research, validation, all_evidence, bool(db_evidence))

        web_evidence: list[EvidenceItem] = []
        searcher = self._serper_factory()
        while (
            validation.confidence < self._threshold
            and validation.decision == "SEARCH_REQUIRED"
            and searcher is not None
            and searcher.attempts < self._max_searches
            and self._remaining(started) > 10
        ):
            results = searcher.search(customer_question)
            web_evidence.extend(results)
            synthesis = self._run(
                AgentStage.WEB_SYNTHESIS,
                {"generic_query": customer_question, "search_results": self._dump(results)},
                WebSynthesisOutput,
                executions,
            )
            selected_ids = set(getattr(synthesis, "evidence_ids", []))
            selected = [item for item in web_evidence if not selected_ids or item.evidence_id in selected_ids]
            validation = self._validate(
                customer_question,
                research,
                db_evidence,
                rag_evidence,
                selected,
                memory,
                executions,
            )
            all_evidence = [*db_evidence, *rag_evidence, *selected]
            validation = self._apply_hard_rules(research, validation, all_evidence, bool(db_evidence))

        manager_used = False
        if validation.decision == "CONFLICT" and validation.confidence < self._threshold and self._remaining(started) > 8:
            manager_used = True
            manager = self._run(
                AgentStage.MANAGER,
                {
                    "customer_question": customer_question,
                    "research": research.model_dump(),
                    "validation": validation.model_dump(),
                    "evidence": self._dump(all_evidence),
                },
                ManagerOutput,
                executions,
            )
            if manager.outcome == "RESOLVED_WITH_EVIDENCE" and manager.answer:
                research = research.model_copy(
                    update={"draft_answer": manager.answer, "evidence_ids": manager.evidence_ids}
                )
                validation = self._validate(
                    customer_question,
                    research,
                    db_evidence,
                    rag_evidence,
                    web_evidence,
                    memory,
                    executions,
                )
                validation = self._apply_hard_rules(research, validation, all_evidence, bool(db_evidence))

        web_count = searcher.attempts if searcher is not None else 0
        fallback_used = any(execution.fallback_used for execution in executions)
        if validation.decision != "PASS" or validation.confidence < self._threshold:
            response_type = "NEED_MORE_INFO" if validation.decision == "NEED_MORE_INFORMATION" else "SAFE_FALLBACK"
            return AgentPipelineResult(
                answer=self._missing_information_answer(validation),
                response_type=response_type,
                confidence=min(validation.confidence, self._threshold - 1),
                validation_decision=validation.decision,
                evidence_ids=[],
                web_search_count=web_count,
                manager_used=manager_used,
                fallback_model_used=fallback_used,
                customer_name=customer.full_name if customer else None,
                semantic_output_safe=True,
                stage_executions=executions,
            )

        email = self._run(
            AgentStage.EMAIL,
            {
                "approved_response": {
                    "answer": research.draft_answer,
                    "evidence_ids": research.evidence_ids,
                    "validation": validation.model_dump(),
                },
                "customer_name": customer.full_name if customer else "",
                "ticket_number": ticket_number,
                "subject": subject,
            },
            EmailOutput,
            executions,
        )
        semantic_guardrail = self._run(
            AgentStage.OUTPUT_GUARDRAIL,
            {
                "candidate_email": email.model_dump(),
                "validated_evidence": self._dump(all_evidence),
            },
            OutputSemanticGuardrailOutput,
            executions,
        )
        if not (email.safe_for_guardrail_check and semantic_guardrail.safe_to_send):
            email = self._run(
                AgentStage.EMAIL,
                {
                    "approved_response": {
                        "answer": research.draft_answer,
                        "evidence_ids": research.evidence_ids,
                        "validation": validation.model_dump(),
                    },
                    "customer_name": customer.full_name if customer else "",
                    "ticket_number": ticket_number,
                    "subject": subject,
                    "revision_requirements": {
                        "remove_violations": semantic_guardrail.violations,
                        "remove_unsupported_claims": semantic_guardrail.unsupported_claims,
                        "masked_fields": semantic_guardrail.masked_fields,
                    },
                },
                EmailOutput,
                executions,
            )
            semantic_guardrail = self._run(
                AgentStage.OUTPUT_GUARDRAIL,
                {
                    "candidate_email": email.model_dump(),
                    "validated_evidence": self._dump(all_evidence),
                },
                OutputSemanticGuardrailOutput,
                executions,
            )
        fallback_used = any(execution.fallback_used for execution in executions)
        safe = bool(email.safe_for_guardrail_check and semantic_guardrail.safe_to_send)
        return AgentPipelineResult(
            answer=email.body if safe else SAFE_FALLBACK_BODY,
            response_type=email.response_type if safe else "SAFE_FALLBACK",
            confidence=validation.confidence if safe else self._threshold - 1,
            validation_decision="PASS" if safe else "SAFE_FALLBACK",
            evidence_ids=research.evidence_ids if safe else [],
            web_search_count=web_count,
            manager_used=manager_used,
            fallback_model_used=fallback_used,
            customer_name=customer.full_name if customer else None,
            semantic_output_safe=safe,
            stage_executions=executions,
        )

    def _run(
        self,
        stage: AgentStage,
        inputs: dict[str, Any],
        output_type: type[BaseModel],
        executions: list[StageExecution],
    ) -> Any:
        execution = self._executor.execute(stage, inputs)
        executions.append(execution)
        return output_type.model_validate(execution.output) if output_type is not BaseModel else execution.output

    def _validate(
        self,
        question: str,
        research: ResearchOutput,
        db_evidence: list[EvidenceItem],
        rag_evidence: list[EvidenceItem],
        web_evidence: list[EvidenceItem],
        memory: TicketMemory,
        executions: list[StageExecution],
    ) -> ValidationOutput:
        return self._run(
            AgentStage.VALIDATION,
            {
                "customer_question": question,
                "proposed_answer": research.model_dump(),
                "db_evidence": self._dump(db_evidence),
                "rag_evidence": self._dump(rag_evidence),
                "web_evidence": self._dump(web_evidence),
                "memory": memory.model_dump(mode="json"),
                "confidence_threshold": self._threshold,
            },
            ValidationOutput,
            executions,
        )

    def _apply_hard_rules(
        self,
        research: ResearchOutput,
        validation: ValidationOutput,
        evidence: list[EvidenceItem],
        has_db_evidence: bool,
    ) -> ValidationOutput:
        available_ids = {item.evidence_id for item in evidence}
        if not set(research.evidence_ids) <= available_ids:
            return validation.model_copy(
                update={
                    "supported": False,
                    "confidence": 0,
                    "decision": "CONFLICT",
                    "unsupported_claims": [*validation.unsupported_claims, "Unregistered evidence reference"],
                }
            )
        if research.intent == "CUSTOMER_SPECIFIC" and not has_db_evidence:
            return validation.model_copy(
                update={
                    "supported": False,
                    "complete": False,
                    "confidence": min(validation.confidence, self._threshold - 1),
                    "decision": "NEED_MORE_INFORMATION",
                }
            )
        if not research.evidence_ids:
            return validation.model_copy(
                update={
                    "supported": False,
                    "complete": False,
                    "confidence": 0,
                    "decision": "SEARCH_REQUIRED",
                }
            )
        if validation.conflicts or validation.unsupported_claims or not validation.supported or not validation.complete:
            decision = "CONFLICT" if validation.conflicts or validation.unsupported_claims else validation.decision
            return validation.model_copy(
                update={"confidence": min(validation.confidence, self._threshold - 1), "decision": decision}
            )
        if validation.confidence < self._threshold and validation.decision == "PASS":
            return validation.model_copy(update={"decision": "SEARCH_REQUIRED"})
        if validation.confidence >= self._threshold and validation.decision != "PASS":
            return validation.model_copy(update={"confidence": self._threshold - 1})
        return validation

    def _lookup_customer_application(
        self, sender_email: str, question: str
    ) -> tuple[CustomerFacts | None, ApplicationFacts | None]:
        if self._los is None:
            return None, None
        customer = self._los.find_customer_by_email(sender_email)
        application_match = APPLICATION_ID.search(question)
        if application_match:
            application = self._los.get_application(application_match.group(0).upper())
            if customer is not None and application is not None and application.customer_id != customer.customer_id:
                return customer, None
            return customer, application
        return customer, self._los.get_latest_application(customer.customer_id) if customer else None

    def _retrieve_rag(self, question: str) -> list[EvidenceItem]:
        if self._rag is None:
            return []
        try:
            return self._rag.retrieve(question, top_k=self._rag_top_k)
        except Exception:
            return []

    def _retrieve_memory(self, ticket_id: UUID, customer_id: str | None, query: str) -> TicketMemory:
        if self._memory is None:
            return TicketMemory(current_ticket_history=[], relevant_closed_summaries=[])
        return self._memory.retrieve(ticket_id, customer_id=customer_id, query=query)

    def _remaining(self, started: float) -> float:
        return self._budget - (monotonic() - started)

    @staticmethod
    def _dump(items: list[BaseModel]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in items]

    @staticmethod
    def _missing_information_answer(validation: ValidationOutput) -> str:
        if validation.decision == "NEED_MORE_INFORMATION" and validation.missing_information:
            missing = ", ".join(validation.missing_information[:3])
            return f"Please provide the minimum missing information needed to continue: {missing}."
        return SAFE_FALLBACK_BODY


def serper_factory(
    *, api_key: str, timeout: float, max_attempts: int
) -> Callable[[], BoundedSerperSearch | None]:
    def create() -> BoundedSerperSearch | None:
        if not api_key or max_attempts == 0:
            return None
        return BoundedSerperSearch(
            SerperClient(api_key=api_key, timeout=timeout),
            max_attempts=max_attempts,
        )

    return create
