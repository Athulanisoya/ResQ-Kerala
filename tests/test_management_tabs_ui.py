"""Administration sections keep actions, validation and private access in the right view."""
from html import unescape
from html.parser import HTMLParser
import re

import pytest

from test_web import clients, login, post


SECTIONS = {
    "create-team": "Create a team",
    "accounts": "Account management",
    "teams": "Response teams",
    "reports": "Aggregate reports",
}


class AdminNavigation(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.in_navigation = False
        self.links = []
        self.link = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "nav" and attrs.get("aria-label") == "Administration sections":
            self.in_navigation = True
        if self.in_navigation and tag == "a":
            self.link = {**attrs, "text": ""}

    def handle_data(self, data):
        if self.link is not None:
            self.link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            self.link["text"] = self.link["text"].strip()
            self.links.append(self.link)
            self.link = None
        if tag == "nav":
            self.in_navigation = False


class TableRows(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.rows = []
        self.row = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = ""

    def handle_data(self, data):
        if self.row is not None:
            self.row += data + " "

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            self.rows.append(" ".join(self.row.split()))
            self.row = None


def assert_selected(response, selected):
    navigation = AdminNavigation(response.text).links
    assert len(navigation) == 4
    for key, label in SECTIONS.items():
        link = next(item for item in navigation if item["text"] == label)
        assert link["href"] == f"/management?tab={key}"
        assert link["hx-get"] == f"/management?tab={key}"
        assert link["hx-target"] == "#main-content"
        assert (link.get("aria-current") == "page") == (key == selected)


def form_markup(response, action):
    match = re.search(r'<form\b[^>]*action="' + re.escape(action) + r'"[^>]*>(.*?)</form>', response.text, re.S)
    assert match, f"Missing form for {action}"
    return match.group(1)


def selected_value(markup, name):
    select = re.search(r'<select\b[^>]*name="' + re.escape(name) + r'"[^>]*>(.*?)</select>', markup, re.S)
    assert select, f"Missing select {name}"
    options = re.findall(r'<option\b([^>]*)>(.*?)</option>', select.group(1), re.S)
    selected = next(((attrs, text) for attrs, text in options if re.search(r'\bselected\b', attrs)), options[0])
    value = re.search(r'\bvalue="([^"]*)"', selected[0])
    return unescape(value.group(1) if value else selected[1].strip())


@pytest.mark.parametrize("section", SECTIONS)
def test_administration_sections_render_only_the_selected_workflow(clients, section):
    _, admin, _ = clients
    login(admin, "admin")
    page = admin.get(f"/management?tab={section}", headers={"HX-Request": "true"})
    assert page.status_code == 200
    assert_selected(page, section)
    actions = re.findall(r'<form\b[^>]*action="([^"]+)"', page.text)
    if section == "create-team":
        assert "/ui/management/teams" in actions
        assert "/ui/management/team-accounts" in actions
        assert not any(action.startswith("/ui/management/users/") for action in actions)
        assert not any(re.fullmatch(r"/ui/management/teams/\d+", action) for action in actions)
    elif section == "accounts":
        assert actions and all(action.startswith("/ui/management/users/") for action in actions)
    elif section == "teams":
        assert actions and all(re.fullmatch(r"/ui/management/teams/\d+", action) for action in actions)
    else:
        assert actions == []


@pytest.mark.parametrize("query", ["", "?tab=not-a-section"])
def test_management_defaults_to_create_team_for_missing_or_unknown_section(clients, query):
    _, admin, _ = clients
    login(admin, "admin")
    page = admin.get("/management" + query)
    assert page.status_code == 200
    assert_selected(page, "create-team")


def test_each_section_remains_admin_only(clients):
    citizen, _, team = clients
    login(citizen, "citizen")
    login(team, "response_team")
    for client in (citizen, team):
        for section in SECTIONS:
            page = client.get(f"/management?tab={section}", headers={"HX-Request": "true"})
            assert page.status_code == 403
            assert "Account management" not in page.text


def test_create_team_stays_in_creation_section_and_retains_invalid_values(clients):
    _, admin, _ = clients
    login(admin, "admin")
    result = post(admin, "/ui/management/teams", name="Synthetic tab team", team_type="Investigation")
    assert result.status_code == 200
    assert result.headers["HX-Push-Url"] == "/management?tab=create-team"
    assert_selected(result, "create-team")
    assert "Synthetic tab team" in result.text
    duplicate = post(admin, "/ui/management/teams", name="Synthetic tab team", team_type="Investigation")
    assert duplicate.status_code == 409
    assert duplicate.headers["HX-Push-Url"] == "/management?tab=create-team"
    assert_selected(duplicate, "create-team")
    form = form_markup(duplicate, "/ui/management/teams")
    assert 'value="Synthetic tab team"' in form
    assert selected_value(form, "team_type") == "Investigation"


def test_team_account_validation_returns_to_creation_without_echoing_password(clients):
    _, admin, _ = clients
    login(admin, "admin")
    body = {"full_name": "Synthetic Tab Member", "email": "tab-member@example.com", "team_id": "1",
            "password": "Synthetic-private-tab!2026", "confirm_password": "Mismatch-private!2026"}
    result = post(admin, "/ui/management/team-accounts", **body)
    assert result.status_code == 422
    assert result.headers["HX-Push-Url"] == "/management?tab=create-team"
    assert_selected(result, "create-team")
    assert 'value="Synthetic Tab Member"' in result.text
    assert 'value="tab-member@example.com"' in result.text
    assert body["password"] not in result.text and body["confirm_password"] not in result.text


def test_account_edit_keeps_account_section_and_retains_validation_values(clients):
    _, admin, _ = clients
    login(admin, "admin")
    accounts = admin.get("/api/management/users").json()
    citizen = next(account for account in accounts if account["role"] == "citizen")
    action = f"/ui/management/users/{citizen['id']}"
    invalid = post(admin, action, role="response_team", team_id="", active="yes")
    assert invalid.status_code == 422
    assert invalid.headers["HX-Push-Url"] == "/management?tab=accounts"
    assert_selected(invalid, "accounts")
    form = form_markup(invalid, action)
    assert selected_value(form, "role") == "response_team"
    assert selected_value(form, "team_id") == ""
    assert selected_value(form, "active") == "yes"
    # This is a real change on isolated fixture data; no live user's account is altered.
    saved = post(admin, action, role="citizen", team_id="", active="no")
    assert saved.status_code == 200
    assert saved.headers["HX-Push-Url"] == "/management?tab=accounts"
    assert_selected(saved, "accounts")
    assert next(account for account in admin.get("/api/management/users").json()
                if account["id"] == citizen["id"])["active"] is False


def test_team_edit_keeps_team_section_and_failed_values(clients):
    _, admin, _ = clients
    login(admin, "admin")
    teams = admin.get("/api/management/teams").json()
    team = teams[0]
    action = f"/ui/management/teams/{team['id']}"
    invalid = post(admin, action, name="Preserved team draft", status="INVALID")
    assert invalid.status_code == 422
    assert invalid.headers["HX-Push-Url"] == "/management?tab=teams"
    assert_selected(invalid, "teams")
    assert 'value="Preserved team draft"' in form_markup(invalid, action)
    saved = post(admin, action, name="Renamed tab team", status="OFFLINE")
    assert saved.status_code == 200
    assert saved.headers["HX-Push-Url"] == "/management?tab=teams"
    assert_selected(saved, "teams")
    assert next(item for item in admin.get("/api/management/teams").json()
                if item["id"] == team["id"])["status"] == "OFFLINE"


@pytest.mark.parametrize("action,section", [("create", "create-team"), ("member", "create-team"),
                                               ("account", "accounts"), ("team", "teams")])
def test_native_management_submissions_redirect_to_their_section(clients, action, section):
    from web.app import CSRF_COOKIE
    _, admin, _ = clients
    login(admin, "admin")
    if action == "create":
        path, values = "/ui/management/teams", {"name": "Native form team", "team_type": "Rescue"}
    elif action == "member":
        path, values = "/ui/management/team-accounts", {
            "full_name": "Native Form Member", "email": "native-member@example.com", "team_id": "1",
            "password": "Synthetic-native-member!2026", "confirm_password": "Synthetic-native-member!2026"}
    elif action == "account":
        citizen = next(account for account in admin.get("/api/management/users").json() if account["role"] == "citizen")
        path, values = f"/ui/management/users/{citizen['id']}", {"role": "citizen", "team_id": "", "active": "yes"}
    else:
        path, values = "/ui/management/teams/1", {"name": "Native team edit", "status": "AVAILABLE"}
    result = admin.post(path, data={"_csrf": admin.cookies.get(CSRF_COOKIE), **values}, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == f"/management?tab={section}"


def test_management_forms_still_require_csrf(clients):
    _, admin, _ = clients
    login(admin, "admin")
    result = admin.post("/ui/management/teams", headers={"HX-Request": "true"},
                        data={"name": "Forged tab team", "team_type": "Rescue", "_csrf": "invalid"})
    assert result.status_code == 403
    assert "form expired" in result.text


def test_aggregate_report_displays_donation_units_as_separate_rows(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen")
    login(admin, "admin")
    for description, quantity, unit in [("Synthetic water", "3", "litres"), ("Synthetic food", "2", "packets")]:
        created = post(citizen, "/ui/community/pledges", campaign_id="", kind="SUPPLIES",
                       description=description, quantity=quantity, unit=unit,
                       idempotency_key="synthetic-administration-pledge-" + unit)
        assert created.status_code == 200
    report = admin.get("/management?tab=reports", headers={"HX-Request": "true"})
    assert report.status_code == 200
    assert_selected(report, "reports")
    rows = TableRows(report.text).rows
    water = next(row for row in rows if "litres" in row)
    food = next(row for row in rows if "packets" in row)
    assert "packets" not in water and "litres" not in food
    assert re.search(r"\b3(?:\.0)?\b", water)
    assert re.search(r"\b2(?:\.0)?\b", food)
