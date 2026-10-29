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
    return web.render(request, 'partials/duplicate_content.html', user=user, candidates=response.json())
