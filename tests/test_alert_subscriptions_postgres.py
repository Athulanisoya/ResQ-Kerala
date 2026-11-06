"""Independent workers cannot send the same area-alert update twice."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from sqlalchemy import func, select

# This shared fixture selects synthetic SQLite app settings before model imports;
# only its explicit RESQ_TEST_POSTGRES_URL is used for the isolated test schema.
from test_operations_postgres import pg_ops
from backend.models.alert import Alert
from backend.models.alert_subscription import AlertSubscriptionDelivery
from backend.models.communication import Notification
from backend.models.user import User
from backend.services.alert_service import _coverage
from backend.services.alert_subscription_service import process_alert_subscriptions, subscribe


def test_competing_workers_deliver_one_area_update(pg_ops):
    now = datetime.now(timezone.utc)
    with pg_ops.sessions() as db:
        alert = Alert(title="Synthetic concurrent subscription alert", message="Synthetic worker retry check.",
                      level="YELLOW", created_by_id=pg_ops.users["admin"],
                      starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
                      **_coverage("ernakulam-aluva"))
        db.add(alert)
        db.commit()
        alert_id = alert.id
        subscribe(db, db.get(User, pg_ops.users["citizen"]), "ernakulam")
        alert = db.get(Alert, alert_id)
        alert.level = "RED"
        db.commit()
    barrier = Barrier(2)

    def worker():
        with pg_ops.sessions() as db:
            barrier.wait(timeout=10)
            result = process_alert_subscriptions(db)
            db.commit()
            return result["notifications_created"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(worker), pool.submit(worker)]
        assert sum(result.result(timeout=30) for result in results) == 1
    with pg_ops.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Notification)) == 2
        delivery = db.scalar(select(AlertSubscriptionDelivery))
        assert delivery.sequence == 2 and delivery.active
