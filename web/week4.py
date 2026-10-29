"""HTMX interface for the administrator's advisory analysis revisions."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def web():
    return import_module('web.app')

async def render_history(request, incident_id, error=None):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    if user.get('role') != 'admin':
        return HTMLResponse('Administrator access required.', status_code=403)
    response = await ui.api_call(request, 'GET', f'/api/incidents/{incident_id}/week4-analysis')
    if response.status_code != 200:
        return ui.render(request, 'partials/week4_result.html', user=user, report={'id': incident_id},
                         revisions=[], error=error or ui.error_message(response))
    return ui.render(request, 'partials/week4_result.html', user=user, report={'id': incident_id},
                     revisions=response.json(), error=error)

@router.get('/ui/reports/{incident_id}/week4-analysis')
async def history(request: Request, incident_id: int):
    return await render_history(request, incident_id)

@router.post('/ui/reports/{incident_id}/week4-analysis')
async def run(request: Request, incident_id: int):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    if user.get('role') != 'admin':
        return HTMLResponse('Administrator access required.', status_code=403)
    # Analysis may use the configured local model; no provider data is sent remotely.
    mode = 'true' if request.state.form.get('use_ai') == 'true' else 'false'
    response = await ui.api_call(request, 'POST', f'/api/incidents/{incident_id}/week4-analysis?use_ai={mode}')
    return await render_history(request, incident_id, None if response.status_code == 200 else ui.error_message(response))
