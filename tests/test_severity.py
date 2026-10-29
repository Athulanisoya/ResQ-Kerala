"""Exercise the shipped severity model and its authenticated API boundary."""

import pytest

from backend.tests.test_auth import api, synthetic_password_hash
from backend.ai import severity_model


def test_shipped_model_loads_relative_to_module_and_normalizes_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    severity_model.get_pipeline.cache_clear()
    message = "  A CHILD is trapped\ninside a flooded house.  "
    normalized = "a child is trapped inside a flooded house."
    assert severity_model.clean_text(message) == normalized
    prediction = severity_model.predict_severity(message)
    assert prediction == "High"
    assert prediction == severity_model.predict_severity(normalized)
    assert severity_model.MODEL_PATH.is_file()


@pytest.mark.parametrize("message,expected", [
    ("A child is trapped inside a flooded house.", "High"),
    ("Water is accumulating near the school compound.", "Low"),
    ("Flood water has blocked the main road in Ernakulam", "Moderate"),
])
def test_shipped_model_preserves_its_three_severity_labels(message, expected):
    assert severity_model.predict_severity(message) == expected


def test_admin_can_predict_using_the_shipped_model(api):
    response = api.client.post("/api/ai/predict-severity", headers=api.headers("admin"),
                               json={"message": "  A child is trapped inside a flooded house.  "})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["message"] == "A child is trapped inside a flooded house."
    assert result["predicted_severity"] == "High"
    assert 0 <= result["model_score"] <= 1
    assert result["requires_manual_review"] is True


@pytest.mark.parametrize("role,expected", [(None, 401), ("citizen", 403), ("response_team", 403)])
def test_prediction_requires_an_admin_session(api, role, expected):
    response = api.client.post("/api/ai/predict-severity", headers=api.headers(role) if role else {},
                               json={"message": "Flood water is rising near the school."})
    assert response.status_code == expected


@pytest.mark.parametrize("payload", [
    {}, {"message": "    "}, {"message": "Help"}, {"message": "x" * 5001},
    {"message": None}, {"message": 12345},
    {"message": "Flood water is rising.", "severity": "Low"},
])
def test_invalid_messages_are_rejected(api, payload):
    response = api.client.post("/api/ai/predict-severity", headers=api.headers("admin"), json=payload)
    assert response.status_code == 422


def test_missing_model_returns_a_service_error_without_breaking_other_routes(api, monkeypatch, tmp_path):
    severity_model.get_pipeline.cache_clear()
    monkeypatch.setattr(severity_model, "MODEL_PATH", tmp_path / "missing.joblib")
    try:
        response = api.client.post("/api/ai/predict-severity", headers=api.headers("admin"),
                                   json={"message": "Flood water is rising near the school."})
        assert response.status_code == 503
        assert response.json() == {"detail": "Severity prediction is temporarily unavailable."}
        assert api.client.get("/health").status_code == 200
    finally:
        severity_model.get_pipeline.cache_clear()


def test_unexpected_model_output_becomes_a_service_error(monkeypatch):
    class InvalidPipeline:
        def predict(self, _messages):
            return ["Unknown"]

    monkeypatch.setattr(severity_model, "get_pipeline", lambda: InvalidPipeline())
    with pytest.raises(severity_model.SeverityUnavailable):
        severity_model.predict_severity("Flood water is rising.")


@pytest.mark.parametrize("message", [
    "no flooding, nobody is trapped or injured",
    "asdf qwerty zxcv",
    "വെള്ളം കയറി ഞങ്ങൾ കുടുങ്ങി അടിയന്തര രക്ഷാപ്രവർത്തനം വേണം",
])
def test_uncertain_messages_require_manual_review(api, message):
    response = api.client.post("/api/ai/predict-severity", headers=api.headers("admin"), json={"message": message})
    assert response.status_code == 422
    assert "review" in response.json()["detail"].lower()
