from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


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


class ResearchOutput(BaseModel):
    intent: Literal["GENERAL", "CUSTOMER_SPECIFIC", "FOLLOW_UP", "RESOLUTION_CONFIRMATION"]
    draft_answer: str
    evidence_ids: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    provisional_confidence: int = Field(ge=0, le=100)


class InputSemanticGuardrailOutput(BaseModel):
    allowed: bool
    spam_confidence: int = Field(ge=0, le=100)
    violations: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class DBAnalysisOutput(BaseModel):
    requires_db_evidence: bool
    facts: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class ValidationOutput(BaseModel):
    supported: bool
    complete: bool
    conflicts: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    decision: Literal["PASS", "SEARCH_REQUIRED", "NEED_MORE_INFORMATION", "CONFLICT"]


class WebSynthesisOutput(BaseModel):
    generic_query: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    relevant_evidence: list[str] = Field(default_factory=list)


class ManagerOutput(BaseModel):
    outcome: Literal[
        "RESOLVED_WITH_EVIDENCE",
        "REQUEST_VALIDATION",
        "NEED_MORE_INFORMATION",
        "SAFE_FALLBACK",
    ]
    answer: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class EmailOutput(BaseModel):
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    response_type: Literal["ANSWER", "NEED_MORE_INFO", "SAFE_FALLBACK"]
    safe_for_guardrail_check: bool


class OutputSemanticGuardrailOutput(BaseModel):
    safe_to_send: bool
    violations: list[str] = Field(default_factory=list)
    masked_fields: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


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
