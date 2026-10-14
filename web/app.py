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


@asynccontextmanager
async def lifespan(_app):
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(title="ResQ Kerala · Week 1", lifespan=lifespan, docs_url=None, redoc_url=None)
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
    ui_page = path in {"/", "/login", "/register", "/dashboard", "/reports", "/reports/new", "/account", "/permissions"} or (
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
             "verified": sum(r["status"] == "VERIFIED" for r in reports), "assigned": sum(r["status"] == "ASSIGNED" for r in reports)}
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
async def reports_page(request: Request, status: str = ""):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    reports, error = await list_reports(request, user)
    total = len(reports)
    if status:
        reports = [report for report in reports if report["status"] == status]
    return render(request, "reports.html", user=user, reports=reports, total=total, filter_status=status,
                  error=error, active_nav="reports", page_title="Reports")


async def detail_page(request, incident_id, *, error=None, status_code=200, values=None):
    user = await current_user(request)
    if not user:
        return redirect(request, "/login")
    response = await api_call(request, "GET", f"/api/incidents/{incident_id}")
    if response.status_code != 200:
        return render(request, "reports.html", user=user, error=error_message(response), status_code=response.status_code)
    report = display_report(response.json(), user)
    history = await api_call(request, "GET", f"/api/incidents/{incident_id}/history")
    teams = []
    if user["role"] == "admin":
        team_response = await api_call(request, "GET", "/api/teams")
        if team_response.status_code == 200:
            teams = team_response.json()
            assigned = next((team for team in teams if team["id"] == report.get("assigned_team_id")), None)
            if assigned:
                report["assigned_team"] = assigned["name"]
    return render(request, "detail.html", user=user, report=report, timeline=history.json() if history.status_code == 200 else [],
                  teams=teams, values=values or {}, error=error or (error_message(history) if history.status_code != 200 else None),
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


# All original JSON endpoints remain reachable on the same origin.
app.mount("/", api)
