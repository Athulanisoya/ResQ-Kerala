"""Exercise Week 1 assignment locks on the configured local PostgreSQL database.

Run directly with the project's Python. This script creates synthetic rows,
removes only those rows, and writes a credential-free QA result under .runtime/.
It deliberately avoids pytest fixtures, which select an in-memory SQLite DB.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from threading import Barrier
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
from sqlalchemy import delete, select, text

from backend.database.connection import SessionLocal, engine
from backend.models import Incident, IncidentStatusHistory, Role, Team, User
from backend.services.incident_service import assign_team, create_incident, review_incident


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def compete(assignments):
    start = Barrier(len(assignments), timeout=10)

    def attempt(incident_id, team_id):
        with SessionLocal() as db:
            # Bound failures while retaining real independent transactions.
            db.execute(text("SET LOCAL lock_timeout = '10s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            start.wait()
            try:
                report = assign_team(db, incident_id, team_id)
                return {"code": 200, "incident_id": report.id, "team_id": team_id}
            except HTTPException as error:
                db.rollback()
                return {"code": error.status_code, "incident_id": incident_id, "team_id": team_id}

    with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
        futures = [pool.submit(attempt, *assignment) for assignment in assignments]
        return [future.result(timeout=30) for future in futures]


def statuses(db, report_id):
    return list(db.scalars(select(IncidentStatusHistory.status)
                           .where(IncidentStatusHistory.incident_id == report_id)
                           .order_by(IncidentStatusHistory.id)))


def main():
    require(engine.dialect.name == "postgresql", "This validation requires PostgreSQL.")
    run_id = uuid4().hex
    marker = f"QA assignment concurrency {run_id}"
    report_ids = []
    team_ids = []
    outcome = {"database": "postgresql", "passed": False, "checks": {}, "cleanup": {"complete": False}}
    destination = ROOT / ".runtime" / "qa" / "postgres-concurrency.json"
    try:
        with SessionLocal() as db:
            citizen_id = db.scalar(select(User.id).where(User.role == Role.CITIZEN, User.active.is_(True))
                                   .order_by(User.id).limit(1))
            require(citizen_id is not None, "A local citizen account is required for synthetic QA reports.")
            teams = [Team(name=f"{marker} team {number}", team_type="Rescue") for number in range(3)]
            db.add_all(teams)
            db.commit()
            team_ids.extend(team.id for team in teams)
            for number in range(3):
                report = create_incident(db, citizen_id, f"{marker} report {number}", "Synthetic QA location")
                report_ids.append(report.id)
                review_incident(db, report.id, "VERIFIED", "Synthetic concurrency validation")

        same_team = compete([(report_ids[0], team_ids[0]), (report_ids[1], team_ids[0])])
        require(sorted(item["code"] for item in same_team) == [200, 409],
                "A team must accept exactly one of two concurrent reports.")
        with SessionLocal() as db:
            for result in same_team:
                report = db.get(Incident, result["incident_id"])
                expected = "ASSIGNED" if result["code"] == 200 else "VERIFIED"
                require(report.status == expected, "Same-team report status is inconsistent.")
                require(report.assigned_team_id == (team_ids[0] if result["code"] == 200 else None),
                        "Same-team report assignment is inconsistent.")
                expected_history = ["SUBMITTED", "VERIFIED"] + (["ASSIGNED"] if result["code"] == 200 else [])
                require(statuses(db, report.id) == expected_history, "Same-team history is inconsistent.")
            require(db.get(Team, team_ids[0]).available is False, "Assigned team must be busy.")
        outcome["checks"]["two_reports_one_team"] = {"responses": [200, 409], "consistent": True}

        same_report = compete([(report_ids[2], team_ids[1]), (report_ids[2], team_ids[2])])
        require(sorted(item["code"] for item in same_report) == [200, 409],
                "A report must accept exactly one of two concurrent team assignments.")
        winning_team = next(item["team_id"] for item in same_report if item["code"] == 200)
        losing_team = next(item["team_id"] for item in same_report if item["code"] == 409)
        with SessionLocal() as db:
            report = db.get(Incident, report_ids[2])
            require(report.status == "ASSIGNED" and report.assigned_team_id == winning_team,
                    "Same-report assignment is inconsistent.")
            require(statuses(db, report.id) == ["SUBMITTED", "VERIFIED", "ASSIGNED"],
                    "Concurrent assignment duplicated or lost history.")
            require(db.get(Team, winning_team).available is False, "Winning team must be busy.")
            require(db.get(Team, losing_team).available is True, "Losing team must remain available.")
        outcome["checks"]["one_report_two_teams"] = {"responses": [200, 409], "consistent": True}
        outcome["passed"] = True
    except Exception as error:
        # Never serialize driver diagnostics or configuration/connection strings.
        outcome["error_type"] = type(error).__name__
    finally:
        try:
            with SessionLocal() as db:
                # Match this unpredictable run marker as well as tracked IDs.
                # No existing report, team, account or seed data is modified.
                owned_reports = list(db.scalars(select(Incident.id).where(
                    Incident.message.startswith(marker), Incident.location == "Synthetic QA location")))
                owned_teams = list(db.scalars(select(Team.id).where(Team.name.startswith(marker))))
                require(set(report_ids).issubset(owned_reports), "QA report cleanup ownership check failed.")
                require(set(team_ids).issubset(owned_teams), "QA team cleanup ownership check failed.")
                if owned_reports:
                    db.execute(delete(IncidentStatusHistory).where(IncidentStatusHistory.incident_id.in_(owned_reports)))
                    db.execute(delete(Incident).where(Incident.id.in_(owned_reports)))
                if owned_teams:
                    db.execute(delete(Team).where(Team.id.in_(owned_teams)))
                db.commit()
                require(not list(db.scalars(select(Incident.id).where(Incident.message.startswith(marker)))),
                        "Synthetic reports remain after cleanup.")
                require(not list(db.scalars(select(Team.id).where(Team.name.startswith(marker)))),
                        "Synthetic teams remain after cleanup.")
                outcome["cleanup"] = {"complete": True, "reports_removed": len(owned_reports),
                                      "teams_removed": len(owned_teams)}
        except Exception as error:
            outcome["passed"] = False
            outcome["cleanup"]["error_type"] = type(error).__name__
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(outcome, indent=2))
        engine.dispose()
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
