"""A legacy acceptance must remain operable in the HTMX progress interface."""
from tests.test_operations_ui import operations_clients, assigned_report, form, submit


def test_legacy_accept_renders_next_step_in_htmx(operations_clients):
    clients = operations_clients
    incident_id = assigned_report(clients)
    rescue = clients['rescue']
    response = rescue.post(f'/api/teams/incidents/{incident_id}/accept')
    assert response.status_code == 200, response.text
    page = rescue.get(f'/reports/{incident_id}')
    body, values = form(page, f'/ui/operations/incidents/{incident_id}/progress')
    assert 'Mark en route' in body and values['status'] == 'EN_ROUTE'
    assert submit(rescue, f'/ui/operations/incidents/{incident_id}/progress', **values).status_code == 200
