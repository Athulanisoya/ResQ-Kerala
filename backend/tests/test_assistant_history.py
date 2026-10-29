"""Assistant conversation ownership and context isolation."""
from backend.tests.test_auth import api, synthetic_password_hash, TEST_PASSWORD
from backend.models.user import Role, User
from backend.routers import assistant


def test_private_sessions_and_owned_model_context(api, monkeypatch):
    seen=[]
    async def answer(db, question, user=None, history=None):
        seen.append(history or [])
        mode='local_status' if 'status' in question else 'agent'
        return {'answer':'Answer to '+question,'mode':mode,'model':None,'sources':[],'tool_events':[],'warning':None}
    monkeypatch.setattr(assistant,'answer_question',answer)
    citizen, admin=api.headers('citizen'),api.headers('admin')
    first=api.client.post('/api/assistant/chat',headers=citizen,json={'question':'Show shelter options'})
    assert first.status_code == 200, first.text
    session=first.json()['session_id']
    second=api.client.post('/api/assistant/chat',headers=citizen,json={'question':'Give me more details','session_id':session})
    assert second.status_code == 200 and len(seen[-1]) == 2
    third=api.client.post('/api/assistant/chat',headers=citizen,json={'question':'What is my report status?','session_id':session})
    assert third.status_code == 200
    fourth=api.client.post('/api/assistant/chat',headers=citizen,json={'question':'Tell me more about shelter','session_id':session})
    assert fourth.status_code == 200
    assert all('report status' not in entry['content'] for entry in seen[-1])
    messages=api.client.get(f'/api/assistant/sessions/{session}',headers=citizen).json()['messages']
    assert len(messages) == 8 and messages[-1]['content'] == 'Answer to Tell me more about shelter'
    assert api.client.get(f'/api/assistant/sessions/{session}',headers=admin).status_code == 404
    assert api.client.post('/api/assistant/chat',headers=admin,json={'question':'show private history','session_id':session}).status_code == 404
    assert api.client.get('/api/assistant/sessions',headers=admin).json() == []


def test_unknown_session_cannot_be_used(api, monkeypatch):
    async def never(*args,**kwargs): raise AssertionError('must reject before invoking model')
    monkeypatch.setattr(assistant,'answer_question',never)
    assert api.client.post('/api/assistant/chat',headers=api.headers('citizen'),json={'question':'Hello there','session_id':9999}).status_code == 404
