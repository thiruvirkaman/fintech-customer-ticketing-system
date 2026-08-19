from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from app.ai.contracts import AgentStage, ModelAttempt, StageExecution
from app.ai.config import AISettings
from app.ai.crew import CrewAIStageRunner, SupportCrewFactory, create_crewai_llm


class StageRunner(Protocol):
    def run(self, stage: AgentStage, inputs: Mapping[str, Any]) -> BaseModel: ...


class ModelProviderError(RuntimeError):
    def __init__(self, safe_code: str, *, retryable: bool, fallback_eligible: bool = True) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.retryable = retryable
        self.fallback_eligible = fallback_eligible


@dataclass(frozen=True)
class ProviderRunner:
    provider: Literal["OPENAI", "OLLAMA"]
    model: str
    runner: StageRunner


class LLMFallbackRouter:
    """Runs a stage on OpenAI, then Ollama only for provider/model failures."""

    def __init__(self, primary: ProviderRunner, fallback: ProviderRunner) -> None:
        if primary.provider != "OPENAI" or fallback.provider != "OLLAMA":
            raise ValueError("fallback routing must be OPENAI -> OLLAMA")
        self._primary = primary
        self._fallback = fallback

    def execute(self, stage: AgentStage, inputs: Mapping[str, Any]) -> StageExecution:
        started = monotonic()
        attempts: list[ModelAttempt] = []
        for attempt_number in (1, 2):
            try:
                output = self._primary.runner.run(stage, inputs)
                attempts.append(self._attempt(self._primary, attempt_number, False, True))
                return self._success(stage, output, self._primary, False, attempts).model_copy(
                    update={"latency_ms": max(0, round((monotonic() - started) * 1000))}
                )
            except ModelProviderError as exc:
                attempts.append(self._attempt(self._primary, attempt_number, False, False, exc.safe_code))
                if not exc.fallback_eligible:
                    raise
                if not exc.retryable or attempt_number == 2:
                    break

        try:
            output = self._fallback.runner.run(stage, inputs)
            attempts.append(self._attempt(self._fallback, 1, True, True))
            return self._success(stage, output, self._fallback, True, attempts).model_copy(
                update={"latency_ms": max(0, round((monotonic() - started) * 1000))}
            )
        except ModelProviderError as exc:
            attempts.append(self._attempt(self._fallback, 1, True, False, exc.safe_code))
            raise ModelProviderError("ALL_LLM_PROVIDERS_FAILED", retryable=False, fallback_eligible=False) from exc

    @staticmethod
    def _attempt(
        provider: ProviderRunner,
        attempt: int,
        fallback_used: bool,
        succeeded: bool,
        error_code: str | None = None,
    ) -> ModelAttempt:
        return ModelAttempt(
            provider=provider.provider,
            model=provider.model,
            attempt=attempt,
            fallback_used=fallback_used,
            succeeded=succeeded,
            error_code=error_code,
        )

    @staticmethod
    def _success(
        stage: AgentStage,
        output: BaseModel,
        provider: ProviderRunner,
        fallback_used: bool,
        attempts: list[ModelAttempt],
    ) -> StageExecution:
        return StageExecution(
            stage=stage,
            output=output,
            provider=provider.provider,
            model=provider.model,
            fallback_used=fallback_used,
            attempts=attempts,
        )


def classify_provider_exception(exc: Exception) -> ModelProviderError:
    """Convert SDK exceptions to stable, non-sensitive routing signals."""
    status_code = getattr(exc, "status_code", None)
    name = type(exc).__name__.casefold()
    if status_code == 429 or "ratelimit" in name:
        return ModelProviderError("RATE_LIMITED", retryable=True)
    if status_code is not None and 500 <= status_code <= 599:
        return ModelProviderError("PROVIDER_UNAVAILABLE", retryable=True)
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return ModelProviderError("PROVIDER_TIMEOUT", retryable=True)
    if "connection" in name:
        return ModelProviderError("PROVIDER_CONNECTION_FAILED", retryable=True)
    if status_code in {401, 403} or "authentication" in name or "permission" in name:
        return ModelProviderError("PROVIDER_AUTH_FAILED", retryable=False, fallback_eligible=False)
    if status_code is not None and 400 <= status_code <= 499:
        return ModelProviderError("PROVIDER_REQUEST_REJECTED", retryable=False, fallback_eligible=False)
    return ModelProviderError("PROVIDER_FAILURE", retryable=False)


class ClassifiedStageRunner:
    """Preserves only a safe error classification at the routing boundary."""

    def __init__(self, runner: StageRunner) -> None:
        self._runner = runner

    def run(self, stage: AgentStage, inputs: Mapping[str, Any]) -> BaseModel:
        try:
            return self._runner.run(stage, inputs)
        except ModelProviderError:
            raise
        except Exception as exc:
            raise classify_provider_exception(exc) from exc


def build_fallback_router(settings: AISettings) -> LLMFallbackRouter:
    """Build the concrete OpenAI -> Ollama CrewAI execution boundary."""
    primary_llm = create_crewai_llm(
        provider="openai",
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
    )
    fallback_llm = create_crewai_llm(
        provider="ollama",
        model=settings.ollama_model,
        api_key=settings.ollama_api_key,
        base_url=settings.ollama_base_url,
        timeout=settings.llm_timeout_seconds,
    )
    primary_runner = ClassifiedStageRunner(CrewAIStageRunner(SupportCrewFactory(primary_llm)))
    fallback_runner = ClassifiedStageRunner(CrewAIStageRunner(SupportCrewFactory(fallback_llm)))
    return LLMFallbackRouter(
        ProviderRunner("OPENAI", settings.openai_model, primary_runner),
        ProviderRunner("OLLAMA", settings.ollama_model, fallback_runner),
    )
