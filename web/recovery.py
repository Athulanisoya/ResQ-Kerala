"""Password recovery pages; no reset tokens in URLs sent to server."""
from importlib import import_module
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

def _web():
    return import_module('web.app')

@router.get('/forgot-password', response_class=HTMLResponse)
async def forgot_page(request: Request):
    return _web().render(request, 'recovery.html', mode='request', page_title='Recover password')

@router.get('/reset-password', response_class=HTMLResponse)
async def reset_page(request: Request):
    return _web().render(request, 'recovery.html', mode='reset', page_title='Reset password')

@router.post('/ui/forgot-password')
async def forgot(request: Request):
    web = _web()
    result = await web.api_call(request, 'POST', '/api/auth/recovery/request', {'email': request.state.form.get('email','')})
    if result.status_code != 202:
        return web.render(request, 'recovery.html', mode='request', page_title='Recover password', error=web.error_message(result), status_code=result.status_code)
    return web.render(request, 'recovery.html', mode='requested', page_title='Recovery requested')

@router.post('/ui/reset-password')
async def reset(request: Request):
    web = _web(); form = request.state.form
    if form.get('password') != form.get('confirm'):
        return web.render(request, 'recovery.html', mode='reset', page_title='Reset password', error='Passwords do not match.', status_code=422)
    result = await web.api_call(request, 'POST', '/api/auth/recovery/reset', {'token': form.get('token',''), 'password': form.get('password','')})
    if result.status_code != 200:
        return web.render(request, 'recovery.html', mode='reset', page_title='Reset password', error=web.error_message(result), status_code=result.status_code)
    return web.render(request, 'recovery.html', mode='complete', page_title='Password updated')
