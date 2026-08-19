import re
import unicodedata

from app.models import GuardrailResult


PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
MOBILE_PATTERN = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")
ACCOUNT_PATTERN = re.compile(r"(?<!\d)\d{8,18}(?!\d)")
INJECTION_PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override|forget|bypass)\b.{0,50}\b(?:previous|prior|system|all|your)\b.{0,30}\b(?:instructions?|rules?|prompts?)\b"),
    re.compile(r"\b(?:show|reveal|print|expose|list|return)\b.{0,50}\b(?:system prompts?|hidden instructions?|secrets?|credentials?|api[_ -]?keys?|database passwords?)\b"),
    re.compile(r"\b(?:database password|system prompt|reveal your api key)\b"),
)
PROHIBITED_OUTPUT_PATTERNS = {
    "SECRET_OR_CREDENTIAL": re.compile(
        r"(?:\b(?:api[_ -]?key|password|secret|access[_ -]?token|refresh[_ -]?token)\b\s*(?::|=|\bis\b)?\s+[A-Za-z0-9_./+=~-]{4,}|\bauthorization\s*:\s*\S+(?:\s+\S+)?|\bbearer\s+[A-Za-z0-9_./+=~-]{4,})",
        re.IGNORECASE,
    ),
    "INTERNAL_INSTRUCTION": re.compile(
        r"\b(?:system prompt|hidden instruction|internal reasoning|chain of thought)\b",
        re.IGNORECASE,
    ),
}


def inspect_input(text: str) -> tuple[bool, list[str]]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[\s\W_]+", " ", normalized)
    reasons = ["PROMPT_INJECTION"] if any(pattern.search(normalized) for pattern in INJECTION_PATTERNS) else []
    return not reasons, reasons


def inspect_output(text: str) -> GuardrailResult:
    masked_fields: list[str] = []

    def mask_pan(match: re.Match[str]) -> str:
        masked_fields.append("PAN")
        return "******" + match.group(0)[-5:]

    def mask_mobile(match: re.Match[str]) -> str:
        masked_fields.append("MOBILE")
        return "******" + match.group(0)[-4:]

    def mask_account(match: re.Match[str]) -> str:
        masked_fields.append("BANK_ACCOUNT")
        return "*" * (len(match.group(0)) - 4) + match.group(0)[-4:]

    masked = PAN_PATTERN.sub(mask_pan, text)
    masked = MOBILE_PATTERN.sub(mask_mobile, masked)
    masked = ACCOUNT_PATTERN.sub(mask_account, masked)
    violations = [name for name, pattern in PROHIBITED_OUTPUT_PATTERNS.items() if pattern.search(masked)]
    return GuardrailResult(
        safe_to_send=not violations,
        violations=violations,
        masked_fields=sorted(set(masked_fields)),
        text=masked,
    )


def mask_sensitive(text: str) -> GuardrailResult:
    """Backward-compatible name for callers that need the full output inspection."""
    return inspect_output(text)


def sanitize_web_query(text: str) -> str:
    sanitized = inspect_output(text).text
    for pattern in PROHIBITED_OUTPUT_PATTERNS.values():
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized
