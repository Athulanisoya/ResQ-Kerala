"""Private updates and clarification screens backed by the communication API."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


async def communication_context(request, incident_id):
    from web.app import api_call, error_message
    response = await api_call(request, "GET", f"/api/communication/incidents/{incident_id}/clarifications")
    return {
        "clarifications": response.json() if response.status_code == 200 else [],
        "communication_error": error_message(response) if response.status_code != 200 else None,
    }


async def updates_view(request, *, error=None, status_code=200):
    from web.app import api_call, current_user, error_message, redirect, render
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    before = request.query_params.get("before_id", "")
    path = "/api/communication/notifications?limit=30"
    if before.isdigit():
        path += f"&before_id={before}"
    response = await api_call(request, "GET", path)
    data = response.json() if response.status_code == 200 else {}
    return render(request, "updates.html", user=user, active_nav="updates", page_title="My updates",
                  notifications=data.get("notifications", []), unread_count=data.get("unread_count", 0),
                  next_before_id=data.get("next_before_id"),
                  error=error or (error_message(response) if response.status_code != 200 else None),
                  status_code=status_code if error else response.status_code)


@router.get("/updates", response_class=HTMLResponse)
async def updates_page(request: Request):
    return await updates_view(request)


@router.get("/ui/updates/count", response_class=HTMLResponse)
async def update_count(request: Request):
    from web.app import api_call, current_user, redirect, render, SessionUnavailable
    try:
        user = await current_user(request)
    except SessionUnavailable:
        return render(request, "partials/update_count.html", unread_count=None)
    if not user:
        return redirect(request, "/login")
    response = await api_call(request, "GET", "/api/communication/notifications?limit=1")
    count = response.json().get("unread_count", 0) if response.status_code == 200 else None
    return render(request, "partials/update_count.html", user=user, unread_count=count)


@router.post("/ui/updates/read-all")
async def read_all(request: Request):
    return await mark_read(request)


@router.post("/ui/updates/{notification_id}/read")
async def read_one(request: Request, notification_id: int):
    return await mark_read(request, notification_id)


async def mark_read(request, notification_id=None):
    from web.app import api_call, current_user, error_message, redirect
    if not await current_user(request):
        return redirect(request, "/login")
    suffix = f"{notification_id}/read" if notification_id else "read-all"
    response = await api_call(request, "POST", f"/api/communication/notifications/{suffix}")
    if response.status_code == 200:
        return redirect(request, "/updates")
    return await updates_view(request, error=error_message(response), status_code=response.status_code)


async def save_communication(request, incident_id, path, payload, allowed_role):
    from web.app import api_call, current_user, detail_page, error_message, redirect
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != allowed_role:
        return HTMLResponse("Your role cannot perform this action.", status_code=403)
    response = await api_call(request, "POST", path, payload)
    if response.status_code in {200, 201}:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=request.state.form)


@router.post("/ui/reports/{incident_id}/clarifications")
async def ask_clarification(request: Request, incident_id: int):
    form = request.state.form
    return await save_communication(request, incident_id,
        f"/api/communication/incidents/{incident_id}/clarifications",
        {"question": form.get("question", ""), "required": form.get("required") == "yes"}, "admin")


@router.post("/ui/reports/{incident_id}/legacy-clarification/reply")
async def reply_legacy_clarification(request: Request, incident_id: int):
    return await save_communication(request, incident_id,
        f"/api/incidents/{incident_id}/clarification/respond",
        {"message": request.state.form.get("legacy_reply", "")}, "citizen")


@router.post("/ui/reports/{incident_id}/clarifications/{clarification_id}/reply")
async def reply_clarification(request: Request, incident_id: int, clarification_id: int):
    request.state.form["reply_clarification_id"] = clarification_id
    return await save_communication(request, incident_id,
        f"/api/communication/clarifications/{clarification_id}/reply",
        {"message": request.state.form.get("reply_message", "")}, "citizen")


@router.post("/ui/reports/{incident_id}/clarifications/{clarification_id}/cancel")
async def cancel_clarification(request: Request, incident_id: int, clarification_id: int):
    return await save_communication(request, incident_id,
        f"/api/communication/clarifications/{clarification_id}/cancel", None, "admin")


@router.post("/ui/reports/{incident_id}/close")
async def close_case(request: Request, incident_id: int):
    return await save_communication(request, incident_id,
        f"/api/communication/incidents/{incident_id}/close",
        {"note": request.state.form.get("closure_note") or None}, "admin")
