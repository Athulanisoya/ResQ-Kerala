import hashlib

from backend.ai.week4_orchestrator import (
    Week4Context,
    tool_1_extract_location,
    tool_7_assemble_evidence,
)
from backend.ai.week4_orchestrator import (
    Week4Context,
    assemble_evidence,
)

class FakeRunContext:
    """Minimal context wrapper for testing the pure tool logic."""

    def __init__(self, context):
        self.context = context


class FakeIncident:
    id = 101


def test_original_malayalam_text_is_preserved():
    original = "ആലപ്പുഴയിൽ വെള്ളം കയറുന്നു, സഹായം വേണം."

    context = Week4Context(
        db=None,
        incident=FakeIncident(),
        original_text=original,
        reported_location="Alappuzha",
    )

    assert context.original_text == original

    expected_hash = hashlib.sha256(
        original.encode("utf-8")
    ).hexdigest()

    assert expected_hash == hashlib.sha256(
        context.original_text.encode("utf-8")
    ).hexdigest()


def test_assembly_reports_missing_tools():
    context = Week4Context(
        db=None,
        incident=FakeIncident(),
        original_text="വെള്ളം കയറുന്നു, സഹായം വേണം.",
        reported_location="Alappuzha",
    )

    # Only populate the first tool's output.
    context.results["tool_1_extract_location"] = {
        "status": "UNCERTAIN",
        "place": None,
    }

    result = assemble_evidence(context)
    

    assert result["status"] == "incomplete"
    assert result["human_review_required"] is True
    assert "tool_2_check_alerts" in result["missing_tools"]
    assert "tool_6_search_shelters" in result["missing_tools"]