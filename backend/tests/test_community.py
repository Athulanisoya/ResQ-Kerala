"""News and donation workflows with role and isolation checks."""
from backend.tests.test_auth import api, synthetic_password_hash, TEST_PASSWORD
from backend.models.user import Role, User


def test_news_requires_verification_and_only_published_visible(api):
    citizen, admin = api.headers('citizen'), api.headers('admin')
    assert api.client.post('/api/community/news', headers=citizen, json={'title':'Flood update','body':'A bridge has reopened.'}).status_code == 403
    result = api.client.post('/api/community/news', headers=admin, json={'title':'Flood update','body':'A bridge has reopened.','source':'Local authority'})
    assert result.status_code == 201, result.text
    news_id = result.json()['id']
    assert api.client.get('/api/community/news', headers=citizen).json() == []
    assert api.client.post(f'/api/community/news/{news_id}/publish', headers=admin).status_code == 409
    assert api.client.post(f'/api/community/news/{news_id}/verify', headers=admin).json()['status'] == 'VERIFIED'
    assert api.client.post(f'/api/community/news/{news_id}/publish', headers=admin).json()['status'] == 'PUBLISHED'
    assert api.client.get('/api/community/news', headers=citizen).json()[0]['title'] == 'Flood update'
    assert api.client.post(f'/api/community/news/{news_id}/verify', headers=admin).status_code == 409


def test_campaign_pledges_are_private_and_require_admin_receipt(api, synthetic_password_hash):
    citizen, admin = api.headers('citizen'), api.headers('admin')
    assert api.client.post('/api/community/campaigns', headers=citizen, json={'title':'Relief','description':'Relief supplies'}).status_code == 403
    created = api.client.post('/api/community/campaigns', headers=admin, json={'title':'Flood relief','description':'Contribute supplies'})
    assert created.status_code == 201, created.text
    campaign = created.json()['id']
    url = f'/api/community/campaigns/{campaign}/pledges'
    assert api.client.post(url, headers=citizen, json={'kind':'MONEY','description':'Contribution','quantity':'10','unit':'USD','idempotency_key':'synthetic-invalid-key-123'}).status_code == 422
    pledge = api.client.post(url, headers=citizen, json={'kind':'MONEY','description':'Contribution','quantity':'100.00','unit':'INR','idempotency_key':'synthetic-pledge-key-123'})
    assert pledge.status_code == 201, pledge.text
    assert pledge.json()['status'] == 'PENDING'
    pledge_id = pledge.json()['id']
    assert api.client.post(f'/api/community/pledges/{pledge_id}/review', headers=citizen, json={'status':'RECEIVED','note':'Checked'}).status_code == 403
    with api.sessions() as db:
        db.add(User(full_name='Other Citizen',email='other-community@example.com',role=Role.CITIZEN,password_hash=synthetic_password_hash)); db.commit()
    from backend.schemas.auth import LoginRequest
    from backend.services.auth_service import login
    with api.sessions() as db:
        token=login(db, LoginRequest(email='other-community@example.com',password=TEST_PASSWORD)).access_token
    assert api.client.get('/api/community/pledges', headers={'Authorization':'Bearer '+token}).json() == []
    reviewed=api.client.post(f'/api/community/pledges/{pledge_id}/review', headers=admin,json={'status':'RECEIVED','note':'Receipt independently confirmed'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['status'] == 'RECEIVED'
    assert api.client.post(f'/api/community/pledges/{pledge_id}/review', headers=admin,json={'status':'REJECTED','note':'repeat attempt'}).status_code == 409
    assert api.client.post(f'/api/community/campaigns/{campaign}/close', headers=admin).status_code == 200
    assert api.client.post(url, headers=citizen,json={'kind':'SUPPLIES','description':'Water','quantity':'1','unit':'litres','idempotency_key':'synthetic-closed-key-123'}).status_code == 409


def test_pledge_retry_is_idempotent_and_key_cannot_change_data(api):
    admin, citizen = api.headers('admin'), api.headers('citizen')
    campaign = api.client.post('/api/community/campaigns', headers=admin, json={'title':'Local campaign','description':'Synthetic response campaign'}).json()['id']
    path = f'/api/community/campaigns/{campaign}/pledges'
    body = {'kind':'MONEY','description':'Contribution','quantity':'100.00','unit':'INR','idempotency_key':'donation-retry-key-12345'}
    first = api.client.post(path,headers=citizen,json=body)
    retry = api.client.post(path,headers=citizen,json=body)
    assert first.status_code == retry.status_code == 201
    assert first.json()['id'] == retry.json()['id']
    assert api.client.post(path,headers=citizen,json={**body,'quantity':'101'}).status_code == 409
    assert len(api.client.get('/api/community/pledges',headers=citizen).json()) == 1
    assert api.client.post(f'/api/community/campaigns/{campaign}/close', headers=admin).status_code == 200
    assert api.client.post(path,headers=citizen,json=body).json()['id'] == first.json()['id']
