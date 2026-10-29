from tests.test_web import clients, login, post
from backend.routers import assistant


def test_assistant_history_htmx_roundtrip_and_privacy(clients, monkeypatch):
    async def answer(db, question, user=None, history=None):
        return {'answer':'Synthetic answer: '+question,'mode':'local_fallback','model':None,'sources':[],'tool_events':[],'warning':'No live model.'}
    monkeypatch.setattr(assistant,'answer_question',answer)
    citizen, admin, team = clients
    login(citizen,'citizen'); login(admin,'admin')
    first=post(citizen,'/ui/assistant/chat',question='Where can I find shelter?')
    assert first.status_code == 200, first.text
    assert 'Synthetic answer: Where can I find shelter?' in first.text
    location=first.headers['HX-Push-Url']; session_id=location.split('=')[-1]
    assert 'No live model.' in first.text and f'name="session_id" value="{session_id}"' in first.text
    next_turn=post(citizen,'/ui/assistant/chat',question='More details please',session_id=session_id)
    assert next_turn.status_code == 200 and 'Where can I find shelter?' in next_turn.text and 'More details please' in next_turn.text
    restored=citizen.get(location,headers={'HX-Request':'true'})
    assert restored.status_code == 200 and 'Synthetic answer: More details please' in restored.text
    assert admin.get(location,headers={'HX-Request':'true'}).status_code == 404
    assert 'Synthetic answer' not in admin.get('/assistant',headers={'HX-Request':'true'}).text


def test_assistant_shows_retrieval_provenance_and_review_warning(clients, monkeypatch):
    async def answer(db, question, user=None, history=None):
        return {'answer':'Source text','mode':'local_fallback','model':None,'tool_events':[],'warning':None,
                'sources':[{'title':'Flood guidance','source_name':'Authority','source_url':'https://example.com',
                            'approval_status':'official_source_paraphrase_for_project_review','review_required':True}]}
    monkeypatch.setattr(assistant,'answer_question',answer)
    citizen, _, _ = clients
    login(citizen,'citizen')
    result=post(citizen,'/ui/assistant/chat',question='Flood safety guidance')
    assert result.status_code == 200
    assert 'Owner verification required.' in result.text
    assert 'official source paraphrase for project review' in result.text
    assert 'Follow current official guidance' in result.text
