"""Exercise the forms actually rendered for task progress and relief delivery."""
import json
import os
import re
from contextlib import ExitStack
from html import unescape

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "operations-ui-tests-only-synthetic-secret-long-enough"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.main import app as api
from backend.models import Role, User
from backend.models.team import Team
from backend.utils.security import hash_password
from web.app import CSRF_COOKIE, app


PASSWORD = "Synthetic-operations-ui!2026"


@pytest.fixture
def operations_clients():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([Team(id=1, name="Rescue Alpha", team_type="rescue"),
                    Team(id=2, name="Relief Delta", team_type="relief"),
                    Team(id=3, name="Other rescue", team_type="rescue")])
        db.flush()
        for name, role, team_id in [("citizen", Role.CITIZEN, None), ("admin", Role.ADMIN, None),
                                    ("rescue", Role.RESPONSE_TEAM, 1), ("relief", Role.RESPONSE_TEAM, 2)]:
            db.add(User(full_name=name.title(), email=f"{name}@operations.example", role=role,
                        team_id=team_id, password_hash=hash_password(PASSWORD)))
        db.commit()

    def override():
        with sessions() as db:
            yield db

    api.dependency_overrides[get_db] = override
    try:
        with ExitStack() as stack:
            clients = {name: stack.enter_context(TestClient(app)) for name in ("citizen", "admin", "rescue", "relief")}
            for name, client in clients.items():
                client.headers["X-ResQ-Page"] = "true"
                assert client.get("/login").status_code == 200
                response = submit(client, "/ui/login", email=f"{name}@operations.example", password=PASSWORD)
                assert response.status_code == 204
                token = json.loads(response.headers["HX-Trigger"])["resq:authenticated"]["access_token"]
                client.headers["Authorization"] = f"Bearer {token}"
            yield clients
    finally:
        api.dependency_overrides.clear()
        engine.dispose()


def submit(client, action, **values):
    return client.post(action, data={"_csrf": client.cookies.get(CSRF_COOKIE), **values}, headers={"HX-Request": "true"})


def form(response, action):
    match = re.search(r'<form\b[^>]*action="' + re.escape(action) + r'"[^>]*>(.*?)</form>', response.text, re.S)
    assert match, f"Expected rendered form: {action}"
    inputs = {}
    for tag in re.findall(r"<input\b[^>]*>", match.group(1)):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name and value:
            inputs[name.group(1)] = unescape(value.group(1))
    return match.group(1), inputs


def assigned_report(clients):
    citizen, admin = clients["citizen"], clients["admin"]
    created = submit(citizen, "/ui/reports", message="Water rising near the village school.",
                     location="Chengannur", people_affected="6", help_required="Rescue and supplies")
    assert created.status_code == 200
    incident_id = int(created.headers["HX-Redirect"].rsplit("/", 1)[-1])
    for status in ("UNDER_REVIEW", "VERIFIED"):
        assert submit(admin, f"/ui/reports/{incident_id}/review", status=status).status_code == 200
    assert submit(admin, f"/ui/reports/{incident_id}/assign", team_id="1").status_code == 200
    return incident_id


def test_visible_accept_travel_progress_handoff_and_private_history(operations_clients):
    clients = operations_clients
    incident_id = assigned_report(clients)
    path = f"/reports/{incident_id}"
    rescue = clients["rescue"]
    accept = f"/ui/operations/incidents/{incident_id}/accept"
    form(rescue.get(path), accept)
    assert submit(rescue, accept, note="Rescue team ready").status_code == 200
    progress = f"/ui/operations/incidents/{incident_id}/progress"
    for expected, label in [("EN_ROUTE", "Mark en route"), ("IN_PROGRESS", "Start field response")]:
        page = rescue.get(path)
        body, values = form(page, progress)
        assert label in body and values["status"] == expected
        assert submit(rescue, progress, **values).status_code == 200
    admin = clients["admin"]
    handoff = f"/ui/operations/incidents/{incident_id}/handoff"
    body, _ = form(admin.get(path), handoff)
    assert "Relief Delta" in body and "Other rescue" not in body
    assert submit(admin, handoff, team_id="2", note="Rescue complete; relief work remains").status_code == 200
    assert rescue.get(path).status_code == 403
    history = rescue.get("/assignments-history")
    assert history.status_code == 200 and "Chengannur" in history.text
    assert "Handed Off" in history.text and f'href="{path}"' not in history.text
    # The successor snapshot has a different ID: report links must use incident_id.
    relief = clients["relief"]
    task = relief.get("/api/operations/tasks").json()[0]
    assert task["id"] != incident_id
    assert f'href="{path}"' in relief.get("/operations").text
    form(relief.get(path), accept)
    assert submit(relief, accept).status_code == 200
    for expected in ("EN_ROUTE", "IN_PROGRESS", "RESOLVED"):
        _, values = form(relief.get(path), progress)
        assert values["status"] == expected
        assert submit(relief, progress, **values).status_code == 200
    assert "Resolve incident" not in relief.get(path).text


def test_citizen_catalogue_partial_delivery_retry_and_validation(operations_clients):
    clients = operations_clients
    incident_id = assigned_report(clients)
    admin, citizen, relief = clients["admin"], clients["citizen"], clients["relief"]
    assert submit(admin, "/ui/operations/inventory", name="Drinking water", unit="litres", quantity="5",
                  form_scope="inventory-create").status_code == 200
    item = admin.get("/api/operations/inventory").json()[0]
    citizen_page = citizen.get("/operations")
    assert "Drinking water" in citizen_page.text and 'value="SUPPLIES"' in citizen_page.text
    assert "Stock on hand" not in citizen_page.text and "Add inventory item" not in citizen_page.text
    assert submit(citizen, "/ui/operations/relief-requests", incident_id=incident_id, kind="SUPPLIES",
                  form_scope="relief-create", **{f"quantity_{item['id']}": "10"}).status_code == 200
    request = admin.get("/api/operations/relief-requests").json()[0]
    request_id, line = request["id"], request["items"][0]
    assign = f"/ui/operations/relief-requests/{request_id}/assign"
    assignment_body, _ = form(admin.get("/operations"), assign)
    assert "Relief Delta" in assignment_body and "Other rescue" not in assignment_body
    assert submit(admin, assign, team_id="2").status_code == 200
    delivery = f"/ui/operations/relief-requests/{request_id}/deliveries"
    body, values = form(relief.get("/operations"), delivery)
    assert 'max="5.0"' in body
    payload = {**values, f"delivery_{line['id']}": "3", "delivery_note": "First trip"}
    assert submit(relief, delivery, **payload).status_code == 200
    assert submit(relief, delivery, **payload).status_code == 200
    detail = relief.get(f"/api/operations/relief-requests/{request_id}").json()
    assert detail["items"][0]["remaining_quantity"] == 7
    assert len(detail["deliveries"]) == 1
    assert relief.get("/api/operations/inventory").json()[0]["quantity"] == 2
    page = relief.get("/operations")
    body, values = form(page, delivery)
    assert "7.0 litres" in page.text and 'max="2.0"' in body
    invalid = submit(relief, delivery, **{**values, f"delivery_{line['id']}": "900", "delivery_note": "Keep this note"})
    assert invalid.status_code == 422 and "exceeds the remaining" in invalid.text
    _, retained = form(invalid, delivery)
    assert retained[f"delivery_{line['id']}"] == "900"
    assert retained["idempotency_key"] == values["idempotency_key"] and "Keep this note" in invalid.text
    assert submit(relief, "/ui/operations/inventory", name="Forbidden", unit="kg", quantity="2").status_code == 403
    assert "Add inventory item" not in relief.get("/operations").text
    # A completed full-delivery retry must reach the API's idempotency check,
    # even though the request now has zero remaining quantity.
    assert submit(admin, f"/ui/operations/inventory/{item['id']}/update", name="Drinking water", unit="litres",
                  quantity="20", reason="Second stock count").status_code == 200
    body, values = form(relief.get("/operations"), delivery)
    full = {**values, f"delivery_{line['id']}": "7"}
    assert submit(relief, delivery, **full).status_code == 200
    assert submit(relief, delivery, **full).status_code == 200
    completed = relief.get(f"/api/operations/relief-requests/{request_id}").json()
    assert completed["status"] == "COMPLETED" and len(completed["deliveries"]) == 2
    audit = admin.get(f"/operations?stock_history={item['id']}")
    assert "Second stock count" in audit.text and "Stock history" in audit.text
    assert citizen.get("/assignments-history").status_code == 403


def test_inventory_form_errors_preserve_values_and_csrf(operations_clients):
    admin = operations_clients["admin"]
    assert admin.post("/ui/operations/inventory", data={"name": "Water", "unit": "litres", "quantity": 2}).status_code == 403
    invalid = submit(admin, "/ui/operations/inventory", name="Drinking water", unit="litres", quantity="-4",
                     form_scope="inventory-create")
    assert invalid.status_code == 422 and "Quantity must be zero or greater" in invalid.text
    _, values = form(invalid, "/ui/operations/inventory")
    assert values["name"] == "Drinking water" and values["quantity"] == "-4"
    assert 'hx-post="/ui/operations/inventory"' in invalid.text
