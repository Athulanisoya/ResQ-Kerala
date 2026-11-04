"""Explicit review of classifier suggestions, separate from inference."""
from importlib import import_module

from fastapi import APIRouter, Request


router = APIRouter(include_in_schema=False)


async def severity_context(request, incident_id):
    ui = import_module("web.app")
    response = await ui.api_call(request, "GET", f"/api/ai/incidents/{incident_id}/severity-predictions")
    return {"severity_predictions": response.json() if response.status_code == 200 else [],
            "severity_error": None if response.status_code == 200 else ui.error_message(response)}


@router.post("/ui/reports/{incident_id}/severity-suggestions/{prediction_id}/review")
async def review_suggestion(request: Request, incident_id: int, prediction_id: int):
    ui = import_module("web.app")
    denied = await ui.report_admin(request)
    if denied is not None:
        return denied
    form = dict(request.state.form)
    form["severity_prediction_id"] = str(prediction_id)
    payload = {"action": form.get("action", ""), "note": form.get("decision_note") or None}
    if payload["action"] == "edit":
        payload["severity"] = form.get("reviewed_severity", "")
    response = await ui.api_call(request, "POST",
                                 f"/api/ai/incidents/{incident_id}/severity-predictions/{prediction_id}/review", payload)
    if response.status_code != 200:
        return await ui.detail_page(request, incident_id, error=ui.error_message(response),
                                    status_code=response.status_code, values=form)
    decision = response.json()["decision"]
    if form.get("analysis_form") and decision["action"] in {"accept", "edit"}:
        form["severity"] = decision["reviewed_severity"]
    return await ui.detail_page(request, incident_id, values=form,
                                notice=("Severity suggestion rejected. The reviewed assessment has not changed."
                                        if decision["action"] == "reject"
                                        else "Severity review saved. Other saved assessment fields have been preserved."))
