"""HTMX pages for explicitly assigned investigation teams."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def _web():
    return import_module("web.app")

@router.get("/investigations")
async def investigations_page(request: Request):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    if user["role"] != "response_team":
        return HTMLResponse("Only investigation team members can view assignments.", status_code=403)
    response = await web.api_call(request, "GET", "/api/admin/incidents/investigations/assigned")
    return web.render(request, "investigations.html", user=user, page_title="Investigations",
                      active_nav="investigations", assignments=response.json() if response.status_code == 200 else [],
                      error=None if response.status_code == 200 else web.error_message(response),
                      status_code=response.status_code)

@router.post("/ui/reports/{incident_id}/investigation/team")
async def assign_team(request: Request, incident_id: int):
    web = _web()
    denied = await web.report_admin(request)
    if denied is not None:
        return denied
    try:
        team_id = int(request.state.form.get("team_id", ""))
    except (TypeError, ValueError):
        return await web.detail_page(request, incident_id, error="Choose an investigation team.", status_code=422)
    response = await web.api_call(request, "POST", f"/api/admin/incidents/{incident_id}/investigation/team", {"team_id": team_id})
    if response.status_code == 200:
        return web.redirect(request, f"/reports/{incident_id}")
    return await web.detail_page(request, incident_id, error=web.error_message(response), status_code=response.status_code)

@router.post("/ui/investigations/{investigation_id}")
async def update_assigned(request: Request, investigation_id: int):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    if user["role"] != "response_team":
        return HTMLResponse("Only assigned investigation teams can update findings.", status_code=403)
    form = request.state.form
    response = await web.api_call(request, "PATCH", f"/api/admin/incidents/investigations/{investigation_id}",
        {"status": form.get("status", "IN_PROGRESS"), "findings": form.get("findings", ""),
         "action_taken": form.get("action_taken") or None})
    if response.status_code == 200:
        return web.redirect(request, "/investigations")
    return HTMLResponse(web.error_message(response), status_code=response.status_code)
