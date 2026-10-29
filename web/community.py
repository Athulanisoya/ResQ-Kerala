"""HTMX community news and donation pledge workspace."""
from importlib import import_module
import secrets
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def _web():
    return import_module("web.app")

async def community_view(request, error=None, status_code=200, values=None, notice=None):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    data, errors = {}, []
    for key in ("news", "campaigns", "pledges"):
        response = await web.api_call(request, "GET", f"/api/community/{key}")
        data[key] = response.json() if response.status_code == 200 else []
        if response.status_code != 200:
            errors.append(web.error_message(response))
    values = dict(values or {})
    if "campaign_id" not in values:
        values["campaign_id"] = request.query_params.get("campaign_id", "")
    if notice is None and request.query_params.get("notice") == "pledge-recorded":
        notice = "Your donation pledge has been recorded. An administrator will review it."
    return web.render(request, "community.html", user=user, page_title="Community", active_nav="community",
                      status_code=status_code, error=error or next(iter(errors), None),
                      notice=notice, pledge_values=values,
                      pledge_key=values.get("idempotency_key") or secrets.token_urlsafe(24), **data)

@router.get("/community", response_class=HTMLResponse)
async def page(request: Request):
    return await community_view(request)

async def action(request, path, payload):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    response = await web.api_call(request, "POST", path, payload)
    if response.status_code in (200, 201):
        return web.redirect(request, "/community")
    return await community_view(request, error=web.error_message(response), status_code=response.status_code)

@router.post("/ui/community/news")
async def add_news(request: Request):
    form = request.state.form
    return await action(request, "/api/community/news", {"title": form.get("title", ""), "body": form.get("body", ""), "source": form.get("source") or None})

@router.post("/ui/community/news/{news_id}/{step}")
async def advance_news(request: Request, news_id: int, step: str):
    if step not in {"verify", "publish"}:
        return await community_view(request, error="Unknown news action", status_code=400)
    return await action(request, f"/api/community/news/{news_id}/{step}", {})

@router.post("/ui/community/campaigns")
async def add_campaign(request: Request):
    form = request.state.form
    return await action(request, "/api/community/campaigns", {"title": form.get("title", ""), "description": form.get("description", "")})

@router.post("/ui/community/campaigns/{campaign_id}/close")
async def close_campaign(request: Request, campaign_id: int):
    return await action(request, f"/api/community/campaigns/{campaign_id}/close", {})

@router.post("/ui/community/campaigns/{campaign_id}/pledges")
async def add_pledge(request: Request, campaign_id: int):
    form = request.state.form
    return await action(request, f"/api/community/campaigns/{campaign_id}/pledges", {"kind": form.get("kind"), "description": form.get("description", ""), "quantity": form.get("quantity", ""), "unit": form.get("unit", ""), "idempotency_key": form.get("idempotency_key", "")})

@router.post("/ui/community/pledges")
async def add_general_pledge(request: Request):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    values = dict(request.state.form)
    response = await web.api_call(request, "POST", "/api/community/pledges", {
        "campaign_id": values.get("campaign_id") or None,
        "kind": values.get("kind"), "description": values.get("description", ""),
        "quantity": values.get("quantity", ""), "unit": values.get("unit", ""),
        "idempotency_key": values.get("idempotency_key", ""),
    })
    if response.status_code == 201:
        if request.headers.get("HX-Request") == "true":
            result = await community_view(request, values={"campaign_id": ""},
                notice="Your donation pledge has been recorded. An administrator will review it.")
            result.headers["HX-Push-Url"] = "/community"
            return result
        return web.redirect(request, "/community?notice=pledge-recorded")
    return await community_view(request, error=web.error_message(response), status_code=response.status_code, values=values)

@router.post("/ui/community/pledges/{pledge_id}/review")
async def review_pledge(request: Request, pledge_id: int):
    form = request.state.form
    return await action(request, f"/api/community/pledges/{pledge_id}/review", {"status": form.get("status"), "note": form.get("note", "")})
