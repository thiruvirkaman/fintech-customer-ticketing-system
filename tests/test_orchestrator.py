from dataclasses import replace

from app.knowledge import BANK_STATEMENT_EVIDENCE
from app.orchestrator import is_explicit_resolution, validate_grounded_answer


def test_explicit_resolution_detection() -> None:
    assert is_explicit_resolution("Thanks, that worked!")
    assert is_explicit_resolution("The issue is fixed")


def test_unresolved_and_ambiguous_gratitude_do_not_close() -> None:
    assert not is_explicit_resolution("Thanks for the update")
    assert not is_explicit_resolution("It is not resolved")
    assert not is_explicit_resolution("I tried that and it still fails")
    assert not is_explicit_resolution("I thought it was resolved, but it broke again")
    assert not is_explicit_resolution("Is the issue resolved?")


def test_confidence_requires_evidence_and_uses_rubric() -> None:
    question = "Why is a bank statement required?"
    answer = BANK_STATEMENT_EVIDENCE.customer_answer
    assert validate_grounded_answer(question, answer, [], complete=True) == 0
    assert validate_grounded_answer(question, answer, [BANK_STATEMENT_EVIDENCE], complete=True) == 90
    fabricated = replace(BANK_STATEMENT_EVIDENCE, evidence_id="made-up-id")
    assert validate_grounded_answer(question, answer, [fabricated], complete=True) == 0
    assert validate_grounded_answer(question, "Unsupported answer", [BANK_STATEMENT_EVIDENCE], complete=True) == 0
