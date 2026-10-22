"""Render HTML through the existing JSON API; business rules stay in backend/."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import secrets
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.main import app as api

ROOT = Path(__file__).resolve().parents[1]
# Old browser-wide credentials are never used for authentication.
LEGACY_TOKEN_COOKIE = "resq_session"
CSRF_COOKIE = "resq_csrf"
templates = Jinja2Templates(directory=str(ROOT / "frontend" / "templates"))


def local_time(value):
    if not value:
        return "—"
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %H:%M IST")
    except ValueError:
        return str(value)


templates.env.filters["local_time"] = local_time


def input_time(value):
    """Format API timestamps for an explicitly IST datetime-local control."""
    if not value:
        return ""
    try:
        timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return str(value)


templates.env.filters["input_time"] = input_time


@asynccontextmanager
async def lifespan(_app):
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(title="ResQ Kerala · Response workspace", lifespan=lifespan,
              openapi_url=None, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "frontend" / "static"), check_dir=False), name="static")


def redirect(request, path):
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": path})
    return RedirectResponse(path, status_code=303)


def render(request, content_template, *, status_code=200, **context):
    token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    context = {"user": None, "page_title": "ResQ Kerala", "active_nav": "",
               "error": None, "notice": None, "values": {}, "stats": {},
               "reports": [], "teams": [], "timeline": [], "filter_status": "",
               **context, "csrf_token": token, "content_template": content_template}
    partial = (request.headers.get("HX-Request") == "true"
               and request.headers.get("HX-History-Restore-Request") != "true"
               and request.headers.get("X-ResQ-Bootstrap") != "true")
    response = templates.TemplateResponse(request=request, name=content_template if partial else "page.html",
                                          context=context, status_code=status_code)
    response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https")
    return response


@app.middleware("http")
async def browser_security(request: Request, call_next):
    path = request.url.path
    ui_page = path in {"/", "/login", "/register", "/dashboard", "/reports", "/reports/new", "/account", "/permissions", "/alerts", "/updates", "/operations", "/assignments-history"} or (
        path.startswith("/reports/") and path.rsplit("/", 1)[-1].isdigit())
    # Document navigation cannot attach a bearer header. The public shell loads
    # the requested page through HTMX using only this tab's saved session.
    if (request.method == "GET" and ui_page and request.headers.get("HX-Request") != "true"
            and request.headers.get("X-ResQ-Page") != "true"):
        response = render(request, "session_bootstrap.html", page_title="Opening your workspace")
        return secure_response(request, response)
    if request.url.path.startswith("/ui/") and request.method == "POST":
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return HTMLResponse("This form came from a different site. Reload and try again.", status_code=403)
        form = await request.form()
        supplied = str(form.get("_csrf", ""))
        expected = request.cookies.get(CSRF_COOKIE, "")
        if not expected or not supplied.isascii() or not expected.isascii() or not secrets.compare_digest(supplied, expected):
            return HTMLResponse("Your form expired. Reload the page and try again.", status_code=403)
        # Retain parsed data across Starlette middleware/request instances.
        request.state.form = dict(form)
    response = await call_next(request)
    return secure_response(request, response)


def secure_response(request, response):
    if LEGACY_TOKEN_COOKIE in request.cookies:
        response.delete_cookie(LEGACY_TOKEN_COOKIE)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "HX-Request, HX-History-Restore-Request"
    return response


async def api_call(request, method, path, payload=None):
    authorization = request.headers.get("Authorization")
    headers = {"Authorization": authorization} if authorization else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api.local") as client:
        try:
            return await client.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError:
            return httpx.Response(503, json={"detail": "The service is temporarily unavailable. Please try again."})


def error_message(response):
    try:
        detail = response.json().get("detail", "Please try again.")
    except (ValueError, AttributeError):
        return "The service is temporarily unavailable. Please try again."
    if isinstance(detail, list):
        return " ".join(f"{'.'.join(str(part) for part in item['loc'] if part != 'body')}: {item['msg']}" for item in detail)
    return str(detail)


class SessionExpired(Exception):
    pass


class SessionUnavailable(Exception):
    pass


@app.exception_handler(SessionExpired)
async def expired_session(request: Request, _error):
    response = redirect(request, "/login?notice=expired")
    response.headers["X-ResQ-Session"] = "expired"
    return response


@app.exception_handler(SessionUnavailable)
async def unavailable_session(request: Request, _error):
    path = request.url.path
    if request.method == "POST":
        if path == "/ui/reports":
            path = "/reports/new"
        elif path.startswith("/ui/reports/") and path.split("/")[3].isdigit():
            path = "/reports/" + path.split("/")[3]
        elif path.startswith("/ui/alerts"):
            path = "/alerts"
        else:
            path = "/dashboard"
    elif request.url.query:
        path += f"?{request.url.query}"
    return render(request, "reconnect.html", status_code=503,
                  retry_path=path,
                  page_title="Reconnect your workspace")


async def current_user(request):
    if not request.headers.get("Authorization"):
        return None
    response = await api_call(request, "GET", "/api/users/me")
    if response.status_code in {401, 403}:
        raise SessionExpired()
    if response.status_code != 200:
        raise SessionUnavailable()
    return response.json()


async def list_reports(request, user):
    path = {"admin": "/api/admin/incidents", "response_team": "/api/teams/assignments"}.get(user["role"], "/api/incidents/")
    response = await api_call(request, "GET", path)
    if response.status_code != 200:
        return [], error_message(response)
    return [display_report(item, user) for item in response.json()], None


def display_report(report, user):
    return {**report, "reference": report.get("report_reference", f"Report #{report['id']}"),
            "assigned_team": f"Response team #{report['assigned_team_id']}" if report.get("assigned_team_id") else None,
            "can_review": user["role"] == "admin" and report["status"] in {"SUBMITTED", "UNDER_REVIEW"},
            "can_assign": user["role"] == "admin" and report["status"] == "VERIFIED"}


@app.get("/", include_in_schema=False)
async def index(request: Request):
    return redirect(request, "/dashboard" if await current_user(request) else "/login")


@app.get("/login", response_class=HTMLResponse)
@app.get("/register", response_class=HTMLResponse)
async def auth_page(request: Request):
    if await current_user(request):
        return redirect(request, "/dashboard")
    mode = "register" if request.url.path == "/register" else "login"
    notices = {
        "expired": "Your session has expired. Please sign in again.",
        "signed-out": "You have signed out. Your server session has been revoked.",
        "logout-unconfirmed": "You have signed out in this tab. The server could not confirm session revocation. Your previous session may remain valid until it expires.",
    }
    return render(request, "auth.html", mode=mode, notice=notices.get(request.query_params.get("notice")),
                  page_title="Create account" if mode == "register" else "Welcome back")


@app.post("/ui/login")
@app.post("/ui/register")
async def sign_in(request: Request):
    mode = request.url.path.rsplit("/", 1)[-1]
    form = request.state.form
    payload = {key: form.get(key, "") for key in ("full_name", "email", "password") if key != "full_name" or mode == "register"}
    response = await api_call(request, "POST", f"/api/auth/{mode}", payload)
    if response.status_code not in {200, 201}:
        return render(request, "auth.html", mode=mode, values={"email": form.get("email", ""), "full_name": form.get("full_name", "")},
                      error=error_message(response), status_code=response.status_code)
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({
        "resq:authenticated": {"access_token": response.json()["access_token"]},
    })})


@app.post("/ui/logout")
async def sign_out(request: Request):
    response = await api_call(request, "POST", "/api/auth/logout")
    notice = "signed-out" if response.status_code == 204 else "logout-unconfirmed"
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({
        "resq:signed-out": {"notice": notice},
    })})


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    return render(request, "account.html", user=user, active_nav="account", page_title="My account")


@app.get("/permissions", response_class=HTMLResponse)
async def permissions_page(request: Request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    checks = []
    for role, title, path in (
        ("citizen", "Citizen workspace", "/api/workspaces/citizen"),
        ("admin", "Admin workspace", "/api/workspaces/admin"),
        ("response_team", "Response team workspace", "/api/workspaces/response-team"),
    ):
        response = await api_call(request, "GET", path)
        if response.status_code == 401:
            raise SessionExpired()
        checks.append({"role": role, "title": title, "status": response.status_code,
                       "message": response.json()["message"] if response.status_code == 200 else error_message(response)})
    error = "Some access checks could not complete. Please try again." if any(c["status"] not in {200, 403} for c in checks) else None
    return render(request, "permissions.html", user=user, access_checks=checks, error=error,
                  active_nav="permissions", page_title="Workspace permissions")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    reports, error = await list_reports(request, user)
    stats = {"total": len(reports), "pending_review": sum(r["status"] in {"SUBMITTED", "UNDER_REVIEW"} for r in reports),
             "verified": sum(r["status"] == "VERIFIED" for r in reports),
             "assigned": sum(r["status"] in {"ASSIGNED", "TASK_ACCEPTED", "EN_ROUTE", "IN_PROGRESS"} for r in reports),
             "resolved": sum(r["status"] == "RESOLVED" for r in reports),
             "closed": sum(r["status"] == "CLOSED" for r in reports)}
    return render(request, "dashboard.html", user=user, reports=reports[:5], stats=stats,
                  error=error, active_nav="dashboard", page_title="Overview")


@app.get("/reports/new", response_class=HTMLResponse)
async def report_form(request: Request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != "citizen":
        return render(request, "reports.html", user=user, error="Only citizens can submit a flood report.", status_code=403)
    return render(request, "report_form.html", user=user, active_nav="new", page_title="Report a flood")


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, status: str = "", q: str = ""):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    reports, error = await list_reports(request, user)
    total = len(reports)
    if status:
        reports = [report for report in reports if report["status"] == status]
    q = q.strip()[:200]
    if q:
        query = q.casefold()
        reports = [report for report in reports if query in " ".join(str(report.get(key) or "") for key in
                    ("reference", "location", "message", "help_required", "disaster_type")).casefold()]
    return render(request, "reports.html", user=user, reports=reports, total=total, filter_status=status,
                  search_query=q,
                  error=error, active_nav="reports", page_title="Reports")


async def detail_page(request, incident_id, *, error=None, status_code=200, values=None, notice=None):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    response = await api_call(request, "GET", f"/api/incidents/{incident_id}")
    if response.status_code != 200:
        return render(request, "reports.html", user=user, error=error_message(response), status_code=response.status_code)
    report = display_report(response.json(), user)
    from web.communication import communication_context
    from web.operations import operation_detail_context
    communication = await communication_context(request, incident_id)
    operations = await operation_detail_context(request, user, incident_id)
    history = await api_call(request, "GET", f"/api/incidents/{incident_id}/history")
    summary_response = await api_call(request, "GET", f"/api/incidents/{incident_id}/summary")
    report_summary = summary_response.json() if summary_response.status_code == 200 else None
    summary_error = error_message(summary_response) if summary_response.status_code not in {200, 404} else None
    teams = []
    analysis, analysis_error, agent_status = None, None, {"configured": False, "model": None}
    report_analysis, investigation, investigation_error = None, None, None
    if user["role"] == "admin":
        team_response = await api_call(request, "GET", "/api/teams")
        if team_response.status_code == 200:
            teams = team_response.json()
            assigned = next((team for team in teams if team["id"] == report.get("assigned_team_id")), None)
            if assigned:
                report["assigned_team"] = assigned["name"]
        analysis, analysis_error, agent_status = await location_analysis_context(request, incident_id)
        report_analysis, investigation, investigation_error = await investigation_context(request, incident_id)
    return render(request, "detail.html", user=user, report=report, timeline=history.json() if history.status_code == 200 else [],
                  teams=teams, values=values or {}, error=error or (error_message(history) if history.status_code != 200 else None),
                  analysis=analysis, analysis_error=analysis_error, agent_status=agent_status,
                  report_analysis=report_analysis, investigation=investigation, investigation_error=investigation_error,
                  report_summary=report_summary, summary_error=summary_error,
                  **communication, **operations,
                  notice=notice,
                  active_nav="reports", page_title=report["reference"], status_code=status_code)


@app.get("/reports/{incident_id}", response_class=HTMLResponse)
async def report_detail(request: Request, incident_id: int):
    return await detail_page(request, incident_id)


@app.post("/ui/reports")
async def submit_report(request: Request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    form = request.state.form
    payload = {key: form.get(key) or None for key in ("message", "location", "people_affected", "help_required")}
    payload["disaster_type"] = form.get("disaster_type") or "Flood"
    response = await api_call(request, "POST", "/api/incidents/", payload)
    if response.status_code == 201:
        return redirect(request, f"/reports/{response.json()['id']}")
    return render(request, "report_form.html", user=user, error=error_message(response), values=form,
                  status_code=response.status_code, active_nav="new", page_title="Report a flood")


@app.post("/ui/reports/{incident_id}/review")
async def review_report(request: Request, incident_id: int):
    if not await current_user(request):
        return redirect(request, "/login")
    form = request.state.form
    response = await api_call(request, "PATCH", f"/api/incidents/{incident_id}/status",
                              {"status": form.get("status", ""), "note": form.get("note") or None})
    if response.status_code == 200:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response), status_code=response.status_code, values=form)


@app.post("/ui/reports/{incident_id}/assign")
async def assign_report(request: Request, incident_id: int):
    if not await current_user(request):
        return redirect(request, "/login")
    form = request.state.form
    response = await api_call(request, "POST", "/api/incidents/admin/assign-team", {"incident_id": incident_id, "team_id": form.get("team_id")})
    if response.status_code == 200:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response), status_code=response.status_code, values=form)


async def alerts_view(request, *, error=None, status_code=200, values=None, edit_id=None, notice=None):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    is_admin = user["role"] == "admin"
    response = await api_call(request, "GET", "/api/alerts?include_inactive=true" if is_admin else "/api/alerts")
    places_response = await api_call(request, "GET", "/api/alerts/places")
    alerts = response.json() if response.status_code == 200 else []
    places = places_response.json() if places_response.status_code == 200 else []
    place_map = {place["id"]: place for place in places}
    alerts = [{**alert, "place": place_map.get(alert["place_id"], {
        "name": alert.get("place_name"), "district": alert.get("district")})} for alert in alerts]
    editing = next((alert for alert in alerts if alert["id"] == edit_id), None) if is_admin else None
    if edit_id and is_admin and not editing and not error:
        error, status_code = "This alert could not be found. Choose an alert from the list.", 404
    if editing and values is None:
        values = {**editing, "starts_at": input_time(editing["starts_at"]), "expires_at": input_time(editing["expires_at"])}
    load_error = error_message(response) if response.status_code != 200 else (
        error_message(places_response) if places_response.status_code != 200 else None)
    return render(request, "alerts_workspace.html", user=user, active_nav="alerts", page_title="Official alerts",
                  official_alerts=alerts, places=places, editing=editing, values=values or {},
                  error=error or load_error, notice=notice, status_code=status_code)


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, edit: int | None = None):
    notices = {"created": "Official alert created.", "updated": "Official alert updated.", "expired": "Official alert expired."}
    return await alerts_view(request, edit_id=edit, notice=notices.get(request.query_params.get("notice")))


def alert_form_payload(form):
    payload = {key: form.get(key, "") for key in ("title", "message", "level", "place_id")}
    for key in ("starts_at", "expires_at"):
        value = str(form.get(key, "")).strip()
        if not value and key == "starts_at":
            continue
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            payload[key] = timestamp.isoformat()
        except ValueError:
            label = "Start time" if key == "starts_at" else "Expiry time"
            raise ValueError(f"{label}: enter a valid date and time in IST.") from None
    return payload


async def save_alert(request, alert_id=None):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != "admin":
        return await alerts_view(request, error="Only administrators can manage official alerts.", status_code=403)
    form = request.state.form
    try:
        payload = alert_form_payload(form)
    except ValueError as exc:
        return await alerts_view(request, error=str(exc), status_code=422, values=form, edit_id=alert_id)
    response = await api_call(request, "PATCH" if alert_id else "POST",
                              f"/api/alerts/{alert_id}" if alert_id else "/api/alerts", payload)
    if response.status_code in {200, 201}:
        return redirect(request, "/alerts?notice=updated" if alert_id else "/alerts?notice=created")
    return await alerts_view(request, error=error_message(response), status_code=response.status_code,
                             values=form, edit_id=alert_id)


@app.post("/ui/alerts")
async def create_alert(request: Request):
    return await save_alert(request)


@app.post("/ui/alerts/{alert_id}/update")
async def update_alert(request: Request, alert_id: int):
    return await save_alert(request, alert_id)


@app.post("/ui/alerts/{alert_id}/expire")
async def expire_alert(request: Request, alert_id: int):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != "admin":
        return await alerts_view(request, error="Only administrators can manage official alerts.", status_code=403)
    response = await api_call(request, "POST", f"/api/alerts/{alert_id}/expire")
    if response.status_code == 200:
        return redirect(request, "/alerts?notice=expired")
    return await alerts_view(request, error=error_message(response), status_code=response.status_code)


async def location_analysis_context(request, incident_id):
    response = await api_call(request, "GET", f"/api/incidents/{incident_id}/location-analysis")
    config = await api_call(request, "GET", "/api/agent/status")
    analysis = response.json() if response.status_code == 200 else None
    error = error_message(response) if response.status_code not in {200, 404} else None
    agent_status = config.json() if config.status_code == 200 else {"configured": False, "model": None}
    if config.status_code != 200:
        error = error or "Agent availability could not be checked. Try again shortly."
    return analysis, error, agent_status


@app.post("/ui/reports/{incident_id}/location-analysis", response_class=HTMLResponse)
async def analyze_location(request: Request, incident_id: int):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Only administrators can analyze incident locations.", status_code=403)
    response = await api_call(request, "POST", f"/api/incidents/{incident_id}/location-analysis",
                              {"use_agent": request.state.form.get("mode") == "agent"})
    analysis, analysis_error, agent_status = await location_analysis_context(request, incident_id)
    if response.status_code == 200:
        analysis = response.json()
    else:
        analysis_error = error_message(response)
    return render(request, "partials/location_analysis.html", user=user, report={"id": incident_id},
                  analysis=analysis, analysis_error=analysis_error, agent_status=agent_status,
                  status_code=response.status_code)


async def investigation_context(request, incident_id):
    analysis_response = await api_call(request, "GET", f"/api/admin/incidents/{incident_id}/analysis")
    investigation_response = await api_call(request, "GET", f"/api/admin/incidents/{incident_id}/investigation")
    report_analysis = analysis_response.json() if analysis_response.status_code == 200 else None
    investigation = investigation_response.json() if investigation_response.status_code == 200 else None
    error = error_message(analysis_response) if analysis_response.status_code != 200 else (
        error_message(investigation_response) if investigation_response.status_code != 200 else None)
    return report_analysis, investigation, error


async def report_admin(request):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    if user["role"] != "admin":
        return HTMLResponse("Only administrators can manage report analysis and investigations.", status_code=403)
    return None


@app.post("/ui/reports/{incident_id}/analysis")
async def save_report_analysis(request: Request, incident_id: int):
    denied = await report_admin(request)
    if denied is not None:
        return denied
    form = request.state.form
    payload = {
        "severity": form.get("severity", "UNKNOWN"),
        "extracted_location": form.get("extracted_location") or None,
        "alert_match": form.get("alert_match", "NOT_CHECKED"),
        "summary": form.get("summary") or None,
        "requires_investigation": form.get("requires_investigation") == "yes",
        "source": "MANUAL_DEMO",
    }
    response = await api_call(request, "PUT", f"/api/admin/incidents/{incident_id}/analysis", payload)
    if response.status_code == 200:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=form)


@app.post("/ui/reports/{incident_id}/severity")
async def predict_report_severity(request: Request, incident_id: int):
    denied = await report_admin(request)
    if denied is not None:
        return denied
    form = dict(request.state.form)
    response = await api_call(request, "POST", f"/api/ai/incidents/{incident_id}/predict-severity")
    if response.status_code == 200:
        if form.get("analysis_form"):
            form["severity"] = response.json()["severity"]
        return await detail_page(request, incident_id, values=form,
                                 notice="Severity prediction saved. Review the result and save any other assessment edits.")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=form)


@app.post("/ui/reports/{incident_id}/summary")
async def generate_report_summary(request: Request, incident_id: int):
    denied = await report_admin(request)
    if denied is not None:
        return denied
    response = await api_call(request, "POST", f"/api/incidents/{incident_id}/summary")
    if response.status_code == 200:
        return await detail_page(request, incident_id, values=request.state.form,
                                 notice="Report summary generated. Your reviewed assessment has not been changed.")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=request.state.form)


@app.post("/ui/reports/{incident_id}/investigation/start")
async def start_report_investigation(request: Request, incident_id: int):
    denied = await report_admin(request)
    if denied is not None:
        return denied
    form = request.state.form
    response = await api_call(request, "POST", f"/api/admin/incidents/{incident_id}/investigation",
                              {"assigned_to_name": form.get("assigned_to_name", "")})
    if response.status_code in {200, 201}:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=form)


@app.post("/ui/reports/{incident_id}/investigation/update")
async def update_report_investigation(request: Request, incident_id: int):
    denied = await report_admin(request)
    if denied is not None:
        return denied
    form = request.state.form
    current = await api_call(request, "GET", f"/api/admin/incidents/{incident_id}/investigation")
    if current.status_code != 200:
        return await detail_page(request, incident_id, error=error_message(current),
                                 status_code=current.status_code, values=form)
    investigation = current.json()
    if not investigation:
        return await detail_page(request, incident_id, error="Start an investigation before updating it.",
                                 status_code=409, values=form)
    response = await api_call(request, "PATCH", f"/api/admin/incidents/investigations/{investigation['id']}", {
        "status": form.get("status", "IN_PROGRESS"), "findings": form.get("findings", ""),
        "action_taken": form.get("action_taken") or None,
    })
    if response.status_code == 200:
        return redirect(request, f"/reports/{incident_id}")
    return await detail_page(request, incident_id, error=error_message(response),
                             status_code=response.status_code, values=form)


# Keep the API mount last so every HTML action remains reachable.
from web.communication import router as communication_ui
from web.operations import router as operations_ui
app.include_router(communication_ui)
app.include_router(operations_ui)
app.mount("/", api)
