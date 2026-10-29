"""Citizen dashboard references sourced from the app's current data."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from backend.ai.shelter_agent import _emergency_contacts
from backend.ai.rag_retriever import retrieve

router = APIRouter(include_in_schema=False)

@router.get('/ui/dashboard/community', response_class=HTMLResponse)
async def citizen_dashboard_info(request: Request):
    web = import_module('web.app')
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, '/login')
    if user['role'] != 'citizen':
        return HTMLResponse('Only citizens can access this view.', status_code=403)
    values, failed = {}, []
    for key, path in [('alerts','/api/alerts'), ('news','/api/community/news'), ('shelters','/api/shelters?available_only=true&limit=5')]:
        response = await web.api_call(request, 'GET', path)
        if response.status_code == 200:
            values[key] = response.json()[:5]
        else:
            values[key] = []
            failed.append(key)
    documents = retrieve('flood safety', top_k=2)
    for item in documents:
        if not item.get('source_url', '').startswith(('https://','http://')):
            item['source_url'] = ''
    return web.render(request, 'partials/dashboard_community_content.html', user=user,
                      alerts=values['alerts'], news=values['news'], shelters=values['shelters'],
                      contacts=_emergency_contacts('emergency')['contacts'], safety_documents=documents, failed=failed)
