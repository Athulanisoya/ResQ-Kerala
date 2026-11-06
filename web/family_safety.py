from importlib import import_module
from fastapi import APIRouter, Request
router = APIRouter(include_in_schema=False)

async def view(request, *, circle_id=None, error=None, notice=None, status_code=200):
    ui = import_module('web.app'); user = await ui.current_user(request)
    if not user: return ui.redirect(request, '/login')
    response = await ui.api_call(request, 'GET', '/api/family-safety/circles')
    data = response.json() if response.status_code == 200 else {'circles': [], 'invitations': []}
    if response.status_code != 200: error, status_code = ui.error_message(response), response.status_code
    selected = None
    try: circle_id = int(circle_id or request.query_params.get('circle_id', '0'))
    except (TypeError, ValueError): circle_id = 0
    if circle_id:
        response = await ui.api_call(request, 'GET', f'/api/family-safety/circles/{circle_id}')
        if response.status_code == 200: selected = response.json()
        else: error, status_code = ui.error_message(response), response.status_code
    shelters = await ui.api_call(request, 'GET', '/api/shelters')
    result = ui.render(request, 'family_safety.html', user=user, active_nav='family', page_title='Family safety',
        family=data, circle=selected, shelters=shelters.json() if shelters.status_code == 200 else [], error=error, notice=notice, status_code=status_code)
    if request.method == 'POST' and request.headers.get('HX-Request') == 'true':
        result.headers['HX-Push-Url'] = '/family-safety' + (f'?circle_id={selected["id"]}' if selected else '')
    return result

@router.get('/family-safety')
async def page(request: Request): return await view(request)

@router.post('/ui/family-safety')
async def action(request: Request):
    ui = import_module('web.app')
    if not await ui.current_user(request): return ui.redirect(request, '/login')
    form = request.state.form
    try:
        operation = form.get('operation'); circle_id = int(form.get('circle_id') or 0); payload, method = {}, 'POST'
        if operation == 'create': path, payload = '/circles', {'name': form.get('name', '')}
        elif operation in ('accept', 'decline'): path = f'/invitations/{int(form["invitation_id"])}/{operation}'
        elif operation == 'invite': path, payload = f'/circles/{circle_id}/invitations', {'email': form.get('email', '')}
        elif operation == 'revoke': path = f'/circles/{circle_id}/invitations/{int(form["invitation_id"])}/revoke'
        elif operation in ('checkin', 'withdraw', 'leave', 'close', 'remove'):
            payload = {'expected_version': int(form.get('expected_version') or 0)}
            path = f'/circles/{circle_id}/' + (f'members/{int(form["member_id"])}/remove' if operation == 'remove' else operation)
            if operation == 'checkin':
                method = 'PUT'; payload.update(status=form.get('status', ''), location=form.get('location') or None,
                    shelter_id=int(form['shelter_id']) if form.get('shelter_id') else None, consent=form.get('consent') == 'true')
        else: raise ValueError
    except (ValueError, TypeError, KeyError):
        return await view(request, error='Reload the current circle and choose a valid action.', status_code=422)
    response = await ui.api_call(request, method, '/api/family-safety'+path, payload)
    if response.status_code not in (200, 201, 202): return await view(request, circle_id=circle_id, error=ui.error_message(response), status_code=response.status_code)
    if operation == 'create': circle_id = response.json()['id']
    elif operation == 'accept': circle_id = response.json()['circle_id']
    elif operation in ('leave', 'close'): circle_id = None
    return await view(request, circle_id=circle_id, notice='Family sharing updated. Only accepted, current members can see shared check-ins.')
