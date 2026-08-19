from collections.abc import Mapping
from typing import Any

import pytest

from app.ai.config import AISettings
from app.ai.contracts import AgentStage, ValidationOutput
from app.ai.model_router import LLMFallbackRouter, ModelProviderError, ProviderRunner, build_fallback_router


def validation(confidence: int) -> ValidationOutput:
    return ValidationOutput(
        supported=confidence >= 70,
        complete=confidence >= 70,
        confidence=confidence,
        decision="PASS" if confidence >= 70 else "SEARCH_REQUIRED",
    )


class SequenceRunner:
    def __init__(self, *results: ValidationOutput | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    def run(self, stage: AgentStage, inputs: Mapping[str, Any]) -> ValidationOutput:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def router(primary: SequenceRunner, fallback: SequenceRunner) -> LLMFallbackRouter:
    return LLMFallbackRouter(
        ProviderRunner("OPENAI", "gpt-4o-mini", primary),
        ProviderRunner("OLLAMA", "glm-5.2:cloud", fallback),
    )


def test_transient_primary_failure_retries_once_then_uses_fallback() -> None:
    primary = SequenceRunner(
        ModelProviderError("PROVIDER_TIMEOUT", retryable=True),
        ModelProviderError("RATE_LIMITED", retryable=True),
    )
    fallback = SequenceRunner(validation(82))

    result = router(primary, fallback).execute(AgentStage.VALIDATION, {})

    assert primary.calls == 2
    assert fallback.calls == 1
    assert result.provider == "OLLAMA"
    assert result.fallback_used
    assert [attempt.error_code for attempt in result.attempts] == [
        "PROVIDER_TIMEOUT",
        "RATE_LIMITED",
        None,
    ]


def test_low_confidence_does_not_trigger_model_fallback() -> None:
    primary = SequenceRunner(validation(42))
    fallback = SequenceRunner(validation(90))

    result = router(primary, fallback).execute(AgentStage.VALIDATION, {})

    assert result.output.confidence == 42
    assert not result.fallback_used
    assert fallback.calls == 0


def test_auth_failure_does_not_send_credentials_to_another_provider() -> None:
    primary = SequenceRunner(
        ModelProviderError("PROVIDER_AUTH_FAILED", retryable=False, fallback_eligible=False)
    )
    fallback = SequenceRunner(validation(90))

    with pytest.raises(ModelProviderError, match="PROVIDER_AUTH_FAILED"):
        router(primary, fallback).execute(AgentStage.RESEARCH, {})

    assert fallback.calls == 0


def test_concrete_router_uses_configured_primary_and_fallback_models() -> None:
    settings = AISettings(
        openai_api_key="test-openai",
        openai_model="gpt-4o-mini",
        openai_embedding_model="text-embedding-3-small",
        ollama_base_url="https://ollama.com",
        ollama_api_key="test-ollama",
        ollama_model="glm-5.2:cloud",
        serper_api_key="",
        rag_top_k=4,
        rag_index_path="data/faiss",
        llm_timeout_seconds=20,
        external_http_timeout_seconds=8,
    )

    built = build_fallback_router(settings)

    assert built._primary.model == "gpt-4o-mini"
    assert built._fallback.model == "glm-5.2:cloud"
