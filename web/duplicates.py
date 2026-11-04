from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
router = APIRouter(include_in_schema=False)

@router.get('/ui/incidents/{incident_id}/possible-duplicates', response_class=HTMLResponse)
async def duplicate_candidates(request: Request, incident_id: int):
    web = import_module('web.app')
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, '/login')
    response = await web.api_call(request, 'GET', f'/api/admin/incidents/{incident_id}/possible-duplicates')
    if response.status_code != 200:
        return HTMLResponse('Unable to load possible duplicates.', status_code=response.status_code)
    original = await web.api_call(request, 'GET', f'/api/incidents/{incident_id}')
    if original.status_code != 200:
        return HTMLResponse('Unable to load the original report.', status_code=original.status_code)
    return web.render(request, 'partials/duplicate_content.html', user=user, report=original.json(), candidates=response.json())


@router.post('/ui/incidents/{incident_id}/duplicate-links', response_class=HTMLResponse)
async def confirm_duplicate(request: Request, incident_id: int):
    web = import_module('web.app')
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, '/login')
    if user['role'] != 'admin':
        return HTMLResponse('Administrator access required.', status_code=403)
    form = request.state.form
    response = await web.api_call(request, 'POST', f'/api/admin/incidents/{incident_id}/duplicate-links',
        {key: form.get(key, '') for key in ('candidate_id', 'source_hash', 'candidate_hash', 'note')})
    if response.status_code == 201:
        return await duplicate_candidates(request, incident_id)
    return HTMLResponse('Unable to confirm the link. Reload the comparison and try again.', status_code=response.status_code)
