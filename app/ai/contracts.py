from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentStage(str, Enum):
    INPUT_GUARDRAIL = "INPUT_GUARDRAIL"
    RESEARCH = "RESEARCH"
    DB = "DB"
    VALIDATION = "VALIDATION"
    WEB_SYNTHESIS = "WEB_SYNTHESIS"
    MANAGER = "MANAGER"
    EMAIL = "EMAIL"
    OUTPUT_GUARDRAIL = "OUTPUT_GUARDRAIL"


class EvidenceItem(BaseModel):
    evidence_id: str = Field(min_length=1)
    source_type: Literal["LOS_DB", "INTERNAL_RAG", "PUBLIC_RAG", "WEB", "MEMORY"]
    source: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_url: str | None = None
    relevance_score: float | None = Field(default=None, ge=-1, le=1)


class StrictAgentOutput(BaseModel):
    """Base for OpenAI Structured Outputs returned by CrewAI stages."""

    model_config = ConfigDict(extra="forbid")


class ResearchOutput(StrictAgentOutput):
    intent: Literal["GENERAL", "CUSTOMER_SPECIFIC", "FOLLOW_UP", "RESOLUTION_CONFIRMATION"]
    draft_answer: str
    evidence_ids: list[str]
    unknowns: list[str]
    provisional_confidence: int = Field(ge=0, le=100)


class InputSemanticGuardrailOutput(StrictAgentOutput):
    allowed: bool
    spam_confidence: int = Field(ge=0, le=100)
    violations: list[str]
    reason_codes: list[str]


class DBFact(StrictAgentOutput):
    name: str = Field(min_length=1)
    value: str


class DBAnalysisOutput(StrictAgentOutput):
    requires_db_evidence: bool
    facts: list[DBFact]
    evidence_ids: list[str]
    unknowns: list[str]


class ValidationOutput(StrictAgentOutput):
    supported: bool
    complete: bool
    conflicts: list[str]
    unsupported_claims: list[str]
    missing_information: list[str]
    confidence: int = Field(ge=0, le=100)
    decision: Literal["PASS", "SEARCH_REQUIRED", "NEED_MORE_INFORMATION", "CONFLICT"]


class WebSynthesisOutput(StrictAgentOutput):
    generic_query: str = Field(min_length=1)
    evidence_ids: list[str]
    relevant_evidence: list[str]


class ManagerOutput(StrictAgentOutput):
    outcome: Literal[
        "RESOLVED_WITH_EVIDENCE",
        "REQUEST_VALIDATION",
        "NEED_MORE_INFORMATION",
        "SAFE_FALLBACK",
    ]
    answer: str
    evidence_ids: list[str]
    rationale: str


class EmailOutput(StrictAgentOutput):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    response_type: Literal["ANSWER", "NEED_MORE_INFO", "SAFE_FALLBACK"]
    safe_for_guardrail_check: bool


class OutputSemanticGuardrailOutput(StrictAgentOutput):
    safe_to_send: bool
    violations: list[str]
    masked_fields: list[str]
    unsupported_claims: list[str]


class ModelAttempt(BaseModel):
    provider: Literal["OPENAI", "OLLAMA"]
    model: str
    attempt: int = Field(ge=1)
    fallback_used: bool
    succeeded: bool
    error_code: str | None = None


class StageExecution(BaseModel):
    stage: AgentStage
    output: Any
    provider: Literal["OPENAI", "OLLAMA"]
    model: str
    fallback_used: bool
    attempts: list[ModelAttempt]
    latency_ms: int = Field(default=0, ge=0)
