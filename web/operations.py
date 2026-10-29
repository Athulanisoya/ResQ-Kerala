"""HTML forms for the operational API; authorization and stock rules stay there."""
from decimal import Decimal, InvalidOperation
from importlib import import_module
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


def _web():
    # The application registers this router after defining its rendering helpers.
    return import_module("web.app")


def _quantity(value, *, allow_zero=False):
    try:
        quantity = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid quantity.") from None
    if not quantity.is_finite() or quantity < 0 or (not allow_zero and quantity == 0):
        raise ValueError("Quantity must be zero or greater." if allow_zero else "Quantity must be greater than zero.")
    if quantity > 1_000_000_000:
        raise ValueError("Quantity must be no greater than 1,000,000,000.")
    return float(quantity)


async def _get(request, path):
    web = _web()
    response = await web.api_call(request, "GET", path)
    return (response.json(), None) if response.status_code == 200 else ([], web.error_message(response))


async def operation_detail_context(request, user, incident_id):
    """Safe, role-scoped context for the report progress and relief partials."""
    context = {"operation_task": None, "operation_history": [], "operations_error": None,
               "relief_requests": [], "operation_teams": [], "operation_can_handoff": False}
    if user["role"] not in {"admin", "response_team"}:
        return context
    response = await _web().api_call(request, "GET", f"/api/operations/incidents/{incident_id}/task")
    context["operations_error"] = _web().error_message(response) if response.status_code != 200 else None
    context["operation_task"] = response.json() if response.status_code == 200 else None
    if user["role"] == "admin":
        teams, team_error = await _get(request, "/api/teams")
        context["operation_teams"] = teams
        context["operations_error"] = context["operations_error"] or team_error
        task = context["operation_task"]
        current_team = next((team for team in teams if task and team["id"] == task["team_id"]), None)
        context["operation_can_handoff"] = bool(current_team and current_team["team_type"].strip().lower() == "rescue")
    return context


async def operations_view(request, *, error=None, status_code=200, values=None, view=None):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    values = values or {}
    selected_view = view or request.query_params.get("view", "active")
    if selected_view not in {"active", "history"}:
        selected_view = "active"
    if selected_view == "history" and user["role"] not in {"admin", "response_team"}:
        selected_view, status_code = "active", 403
        error = error or "Assignment history is available to administrators and response teams."
    inventory, tasks, history, teams, relief_requests = [], [], [], [], []
    errors = []
    inventory, inventory_error = await _get(request, "/api/operations/inventory")
    errors.append(inventory_error)
    if user["role"] in {"admin", "response_team"}:
        if selected_view == "history":
            history, history_error = await _get(request, "/api/operations/task-history")
            errors.append(history_error)
        else:
            tasks, task_error = await _get(request, "/api/operations/tasks")
            errors.append(task_error)
    relief_requests, relief_error = await _get(request, "/api/operations/relief-requests")
    errors.append(relief_error)
    reports, report_error = await web.list_reports(request, user)
    errors.append(report_error)
    if user["role"] == "admin":
        teams, team_error = await _get(request, "/api/teams")
        errors.append(team_error)
    inventory_adjustments = []
    stock_history_id = None
    if user["role"] == "admin" and request.query_params.get("stock_history"):
        try:
            stock_history_id = int(request.query_params["stock_history"])
        except ValueError:
            errors.append("Choose a valid inventory item to view stock history.")
        if stock_history_id is not None:
            inventory_adjustments, audit_error = await _get(request, f"/api/operations/inventory/{stock_history_id}/history")
            errors.append(audit_error)
    stock = {item["id"]: item for item in inventory}
    keys = {item["id"]: secrets.token_urlsafe(24) for item in relief_requests}
    if values.get("request_id") and values.get("idempotency_key"):
        try:
            keys[int(values["request_id"])] = values["idempotency_key"]
        except (TypeError, ValueError):
            pass
    notices = {"inventory-created": "Inventory item created.", "inventory-updated": "Inventory stock updated.",
               "requested": "Relief request created.", "assigned": "Relief team assigned.",
               "delivered": "Delivery recorded. Remaining quantities have been updated.",
               "completed": "Rescue support completed."}
    return web.render(request, "operations.html", user=user, page_title="Operations",
                      active_nav="history" if selected_view == "history" else "operations",
                      error=error or next((item for item in errors if item), None),
                      status_code=status_code, values=values, operation_view=selected_view,
                      inventory=inventory, inventory_by_id=stock, operation_tasks=tasks,
                      operation_history=history, relief_requests=relief_requests, operation_teams=teams,
                      operation_reports=reports, delivery_keys=keys,
                      inventory_adjustments=inventory_adjustments, stock_history_id=stock_history_id,
                      notice=notices.get(request.query_params.get("notice")))


@router.get("/operations", response_class=HTMLResponse)
async def operations_page(request: Request):
    return await operations_view(request)


@router.get("/assignments-history", response_class=HTMLResponse)
async def assignments_history(request: Request):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    if user["role"] not in {"admin", "response_team"}:
        return await operations_view(request, view="active", status_code=403,
                                     error="Assignment history is available to administrators and response teams.")
    return await operations_view(request, view="history")


async def _workspace_action(request, method, path, payload, success, *, values=None):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    response = await web.api_call(request, method, path, payload)
    if response.status_code in {200, 201}:
        return web.redirect(request, "/operations?notice=" + success)
    return await operations_view(request, error=web.error_message(response), status_code=response.status_code,
                                 values=values or request.state.form)


@router.post("/ui/operations/inventory")
async def create_inventory(request: Request):
    form = request.state.form
    try:
        payload = {"name": form.get("name", "").strip(), "unit": form.get("unit", "").strip(),
                   "quantity": _quantity(form.get("quantity", ""), allow_zero=True),
                   "reason": form.get("reason") or "Initial inventory"}
    except ValueError as exc:
        return await operations_view(request, error=str(exc), status_code=422, values=form)
    return await _workspace_action(request, "POST", "/api/operations/inventory", payload, "inventory-created")


@router.post("/ui/operations/inventory/{item_id}/update")
async def update_inventory(request: Request, item_id: int):
    form = request.state.form
    values = {**form, "edit_inventory_id": str(item_id)}
    try:
        payload = {"name": form.get("name", "").strip(), "unit": form.get("unit", "").strip(),
                   "quantity": _quantity(form.get("quantity", ""), allow_zero=True),
                   "reason": form.get("reason") or "Admin stock adjustment"}
    except ValueError as exc:
        return await operations_view(request, error=str(exc), status_code=422, values=values)
    return await _workspace_action(request, "PATCH", f"/api/operations/inventory/{item_id}", payload,
                                   "inventory-updated", values=values)


@router.post("/ui/operations/relief-requests")
async def create_relief_request(request: Request):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, "/login")
    form = request.state.form
    payload = {"incident_id": form.get("incident_id"), "kind": form.get("kind", "RESCUE_SUPPORT"),
               "note": form.get("note") or None, "items": []}
    if payload["kind"] == "SUPPLIES":
        inventory, error = await _get(request, "/api/operations/inventory")
        if error:
            return await operations_view(request, error=error, status_code=503, values=form)
        try:
            for item in inventory:
                raw = form.get(f"quantity_{item['id']}", "").strip()
                if not raw:
                    continue
                quantity = _quantity(raw, allow_zero=True)
                if quantity:
                    payload["items"].append({"inventory_item_id": item["id"], "quantity": quantity, "unit": item["unit"]})
            if not payload["items"]:
                raise ValueError("Choose at least one supply and enter the quantity needed.")
        except ValueError as exc:
            return await operations_view(request, error=str(exc), status_code=422, values=form)
    return await _workspace_action(request, "POST", "/api/operations/relief-requests", payload, "requested")


@router.post("/ui/operations/relief-requests/{request_id}/assign")
async def assign_relief_request(request: Request, request_id: int):
    return await _workspace_action(request, "POST", f"/api/operations/relief-requests/{request_id}/assign",
                                   {"team_id": request.state.form.get("team_id")}, "assigned",
                                   values={**request.state.form, "request_id": str(request_id)})


@router.post("/ui/operations/relief-requests/{request_id}/deliveries")
async def deliver_relief_request(request: Request, request_id: int):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    form = request.state.form
    values = {**form, "request_id": str(request_id)}
    response = await web.api_call(request, "GET", f"/api/operations/relief-requests/{request_id}")
    if response.status_code != 200:
        return await operations_view(request, error=web.error_message(response), status_code=response.status_code, values=values)
    detail = response.json()
    payload = {"idempotency_key": form.get("idempotency_key", ""), "items": [], "note": form.get("delivery_note") or None}
    replay = any(delivery["idempotency_key"] == payload["idempotency_key"] for delivery in detail.get("deliveries", []))
    try:
        for item in detail["items"]:
            raw = form.get(f"delivery_{item['id']}", "").strip()
            if not raw:
                continue
            quantity = _quantity(raw, allow_zero=True)
            if quantity:
                if not replay and quantity > float(item["remaining_quantity"]):
                    raise ValueError(f"Delivery of {item['item_name']} exceeds the remaining requested quantity.")
                payload["items"].append({"request_item_id": item["id"], "quantity": quantity, "unit": item["unit"]})
        if not payload["items"]:
            raise ValueError("Enter at least one quantity to deliver.")
    except ValueError as exc:
        return await operations_view(request, error=str(exc), status_code=422, values=values)
    return await _workspace_action(request, "POST", f"/api/operations/relief-requests/{request_id}/deliveries", payload,
                                   "delivered", values=values)


@router.post("/ui/operations/relief-requests/{request_id}/complete")
async def complete_rescue_support(request: Request, request_id: int):
    return await _workspace_action(request, "POST", f"/api/operations/relief-requests/{request_id}/complete",
                                   {"note": request.state.form.get("delivery_note") or None}, "completed")


async def _incident_action(request, incident_id, action, payload):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, "/login")
    response = await web.api_call(request, "POST", f"/api/operations/incidents/{incident_id}/{action}", payload)
    if response.status_code == 200:
        return web.redirect(request, f"/reports/{incident_id}")
    return await web.detail_page(request, incident_id, error=web.error_message(response),
                                 status_code=response.status_code, values=request.state.form)


@router.post("/ui/operations/incidents/{incident_id}/accept")
async def accept_incident(request: Request, incident_id: int):
    return await _incident_action(request, incident_id, "accept", {"note": request.state.form.get("note") or None})


@router.post("/ui/operations/incidents/{incident_id}/progress")
async def progress_incident(request: Request, incident_id: int):
    return await _incident_action(request, incident_id, "progress", {
        "status": request.state.form.get("status", ""), "note": request.state.form.get("note") or None})


@router.post("/ui/operations/incidents/{incident_id}/handoff")
async def handoff_incident(request: Request, incident_id: int):
    return await _incident_action(request, incident_id, "handoff", {
        "team_id": request.state.form.get("team_id"), "note": request.state.form.get("note", "")})
