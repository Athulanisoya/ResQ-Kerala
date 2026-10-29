"""HTMX administration and aggregate reporting workspace."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
def web(): return import_module("web.app")

async def management_page(request, error=None, status_code=200):
    w = web()
    user = await w.current_user(request)
    if not user: return w.redirect(request, "/login")
    if user["role"] != "admin": return HTMLResponse("Only administrators may manage accounts and teams.", status_code=403)
    results = [await w.api_call(request, "GET", path) for path in
               ("/api/management/users", "/api/management/teams", "/api/management/reports")]
    for response in results:
        if response.status_code != 200:
            return w.render(request, "management.html", user=user, page_title="Administration", active_nav="management",
                            accounts=[], managed_teams=[], report={}, error=error or w.error_message(response),
                            status_code=response.status_code)
    return w.render(request, "management.html", user=user, page_title="Administration", active_nav="management",
                    accounts=results[0].json(), managed_teams=results[1].json(), report=results[2].json(),
                    error=error, status_code=status_code)

@router.get("/management")
async def index(request: Request):
    return await management_page(request)

async def _action(request, method, path, payload):
    w = web()
    user = await w.current_user(request)
    if not user: return w.redirect(request, "/login")
    if user["role"] != "admin": return HTMLResponse("Only administrators may manage accounts and teams.", status_code=403)
    response = await w.api_call(request, method, path, payload)
    if response.status_code in {200, 201}:
        return w.redirect(request, "/management")
    return await management_page(request, error=w.error_message(response), status_code=response.status_code)

@router.post("/ui/management/users/{user_id}")
async def update_user(request: Request, user_id: int):
    form = request.state.form
    team_id = form.get("team_id", "")
    try:
        team_id = int(team_id) if team_id else None
    except (TypeError, ValueError):
        return await management_page(request, error="Choose a valid team.", status_code=422)
    return await _action(request, "PATCH", f"/api/management/users/{user_id}", {
        "role": form.get("role", ""), "active": form.get("active") == "yes", "team_id": team_id})

@router.post("/ui/management/teams")
async def create_team(request: Request):
    form = request.state.form
    return await _action(request, "POST", "/api/management/teams", {
        "name": form.get("name", ""), "team_type": form.get("team_type", "")})

@router.post("/ui/management/teams/{team_id}")
async def update_team(request: Request, team_id: int):
    form = request.state.form
    return await _action(request, "PATCH", f"/api/management/teams/{team_id}", {
        "name": form.get("name", ""), "status": form.get("status", "")})
