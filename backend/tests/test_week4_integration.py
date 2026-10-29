"""Integrated AI workflow: safe fallback, bounded SDK path, and revisions."""
import asyncio
import json
from types import SimpleNamespace
import httpx
from backend.tests.test_relief_shelters import services, api, synthetic_password_hash
from backend.ai.local_language import generate_local_drafts
from backend.ai import week4_orchestrator as workflow


def test_local_language_provisional_and_failure():
    text = 'വെള്ളം കയറി. 2 ആളുകൾ കുടുങ്ങി.'
    settings = SimpleNamespace(ollama_base_url='http://127.0.0.1:11434', ollama_model='synthetic', agent_timeout_seconds=5)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'message': {'content': json.dumps({'translation':'Two people are trapped.', 'summary':'2 people are trapped.'})}}))) as client:
            bad_numbers = await generate_local_drafts(text, settings, client=client)
            assert bad_numbers['translation'] is None
            assert bad_numbers['summary'] == '2 people are trapped.'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'message': {'content': json.dumps({'translation':'2 people are trapped.', 'summary':'2 people are trapped.'})}}))) as client:
            draft = await generate_local_drafts(text, settings, client=client)
            assert draft['translation'] == '2 people are trapped.' and draft['requires_manual_review']
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
            failed = await generate_local_drafts(text, settings, client=client)
            assert failed['translation'] is None and failed['summary'] is None
    asyncio.run(run())


def test_week4_revision_history_and_access(services):
    api = services
    path = f'/api/incidents/{api.incident_id}/week4-analysis'
    assert api.client.post(path + '?use_ai=false', headers=api.headers('citizen')).status_code == 403
    for revision in (1, 2):
        response = api.client.post(path + '?use_ai=false', headers=api.headers('admin'))
        assert response.status_code == 200, response.text
        assert response.json()['revision'] == revision
        assert response.json()['orchestration_mode'] == 'python_sequential'
        assert response.json()['human_review_required'] is True
    history = api.client.get(path, headers=api.headers('admin')).json()
    assert [item['revision'] for item in history] == [2, 1]
    assert api.client.get(path, headers=api.headers('citizen')).status_code == 403


def test_bounded_sdk_records_actual_tool_sequence(services, monkeypatch):
    async def drafts(text, settings):
        return {'translation':None, 'summary':'Provisional draft', 'status':'provisional'}
    async def run(agent, input, context, max_turns, run_config):
        for tool in agent.tools:
            await workflow.invoke_week4_tool(tool, context)
        return SimpleNamespace(final_output='Draft for review')
    monkeypatch.setattr(workflow, 'generate_local_drafts', drafts)
    monkeypatch.setattr(workflow.Runner, 'run', run)
    with services.sessions() as db:
        from backend.models import Incident
        incident = db.get(Incident, services.incident_id)
        result = asyncio.run(workflow.run_week4_workflow(db, incident))
    assert result['orchestration_mode'] == 'sdk_agent'
    assert result['llm_used'] is True and result['generative_summary'] == 'Provisional draft'
    assert len(result['tool_events']) == 7
    assert result['original_text'] == incident.message


def test_incomplete_sdk_sequence_falls_back_without_fabricating_tools(services, monkeypatch):
    async def drafts(text, settings):
        return {'translation':None, 'summary':None, 'status':'unavailable'}
    async def run(agent, input, context, max_turns, run_config):
        return SimpleNamespace(final_output='All done')
    monkeypatch.setattr(workflow, 'generate_local_drafts', drafts)
    monkeypatch.setattr(workflow.Runner, 'run', run)
    with services.sessions() as db:
        from backend.models import Incident
        incident = db.get(Incident, services.incident_id)
        result = asyncio.run(workflow.run_week4_workflow(db, incident))
    assert result['orchestration_mode'] == 'python_sequential'
    assert not result['llm_used'] and result['agent_response'] is None
    assert 'fallback' in result['warning']
    assert len(result['tool_events']) == 7


def test_assembly_marks_failed_tools_incomplete():
    context = workflow.Week4Context(db=None, incident=SimpleNamespace(id=1), original_text='Original', reported_location='Kochi')
    for name in ('tool_1_extract_location', 'tool_2_check_alerts', 'tool_3_predict_severity',
                 'tool_4_create_summary', 'tool_5_retrieve_safety_evidence', 'tool_6_search_shelters'):
        context.results[name] = {'status': 'completed'}
    context.results['tool_3_predict_severity'] = {'status': 'uncertain', 'reason': 'Manual review required'}
    assembled = workflow.assemble_evidence(context)
    assert assembled['status'] == 'incomplete'
    assert 'tool_3_predict_severity' in assembled['missing_tools']
