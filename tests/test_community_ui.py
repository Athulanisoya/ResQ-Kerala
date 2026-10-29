from tests.test_operations_ui import operations_clients, submit


def test_community_htmx_news_campaign_and_pledges(operations_clients):
    citizen, admin = operations_clients['citizen'], operations_clients['admin']
    assert citizen.get('/community',headers={'HX-Request':'true'}).status_code == 200
    created=submit(admin,'/ui/community/news',title='Bridge update',body='The bridge has reopened.',source='District office')
    assert created.status_code == 200
    admin_page=admin.get('/community',headers={'HX-Request':'true'})
    assert 'Bridge update' in admin_page.text and '/verify' in admin_page.text
    assert 'Bridge update' not in citizen.get('/community',headers={'HX-Request':'true'}).text
    assert submit(admin,'/ui/community/news/1/verify').status_code == 200
    assert submit(admin,'/ui/community/news/1/publish').status_code == 200
    assert 'Bridge update' in citizen.get('/community',headers={'HX-Request':'true'}).text
    assert submit(admin,'/ui/community/campaigns',title='Flood support',description='Offer clean water').status_code == 200
    assert submit(citizen,'/ui/community/campaigns/1/pledges',kind='SUPPLIES',description='Drinking water',quantity='5',unit='litres',idempotency_key='synthetic-ui-pledge-key-123').status_code == 200
    page=citizen.get('/community',headers={'HX-Request':'true'})
    assert 'Drinking water' in page.text and 'Pending' in page.text and 'does not collect or process payments' in page.text
    assert submit(admin,'/ui/community/pledges/1/review',status='RECEIVED',note='Delivery verified').status_code == 200
    assert 'Received' in citizen.get('/community',headers={'HX-Request':'true'}).text
