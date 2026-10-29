from tests.test_web import clients, login, post


def test_week4_admin_ui_creates_and_lists_revisions(clients):
    citizen, admin, _ = clients
    login(citizen, 'citizen')
    create = post(citizen, '/ui/reports', message='Water entered a synthetic house and two need rescue.',
                  location='Kochi', people_affected='2', help_required='Rescue')
    assert create.status_code == 200
    path = create.headers['HX-Redirect']
    incident_id = int(path.rsplit('/', 1)[-1])
    login(admin, 'admin')
    detail = admin.get(path, headers={'HX-Request':'true'})
    assert 'id="week4-analysis"' in detail.text
    initial = admin.get(f'/ui/reports/{incident_id}/week4-analysis', headers={'HX-Request':'true'})
    assert initial.status_code == 200 and 'No integrated analysis has been run' in initial.text
    result = post(admin, f'/ui/reports/{incident_id}/week4-analysis')
    assert result.status_code == 200
    assert 'Revision 1' in result.text
    assert 'advisory' in result.text
    forbidden = citizen.get(f'/ui/reports/{incident_id}/week4-analysis', headers={'HX-Request':'true'})
    assert forbidden.status_code == 403
