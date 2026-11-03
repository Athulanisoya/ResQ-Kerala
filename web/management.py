"""HTMX administration and aggregate reporting workspace."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)
MANAGEMENT_TABS = {"create-team", "accounts", "teams", "reports"}
def web(): return import_module("web.app")

async def management_page(request, error=None, status_code=200, notice=None, new_account_values=None,
                          *, tab=None, new_team_values=None, account_values=None, edited_account_id=None,
                          team_values=None, edited_team_id=None):
    w = web()
    user = await w.current_user(request)
    if not user: return w.redirect(request, "/login")
    if user["role"] != "admin": return HTMLResponse("Only administrators may manage accounts and teams.", status_code=403)
    selected = tab if tab is not None else request.query_params.get("tab", "create-team")
    selected = selected if selected in MANAGEMENT_TABS else "create-team"
    context = {
        "user": user, "page_title": "Administration", "active_nav": "management",
        "management_tab": selected, "notice": notice,
        "new_account_values": new_account_values or {}, "new_team_values": new_team_values or {},
        "account_values": account_values or {}, "edited_account_id": edited_account_id,
        "team_values": team_values or {}, "edited_team_id": edited_team_id,
    }

    def render_page(*, accounts=None, managed_teams=None, report=None, error=None, response_status=200):
        result = w.render(request, "management.html", **context,
                          accounts=accounts or [], managed_teams=managed_teams or [], report=report or {},
                          error=error, status_code=response_status)
        if request.method == "POST" and request.headers.get("HX-Request") == "true":
            result.headers["HX-Push-Url"] = f"/management?tab={selected}"
        return result

    results = [await w.api_call(request, "GET", path) for path in
               ("/api/management/users", "/api/management/teams", "/api/management/reports")]
    for response in results:
        if response.status_code != 200:
            return render_page(error=error or w.error_message(response), response_status=response.status_code)
    return render_page(accounts=results[0].json(), managed_teams=results[1].json(), report=results[2].json(),
                       error=error, response_status=status_code)

@router.get("/management")
async def index(request: Request):
    return await management_page(request)

async def _action(request, method, path, payload, *, tab, notice, **retained_values):
    w = web()
    user = await w.current_user(request)
    if not user: return w.redirect(request, "/login")
    if user["role"] != "admin": return HTMLResponse("Only administrators may manage accounts and teams.", status_code=403)
    response = await w.api_call(request, method, path, payload)
    if response.status_code in {200, 201}:
        if request.headers.get("HX-Request") != "true":
            return w.redirect(request, f"/management?tab={tab}")
        return await management_page(request, tab=tab, notice=notice)
    return await management_page(request, error=w.error_message(response), status_code=response.status_code,
                                 tab=tab, **retained_values)

@router.post("/ui/management/users/{user_id}")
async def update_user(request: Request, user_id: int):
    form = request.state.form
    values = {key: form.get(key, "") for key in ("role", "team_id", "active")}
    team_id = form.get("team_id", "")
    try:
        team_id = int(team_id) if team_id else None
    except (TypeError, ValueError):
        return await management_page(request, error="Choose a valid team.", status_code=422,
                                     tab="accounts", account_values=values, edited_account_id=user_id)
    return await _action(request, "PATCH", f"/api/management/users/{user_id}", {
        "role": form.get("role", ""), "active": form.get("active") == "yes", "team_id": team_id},
        tab="accounts", notice="Account saved. Access changes require the member to sign in again.",
        account_values=values, edited_account_id=user_id)

@router.post("/ui/management/team-accounts")
async def create_team_account(request: Request):
    w = web()
    user = await w.current_user(request)
    if not user: return w.redirect(request, "/login")
    if user["role"] != "admin": return HTMLResponse("Only administrators may create team accounts.", status_code=403)
    form = request.state.form
    # Re-render only non-sensitive values. Passwords never appear in page HTML.
    values = {key: form.get(key, "") for key in ("full_name", "email", "team_id")}
    if form.get("password") != form.get("confirm_password"):
        return await management_page(request, error="The passwords do not match.", status_code=422,
                                     tab="create-team", new_account_values=values)
    response = await w.api_call(request, "POST", "/api/management/team-accounts", {
        **values, "password": form.get("password", ""),
    })
    if response.status_code == 201:
        if request.headers.get("HX-Request") != "true":
            return w.redirect(request, "/management?tab=create-team")
        return await management_page(request, tab="create-team",
                                     notice="Team account created. The team member can now sign in with the email and password you set.")
    return await management_page(request, error=w.error_message(response), status_code=response.status_code,
                                 tab="create-team", new_account_values=values)

@router.post("/ui/management/teams")
async def create_team(request: Request):
    form = request.state.form
    values = {key: form.get(key, "") for key in ("name", "team_type")}
    return await _action(request, "POST", "/api/management/teams", {
        "name": form.get("name", ""), "team_type": form.get("team_type", "")},
        tab="create-team", notice="Response team created. You can now add a team member account.",
        new_team_values=values)

@router.post("/ui/management/teams/{team_id}")
async def update_team(request: Request, team_id: int):
    form = request.state.form
    values = {key: form.get(key, "") for key in ("name", "status")}
    return await _action(request, "PATCH", f"/api/management/teams/{team_id}", {
        "name": form.get("name", ""), "status": form.get("status", "")},
        tab="teams", notice="Response team updated.", team_values=values, edited_team_id=team_id)
