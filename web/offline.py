"""Public offline shell. Authenticated pages and API responses are never cached."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1]


@router.get('/offline-worker.js', include_in_schema=False)
def offline_worker():
    return FileResponse(ROOT / 'frontend/static/offline-worker.js', media_type='application/javascript',
                        headers={'Service-Worker-Allowed': '/', 'Cache-Control': 'no-store'})


@router.get('/offline-report', include_in_schema=False)
def legacy_report():
    return RedirectResponse('/reports/new', status_code=303)


@router.get('/offline/report-form', include_in_schema=False)
def cached_report_form(request: Request):
    from web.app import templates
    return templates.TemplateResponse(request=request, name='offline_report.html',
                                      context={'values': {}, 'csrf_token': ''})
