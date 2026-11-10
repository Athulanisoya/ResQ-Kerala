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
    assert 'This saved reply has no recorded evidence checks.' in first.text
    location=first.headers['HX-Push-Url']; session_id=location.split('=')[-1]
    assert 'No live model.' in first.text and f'name="session_id" value="{session_id}"' in first.text
    next_turn=post(citizen,'/ui/assistant/chat',question='More details please',session_id=session_id)
    assert next_turn.status_code == 200 and 'Where can I find shelter?' in next_turn.text and 'More details please' in next_turn.text
    restored=citizen.get(location,headers={'HX-Request':'true'})
    assert restored.status_code == 200 and 'Synthetic answer: More details please' in restored.text
    assert 'Treat it as unverified and ask again for current source records.' in restored.text
    assert admin.get(location,headers={'HX-Request':'true'}).status_code == 404
    assert 'Synthetic answer' not in admin.get('/assistant',headers={'HX-Request':'true'}).text


def test_assistant_shows_retrieval_provenance_and_review_warning(clients, monkeypatch):
    async def answer(db, question, user=None, history=None):
        return {'answer':'Source text','mode':'evidence','model':None,'tool_events':[],
                'warning':'Review this source before relying on it.',
                'evidence_status':'review_required',
                'evidence':[{'kind':'guidance','record_count':1,'status':'review_required',
                             'checked_at':'2026-11-10T05:30:00+00:00'}],
                'sources':[{'title':'Flood guidance','source_name':'Authority','source_url':'https://example.com',
                            'approval_status':'official_source_paraphrase_for_project_review','review_required':True},
                           {'title':'Second source','review_required':True}]}
    monkeypatch.setattr(assistant,'answer_question',answer)
    citizen, _, _ = clients
    login(citizen,'citizen')
    result=post(citizen,'/ui/assistant/chat',question='Flood safety guidance')
    assert result.status_code == 200
    answer_markup, evidence_markup = result.text.split('<details class="chat-sources">', 1)
    evidence_markup = evidence_markup.split('</details>', 1)[0]
    assert '<p>Source text</p>' in answer_markup
    assert 'Review needed' not in answer_markup
    assert 'Review this source before relying on it.' not in answer_markup
    assert '<summary>Sources and evidence</summary>' in evidence_markup
    assert 'Safety reference passages: 1 record' in evidence_markup
    assert '<time datetime="2026-11-10T05:30:00+00:00">' in evidence_markup
    assert 'Review this source before relying on it.' in evidence_markup
    assert evidence_markup.count('require owner verification') == 1
    assert evidence_markup.count('<span>Review needed</span>') == 2
    assert 'official source paraphrase for project review' in evidence_markup
    assert 'href="https://example.com"' in evidence_markup
    assert 'Follow current official guidance' in result.text
