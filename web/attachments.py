"""HTMX upload and private display of report attachments."""
from importlib import import_module
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def _web():
    return import_module('web.app')

async def attachment_view(request, incident_id, error=None, status_code=200):
    web = _web()
    user = await web.current_user(request)
    if not user:
        return web.redirect(request, '/login')
    result = await web.api_call(request, 'GET', f'/api/incidents/{incident_id}/attachments')
    if result.status_code != 200:
        return HTMLResponse(web.error_message(result), status_code=result.status_code)
    rows = []
    for item in result.json():
        content = await web.api_call(request, 'GET', f'/api/incidents/{incident_id}/attachments/{item["id"]}')
        if content.status_code == 200:
            rows.append(content.json())
    report = await web.api_call(request, 'GET', f'/api/incidents/{incident_id}')
    can_upload = report.status_code == 200 and user['role'] == 'citizen' and report.json().get('user_id') == user['id'] and report.json().get('status') not in {'CLOSED', 'REJECTED', 'CANCELLED'}
    return web.render(request, 'partials/attachment_content.html', user=user, incident_id=incident_id,
                      attachments=rows, can_upload=can_upload, error=error, status_code=status_code)

@router.get('/ui/incidents/{incident_id}/attachments', response_class=HTMLResponse)
async def show(request: Request, incident_id: int):
    return await attachment_view(request, incident_id)

@router.post('/ui/incidents/{incident_id}/attachments')
async def upload(request: Request, incident_id: int):
    web = _web()
    if not await web.current_user(request):
        return web.redirect(request, '/login')
    file = request.state.form.get('file')
    if file is None or not hasattr(file, 'read'):
        return await attachment_view(request, incident_id, 'Choose an image or audio file.', 422)
    content = await file.read(3 * 1024 * 1024 + 1)
    headers = {'Authorization': request.headers.get('Authorization', '')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.api), base_url='http://api.local') as client:
        response = await client.post(f'/api/incidents/{incident_id}/attachments', headers=headers,
                                     files={'file': (file.filename, content, file.content_type or 'application/octet-stream')})
    if response.status_code != 201:
        return await attachment_view(request, incident_id, web.error_message(response), response.status_code)
    return await attachment_view(request, incident_id)
