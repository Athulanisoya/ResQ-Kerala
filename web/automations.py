from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(include_in_schema=False)


async def page(request, *, error=None, notice=None, values=None, status_code=200):
    ui = import_module("web.app")
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Administrator access is required.", status_code=403)
    response = await ui.api_call(request, "GET", "/api/admin/automations")
    data = response.json() if response.status_code == 200 else {}
    return ui.render(request, "automations.html", user=user, active_nav="automations", page_title="Automation settings",
                     automation=data, values=values or {}, error=error or (ui.error_message(response) if response.status_code != 200 else None),
                     notice=notice, status_code=status_code if error else response.status_code)


@router.get("/automation-settings", response_class=HTMLResponse)
async def settings(request: Request):
    return await page(request)


@router.post("/ui/automation-settings", response_class=HTMLResponse)
async def save(request: Request):
    ui = import_module("web.app")
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Administrator access is required.", status_code=403)
    form = dict(request.state.form)
    try:
        payload = {key: int(form.get(key, "")) for key in ("stale_minutes", "reminder_minutes", "escalation_minutes", "waitlist_offer_minutes", "expected_version")}
    except (ValueError, TypeError):
        return await page(request, error="Enter whole-minute thresholds and reload the latest settings.", values=form, status_code=422)
    response = await ui.api_call(request, "PUT", "/api/admin/automations", payload)
    if response.status_code != 200:
        return await page(request, error=ui.error_message(response), values=form, status_code=response.status_code)
    return await page(request, notice="Automation settings saved. New checks use these thresholds; existing offers retain their displayed deadlines.")


@router.post("/ui/automation-settings/run", response_class=HTMLResponse)
async def run(request: Request):
    ui = import_module("web.app")
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Administrator access is required.", status_code=403)
    response = await ui.api_call(request, "POST", "/api/admin/automations/run")
    if response.status_code != 200:
        return await page(request, error=ui.error_message(response), status_code=response.status_code)
    return await page(request, notice="Checks completed. Review the latest status below.")
