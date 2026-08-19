import secrets
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.guardrails import inspect_input
from app.models import DeliveryRequest, IncomingEmail, ProcessTicketRequest
from app.orchestrator import TicketOrchestrator
from app.repository import (
    DeliveryConflictError,
    MessageBindingError,
    MessageNotPreflightedError,
    ProcessingInProgressError,
    TicketNotFoundError,
    repository,
)
from app.runtime import build_agent_pipeline
from app.rag.build_index import build_persistent_index
from app.spam import SpamService


app = FastAPI(title="NBFC LOS AI Email Ticketing Demo", version="0.1.0")
logger = logging.getLogger(__name__)
agent_pipeline = build_agent_pipeline(repository)
orchestrator = TicketOrchestrator(repository, agent_pipeline=agent_pipeline)
_session_factory = getattr(repository, "session_factory", None)
spam_service = SpamService(_session_factory) if _session_factory is not None else None


class KnowledgeIngestRequest(BaseModel):
    refresh_public: bool = False


def require_api_key(x_internal_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_api_key, settings.internal_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal API key")


@app.get("/health")
def health() -> dict[str, str]:
    healthcheck = getattr(repository, "healthcheck", None)
    if healthcheck is not None:
        try:
            healthcheck()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            ) from exc
    return {"status": "ok"}


@app.post("/api/v1/knowledge/ingest", dependencies=[Depends(require_api_key)])
def ingest_knowledge(request: KnowledgeIngestRequest) -> dict[str, int | str]:
    try:
        count = build_persistent_index(
            data_root=Path(os.getenv("DATA_ROOT", "data")),
            index_path=Path(os.getenv("RAG_INDEX_PATH", "data/faiss")),
            refresh_public=request.refresh_public,
        )
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("knowledge ingestion failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="knowledge embedding provider is unavailable",
        ) from exc
    return {"status": "indexed", "chunks": count}


@app.post("/api/v1/preflight", dependencies=[Depends(require_api_key)])
def preflight(email: IncomingEmail) -> dict:
    allowed, reasons = inspect_input(f"{email.subject}\n{email.body_text}")
    if not allowed:
        return {"allowed": False, "duplicate": False, "blocked": True, "ticket": None, "guardrail": {"spam": False, "prompt_injection": True, "reason_codes": reasons}}
    if spam_service is not None:
        spam = spam_service.evaluate(email)
        if spam.spam:
            return {
                "allowed": False,
                "duplicate": False,
                "blocked": spam.blocked,
                "ticket": None,
                "guardrail": {
                    "spam": True,
                    "prompt_injection": False,
                    "reason_codes": spam.reason_codes,
                },
            }
    if agent_pipeline is not None:
        try:
            semantic, execution = agent_pipeline.semantic_input_guardrail(email.model_dump(mode="json"))
            record_guardrail = getattr(repository, "record_guardrail_audit", None)
            if record_guardrail is not None:
                record_guardrail(execution, semantic.model_dump(mode="json"))
        except Exception as exc:
            logger.error("semantic input guardrail failed safely")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="input safety validation is temporarily unavailable",
            ) from exc
        if not semantic.allowed:
            return {
                "allowed": False,
                "duplicate": False,
                "blocked": True,
                "ticket": None,
                "guardrail": {
                    "spam": semantic.spam_confidence >= 90,
                    "prompt_injection": "PROMPT_INJECTION" in semantic.reason_codes,
                    "reason_codes": semantic.reason_codes,
                },
            }
    ticket, duplicate, is_new = repository.preflight(email)
    if duplicate:
        return {"allowed": False, "duplicate": True, "blocked": False, "ticket": None, "guardrail": {"spam": False, "prompt_injection": False, "reason_codes": []}}
    return {
        "allowed": True,
        "duplicate": False,
        "blocked": False,
        "ticket": {**ticket.model_dump(mode="json"), "is_new": is_new},
        "guardrail": {"spam": False, "prompt_injection": False, "reason_codes": []},
    }


@app.post("/api/v1/tickets/process", dependencies=[Depends(require_api_key)])
def process_ticket(request: ProcessTicketRequest) -> dict:
    try:
        return orchestrator.process(request).model_dump(mode="json")
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MessageNotPreflightedError, MessageBindingError, ProcessingInProgressError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/tickets/delivery", dependencies=[Depends(require_api_key)])
def delivery(request: DeliveryRequest) -> dict[str, str]:
    if request.delivery_status == "SENT" and not request.gmail_outbound_message_id:
        raise HTTPException(status_code=422, detail="gmail_outbound_message_id is required for SENT")
    try:
        duplicate = repository.record_delivery(request)
    except TicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MessageBindingError, DeliveryConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "duplicate" if duplicate else "recorded"}
