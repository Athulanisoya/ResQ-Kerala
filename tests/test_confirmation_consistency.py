"""Confirmed location evidence stays consistent across analysis and duplicate review."""
from sqlalchemy import event

from backend.tests.test_auth import api, synthetic_password_hash
from backend.ai.location_extractor import extract_location, list_places
from backend.models import Incident


def seed(api, count=2, location="Paravur"):
    with api.sessions() as db:
        rows = [Incident(report_reference=f"SYNTHETIC-LOCATION-CONSISTENCY-{i}", user_id=api.users["citizen"],
                         message="Children are trapped inside a flooded house. Rescue needed.", location=location,
                         people_affected=2, help_required="Rescue", status="SUBMITTED") for i in range(count)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def confirm(api, report_id, place, locality=None):
    path = f"/api/incidents/{report_id}"
    follow_up = api.client.get(path + "/location-clarification", headers=api.headers("citizen")).json()
    response = api.client.post(path + "/location-confirmations", headers=api.headers("citizen"), json={
        "place_id": place.id, "input_hash": follow_up["input_hash"], "locality": locality})
    assert response.status_code == 201, response.text
    return response.json()


def candidates(api, report_id):
    response = api.client.get(f"/api/admin/incidents/{report_id}/possible-duplicates", headers=api.headers("admin"))
    assert response.status_code == 200, response.text
    return response.json()


def test_integrated_location_tool_uses_the_current_human_confirmation(api):
    report_id = seed(api, 1)[0]
    selected = extract_location("", "Paravur").candidates[0]
    confirm(api, report_id, selected)
    response = api.client.post(f"/api/incidents/{report_id}/week4-analysis?use_ai=false", headers=api.headers("admin"))
    assert response.status_code == 200, response.text
    extraction = response.json()["results"]["tool_1_extract_location"]
    assert extraction["place"]["id"] == selected.id
    assert extraction["source"] == "human_confirmation"
    assert "human confirmation" in extraction["reason"]
    assert response.json()["results"]["tool_2_check_alerts"]["status"] == "NO_MATCH"
    severity = response.json()["results"]["tool_3_predict_severity"]
    assert severity['model_version'].startswith('sha256:')
    assert severity['generated_at'] and severity['requires_manual_review'] is True
    with api.sessions() as db:
        original = db.get(Incident, report_id)
        assert original.location == "Paravur"
        assert original.message == response.json()["original_text"]


def test_same_written_alias_cannot_override_different_confirmed_districts(api):
    first, second = seed(api)
    places = extract_location("", "Paravur").candidates
    selected = places[0]
    other = next(place for place in places if place.district_id != selected.district_id)
    assert candidates(api, first) == []
    confirm(api, first, selected)
    confirm(api, second, selected)
    match = candidates(api, first)[0]
    assert match["id"] == second
    assert "human-confirmed locality" in match["reasons"][0]
    confirm(api, second, other)
    assert candidates(api, first) == []
    stale = api.client.post(f"/api/admin/incidents/{first}/duplicate-links", headers=api.headers("admin"), json={
        "candidate_id": second, "source_hash": match["source_hash"], "candidate_hash": match["candidate_hash"]})
    assert stale.status_code == 409


def test_same_district_does_not_override_different_confirmed_localities(api):
    first, second = seed(api)
    selected = extract_location("", "Paravur").candidates[0]
    other = next(p for p in list_places() if p.kind == "locality" and p.district_id == selected.district_id and p.id != selected.id)
    confirm(api, first, selected)
    confirm(api, second, other)
    assert candidates(api, first) == []


def test_district_only_confirmations_preserve_unverified_locality_text(api):
    first, second = seed(api, location="Unlisted Riverside Junction")
    district = next(p for p in list_places() if p.kind == "district")
    confirm(api, first, district, "Unlisted Riverside Junction")
    confirm(api, second, district, "Another unrelated junction")
    assert candidates(api, first) == []
    confirm(api, second, district, "Unlisted Riverside Junction")
    match = candidates(api, first)[0]
    assert "same unverified locality text" in match["reasons"][0]
    assert "still requires review" in match["reasons"][0]


def test_confirmation_snapshot_change_requires_reloading_even_if_place_is_unchanged(api):
    first, second = seed(api)
    selected = extract_location("", "Paravur").candidates[0]
    for report_id in (first, second):
        confirm(api, report_id, selected)
    original_match = candidates(api, first)[0]
    confirm(api, second, selected)
    current_match = candidates(api, first)[0]
    assert current_match["candidate_hash"] != original_match["candidate_hash"]
    stale = api.client.post(f"/api/admin/incidents/{first}/duplicate-links", headers=api.headers("admin"), json={
        "candidate_id": second, "source_hash": original_match["source_hash"], "candidate_hash": original_match["candidate_hash"]})
    assert stale.status_code == 409
    saved = api.client.post(f"/api/admin/incidents/{first}/duplicate-links", headers=api.headers("admin"), json={
        "candidate_id": second, "source_hash": current_match["source_hash"], "candidate_hash": current_match["candidate_hash"]})
    assert saved.status_code == 201, saved.text


def test_changed_original_inputs_invalidate_the_confirmation_for_all_matching(api):
    first, second = seed(api)
    selected = extract_location("", "Paravur").candidates[0]
    for report_id in (first, second):
        confirm(api, report_id, selected)
    assert candidates(api, first)
    with api.sessions() as db:
        incident = db.get(Incident, second)
        incident.message += " Additional original information changed."
        db.commit()
    assert candidates(api, first) == []
    response = api.client.post(f"/api/incidents/{second}/week4-analysis?use_ai=false", headers=api.headers("admin"))
    assert response.status_code == 200
    extraction = response.json()["results"]["tool_1_extract_location"]
    assert extraction["source"] == "gazetteer" and extraction["status"] == "UNCERTAIN"


def test_candidate_search_batches_confirmation_loading_across_the_time_window(api):
    reports = seed(api, 14, location="Kochi")
    selected = next(p for p in list_places() if p.name == "Kochi" and p.kind == "locality")
    for report_id in reports:
        confirm(api, report_id, selected)
    with api.sessions() as db:
        engine = db.get_bind()
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        if "incident_location_confirmations" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert len(candidates(api, reports[0])) == 13
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) == 1
