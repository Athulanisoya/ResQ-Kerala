"""Real PostgreSQL sessions arbitrate concurrent offline replays atomically."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from test_operations_postgres import pg_ops
from backend.models import Incident, IncidentStatusHistory
from backend.models.communication import Notification
from backend.models.incident_summary import IncidentSummary
from backend.models.location_analysis import LocationAnalysis
from backend.models.report_analysis import ReportAnalysis
from backend.services.incident_service import create_incident
from backend.services import incident_service


def run_race(pg, messages, monkeypatch):
    barrier = Barrier(len(messages))
    key = uuid4()
    original_reference = incident_service.generate_report_reference

    def simultaneous_insert(db):
        # All initial lookups have observed "not found" before any insert.
        barrier.wait(timeout=10)
        return original_reference(db)

    monkeypatch.setattr(incident_service, "generate_report_reference", simultaneous_insert)

    def submit(message):
        with pg.sessions() as db:
            barrier.wait(timeout=10)
            try:
                record = create_incident(db, pg.users["citizen"], message, "Aluva", client_submission_id=key)
                return 201, record.id
            except HTTPException as error:
                return error.status_code, None

    with ThreadPoolExecutor(max_workers=len(messages)) as pool:
        results = [pool.submit(submit, message) for message in messages]
        return key, [result.result(timeout=30) for result in results]


def test_concurrent_identical_replays_create_only_one_report_and_side_effect_set(pg_ops, monkeypatch):
    pg = pg_ops
    key, results = run_race(pg, ["Synthetic parallel offline retry"] * 3, monkeypatch)
    assert all(status == 201 for status, _ in results)
    assert len({ident for _, ident in results}) == 1
    report_id = results[0][1]
    with pg.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Incident).where(Incident.client_submission_id == str(key))) == 1
        for model in (IncidentStatusHistory, ReportAnalysis, IncidentSummary, LocationAnalysis):
            assert db.scalar(select(func.count()).select_from(model).where(model.incident_id == report_id)) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.incident_id == report_id)) == 2


def test_concurrent_different_payloads_with_same_key_conflict(pg_ops, monkeypatch):
    key, results = run_race(pg_ops, ["Synthetic offline payload one", "Synthetic offline payload two"], monkeypatch)
    assert sorted(status for status, _ in results) == [201, 409]
    with pg_ops.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Incident).where(Incident.client_submission_id == str(key))) == 1
