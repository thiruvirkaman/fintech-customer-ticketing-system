import pytest

from app.tools.serper import BoundedSerperSearch, SERPER_URL, SerperClient, generic_web_query


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "organic": [
                {
                    "title": "Blog",
                    "link": "https://example.com/blog",
                    "snippet": "General information",
                },
                {
                    "title": "RBI guidance",
                    "link": "https://www.rbi.org.in/guidance",
                    "snippet": "Authoritative information",
                },
                {"title": "Unsafe", "link": "http://example.com", "snippet": "ignored"},
            ]
        }


class FakeHttpClient:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_generic_query_removes_customer_identifiers() -> None:
    query = generic_web_query(
        "demo@example.com APP-DEMO-0010 PAN ABCDE1234F mobile 9876543210 bank statement encrypted"
    )

    assert "demo@example.com" not in query
    assert "APP-DEMO-0010" not in query
    assert "ABCDE1234F" not in query
    assert "9876543210" not in query
    assert "bank statement encrypted" in query


def test_serper_returns_https_provenance_and_prioritizes_authority() -> None:
    http = FakeHttpClient()
    client = SerperClient(api_key="test-serper-key", client=http)

    results = client.search("bank statement requirement")

    assert [result.source for result in results] == ["RBI guidance", "Blog"]
    assert all(result.source_type == "WEB" and result.source_url.startswith("https://") for result in results)
    assert http.calls[0][0] == SERPER_URL
    assert http.calls[0][1]["headers"]["X-API-KEY"] == "test-serper-key"


def test_web_search_is_bounded_to_two_attempts() -> None:
    bounded = BoundedSerperSearch(
        SerperClient(api_key="test-serper-key", client=FakeHttpClient()),
        max_attempts=2,
    )
    bounded.search("first bank statement question")
    bounded.search("refined bank statement question")

    with pytest.raises(RuntimeError, match="maximum web search attempts"):
        bounded.search("third query")

    assert bounded.attempts == 2

