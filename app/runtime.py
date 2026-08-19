import os
from pathlib import Path

from app.ai.config import AISettings
from app.ai.crew import CrewAIStageRunner, SupportCrewFactory, create_crewai_llm
from app.ai.model_router import ClassifiedStageRunner, LLMFallbackRouter, ProviderRunner
from app.ai.pipeline import AgentPipeline, serper_factory
from app.memory.repository import MemoryRepository
from app.rag.index import FaissKnowledgeIndex, OpenAIEmbeddingProvider
from app.tools.los_db import LosDataTools
from app.config import settings as app_settings


def crewai_enabled() -> bool:
    return os.getenv("ENABLE_CREWAI", "true").casefold() == "true"


def build_agent_pipeline(repository: object) -> AgentPipeline | None:
    if not crewai_enabled():
        return None

    settings = AISettings.from_env()
    missing = [
        name
        for name, value in (
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("OLLAMA_API_KEY", settings.ollama_api_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"CrewAI is enabled but required configuration is missing: {', '.join(missing)}")

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
    executor = LLMFallbackRouter(
        ProviderRunner(
            provider="OPENAI",
            model=settings.openai_model,
            runner=ClassifiedStageRunner(CrewAIStageRunner(SupportCrewFactory(primary_llm))),
        ),
        ProviderRunner(
            provider="OLLAMA",
            model=settings.ollama_model,
            runner=ClassifiedStageRunner(CrewAIStageRunner(SupportCrewFactory(fallback_llm))),
        ),
    )
    embedder = OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
        timeout=settings.llm_timeout_seconds,
    )
    session_factory = getattr(repository, "session_factory", None)
    los_tools = LosDataTools(session_factory) if session_factory is not None else None
    memory = MemoryRepository(session_factory) if session_factory is not None else None
    return AgentPipeline(
        executor=executor,
        rag_index=FaissKnowledgeIndex(Path(settings.rag_index_path), embedder),
        los_tools=los_tools,
        memory_repository=memory,
        serper_factory=serper_factory(
            api_key=settings.serper_api_key,
            timeout=settings.external_http_timeout_seconds,
            max_attempts=app_settings.max_web_search_attempts,
        ),
        confidence_threshold=app_settings.confidence_threshold,
        max_web_search_attempts=app_settings.max_web_search_attempts,
        processing_budget_seconds=settings.processing_budget_seconds,
        rag_top_k=settings.rag_top_k,
    )
