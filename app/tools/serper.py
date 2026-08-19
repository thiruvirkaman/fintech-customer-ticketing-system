import re
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.ai.contracts import EvidenceItem


SERPER_URL = "https://google.serper.dev/search"
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
_MOBILE_OR_ACCOUNT = re.compile(r"(?<!\d)\d{8,18}(?!\d)")
_DEMO_IDENTIFIER = re.compile(r"\b(?:APP|CUST|TKT)-[A-Z0-9-]+\b", re.IGNORECASE)
_CONTROL = re.compile(r"[^\w\s?.,:/()\-]", re.UNICODE)

_OFFICIAL_DOMAINS = (
    "rbi.org.in",
    "npci.org.in",
    "transunioncibil.com",
    "cibil.com",
)


class HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...


def generic_web_query(text: str) -> str:
    sanitized = _EMAIL.sub(" ", text)
    sanitized = _PAN.sub(" ", sanitized)
    sanitized = _MOBILE_OR_ACCOUNT.sub(" ", sanitized)
    sanitized = _DEMO_IDENTIFIER.sub(" ", sanitized)
    sanitized = _CONTROL.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split())[:300].strip()
    if not sanitized:
        raise ValueError("web search query is empty after PII removal")
    return sanitized


class SerperClient:
    def __init__(self, *, api_key: str, timeout: float = 8.0, client: HttpClient | None = None) -> None:
        if not api_key:
            raise RuntimeError("SERPER_API_KEY is not configured")
        if not 1 <= timeout <= 20:
            raise ValueError("Serper timeout must be between 1 and 20 seconds")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client()

    def search(self, customer_question: str, *, max_results: int = 5) -> list[EvidenceItem]:
        if not 1 <= max_results <= 10:
            raise ValueError("max_results must be between 1 and 10")
        query = generic_web_query(customer_question)
        response = self._client.post(
            SERPER_URL,
            headers={"X-API-KEY": self._api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        organic = payload.get("organic", [])
        if not isinstance(organic, list):
            raise ValueError("Serper response has an invalid organic result list")

        parsed: list[tuple[int, int, EvidenceItem]] = []
        seen_urls: set[str] = set()
        for original_rank, item in enumerate(organic):
            if not isinstance(item, dict):
                continue
            url = str(item.get("link", "")).strip()
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            parsed_url = urlparse(url)
            if parsed_url.scheme != "https" or not parsed_url.netloc or not title or not snippet or url in seen_urls:
                continue
            seen_urls.add(url)
            host = (parsed_url.hostname or "").casefold()
            authority_rank = 0 if any(host == domain or host.endswith("." + domain) for domain in _OFFICIAL_DOMAINS) else 1
            digest = sha256(url.encode("utf-8")).hexdigest()[:16]
            parsed.append(
                (
                    authority_rank,
                    original_rank,
                    EvidenceItem(
                        evidence_id=f"WEB-{digest}",
                        source_type="WEB",
                        source=title,
                        source_url=url,
                        content=snippet,
                    ),
                )
            )
        parsed.sort(key=lambda entry: (entry[0], entry[1]))
        return [entry[2] for entry in parsed[:max_results]]


class BoundedSerperSearch:
    """Per-ticket counter that makes the two-attempt cap impossible to bypass accidentally."""

    def __init__(self, client: SerperClient, *, max_attempts: int = 2) -> None:
        if not 0 <= max_attempts <= 2:
            raise ValueError("max_attempts must be between 0 and 2")
        self._client = client
        self._max_attempts = max_attempts
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    def search(self, customer_question: str, *, max_results: int = 5) -> list[EvidenceItem]:
        if self._attempts >= self._max_attempts:
            raise RuntimeError("maximum web search attempts reached")
        self._attempts += 1
        return self._client.search(customer_question, max_results=max_results)

