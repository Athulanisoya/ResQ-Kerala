from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.ai.translator import translate_text


def test_empty_input_requires_manual_review():
    result = translate_text("")

    assert result["translated_text"] == ""
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True


def test_missing_api_key_fails_safely(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = translate_text("No one is injured.")

    assert result["translated_text"] == ""
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True


def test_translation_prompt_preserves_critical_facts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    response = SimpleNamespace(
        output_text="കൊച്ചിയിൽ വെള്ളം കയറി. ആരും പരിക്കേറ്റിട്ടില്ല."
    )

    mock_client = Mock()
    mock_client.interactions.create.return_value = response

    with patch(
        "backend.ai.translator.genai.Client",
        return_value=mock_client,
    ):
        result = translate_text(
            "Flood water entered Kochi. No one is injured."
        )

    prompt = mock_client.interactions.create.call_args.kwargs["input"]

    assert result["translated_text"] == (
        "കൊച്ചിയിൽ വെള്ളം കയറി. ആരും പരിക്കേറ്റിട്ടില്ല."
    )
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True

    assert "Preserve negation" in prompt
    assert "Preserve uncertainty" in prompt
    assert "Preserve locations, names, dates, and numbers exactly" in prompt
    assert "Do not add, remove, or infer incident details" in prompt


def test_provider_failure_fails_safely(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch(
        "backend.ai.translator.genai.Client",
        side_effect=RuntimeError("Simulated provider failure"),
    ):
        result = translate_text("Flood water entered Kochi.")

    assert result["translated_text"] == ""
    assert result["is_provisional"] is True
    assert result["requires_manual_review"] is True


def test_empty_translation_fails_safely(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_client = Mock()
    mock_client.interactions.create.return_value = SimpleNamespace(
        output_text="   "
    )

    with patch(
        "backend.ai.translator.genai.Client",
        return_value=mock_client,
    ):
        result = translate_text("Flood water entered Kochi.")

    assert result["translated_text"] == ""
    assert result["requires_manual_review"] is True