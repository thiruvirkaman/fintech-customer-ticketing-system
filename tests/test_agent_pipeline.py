from uuid import uuid4

from app.ai.contracts import (
    AgentStage,
    DBAnalysisOutput,
    EmailOutput,
    EvidenceItem,
    OutputSemanticGuardrailOutput,
    ResearchOutput,
    StageExecution,
    ValidationOutput,
    WebSynthesisOutput,
)
from app.ai.pipeline import AgentPipeline


def execution(stage: AgentStage, output: object) -> StageExecution:
    return StageExecution(
        stage=stage,
        output=output,
        provider="OPENAI",
        model="test-model",
        fallback_used=False,
        attempts=[],
    )


class FakeExecutor:
    def __init__(self, outputs: dict[AgentStage, list[object]]) -> None:
        self.outputs = {stage: list(values) for stage, values in outputs.items()}
        self.calls: list[AgentStage] = []

    def execute(self, stage: AgentStage, inputs: dict) -> StageExecution:
        self.calls.append(stage)
        return execution(stage, self.outputs[stage].pop(0))


class FakeRag:
    def retrieve(self, query: str, *, top_k: int = 4) -> list[EvidenceItem]:
        return [
            EvidenceItem(
                evidence_id="RAG-1",
                source_type="INTERNAL_RAG",
                source="Synthetic guidance",
                content="Bank statements support income and cash-flow review in this demo.",
            )
        ]


class FakeSearch:
    def __init__(self) -> None:
        self.attempts = 0

    def search(self, question: str) -> list[EvidenceItem]:
        self.attempts += 1
        return [
            EvidenceItem(
                evidence_id="WEB-1",
                source_type="WEB",
                source="Official source",
                source_url="https://www.rbi.org.in/example",
                content="Official external evidence.",
            )
        ]


def test_general_question_uses_rag_validation_email_and_guardrail() -> None:
    executor = FakeExecutor(
        {
            AgentStage.RESEARCH: [
                ResearchOutput(
                    intent="GENERAL",
                    draft_answer="A grounded answer.",
                    evidence_ids=["RAG-1"],
                    provisional_confidence=90,
                )
            ],
            AgentStage.VALIDATION: [
                ValidationOutput(supported=True, complete=True, confidence=90, decision="PASS")
            ],
            AgentStage.EMAIL: [
                EmailOutput(
                    subject="Re: Question",
                    body="A grounded answer.",
                    response_type="ANSWER",
                    safe_for_guardrail_check=True,
                )
            ],
            AgentStage.OUTPUT_GUARDRAIL: [OutputSemanticGuardrailOutput(safe_to_send=True)],
        }
    )
    pipeline = AgentPipeline(
        executor=executor,
        rag_index=FakeRag(),  # type: ignore[arg-type]
        los_tools=None,
        memory_repository=None,
        serper_factory=lambda: None,
    )
    result = pipeline.process(
        ticket_id=uuid4(),
        ticket_number="TKT-000001",
        sender_email="demo@example.com",
        subject="Question",
        customer_question="Why is a bankstatement required?",
    )
    assert result.response_type == "ANSWER"
    assert result.confidence == 90
    assert result.evidence_ids == ["RAG-1"]
    assert AgentStage.DB not in executor.calls


def test_low_confidence_triggers_bounded_web_search_then_revalidation() -> None:
    executor = FakeExecutor(
        {
            AgentStage.RESEARCH: [
                ResearchOutput(
                    intent="GENERAL",
                    draft_answer="Draft",
                    evidence_ids=["RAG-1"],
                    provisional_confidence=40,
                )
            ],
            AgentStage.VALIDATION: [
                ValidationOutput(supported=True, complete=True, confidence=50, decision="SEARCH_REQUIRED"),
                ValidationOutput(supported=True, complete=True, confidence=80, decision="PASS"),
            ],
            AgentStage.WEB_SYNTHESIS: [
                WebSynthesisOutput(
                    generic_query="generic question",
                    evidence_ids=["WEB-1"],
                    relevant_evidence=["Official external evidence."],
                )
            ],
            AgentStage.EMAIL: [
                EmailOutput(
                    subject="Re: Question",
                    body="Validated answer",
                    response_type="ANSWER",
                    safe_for_guardrail_check=True,
                )
            ],
            AgentStage.OUTPUT_GUARDRAIL: [OutputSemanticGuardrailOutput(safe_to_send=True)],
        }
    )
    search = FakeSearch()
    pipeline = AgentPipeline(
        executor=executor,
        rag_index=FakeRag(),  # type: ignore[arg-type]
        los_tools=None,
        memory_repository=None,
        serper_factory=lambda: search,  # type: ignore[return-value]
        max_web_search_attempts=2,
    )
    result = pipeline.process(
        ticket_id=uuid4(),
        ticket_number="TKT-000002",
        sender_email="demo@example.com",
        subject="Question",
        customer_question="What is the requirement?",
    )
    assert result.confidence == 80
    assert result.web_search_count == 1
    assert executor.calls.count(AgentStage.VALIDATION) == 2


def test_customer_specific_request_without_db_facts_requests_information() -> None:
    executor = FakeExecutor(
        {
            AgentStage.RESEARCH: [
                ResearchOutput(
                    intent="CUSTOMER_SPECIFIC",
                    draft_answer="Unknown current status.",
                    evidence_ids=["RAG-1"],
                    provisional_confidence=20,
                ),
                ResearchOutput(
                    intent="CUSTOMER_SPECIFIC",
                    draft_answer="Unknown current status.",
                    evidence_ids=["RAG-1"],
                    provisional_confidence=20,
                ),
            ],
            AgentStage.DB: [
                DBAnalysisOutput(requires_db_evidence=True, unknowns=["application identity"])
            ],
            AgentStage.VALIDATION: [
                ValidationOutput(
                    supported=False,
                    complete=False,
                    missing_information=["application ID"],
                    confidence=20,
                    decision="NEED_MORE_INFORMATION",
                )
            ],
        }
    )
    pipeline = AgentPipeline(
        executor=executor,
        rag_index=FakeRag(),  # type: ignore[arg-type]
        los_tools=None,
        memory_repository=None,
        serper_factory=lambda: None,
    )
    result = pipeline.process(
        ticket_id=uuid4(),
        ticket_number="TKT-000003",
        sender_email="unknown@example.com",
        subject="Pending",
        customer_question="Why is my application pending?",
    )
    assert result.response_type == "NEED_MORE_INFO"
    assert result.web_search_count == 0
    assert "application ID" in result.answer


def test_unsafe_email_gets_only_one_bounded_regeneration() -> None:
    executor = FakeExecutor(
        {
            AgentStage.RESEARCH: [
                ResearchOutput(
                    intent="GENERAL",
                    draft_answer="Grounded answer",
                    evidence_ids=["RAG-1"],
                    provisional_confidence=90,
                )
            ],
            AgentStage.VALIDATION: [
                ValidationOutput(supported=True, complete=True, confidence=90, decision="PASS")
            ],
            AgentStage.EMAIL: [
                EmailOutput(subject="Re: Question", body="unsafe", response_type="ANSWER", safe_for_guardrail_check=True),
                EmailOutput(subject="Re: Question", body="safe revision", response_type="ANSWER", safe_for_guardrail_check=True),
            ],
            AgentStage.OUTPUT_GUARDRAIL: [
                OutputSemanticGuardrailOutput(safe_to_send=False, violations=["INTERNAL_CONTENT"]),
                OutputSemanticGuardrailOutput(safe_to_send=True),
            ],
        }
    )
    pipeline = AgentPipeline(
        executor=executor,
        rag_index=FakeRag(),  # type: ignore[arg-type]
        los_tools=None,
        memory_repository=None,
        serper_factory=lambda: None,
    )

    result = pipeline.process(
        ticket_id=uuid4(),
        ticket_number="TKT-000004",
        sender_email="demo@example.com",
        subject="Question",
        customer_question="Why is a bank statement required?",
    )

    assert result.answer == "safe revision"
    assert executor.calls.count(AgentStage.EMAIL) == 2
    assert executor.calls.count(AgentStage.OUTPUT_GUARDRAIL) == 2
