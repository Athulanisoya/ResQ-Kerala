"""Local summary adapter for the merged report-analysis snapshot contract.

Citizen submission stays offline and does not wait for a language model. The
optional Gemma 4 location agent is a separate explicit administrator action.
"""
from types import SimpleNamespace

from backend.ai.report_summarizer import summarize_report as extract_summary


def fallback_summary(message: str) -> str:
    if not message or not message.strip():
        return "No report text available. Manual review required."
    return "Summary unavailable. Review the original report manually."


def summarize_report(message) -> dict:
    """Accept the historical text argument or a complete incident record."""
    incident = SimpleNamespace(message=message) if isinstance(message, str) else message
    summary = extract_summary(incident)
    if not summary.strip():
        summary = fallback_summary(getattr(incident, "message", ""))
    return {
        "summary": summary,
        "is_provisional": True,
        "requires_manual_review": True,
    }
