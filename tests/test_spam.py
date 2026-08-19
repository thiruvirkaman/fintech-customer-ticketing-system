from app.spam import classify_high_confidence_spam


def test_normal_customer_email_is_not_deterministic_spam() -> None:
    assert classify_high_confidence_spam(
        "Bank statement failed",
        "My password-protected statement was rejected. What should I do?",
    ) == []


def test_high_confidence_spam_patterns_are_reason_coded() -> None:
    reasons = classify_high_confidence_spam(
        "Guaranteed crypto offer",
        "Double your bitcoin now: https://a.example https://b.example",
    )
    assert "CRYPTO_PROMOTION" in reasons


def test_excessive_links_are_spam() -> None:
    body = " ".join(f"https://example.com/{index}" for index in range(5))
    assert classify_high_confidence_spam("Links", body) == ["EXCESSIVE_LINKS"]
