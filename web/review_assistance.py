from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


async def location_context(request, incident_id):
    web = import_module("web.app")
    response = await web.api_call(request, "GET", f"/api/incidents/{incident_id}/location-clarification")
    return {"location_follow_up": response.json() if response.status_code == 200 else None,
            "location_follow_up_error": web.error_message(response) if response.status_code != 200 else None}


@router.post("/ui/reports/{incident_id}/location-confirmations")
async def confirm_location(request: Request, incident_id: int):
    web = import_module("web.app")
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    form = request.state.form
    response = await web.api_call(request, "POST", f"/api/incidents/{incident_id}/location-confirmations",
        {"place_id": form.get("place_id", ""), "input_hash": form.get("input_hash", ""),
         "locality": form.get("confirmed_locality") or None, "note": form.get("location_note") or None})
    return await web.detail_page(request, incident_id,
        notice="Location confirmation saved. The original report is preserved." if response.status_code == 201 else None,
        error=web.error_message(response) if response.status_code != 201 else None,
        status_code=200 if response.status_code == 201 else response.status_code, values=form)


@router.get("/ui/reports/{incident_id}/clarification-draft")
async def clarification_draft(request: Request, incident_id: int, field: str = ""):
    web = import_module("web.app")
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Administrator access required.", status_code=403)
    response = await web.api_call(request, "GET", f"/api/communication/incidents/{incident_id}/clarification-suggestions")
    if response.status_code != 200:
        return HTMLResponse("Unable to draft a clarification question.", status_code=response.status_code)
    suggestion = next((s for s in response.json()["suggestions"] if s["field"] == field), None)
    if not suggestion:
        return HTMLResponse("This suggestion is no longer applicable. Reload the report.", status_code=409)
    return web.render(request, "partials/clarification_compose.html", user=user, report={"id": incident_id},
                      values={"question": suggestion["question"], "required": "yes"}, drafted=True)
