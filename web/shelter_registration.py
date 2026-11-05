"""Shelter join requests and private reception controls in the HTMX workspace."""
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


async def join_view(request, shelter_id, *, error=None, notice=None, values=None, status_code=200):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}")
    if response.status_code != 200:
        return ui.render(request, "shelter_registration.html", user=user, active_nav="shelters",
                         page_title="Shelter registration", shelter=None, registrations=[], districts=[],
                         error=ui.error_message(response), status_code=response.status_code)
    records = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}/registrations")
    form = dict(values or {})
    form.setdefault("request_key", str(uuid4()))
    form.setdefault("contact", user.get("email", ""))
    if values is None:
        for name in ("origin_district", "origin_locality", "origin_latitude", "origin_longitude"):
            form[name] = request.query_params.get(name, "")
    result = ui.render(request, "shelter_registration.html", user=user, active_nav="shelters",
                     page_title="Register for a shelter" if user["role"] == "citizen" else "Shelter reception",
                     shelter=response.json(), registrations=records.json() if records.status_code == 200 else [],
                     districts=districts(), values=form, notice=notice,
                     error=error or (ui.error_message(records) if records.status_code != 200 else None),
                     can_manage=user["role"] != "citizen" and records.status_code == 200,
                     status_code=status_code if error else records.status_code)
    if request.url.path.startswith("/ui/"):
        result.headers["HX-Push-Url"] = f"/shelters/{shelter_id}/join"
    return result


@router.get("/shelters/{shelter_id}/join", response_class=HTMLResponse)
async def join(request: Request, shelter_id: int):
    return await join_view(request, shelter_id)


@router.post("/ui/shelters/{shelter_id}/registrations", response_class=HTMLResponse)
async def reserve(request: Request, shelter_id: int):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    if user["role"] != "citizen":
        return HTMLResponse("Only citizen accounts can register for shelter spaces.", status_code=403)
    form = dict(request.state.form)
    try:
        payload = {name: str(form.get(name, "")) for name in
                   ("origin_district", "origin_locality", "request_key", "contact", "note")}
        payload["party_size"] = int(form.get("party_size", ""))
        for name in ("origin_latitude", "origin_longitude"):
            value = str(form.get(name, "")).strip()
            payload[name] = float(value) if value else None
            if payload[name] is not None and not math.isfinite(payload[name]):
                raise ValueError("Coordinates must be finite")
    except (TypeError, ValueError):
        return await join_view(request, shelter_id, error="Enter a valid number of people and location coordinates.",
                               values=form, status_code=422)
    response = await ui.api_call(request, "POST", f"/api/shelters/{shelter_id}/registrations", payload)
    if response.status_code not in {200, 201}:
        return await join_view(request, shelter_id, error=ui.error_message(response), values=form,
                               status_code=response.status_code)
    notice = ("Your spaces are reserved. Contact the shelter before travelling; reception will confirm arrival."
              if response.json()["status"] == "RESERVED" else
              "This request was already recorded. Its current registration status is shown below.")
    result = await join_view(request, shelter_id, notice=notice)
    result.headers["HX-Trigger"] = json.dumps({"resq:shelters-changed": True})
    return result


@router.post("/ui/shelters/{shelter_id}/registrations/{registration_id}/status", response_class=HTMLResponse)
async def status(request: Request, shelter_id: int, registration_id: int):
    ui = web()
    if not await ui.current_user(request):
        return ui.redirect(request, "/login")
    form = dict(request.state.form)
    # Bind the registration ID to this shelter before changing it.
    records = await ui.api_call(request, "GET", f"/api/shelters/{shelter_id}/registrations")
    if records.status_code != 200 or not any(row["id"] == registration_id for row in records.json()):
        return HTMLResponse("Shelter registration is outside your access.", status_code=403)
    try:
        payload = {"status": str(form.get("status", "")), "expected_version": int(form.get("expected_version", "")),
                   "note": str(form.get("note", "")).strip() or None}
    except (TypeError, ValueError):
        return await join_view(request, shelter_id, error="Reload the registration's latest status before updating.", status_code=422)
    response = await ui.api_call(request, "PATCH", f"/api/shelter-registrations/{registration_id}/status", payload)
    if response.status_code != 200:
        return await join_view(request, shelter_id, error=ui.error_message(response), status_code=response.status_code)
    result = await join_view(request, shelter_id, notice="Registration updated. Available spaces are refreshing.")
    result.headers["HX-Trigger"] = json.dumps({"resq:shelters-changed": True})
    return result


@router.get("/shelter-registrations", response_class=HTMLResponse)
async def own_registrations(request: Request):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, "/login")
    response = await ui.api_call(request, "GET", "/api/shelter-registrations")
    return ui.render(request, "shelter_registrations.html", user=user, active_nav="shelters",
                     page_title="My shelter registrations", registrations=response.json() if response.status_code == 200 else [],
                     can_manage=False, error=ui.error_message(response) if response.status_code != 200 else None,
                     status_code=response.status_code)
