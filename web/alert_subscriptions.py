"""A consistent HTMX screen for private followed alert areas."""
from importlib import import_module
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(include_in_schema=False)


async def view(request, *, notice=None, error=None, status_code=200):
    ui = import_module("web.app")
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    follows = await ui.api_call(request, "GET", "/api/alert-subscriptions")
    places = await ui.api_call(request, "GET", "/api/alerts/places")
    return ui.render(request, "alert_subscriptions.html", user=user, active_nav="subscriptions", page_title="Follow alert areas",
                     subscriptions=follows.json() if follows.status_code == 200 else [],
                     places=places.json() if places.status_code == 200 else [], notice=notice,
                     error=error or (ui.error_message(follows) if follows.status_code != 200 else
                                    ui.error_message(places) if places.status_code != 200 else None),
                     status_code=status_code if error else max(follows.status_code, places.status_code))


@router.get("/alert-subscriptions", response_class=HTMLResponse)
async def subscriptions_page(request: Request):
    return await view(request)


@router.post("/ui/alert-subscriptions", response_class=HTMLResponse)
async def follow(request: Request):
    ui = import_module("web.app")
    if not await ui.current_user(request):
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "POST", "/api/alert-subscriptions",
                                 {"place_id": str(request.state.form.get("place_id", ""))})
    if response.status_code not in {200, 201}:
        return await view(request, error=ui.error_message(response), status_code=response.status_code)
    result = await view(request, notice="Area followed. Current matching alerts and future changes appear in Notifications.")
    result.headers["HX-Trigger"] = json.dumps({"resq:refresh-updates": True})
    result.headers["HX-Push-Url"] = "/alert-subscriptions"
    return result


@router.post("/ui/alert-subscriptions/{subscription_id}/unsubscribe", response_class=HTMLResponse)
async def unfollow(request: Request, subscription_id: int):
    ui = import_module("web.app")
    if not await ui.current_user(request):
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "POST", f"/api/alert-subscriptions/{subscription_id}/unsubscribe")
    if response.status_code != 200:
        return await view(request, error=ui.error_message(response), status_code=response.status_code)
    return await view(request, notice="Area unfollowed. Existing notifications stay in your private history.")
