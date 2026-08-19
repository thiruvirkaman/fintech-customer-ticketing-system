from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: Literal["SYNTHETIC_INTERNAL"]
    source_title: str
    content: str
    supported_question_terms: tuple[str, ...]
    customer_answer: str


BANK_STATEMENT_EVIDENCE = Evidence(
    evidence_id="SYNTHETIC-INTERNAL-BANK-STATEMENT-001",
    source_type="SYNTHETIC_INTERNAL",
    source_title="Demo bank-statement support guidance",
    content=(
        "In the synthetic demo workflow, bank statements provide income and cash-flow information for loan assessment. "
        "This is demo guidance and must not be represented as a real lender's unpublished policy."
    ),
    supported_question_terms=("bank statement",),
    customer_answer=(
        "In this demo workflow, a bank statement is used to review income and cash-flow information during loan assessment. "
        "Actual lender requirements may differ; please follow the instructions shown in your application."
    ),
)


EVIDENCE_REGISTRY = {BANK_STATEMENT_EVIDENCE.evidence_id: BANK_STATEMENT_EVIDENCE}


def is_registered_evidence(evidence: Evidence) -> bool:
    return EVIDENCE_REGISTRY.get(evidence.evidence_id) == evidence
