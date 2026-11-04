"""HTMX interface for the administrator's advisory analysis revisions."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def web():
    return import_module('web.app')

async def render_history(request, incident_id, error=None, *, status_code=200, review_values=None, notice=None):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    if user.get('role') != 'admin':
        return HTMLResponse('Administrator access required.', status_code=403)
    response = await ui.api_call(request, 'GET', f'/api/incidents/{incident_id}/review-context')
    if response.status_code != 200:
        return ui.render(request, 'partials/week4_result.html', user=user, report={'id': incident_id},
                         revisions=[], reporter=None, evidence={}, suggestions=[], review_values=review_values or {},
                         error=error or ui.error_message(response), status_code=response.status_code)
    return ui.render(request, 'partials/week4_result.html', user=user, **response.json(),
                     review_values=review_values or {}, error=error, notice=notice, status_code=status_code)

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


@router.post('/ui/reports/{incident_id}/week4-analysis/{revision}/review')
async def review(request: Request, incident_id: int, revision: int):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    if user.get('role') != 'admin':
        return HTMLResponse('Administrator access required.', status_code=403)
    form = request.state.form
    values = {key: form.get(key, '') for key in ('suggestion_key', 'value', 'note')}
    try:
        previous = int(form.get('expected_review_id', '0'))
    except (ValueError, TypeError):
        return await render_history(request, incident_id, 'Reload the latest review before saving.',
                                    status_code=422, review_values=values)
    decision = form.get('decision', '')
    response = await ui.api_call(request, 'POST', f'/api/incidents/{incident_id}/week4-analysis/{revision}/reviews',
                                 {**values, 'value': values['value'] if decision == 'edited' else None,
                                  'decision': decision, 'expected_review_id': previous})
    if response.status_code != 201:
        return await render_history(request, incident_id, ui.error_message(response),
                                    status_code=response.status_code, review_values=values)
    if request.headers.get('HX-Request') != 'true':
        return ui.redirect(request, f'/reports/{incident_id}#week4-analysis')
    return await render_history(request, incident_id, notice='Review decision saved with its evidence and revision. The original report is preserved.')
