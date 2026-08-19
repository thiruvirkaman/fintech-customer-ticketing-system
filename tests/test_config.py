import pytest

from app.config import Settings, _bounded_int


def test_bounded_integer_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0")
    with pytest.raises(RuntimeError, match="between 1 and 100"):
        _bounded_int("CONFIDENCE_THRESHOLD", default=70, minimum=1, maximum=100)


def test_internal_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="at least 16 characters"):
        Settings.from_env()
