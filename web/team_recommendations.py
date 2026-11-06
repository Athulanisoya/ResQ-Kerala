"""HTMX administration for declared coverage and explicit team suggestions."""
from importlib import import_module
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.services.team_recommendation_service import coverage_catalog


router = APIRouter(include_in_schema=False)


def web():
    return import_module("web.app")


async def administrator(request):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return None, ui.redirect(request, "/login")
    if user["role"] != "admin":
        return None, HTMLResponse("Only administrators can manage team coverage and recommendations.", status_code=403)
    return user, None


async def coverage_view(request, team_id, *, values=None, error=None, notice=None, status_code=200):
    ui = web()
    user, denied = await administrator(request)
    if denied is not None:
        return denied
    response = await ui.api_call(request, "GET", f"/api/admin/teams/{team_id}/coverage")
    if response.status_code != 200:
        return ui.render(request, "team_coverage.html", user=user, active_nav="management", page_title="Team operating areas",
                         profile=None, catalog=coverage_catalog(), values={}, error=ui.error_message(response),
                         status_code=response.status_code)
    profile = response.json()
    return ui.render(request, "team_coverage.html", user=user, active_nav="management", page_title="Team operating areas",
                     profile=profile, catalog=coverage_catalog(), values=values or profile, error=error, notice=notice,
                     status_code=status_code)


@router.get("/team-coverage/{team_id}", response_class=HTMLResponse)
async def coverage(request: Request, team_id: int):
    return await coverage_view(request, team_id)


@router.post("/ui/teams/{team_id}/coverage", response_class=HTMLResponse)
async def save_coverage(request: Request, team_id: int):
    ui = web()
    user, denied = await administrator(request)
    if denied is not None:
        return denied
    form = request.state.form
    values = {"area_ids": [key.removeprefix("area:") for key, value in form.items() if key.startswith("area:") and value == "true"],
              "capabilities": [key.removeprefix("capability:") for key, value in form.items() if key.startswith("capability:") and value == "true"],
              "note": str(form.get("note", "")), "version": form.get("expected_version", "")}
    try:
        payload = {"area_ids": values["area_ids"], "capabilities": values["capabilities"], "note": values["note"],
                   "expected_version": int(values["version"])}
    except (ValueError, TypeError):
        return await coverage_view(request, team_id, values=values, error="Reload the team's current coverage version before saving.", status_code=422)
    response = await ui.api_call(request, "PUT", f"/api/admin/teams/{team_id}/coverage", payload)
    if response.status_code != 200:
        return await coverage_view(request, team_id, values=values, error=ui.error_message(response), status_code=response.status_code)
    result = await coverage_view(request, team_id, notice="Team operating areas and capabilities saved.")
    result.headers["HX-Push-Url"] = f"/team-coverage/{team_id}"
    return result


@router.get("/ui/reports/{incident_id}/team-recommendations", response_class=HTMLResponse)
async def candidates(request: Request, incident_id: int, team_type: str = "Rescue", capability: str = ""):
    ui = web()
    user, denied = await administrator(request)
    if denied is not None:
        return denied
    query = {"team_type": team_type}
    if capability:
        query["capability"] = capability
    response = await ui.api_call(request, "GET", f"/api/admin/incidents/{incident_id}/team-recommendations?" + urlencode(query))
    return ui.render(request, "partials/team_recommendations.html", user=user, incident_id=incident_id,
                     recommendations=response.json() if response.status_code == 200 else None,
                     recommendation_error=ui.error_message(response) if response.status_code != 200 else None,
                     recommendation_type=team_type, recommendation_capability=capability,
                     catalog=coverage_catalog(), status_code=response.status_code)
