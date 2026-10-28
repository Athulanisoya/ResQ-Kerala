from types import SimpleNamespace

from backend.ai.report_summarizer import summarize_report


def make_report(message, **overrides):
    data = {
        "message": message,
        "location": "Kochi",
        "people_affected": None,
        "help_required": None,
        "disaster_type": "Flood",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_summary_preserves_explicit_negation():
    report = make_report(
        "Water entered my house. No one is injured."
    )

    summary = summarize_report(report)

    assert "No one is injured." in summary


def test_summary_does_not_invent_injuries():
    report = make_report(
        "Water entered my house. We need drinking water."
    )

    summary = summarize_report(report)

    assert "Water entered my house." in summary
    assert "We need drinking water." in summary
    assert "injured" not in summary.lower()
    assert "trapped" not in summary.lower()


def test_summary_preserves_uncertainty():
    report = make_report(
        "Water entered my house. I don't know whether anyone is trapped."
    )

    summary = summarize_report(report)

    assert "I don't know whether anyone is trapped." in summary


def test_summary_does_not_invent_people_affected():
    report = make_report("Flood water entered the house.")

    summary = summarize_report(report)

    assert "Flood water entered the house." in summary
    assert "People affected" not in summary