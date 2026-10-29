"""Verify concurrent retries cannot duplicate donation pledges."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import func, select
from backend.models.user import User
from backend.models.community import DonationCampaign, DonationPledge
from backend.routers.community import PledgeInput, create_pledge
from test_operations_postgres import pg_ops


@pytest.mark.parametrize('general', [False, True])
def test_pledge_retries_are_serialized_per_donor(pg_ops, general):
    with pg_ops.sessions() as db:
        campaign=DonationCampaign(title="Synthetic campaign", description="Testing retries", created_by=pg_ops.users['admin'])
        db.add(campaign); db.commit(); campaign_id=campaign.id
    payload=PledgeInput(kind="SUPPLIES",description="Food",quantity="10",unit="packets",idempotency_key="postgres-donation-key-123")
    gate=Barrier(2)
    def attempt():
        with pg_ops.sessions() as db:
            user=db.get(User, pg_ops.users['citizen'])
            gate.wait(timeout=10)
            return create_pledge(None if general else campaign_id, payload, db, user)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        first,second=pool.submit(attempt),pool.submit(attempt)
        assert first.result(timeout=30) == second.result(timeout=30)
    with pg_ops.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DonationPledge)) == 1
