from unittest.mock import patch

from backend.ai.summarizer import (
    fallback_summary,
    summarize_report,
)


def test_missing_api_key_returns_local_provisional_summary(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = summarize_report("Flood water entered a house in Kochi.")

    assert result["summary"] == "Report excerpts: Flood water entered a house in Kochi."
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True


def test_empty_report_requires_manual_review(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = summarize_report("")

    assert result["summary"] == (
        "No report text available. Manual review required."
    )
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True


def test_configured_api_key_does_not_trigger_network_summarization(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch("socket.socket.connect", side_effect=AssertionError("Unexpected network request")):
        result = summarize_report(
            "Flood water entered a house in Kochi."
        )

    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True
    assert result["summary"] == "Report excerpts: Flood water entered a house in Kochi."


def test_fallback_summary_does_not_invent_facts():
    result = fallback_summary(
        "A family reported flooding in Kochi."
    )

    assert "Kochi" not in result
    assert "injured" not in result.lower()
    assert "trapped" not in result.lower()
    assert "Review the original report manually." in result
