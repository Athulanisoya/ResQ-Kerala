from importlib import import_module
from fastapi import APIRouter, Request
from backend.services.preparedness_service import guidance, REVISION
router = APIRouter(include_in_schema=False)

async def view(request, *, error=None, notice=None, values=None, status_code=200):
    ui = import_module('web.app'); user = await ui.current_user(request)
    if not user: return ui.redirect(request, '/login')
    result = await ui.api_call(request, 'GET', '/api/preparedness/me')
    plan = result.json() if result.status_code == 200 else {}
    if result.status_code != 200: error, status_code = ui.error_message(result), result.status_code
    language = request.query_params.get('lang', (values or plan).get('language', 'en'))
    if language not in ('en', 'ml'): language = 'en'
    return ui.render(request, 'preparedness.html', user=user, active_nav='preparedness', page_title='Household preparedness',
        plan=plan, plan_values=values if values is not None else plan, guidance=guidance(), language=language,
        error=error, notice=notice, status_code=status_code)

@router.get('/preparedness')
async def page(request: Request): return await view(request)

@router.post('/ui/preparedness')
async def save(request: Request):
    ui = import_module('web.app')
    if not await ui.current_user(request): return ui.redirect(request, '/login')
    form = request.state.form
    values = {key: form.get(key, '') for key in ('language', 'nearby_meeting', 'outside_meeting', 'support_plan')}
    values['completed'] = [key[5:] for key, value in form.items() if key.startswith('done:') and value]
    values['contacts'] = [{key: form.get(f'contact_{i}_{key}', '') for key in ('name', 'phone', 'relationship')}
        for i in range(3) if form.get(f'contact_{i}_name') or form.get(f'contact_{i}_phone')]
    values['next_review_on'] = form.get('next_review_on') or None
    values['reviewed'] = form.get('reviewed') == 'true'
    values['guidance_revision'] = form.get('guidance_revision', '')
    try: values['expected_version'] = int(form.get('expected_version', '0'))
    except (TypeError, ValueError): return await view(request, error='Reload the current plan before saving.', status_code=422)
    response = await ui.api_call(request, 'PUT', '/api/preparedness/me', values)
    return await view(request, error=ui.error_message(response) if response.status_code != 200 else None,
        notice='Your private household plan and checklist progress have been saved.' if response.status_code == 200 else None,
        values=values if response.status_code != 200 else None, status_code=response.status_code)
