"""Live availability is isolated from the forms so polling cannot erase drafts."""
import json
import math
from datetime import datetime, timedelta, timezone
from importlib import import_module
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


def web():
    return import_module('web.app')


@router.get('/ui/shelters/live', response_class=HTMLResponse)
async def availability(request: Request, q: str = '', available_only: bool = False,
                       latitude: str = '', longitude: str = ''):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    params = {'q': q[:160], 'available_only': str(available_only).lower()}
    if latitude or longitude:
        params.update(latitude=latitude, longitude=longitude)
    response = await ui.api_call(request, 'GET', '/api/shelters?' + urlencode(params))
    return ui.render(request, 'partials/shelter_results.html', user=user,
        shelters=response.json() if response.status_code == 200 else [],
        live_error=None if response.status_code == 200 else ui.error_message(response),
        refreshed_at=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime('%H:%M:%S'))


async def editor_view(request, shelter_id, *, error=None, notice=None, values=None, status_code=200):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    # History uses the same designated-team authorization as shelter updates.
    permission = await ui.api_call(request, 'GET', f'/api/shelters/{shelter_id}/history')
    if permission.status_code != 200:
        return HTMLResponse(escape(ui.error_message(permission)), status_code=permission.status_code)
    response = await ui.api_call(request, 'GET', f'/api/shelters/{shelter_id}')
    if response.status_code != 200:
        return HTMLResponse(escape(ui.error_message(response)), status_code=response.status_code)
    return ui.render(request, 'partials/shelter_editor.html', user=user, shelter=response.json(),
                     error=error, notice=notice, values=values or {}, conflict=status_code == 409,
                     status_code=status_code)


@router.get('/ui/shelters/{shelter_id}/editor', response_class=HTMLResponse)
async def edit(request: Request, shelter_id: int):
    return await editor_view(request, shelter_id)


@router.post('/ui/shelters/{shelter_id}/capacity', response_class=HTMLResponse)
async def update(request: Request, shelter_id: int):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return ui.redirect(request, '/login')
    form = dict(request.state.form)
    try:
        payload = {name: int(form.get(name, '')) for name in ('capacity', 'occupied', 'expected_version')}
        payload.update(note=str(form.get('note', '')), status=str(form.get('status', 'OPEN')),
                       facilities=str(form.get('facilities', '')).strip() or None)
        for name in ('latitude', 'longitude'):
            value = str(form.get(name, '')).strip()
            payload[name] = float(value) if value else None
            if payload[name] is not None and not math.isfinite(payload[name]):
                raise ValueError('Coordinates must be finite')
    except (TypeError, ValueError):
        return await editor_view(request, shelter_id, error='Enter valid capacity, occupancy and coordinates.',
                                 values=form, status_code=422)
    response = await ui.api_call(request, 'PATCH', f'/api/shelters/{shelter_id}', payload)
    if response.status_code != 200:
        return await editor_view(request, shelter_id, error=ui.error_message(response),
                                 values=form, status_code=response.status_code)
    result = await editor_view(request, shelter_id, notice='Shelter capacity updated. Live availability is refreshing.')
    result.headers['HX-Trigger'] = json.dumps({'resq:shelters-changed': True})
    return result
