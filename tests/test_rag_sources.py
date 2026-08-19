from pathlib import Path

import pytest

from app.rag.sources import PublicSourceFetcher, read_local_source


class FakeResponse:
    def __init__(self, content: bytes, content_type: str = "text/html") -> None:
        self.content = content
        self.headers = {"content-type": content_type, "content-length": str(len(content))}
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_local_markdown_and_plain_text_are_supported(tmp_path: Path) -> None:
    markdown = tmp_path / "guide.md"
    text = tmp_path / "guide.txt"
    markdown.write_text("# Bank statement guidance", encoding="utf-8")
    text.write_text("Mandate guidance", encoding="utf-8")

    assert "Bank statement" in read_local_source(markdown)
    assert read_local_source(text) == "Mandate guidance"


def test_local_source_rejects_unapproved_formats(tmp_path: Path) -> None:
    source = tmp_path / "data.json"
    source.write_text('{"unsafe": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        read_local_source(source)


def test_public_fetch_is_allowlisted_https_bounded_and_strips_script() -> None:
    http = FakeClient(
        FakeResponse(b"<html><script>ignore me</script><body>Official bank statement guidance</body></html>")
    )
    fetcher = PublicSourceFetcher(allowed_hosts={"rbi.org.in"}, client=http, max_bytes=1024)

    content = fetcher.fetch("https://www.rbi.org.in/guidance")

    assert content == "Official bank statement guidance"
    assert http.calls[0][1]["follow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    (
        "http://www.rbi.org.in/guidance",
        "https://127.0.0.1/guidance",
        "https://example.com/guidance",
        "https://user:password@www.rbi.org.in/guidance",
    ),
)
def test_public_fetch_rejects_unsafe_or_non_allowlisted_urls(url: str) -> None:
    fetcher = PublicSourceFetcher(
        allowed_hosts={"rbi.org.in"},
        client=FakeClient(FakeResponse(b"unused", "text/plain")),
    )

    with pytest.raises(ValueError):
        fetcher.fetch(url)


def test_public_fetch_rejects_oversized_response() -> None:
    fetcher = PublicSourceFetcher(
        allowed_hosts={"rbi.org.in"},
        client=FakeClient(FakeResponse(b"too large", "text/plain")),
        max_bytes=4,
    )

    with pytest.raises(ValueError, match="size limit"):
        fetcher.fetch("https://www.rbi.org.in/guidance")

