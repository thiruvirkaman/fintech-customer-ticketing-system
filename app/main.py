import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status

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


app = FastAPI(title="NBFC LOS AI Email Ticketing Demo", version="0.1.0")
orchestrator = TicketOrchestrator(repository)


def require_api_key(x_internal_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_api_key, settings.internal_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal API key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/preflight", dependencies=[Depends(require_api_key)])
def preflight(email: IncomingEmail) -> dict:
    allowed, reasons = inspect_input(f"{email.subject}\n{email.body_text}")
    if not allowed:
        return {"allowed": False, "duplicate": False, "blocked": True, "ticket": None, "guardrail": {"spam": False, "prompt_injection": True, "reason_codes": reasons}}
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
