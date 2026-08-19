import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class AISettings:
    openai_api_key: str
    openai_model: str
    openai_embedding_model: str
    ollama_base_url: str
    ollama_api_key: str
    ollama_model: str
    serper_api_key: str
    rag_top_k: int
    rag_index_path: str
    llm_timeout_seconds: float
    external_http_timeout_seconds: float
    processing_budget_seconds: float = 50.0

    @classmethod
    def from_env(cls) -> "AISettings":
        settings = cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "") or "https://ollama.com",
            ollama_api_key=os.getenv("OLLAMA_API_KEY", ""),
            ollama_model=os.getenv("OLLAMA_MODEL", "glm-5.2:cloud"),
            serper_api_key=os.getenv("SERPER_API_KEY", ""),
            rag_top_k=_bounded_int("RAG_TOP_K", 4, 1, 20),
            rag_index_path=os.getenv("RAG_INDEX_PATH", "data/faiss"),
            llm_timeout_seconds=_bounded_float("LLM_TIMEOUT_SECONDS", 20.0, 1.0, 45.0),
            external_http_timeout_seconds=_bounded_float(
                "EXTERNAL_HTTP_TIMEOUT_SECONDS", 8.0, 1.0, 20.0
            ),
            processing_budget_seconds=_bounded_float(
                "PROCESSING_BUDGET_SECONDS", 50.0, 10.0, 55.0
            ),
        )
        _validate_ollama_url(settings.ollama_base_url)
        for name, value in (
            ("OPENAI_MODEL", settings.openai_model),
            ("OPENAI_EMBEDDING_MODEL", settings.openai_embedding_model),
            ("OLLAMA_MODEL", settings.ollama_model),
            ("RAG_INDEX_PATH", settings.rag_index_path),
        ):
            if not value.strip():
                raise RuntimeError(f"{name} must not be empty")
        return settings


def _validate_ollama_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("OLLAMA_BASE_URL must be an absolute HTTP(S) URL")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "ollama"}:
        raise RuntimeError("OLLAMA_BASE_URL must use HTTPS unless it targets the local Ollama service")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value
