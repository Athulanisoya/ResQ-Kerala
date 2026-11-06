"""Suggestions use explicit areas and never assign or overwrite a report."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Incident, Role, Team, User
from backend.models.admin_audit import AdminChange
from backend.models.review_assistance import LocationConfirmation
from backend.models.team_coverage import TeamOperationalProfile
from backend.services.review_assistance import report_input_hash


def team(api, name, *, kind="Rescue", status="AVAILABLE", active=True, account=True, areas=None, capabilities=None):
    with api.sessions() as db:
        row = Team(name=name, team_type=kind, status=status)
        db.add(row); db.flush()
        if account:
            db.add(User(full_name="Synthetic candidate member", email=f"team-{uuid4().hex}@example.com",
                        password_hash="synthetic-unused-hash", role=Role.RESPONSE_TEAM, team_id=row.id, active=active))
        if areas is not None or capabilities is not None:
            db.add(TeamOperationalProfile(team_id=row.id, area_ids=areas or [], capabilities=capabilities or [],
                                          note="Synthetic area declaration", version=1, updated_by_id=api.users["admin"]))
        db.commit()
        return row.id


def report(api, *, location="Aluva, Ernakulam", message="Synthetic flood report", status="VERIFIED"):
    with api.sessions() as db:
        row = Incident(report_reference=f"RESQ TEAM REC {uuid4().hex}", user_id=api.users["citizen"],
                       message=message, location=location, status=status)
        db.add(row); db.commit()
        return row.id


def suggestions(api, incident, **query):
    response = api.client.get(f"/api/admin/incidents/{incident}/team-recommendations", params=query, headers=api.headers("admin"))
    assert response.status_code == 200, response.text
    return response.json()


def test_candidates_rank_locality_then_district_then_unknown_without_assigning(api):
    unknown = team(api, "A unknown coverage")
    district = team(api, "B district coverage", areas=["ernakulam"])
    locality = team(api, "C locality coverage", areas=["ernakulam-aluva"])
    outside = team(api, "Outside coverage", areas=["thrissur"])
    incident = report(api)
    result = suggestions(api, incident)
    assert [candidate["team_id"] for candidate in result["teams"]] == [locality, district, unknown]
    assert [candidate["score"] for candidate in result["teams"]] == [40, 20, 0]
    assert result["teams"][-1]["area_match"] == "unknown_coverage"
    assert result["excluded_counts"]["outside_coverage"] == 1
    assert result["can_assign"] is True
    assert result["location_source"] == "catalog_extraction"
    assert result["location"]["place"]["id"] == "ernakulam-aluva"
    assert "not a probability" in result["ranking_note"]
    with api.sessions() as db:
        assert db.get(Incident, incident).status == "VERIFIED"
        assert db.get(Incident, incident).assigned_team_id is None
        assert db.get(Team, locality).status == "AVAILABLE"
        assert outside not in [item["team_id"] for item in result["teams"]]


def test_eligibility_checks_type_availability_and_active_team_account(api):
    expected = team(api, "Eligible", kind="rescue")
    team(api, "Busy", status="BUSY")
    team(api, "Offline", status="OFFLINE")
    team(api, "Inactive account", active=False)
    team(api, "No account", account=False)
    relief = team(api, "Relief team", kind="Relief")
    incident = report(api)
    result = suggestions(api, incident)
    assert [item["team_id"] for item in result["teams"]] == [expected]
    assert result["excluded_counts"] == {"different_type": 1, "unavailable": 2, "no_active_account": 2, "missing_capability": 0, "outside_coverage": 0}
    assert [item["team_id"] for item in suggestions(api, incident, team_type="Relief")["teams"]] == [relief]


def test_required_capability_is_explicit_and_not_guessed_from_message(api):
    equipped = team(api, "Water equipped", capabilities=["water_rescue"])
    team(api, "Evacuation team", capabilities=["evacuation"])
    team(api, "Undeclared")
    incident = report(api, message="Synthetic water rescue request")
    assert len(suggestions(api, incident)["teams"]) == 3
    result = suggestions(api, incident, capability="water_rescue")
    assert [item["team_id"] for item in result["teams"]] == [equipped]
    assert result["teams"][0]["score"] == 20
    assert result["excluded_counts"]["missing_capability"] == 2
    assert "Administrator-declared capability" in " ".join(result["teams"][0]["reasons"])


def test_uncertain_location_has_no_fabricated_operating_area_match(api):
    one = team(api, "Known district", areas=["ernakulam"])
    other = team(api, "Another district", areas=["thrissur"])
    incident = report(api, location="Paravur")
    result = suggestions(api, incident)
    assert result["location"]["status"] == "UNCERTAIN"
    assert {item["team_id"] for item in result["teams"]} == {one, other}
    assert {item["area_match"] for item in result["teams"]} == {"unknown_location"}
    assert {item["score"] for item in result["teams"]} == {0}


def test_current_human_confirmation_overrides_ambiguous_original_but_stale_one_does_not(api):
    kochi = team(api, "Ernakulam team", areas=["ernakulam"])
    kollam = team(api, "Kollam team", areas=["kollam"])
    incident = report(api, location="Paravur")
    with api.sessions() as db:
        row = db.get(Incident, incident)
        db.add(LocationConfirmation(incident_id=incident, place_id="ernakulam-north-paravur",
                                   locality="North Paravur", input_hash=report_input_hash(row),
                                   confirmed_by=api.users["admin"], note="Synthetic clarification"))
        db.commit()
    result = suggestions(api, incident)
    assert result["location_source"] == "human_confirmation"
    assert [item["team_id"] for item in result["teams"]] == [kochi]
    with api.sessions() as db:
        db.get(Incident, incident).location = "Unknown synthetic locality"; db.commit()
    result = suggestions(api, incident)
    assert result["location_source"] == "catalog_extraction"
    assert {item["team_id"] for item in result["teams"]} == {kochi, kollam}


def test_district_only_location_cannot_claim_locality_coverage_is_district_wide(api):
    exact = team(api, "District team", areas=["ernakulam"])
    partial = team(api, "Local team", areas=["ernakulam-aluva"])
    incident = report(api, location="Ernakulam")
    result = suggestions(api, incident)
    assert [item["team_id"] for item in result["teams"]] == [exact, partial]
    assert result["teams"][1]["area_match"] == "partial_district"
    assert "clarify" in result["teams"][1]["reasons"][1]


@pytest.mark.parametrize("role", ["citizen", "response_team"])
def test_coverage_and_recommendation_resources_are_administrator_only(api, role):
    target = team(api, "Private admin profile")
    incident = report(api)
    headers = api.headers(role)
    for path in (f"/api/admin/teams/{target}/coverage", "/api/admin/team-coverage/catalog", f"/api/admin/incidents/{incident}/team-recommendations"):
        assert api.client.get(path, headers=headers).status_code == 403
    assert api.client.put(f"/api/admin/teams/{target}/coverage", headers=headers,
                          json={"expected_version": 0, "area_ids": []}).status_code == 403


def test_coverage_edit_has_version_guard_known_areas_and_retained_audit(api):
    target = team(api, "Editable area profile")
    path = f"/api/admin/teams/{target}/coverage"
    headers = api.headers("admin")
    initial = api.client.get(path, headers=headers).json()
    assert initial["configured"] is False and initial["version"] == 0
    payload = {"expected_version": 0, "area_ids": ["ernakulam", "ernakulam", "ernakulam-aluva"],
               "capabilities": ["water_rescue", "water_rescue"], "note": "Synthetic transport declaration"}
    saved = api.client.put(path, headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["area_ids"] == ["ernakulam", "ernakulam-aluva"]
    assert saved.json()["version"] == 1
    assert saved.json()["capabilities"] == ["water_rescue"]
    assert api.client.put(path, headers=headers, json=payload).status_code == 409
    assert api.client.put(path, headers=headers, json={"expected_version": 1, "area_ids": ["invented-place"]}).status_code == 422
    assert api.client.put(path, headers=headers, json={"expected_version": True}).status_code == 422
    assert api.client.put(path, headers=headers, json={"expected_version": 1, "capabilities": ["invented-skill"]}).status_code == 422
    assert api.client.get(path, headers=headers).json()["version"] == 1
    with api.sessions() as db:
        audit = db.scalar(select(AdminChange).where(AdminChange.target_id == target, AdminChange.action == "operating_coverage"))
        assert '"version": 1' in audit.details


def test_recommendations_remain_preview_until_verified_and_explicit_assignment(api):
    selected = team(api, "Suggested team", areas=["ernakulam"])
    incident = report(api, status="SUBMITTED")
    assert suggestions(api, incident)["can_assign"] is False
    with api.sessions() as db:
        db.get(Incident, incident).status = "VERIFIED"; db.commit()
    assert suggestions(api, incident)["can_assign"] is True
    # A busy-team race remains protected by the existing explicit assignment service.
    with api.sessions() as db:
        db.get(Team, selected).status = "BUSY"; db.commit()
    response = api.client.post("/api/incidents/admin/assign-team", headers=api.headers("admin"),
                               json={"incident_id": incident, "team_id": selected})
    assert response.status_code == 409
    with api.sessions() as db:
        assert db.get(Incident, incident).assigned_team_id is None


def test_invalid_filters_and_missing_records_are_rejected(api):
    incident = report(api)
    headers = api.headers("admin")
    path = f"/api/admin/incidents/{incident}/team-recommendations"
    assert api.client.get(path, headers=headers, params={"team_type": "AI invented"}).status_code == 422
    assert api.client.get(path, headers=headers, params={"capability": "unverified"}).status_code == 422
    assert api.client.get("/api/admin/teams/999999/coverage", headers=headers).status_code == 404
    assert api.client.get("/api/admin/incidents/999999/team-recommendations", headers=headers).status_code == 404
