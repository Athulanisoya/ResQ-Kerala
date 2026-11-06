"""Explicit waiting-list offers within the existing authenticated HTMX shell."""
from importlib import import_module
import json
import math
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.services.shelter_registration_service import districts


router = APIRouter(include_in_schema=False)


def web():
    return import_module("web.app")


async def waiting_view(request, shelter_id, *, error=None, notice=None, values=None, status_code=200):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}")
    if response.status_code != 200:
        return ui.render(request, "shelter_waitlist.html", user=user, active_nav="shelters", shelter=None,
                         entries=[], districts=[], error=ui.error_message(response), status_code=response.status_code)
    records = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}/waitlist")
    form = dict(values or {})
    form.setdefault("request_key", str(uuid4()))
    form.setdefault("contact", user.get("email", ""))
    if values is None:
        for name in ("origin_district", "origin_locality"):
            form[name] = request.query_params.get(name, "")
    result = ui.render(request, "shelter_waitlist.html", user=user, active_nav="shelters",
        page_title="Shelter waiting list", shelter=response.json(), entries=records.json() if records.status_code == 200 else [],
        districts=districts(), values=form, can_manage=user["role"] != "citizen" and records.status_code == 200,
        error=error or (ui.error_message(records) if records.status_code != 200 else None), notice=notice,
        status_code=status_code if error else records.status_code)
    if request.url.path.startswith("/ui/"):
        result.headers["HX-Push-Url"] = f"/shelters/{shelter_id}/waitlist"
    return result


@router.get("/shelters/{shelter_id}/waitlist", response_class=HTMLResponse)
async def waiting(request: Request, shelter_id: int):
    return await waiting_view(request, shelter_id)


async def records_view(request, shelter_id=None):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    path = f"/api/shelters/{shelter_id}/waitlist" if shelter_id is not None else "/api/shelter-waitlist"
    response = await ui.api_call(request, "GET", path)
    return ui.render(request, "partials/shelter_waitlist_records.html", user=user,
        entries=response.json() if response.status_code == 200 else [],
        can_manage=shelter_id is not None and user["role"] != "citizen" and response.status_code == 200,
        records_error=ui.error_message(response) if response.status_code != 200 else None,
        status_code=response.status_code)


@router.get("/ui/shelters/{shelter_id}/waitlist/records", response_class=HTMLResponse)
async def shelter_records(request: Request, shelter_id: int):
    return await records_view(request, shelter_id)


@router.get("/ui/shelter-waitlist/records", response_class=HTMLResponse)
async def own_records(request: Request):
    return await records_view(request)


@router.post("/ui/shelters/{shelter_id}/waitlist", response_class=HTMLResponse)
async def join(request: Request, shelter_id: int):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    if user["role"] != "citizen":
        return HTMLResponse("Only citizen accounts can join a waiting list.", status_code=403)
    form = dict(request.state.form)
    try:
        payload = {key: str(form.get(key, "")) for key in ("origin_district", "origin_locality", "contact", "note", "request_key")}
        payload["party_size"] = int(form.get("party_size", ""))
        for key in ("origin_latitude", "origin_longitude"):
            value = str(form.get(key, "")).strip()
            payload[key] = float(value) if value else None
            if payload[key] is not None and not math.isfinite(payload[key]):
                raise ValueError
    except (TypeError, ValueError):
        return await waiting_view(request, shelter_id, error="Enter a valid group size and optional coordinate pair.", values=form, status_code=422)
    response = await ui.api_call(request, "POST", f"/api/shelters/{shelter_id}/waitlist", payload)
    if response.status_code not in {200, 201}:
        return await waiting_view(request, shelter_id, error=ui.error_message(response), values=form, status_code=response.status_code)
    row = response.json()
    notice = ("Spaces are temporarily held for your group. Accept the offer below before its deadline to create your reservation."
              if row["status"] == "OFFERED" else "Your waiting-list entry is recorded. Its current status is shown below.")
    result = await waiting_view(request, shelter_id, notice=notice)
    result.headers["HX-Trigger"] = json.dumps({"resq:shelters-changed": True})
    return result


@router.post("/ui/shelters/{shelter_id}/waitlist/{entry_id}/{action}", response_class=HTMLResponse)
async def action(request: Request, shelter_id: int, entry_id: int, action: str):
    ui = web()
    if not await ui.current_user(request):
        return ui.redirect(request, "/login")
    if action not in {"accept", "cancel"}:
        return HTMLResponse("Waiting-list action not found.", status_code=404)
    records = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}/waitlist")
    if records.status_code != 200 or not any(row["id"] == entry_id for row in records.json()):
        return HTMLResponse("Waiting-list entry is outside your access.", status_code=403)
    try:
        payload = {"expected_version": int(request.state.form.get("expected_version", ""))}
    except (TypeError, ValueError):
        return await waiting_view(request, shelter_id, error="Reload the latest waiting-list status before updating.", status_code=422)
    response = await ui.api_call(request, "POST", f"/api/shelter-waitlist/{entry_id}/{action}", payload)
    if response.status_code != 200:
        return await waiting_view(request, shelter_id, error=ui.error_message(response), status_code=response.status_code)
    result = await waiting_view(request, shelter_id, notice=("Offer accepted. Your spaces are now reserved; reception confirms arrival separately."
                                                                           if action == "accept" else "Waiting-list entry cancelled; any held spaces have been released."))
    result.headers["HX-Trigger"] = json.dumps({"resq:shelters-changed": True})
    return result


@router.get("/shelter-waitlist", response_class=HTMLResponse)
async def own_waiting(request: Request):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "GET", "/api/shelter-waitlist")
    return ui.render(request, "shelter_waitlists.html", user=user, active_nav="waitlist", page_title="My shelter waiting lists",
                     entries=response.json() if response.status_code == 200 else [], can_manage=False,
                     error=ui.error_message(response) if response.status_code != 200 else None, status_code=response.status_code)
