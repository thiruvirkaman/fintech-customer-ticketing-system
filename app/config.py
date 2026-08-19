import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    internal_api_key: str
    confidence_threshold: int
    max_web_search_attempts: int

    @classmethod
    def from_env(cls) -> "Settings":
        internal_api_key = os.getenv("INTERNAL_API_KEY", "")
        if len(internal_api_key) < 16:
            raise RuntimeError("INTERNAL_API_KEY must be set and contain at least 16 characters")

        confidence_threshold = _bounded_int("CONFIDENCE_THRESHOLD", default=70, minimum=1, maximum=100)
        max_web_search_attempts = _bounded_int("MAX_WEB_SEARCH_ATTEMPTS", default=2, minimum=0, maximum=2)
        return cls(
            internal_api_key=internal_api_key,
            confidence_threshold=confidence_threshold,
            max_web_search_attempts=max_web_search_attempts,
        )


def _bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


settings = Settings.from_env()
