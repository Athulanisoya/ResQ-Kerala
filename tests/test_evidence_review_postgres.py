"""Competing review decisions use isolated real PostgreSQL transactions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from sqlalchemy import select

from backend.models import Incident
from backend.models.week4_analysis import Week4AnalysisRevision, Week4SuggestionReview
from backend.schemas.week4_schema import Week4ReviewRequest
from backend.services.analysis_review_service import save_review
from test_operations_postgres import pg_ops


def test_competing_decisions_append_exactly_one_review_for_the_same_predecessor(pg_ops):
    with pg_ops.sessions() as db:
        incident = db.get(Incident, pg_ops.incidents[0])
        original = incident.message
        revision = Week4AnalysisRevision(incident_id=incident.id, revision=1,
                                        created_by=pg_ops.users["admin"], result={
                                            "original_text": original,
                                            "results": {"tool_4_create_summary": {"summary": "Synthetic summary"}}})
        db.add(revision)
        db.commit()
        revision_id = revision.id
    start = Barrier(2)

    def decide(value):
        with pg_ops.sessions() as db:
            incident = db.get(Incident, pg_ops.incidents[0])
            start.wait(timeout=10)
            try:
                result = save_review(db, incident, 1, Week4ReviewRequest(
                    suggestion_key="summary", decision="edited", value=value, expected_review_id=0), pg_ops.users["admin"])
                return 201, result
            except HTTPException as error:
                db.rollback()
                return error.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(decide, value) for value in ("First reviewed summary", "Second reviewed summary")]
        outcomes = [future.result(timeout=30) for future in futures]
    assert sorted(status for status, _ in outcomes) == [201, 409]
    with pg_ops.sessions() as db:
        reviews = list(db.scalars(select(Week4SuggestionReview).where(Week4SuggestionReview.revision_id == revision_id)))
        assert len(reviews) == 1
        assert reviews[0].reviewed_value in {"First reviewed summary", "Second reviewed summary"}
        assert reviews[0].previous_review_id == 0
        assert db.get(Incident, pg_ops.incidents[0]).message == original
