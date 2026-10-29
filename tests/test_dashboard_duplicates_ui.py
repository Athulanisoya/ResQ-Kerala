from tests.test_operations_ui import operations_clients, submit


def create_report(client, message, location):
    response=submit(client,'/ui/reports',message=message,location=location,people_affected='2',help_required='Rescue')
    assert response.status_code == 200, response.text
    return int(response.headers['HX-Redirect'].rsplit('/',1)[-1])


def test_admin_duplicate_review_is_advisory_and_private(operations_clients):
    citizen, admin = operations_clients['citizen'], operations_clients['admin']
    first=create_report(citizen,'Flood water entered the house and we need rescue.','Kochi')
    second=create_report(citizen,'Flood water entered the house and we need rescue now.','Kochi')
    create_report(citizen,'Flood water entered the house and we need rescue now.','Kollam')
    path=f'/ui/incidents/{first}/possible-duplicates'
    assert citizen.get(path,headers={'HX-Request':'true'}).status_code == 403
    result=admin.get(path,headers={'HX-Request':'true'})
    assert result.status_code == 200 and f'/reports/{second}' in result.text and 'Kollam' not in result.text
    detail=admin.get(f'/reports/{first}',headers={'HX-Request':'true'})
    assert 'No reports are merged automatically' in detail.text
    assert citizen.get(f'/reports/{first}',headers={'HX-Request':'true'}).status_code == 200


def test_citizen_dashboard_resources_and_privacy(operations_clients):
    citizen, admin=operations_clients['citizen'],operations_clients['admin']
    response=citizen.get('/ui/dashboard/community',headers={'HX-Request':'true'})
    assert response.status_code == 200, response.text
    for title in ('Active alerts','Emergency contacts','Available shelters','Safety information','Latest news'):
        assert title in response.text
    assert 'not a proximity ranking' in response.text and 'await review' in response.text
    assert admin.get('/ui/dashboard/community',headers={'HX-Request':'true'}).status_code == 403
    assert '/ui/dashboard/community' in citizen.get('/dashboard',headers={'HX-Request':'true'}).text
