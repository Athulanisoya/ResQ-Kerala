"""Relief delivery and shelter workflows against isolated synthetic data."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .test_auth import api, synthetic_password_hash
from backend.models import Incident, Role, Team, User
from backend.models.relief import Distribution, Inventory, ReliefRequest


@pytest.fixture
def services(api, synthetic_password_hash):
    with api.sessions() as db:
        # Team IDs intentionally differ from user IDs so the delivery foreign key
        # cannot accidentally pass by referencing an unrelated user.
        db.add_all([Team(name=f"Unused {i}", team_type="Rescue") for i in range(6)])
        db.flush()
        relief = Team(name="Synthetic Relief Team", team_type="Relief")
        shelter = Team(name="Synthetic Shelter Team", team_type="Shelter")
        other_shelter = Team(name="Other Shelter Team", team_type="Shelter")
        db.add_all([relief, shelter, other_shelter])
        db.flush()
        db.get(User, api.users["response_team"]).team_id = relief.id
        for name, team in (("shelter", shelter), ("other_shelter", other_shelter)):
            user = User(full_name=f"Synthetic {name}", email=f"{name}@example.com",
                        role=Role.RESPONSE_TEAM, team_id=team.id,
                        password_hash=synthetic_password_hash)
            db.add(user)
            db.flush()
            api.users[name] = user.id
        incident = Incident(report_reference="RELIEF-TEST", user_id=api.users["citizen"],
                            message="Food and water needed", location="Kochi",
                            assigned_team_id=relief.id, status="IN_PROGRESS")
        db.add(incident)
        db.commit()
        api.incident_id = incident.id
        api.relief_team_id = relief.id
        api.shelter_team_id = shelter.id
    return api


def request_relief(api, item="FOOD", quantity=10):
    return api.client.post(f"/api/relief/incidents/{api.incident_id}/requests",
                           headers=api.headers("citizen"),
                           json={"item": item, "quantity": quantity})


def stock(api, quantity=25):
    return api.client.post("/api/relief/inventory", headers=api.headers("admin"),
                           json={"item": "FOOD", "quantity": quantity})


def deliver(api, request_id, quantity, key=None):
    return api.client.post(f"/api/relief/requests/{request_id}/distributions",
                           headers=api.headers("response_team"),
                           json={"quantity": quantity, "idempotency_key": key or str(uuid4())})


def test_delivery_records_team_and_user_and_retries_only_once(services):
    api = services
    request = request_relief(api)
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    assert stock(api).status_code == 201
    key = str(uuid4())
    first = deliver(api, request_id, 4, key)
    assert first.status_code == 200, first.text
    assert first.json()["team_id"] == api.relief_team_id
    assert first.json()["recorded_by"] == api.users["response_team"]
    assert deliver(api, request_id, 4, key).json() == first.json()
    assert deliver(api, request_id, 5, key).status_code == 409
    history = api.client.get(f"/api/relief/incidents/{api.incident_id}/distributions",
                             headers=api.headers("citizen"))
    assert history.json() == [first.json()]
    with api.sessions() as db:
        assert db.get(ReliefRequest, request_id).fulfilled == 4
        assert db.scalar(select(Inventory)).quantity == 21
        assert len(list(db.scalars(select(Distribution)))) == 1


def test_failed_deliveries_preserve_stock_and_demand(services):
    api = services
    request_id = request_relief(api, quantity=10).json()["id"]
    stock_id = stock(api, quantity=5).json()["id"]
    assert deliver(api, request_id, 6).status_code == 409
    assert api.client.post(f"/api/relief/inventory/{stock_id}/restock",
                           headers=api.headers("admin"), json={"quantity": 15}).status_code == 200
    assert deliver(api, request_id, 11).status_code == 409
    with api.sessions() as db:
        assert db.get(ReliefRequest, request_id).fulfilled == 0
        assert db.get(Inventory, stock_id).quantity == 20
        assert list(db.scalars(select(Distribution))) == []


def test_duplicate_requests_and_stock_are_conflicts(services):
    assert request_relief(services).status_code == 201
    assert request_relief(services).status_code == 409
    assert stock(services).status_code == 201
    assert stock(services).status_code == 409


@pytest.mark.parametrize("fulfilled", [-1, 11])
def test_relief_database_constraint_rejects_invalid_fulfillment(services, fulfilled):
    with services.sessions() as db:
        db.add(ReliefRequest(incident_id=services.incident_id, item="FOOD", quantity=10,
                             fulfilled=fulfilled, created_by=services.users["citizen"]))
        with pytest.raises(IntegrityError):
            db.commit()


def shelter_payload(api, **changes):
    return {"name": "Kochi Shelter", "location": "Kochi School", "capacity": 30,
            "occupied": 10, "team_id": api.shelter_team_id, **changes}


def test_shelter_updates_require_designated_team_and_current_version(services):
    api = services
    created = api.client.post("/api/shelters", headers=api.headers("admin"),
                              json=shelter_payload(api))
    assert created.status_code == 201, created.text
    shelter_id = created.json()["id"]
    assert created.json()["available"] == 20
    patch = {"capacity": 30, "occupied": 30, "expected_version": 1, "note": "All beds filled"}
    for role in ("citizen", "response_team", "other_shelter"):
        assert api.client.patch(f"/api/shelters/{shelter_id}", headers=api.headers(role),
                                json=patch).status_code == 403
    result = api.client.patch(f"/api/shelters/{shelter_id}", headers=api.headers("shelter"), json=patch)
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2 and result.json()["available"] == 0
    assert api.client.patch(f"/api/shelters/{shelter_id}", headers=api.headers("admin"),
                            json=patch).status_code == 409
    history = api.client.get(f"/api/shelters/{shelter_id}/history", headers=api.headers("shelter")).json()
    assert [row["version"] for row in history] == [1, 2]
    assert history[-1]["changed_by"] == api.users["shelter"]
    assert api.client.get("/api/shelters?available_only=true", headers=api.headers("citizen")).json() == []


@pytest.mark.parametrize("changes", [{"occupied": 31}, {"capacity": 0}, {"occupied": -1},
                                      {"occupied": True}, {"name": "   "}])
def test_shelter_rejects_invalid_counts_and_names(services, changes):
    response = services.client.post("/api/shelters", headers=services.headers("admin"),
                                    json=shelter_payload(services, **changes))
    assert response.status_code == 422, response.text


def test_shelter_creation_requires_shelter_team(services):
    response = services.client.post("/api/shelters", headers=services.headers("admin"),
                                    json=shelter_payload(services, team_id=services.relief_team_id))
    assert response.status_code == 409


def test_both_shelter_workflows_share_search_and_history(services):
    api = services
    headers = api.headers("admin")
    created = api.client.post("/api/shelters", headers=headers, json={
        "name": "Community Centre", "district": "Ernakulam", "locality": "Aluva",
        "address": "Aluva School", "capacity": 20, "occupied": 5,
        "source_name": "Synthetic community listing",
    })
    assert created.status_code == 201, created.text
    shelter_id = created.json()["id"]
    managed = api.client.post("/api/shelters", headers=headers, json=shelter_payload(api))
    assert managed.status_code == 201, managed.text
    search = api.client.get("/api/shelters", headers=headers, params={"location": "Aluva"})
    assert [row["id"] for row in search.json()] == [shelter_id]
    history = api.client.get(f"/api/shelters/{shelter_id}/history", headers=headers)
    assert [row["version"] for row in history.json()] == [1]
    patch = {"capacity": 20, "occupied": 20, "expected_version": 1, "note": "All beds filled"}
    assert api.client.patch(f"/api/shelters/{shelter_id}", headers=headers, json=patch).json()["status"] == "FULL"
    assert [row["version"] for row in api.client.get(f"/api/shelters/{shelter_id}/history", headers=headers).json()] == [1, 2]
    assert shelter_id in [row["id"] for row in api.client.get("/api/shelters", headers=headers).json()]
    assert shelter_id not in [row["id"] for row in api.client.get("/api/shelters?available_only=true", headers=headers).json()]


def test_shelter_list_does_not_silently_truncate(services):
    from backend.models.shelter import Shelter
    api = services
    with api.sessions() as db:
        db.add_all([Shelter(name=f"Synthetic shelter {i}", location="Kochi", capacity=10, occupied=1)
                    for i in range(12)])
        db.commit()
    response = api.client.get("/api/shelters", headers=api.headers("citizen"))
    assert len(response.json()) == 12
    limited = api.client.get("/api/shelters?limit=5", headers=api.headers("citizen"))
    assert len(limited.json()) == 5


def test_week4_shelter_tool_preserves_managed_location(services):
    import asyncio
    import json
    from agents.tool import ToolContext
    from backend.ai.week4_orchestrator import Week4Context, tool_6_search_shelters
    api = services
    created = api.client.post("/api/shelters", headers=api.headers("admin"), json=shelter_payload(api))
    assert created.status_code == 201
    with api.sessions() as db:
        context = Week4Context(db=db, incident=None, original_text="", reported_location="Kochi School")
        output = asyncio.run(tool_6_search_shelters.on_invoke_tool(ToolContext(context, tool_name="tool_6_search_shelters", tool_call_id="test", tool_arguments="{}"), "{}"))
        result = json.loads(output) if isinstance(output, str) else output
        assert result["count"] == 1
        assert result["shelters"][0]["location"] == "Kochi School"
        assert result["shelters"][0]["source_name"] is None
