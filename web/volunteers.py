"""Themed HTMX volunteer applications, review, shifts and private rosters."""
from datetime import datetime, timedelta, timezone
from importlib import import_module
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.services.volunteer_service import catalog

router = APIRouter(include_in_schema=False)


def web():
    return import_module('web.app')


async def participant(request):
    ui = web()
    user = await ui.current_user(request)
    if not user:
        return None, ui.redirect(request, '/login')
    if user['role'] not in ('citizen', 'admin'):
        return None, HTMLResponse('Volunteer applications and rosters are private to citizens and administrators.', status_code=403)
    return user, None


async def view(request, *, tab=None, error=None, notice=None, status_code=200, values=None, shift_id=None):
    ui = web()
    user, denied = await participant(request)
    if denied is not None:
        return denied
    tab = tab or request.query_params.get('tab') or ('application' if user['role'] == 'citizen' else 'shifts')
    allowed = {'application', 'shifts'} if user['role'] == 'citizen' else {'shifts', 'applications', 'roster'}
    if tab not in allowed:
        tab = 'application' if user['role'] == 'citizen' else 'shifts'
    try:
        offset = max(0, int(request.query_params.get('offset', '0')))
    except ValueError:
        offset = 0
    result = {'application': None, 'history': []}
    shifts, applications, roster, shelters = {}, {}, None, []
    if user['role'] == 'citizen':
        response = await ui.api_call(request, 'GET', '/api/volunteers/me')
        if response.status_code == 200:
            result = response.json()
        else:
            error, status_code = error or ui.error_message(response), response.status_code
    path = f'/api/volunteers/shifts?offset={offset}'
    response = await ui.api_call(request, 'GET', path)
    if response.status_code == 200:
        shifts = response.json()
    else:
        error, status_code = error or ui.error_message(response), response.status_code
    if tab == 'applications':
        response = await ui.api_call(request, 'GET', f'/api/volunteers/admin/applications?offset={offset}')
        if response.status_code == 200:
            applications = response.json()
        else:
            error, status_code = error or ui.error_message(response), response.status_code
    if user['role'] == 'admin' and tab == 'shifts':
        response = await ui.api_call(request, 'GET', '/api/shelters')
        if response.status_code == 200:
            shelters = response.json()
        else:
            error, status_code = error or ui.error_message(response), response.status_code
    if tab == 'roster':
        try:
            shift_id = int(shift_id or request.query_params.get('shift_id', ''))
        except (TypeError, ValueError):
            error, status_code = 'Choose a shift to open its private roster.', 422
        else:
            response = await ui.api_call(request, 'GET', f'/api/volunteers/admin/shifts/{shift_id}/roster')
            if response.status_code == 200:
                roster = response.json()
            else:
                error, status_code = error or ui.error_message(response), response.status_code
    response = ui.render(request, 'volunteers.html', user=user, active_nav='volunteers', page_title='Volunteer community',
                         volunteer_tab=tab, application=result['application'], application_history=result['history'],
                         application_values=values if values is not None and tab == 'application' else result['application'] or {},
                         shift_values=values if values is not None and tab == 'shifts' else {},
                         catalog=catalog(), shift_data=shifts, application_data=applications, roster=roster,
                         shelters=shelters, error=error, notice=notice, status_code=status_code)
    if request.method == 'POST' and request.headers.get('HX-Request') == 'true':
        response.headers['HX-Push-Url'] = f'/volunteers?tab={tab}' + (f'&shift_id={shift_id}' if tab == 'roster' and shift_id else '')
        if notice:
            response.headers['HX-Trigger'] = json.dumps({'resq:refresh-updates': True})
    return response


@router.get('/volunteers', response_class=HTMLResponse)
async def index(request: Request):
    return await view(request)


def skills(form, prefix):
    return [key[len(prefix):] for key, value in form.items() if key.startswith(prefix) and value]


def number(form, key, *, optional=False):
    value = form.get(key, '')
    if optional and not value:
        return None
    return int(value)


async def action(request, method, path, payload, *, tab, notice, values=None, shift_id=None):
    ui = web()
    _, denied = await participant(request)
    if denied is not None:
        return denied
    response = await ui.api_call(request, method, path, payload)
    return await view(request, tab=tab, notice=notice if response.status_code in (200, 201) else None,
                      error=ui.error_message(response) if response.status_code not in (200, 201) else None,
                      status_code=200 if response.status_code in (200, 201) else response.status_code,
                      values=None if response.status_code in (200, 201) else values, shift_id=shift_id)


@router.post('/ui/volunteers/application')
async def apply(request: Request):
    form = request.state.form
    values = {key: form.get(key, '') for key in ('district_id', 'locality_id', 'ward', 'availability', 'expected_version')}
    values.update(skills=skills(form, 'skill:'), consent=form.get('consent') == 'true')
    try:
        payload = values | {'expected_version': number(form, 'expected_version')}
    except (ValueError, TypeError):
        return await view(request, tab='application', values=values, error='Reload your current application version before saving.', status_code=422)
    return await action(request, 'PUT', '/api/volunteers/me', payload, tab='application', values=values,
                        notice='Application submitted for review. Future shift signups were released if you revised an existing application.')


@router.post('/ui/volunteers/applications/{application_id}/review')
async def review(request: Request, application_id: int):
    form = request.state.form
    try:
        payload = {'expected_version': number(form, 'expected_version'), 'decision': form.get('decision', ''), 'note': form.get('note', '')}
    except (ValueError, TypeError):
        return await view(request, tab='applications', error='Reload the current application version before reviewing.', status_code=422)
    return await action(request, 'POST', f'/api/volunteers/admin/applications/{application_id}/review', payload,
                        tab='applications', notice='Application review recorded. Account permissions are unchanged.')


def shift_input(form):
    # datetime-local controls are explicitly labelled IST, never machine-local time.
    def timestamp(key):
        value = datetime.fromisoformat(str(form.get(key, '')))
        if value.tzinfo is not None:
            raise ValueError
        return value.replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat()
    return {'title': form.get('title', ''), 'kind': form.get('kind', ''), 'place_id': form.get('place_id', ''),
            'shelter_id': number(form, 'shelter_id', optional=True), 'starts_at': timestamp('starts_at'),
            'ends_at': timestamp('ends_at'), 'slots': number(form, 'slots'),
            'required_skills': skills(form, 'required_skill:'), 'instructions': form.get('instructions', '')}


@router.post('/ui/volunteers/shifts')
async def create(request: Request):
    form = request.state.form
    values = dict(form) | {'required_skills': skills(form, 'required_skill:')}
    try:
        payload = shift_input(form)
    except (ValueError, TypeError):
        return await view(request, tab='shifts', values=values, error='Enter valid shift times in IST, a capacity and an optional shelter.', status_code=422)
    return await action(request, 'POST', '/api/volunteers/shifts', payload, tab='shifts', values=values, notice='Volunteer shift created.')


@router.post('/ui/volunteers/shifts/{shift_id}/update')
async def update(request: Request, shift_id: int):
    form = request.state.form
    try:
        payload = shift_input(form) | {'expected_version': number(form, 'expected_version')}
    except (ValueError, TypeError):
        return await view(request, tab='roster', shift_id=shift_id, error='Enter valid IST shift times and reload the current version.', status_code=422)
    return await action(request, 'PUT', f'/api/volunteers/shifts/{shift_id}', payload, tab='roster', shift_id=shift_id, notice='Volunteer shift updated.')


@router.post('/ui/volunteers/shifts/{shift_id}/cancel')
async def cancel_shift(request: Request, shift_id: int):
    form = request.state.form
    try:
        payload = {'expected_version': number(form, 'expected_version'), 'note': form.get('note', '')}
    except (ValueError, TypeError):
        return await view(request, tab='shifts', error='Reload the current shift version before cancelling.', status_code=422)
    return await action(request, 'POST', f'/api/volunteers/shifts/{shift_id}/cancel', payload, tab='shifts', notice='Shift cancelled. Participants received private notifications and their places were released.')


@router.post('/ui/volunteers/shifts/{shift_id}/signup')
async def signup(request: Request, shift_id: int):
    try:
        payload = {'expected_version': number(request.state.form, 'expected_version')}
    except (ValueError, TypeError):
        return await view(request, tab='shifts', error='Reload the current shift version before joining.', status_code=422)
    return await action(request, 'POST', f'/api/volunteers/shifts/{shift_id}/signup', payload, tab='shifts', notice='You joined the shift. Your confirmed signup is shown below.')


@router.post('/ui/volunteers/signups/{signup_id}/cancel')
async def cancel_signup(request: Request, signup_id: int):
    form = request.state.form
    try:
        payload = {'expected_version': number(form, 'expected_version'), 'note': form.get('note', '')}
    except (ValueError, TypeError):
        return await view(request, tab='shifts', error='Reload your current signup version before cancelling.', status_code=422)
    return await action(request, 'POST', f'/api/volunteers/signups/{signup_id}/cancel', payload, tab='shifts', notice='Your signup was cancelled and its place released.')


@router.post('/ui/volunteers/signups/{signup_id}/attendance')
async def attendance(request: Request, signup_id: int):
    form = request.state.form
    try:
        payload = {'expected_version': number(form, 'expected_version'), 'status': form.get('status', ''), 'note': form.get('note', '')}
        shift_id = number(form, 'shift_id')
    except (ValueError, TypeError):
        return await view(request, tab='shifts', error='Reload the current roster before recording attendance.', status_code=422)
    return await action(request, 'POST', f'/api/volunteers/admin/signups/{signup_id}/attendance', payload,
                        tab='roster', shift_id=shift_id, notice='Attendance recorded in the private signup history.')
