import io
import ipaddress
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader


MAX_SOURCE_BYTES = 2 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "text/html",
    "text/markdown",
    "text/plain",
}


class HttpGetClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._parts)


def read_local_source(path: Path, *, max_bytes: int = MAX_SOURCE_BYTES) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"knowledge source exceeds {max_bytes} bytes: {path.name}")
    suffix = path.suffix.casefold()
    if suffix in {".md", ".markdown", ".txt"}:
        content = path.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        content = extract_pdf_text(path.read_bytes())
    else:
        raise ValueError(f"unsupported knowledge source type: {suffix or '<none>'}")
    if not content.strip():
        raise ValueError(f"knowledge source contains no extractable text: {path.name}")
    return content


def extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except Exception as exc:
        raise ValueError("knowledge PDF could not be parsed") from exc
    if not text.strip():
        raise ValueError("knowledge PDF contains no extractable text")
    return text


class PublicSourceFetcher:
    def __init__(
        self,
        *,
        allowed_hosts: set[str],
        timeout: float = 10.0,
        max_bytes: int = MAX_SOURCE_BYTES,
        client: HttpGetClient | None = None,
    ) -> None:
        normalized_hosts = {host.casefold().strip().strip(".") for host in allowed_hosts if host.strip()}
        if not normalized_hosts:
            raise ValueError("at least one public source host must be allowlisted")
        if not 1 <= timeout <= 20:
            raise ValueError("public source timeout must be between 1 and 20 seconds")
        if not 1 <= max_bytes <= 10 * 1024 * 1024:
            raise ValueError("public source size limit must be between 1 byte and 10 MiB")
        self._allowed_hosts = normalized_hosts
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._client = client or httpx.Client(follow_redirects=False)

    def fetch(self, url: str) -> str:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold().strip(".")
        if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
            raise ValueError("public knowledge URL must be an absolute credential-free HTTPS URL")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (address.is_private or address.is_loopback or address.is_link_local):
            raise ValueError("public knowledge URL cannot target a private address")
        if not any(hostname == host or hostname.endswith("." + host) for host in self._allowed_hosts):
            raise ValueError(f"public knowledge host is not allowlisted: {hostname}")

        response = self._client.get(
            url,
            timeout=self._timeout,
            follow_redirects=False,
            headers={"Accept": "text/html,text/plain,text/markdown,application/pdf"},
        )
        response.raise_for_status()
        content_type = str(response.headers.get("content-type", "")).split(";", 1)[0].casefold().strip()
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(f"unsupported public knowledge content type: {content_type or '<missing>'}")
        declared_length = response.headers.get("content-length")
        if declared_length:
            try:
                parsed_length = int(declared_length)
            except ValueError as exc:
                raise ValueError("public knowledge source has an invalid Content-Length") from exc
            if parsed_length < 0:
                raise ValueError("public knowledge source has an invalid Content-Length")
            if parsed_length > self._max_bytes:
                raise ValueError("public knowledge source exceeds configured size limit")
        raw = bytes(response.content)
        if len(raw) > self._max_bytes:
            raise ValueError("public knowledge source exceeds configured size limit")
        if content_type == "application/pdf":
            return extract_pdf_text(raw)
        charset = response.encoding or "utf-8"
        try:
            decoded = raw.decode(charset)
        except (LookupError, UnicodeDecodeError) as exc:
            raise ValueError("public knowledge source has invalid text encoding") from exc
        if content_type == "text/html":
            parser = _VisibleTextParser()
            parser.feed(decoded)
            decoded = parser.text()
        if not decoded.strip():
            raise ValueError("public knowledge source contains no extractable text")
        return decoded
