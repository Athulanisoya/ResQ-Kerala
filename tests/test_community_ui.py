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


def test_active_campaign_pledge_actions_are_visible_and_submit_for_each_role(operations_clients):
    from html.parser import HTMLParser
    from tests.test_operations_ui import form

    class PledgeControls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.details_depth = 0
            self.pledge_forms = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'details':
                self.details_depth += 1
            if tag == 'form' and attrs.get('action', '').endswith('/pledges'):
                self.pledge_forms.append((attrs, self.details_depth))
        def handle_endtag(self, tag):
            if tag == 'details':
                self.details_depth -= 1

    admin = operations_clients['admin']
    assert submit(admin, '/ui/community/campaigns', title='Visible flood appeal', description='Support displaced families').status_code == 200
    action = '/ui/community/pledges'
    for name in ('citizen', 'admin', 'rescue'):
        page = operations_clients[name].get('/community', headers={'HX-Request': 'true'})
        controls = PledgeControls()
        controls.feed(page.text)
        assert len(controls.pledge_forms) == 1
        attrs, depth = controls.pledge_forms[0]
        assert depth == 0, 'Donation actions must be visible without expanding a disclosure'
        assert attrs['hx-post'] == action
        assert 'Add donation pledge' in page.text
        body, values = form(page, action)
        assert 'type="submit"' in body and 'Add donation pledge' in body
        assert values['idempotency_key']
        result = submit(operations_clients[name], action, **{**values, 'campaign_id': '1', 'kind': 'MONEY', 'description': f'{name} support', 'quantity': '100', 'unit': 'INR'})
        assert result.status_code == 200, result.text
        assert f'{name} support' in operations_clients[name].get('/community', headers={'HX-Request': 'true'}).text


def test_pledge_form_is_available_without_any_campaign_for_every_role(operations_clients):
    from tests.test_operations_ui import form
    for role in ('citizen', 'admin', 'rescue'):
        client = operations_clients[role]
        response = client.get('/community', headers={'HX-Request': 'true'})
        assert 'href="#add-donation-pledge"' in response.text
        assert 'General relief support' in response.text
        assert '<section id="add-donation-pledge"' in response.text
        body, values = form(response, '/ui/community/pledges')
        assert 'Add donation pledge' in body
        result = submit(client, '/ui/community/pledges', **{**values, 'campaign_id': '', 'kind': 'SUPPLIES', 'description': f'{role} general support', 'quantity': '5', 'unit': 'litres'})
        assert result.status_code == 200, result.text
        assert 'Your donation pledge has been recorded.' in result.text
        assert result.headers.get('HX-Push-Url') == '/community'
        page = client.get('/community', headers={'HX-Request': 'true'})
        assert f'{role} general support' in page.text
        if role == 'admin':
            assert '<section id="create-campaign"' in page.text


def test_pledge_validation_preserves_entered_values_and_retry_key(operations_clients):
    from tests.test_operations_ui import form
    client = operations_clients['citizen']
    page = client.get('/community', headers={'HX-Request': 'true'})
    _, values = form(page, '/ui/community/pledges')
    result = submit(client, '/ui/community/pledges', **{**values, 'campaign_id': '', 'kind': 'SUPPLIES', 'description': 'Drinking water', 'quantity': '0', 'unit': 'litres'})
    assert result.status_code == 422
    assert 'value="Drinking water"' in result.text
    assert 'value="litres"' in result.text
    _, retry_values = form(result, '/ui/community/pledges')
    assert retry_values['idempotency_key'] == values['idempotency_key']


def test_consecutive_pledges_update_visible_records_and_generate_a_new_key(operations_clients):
    from tests.test_operations_ui import form
    client = operations_clients['citizen']
    response = client.get('/community', headers={'HX-Request': 'true'})
    keys = []
    for description in ('First general pledge', 'Second general pledge'):
        _, values = form(response, '/ui/community/pledges')
        keys.append(values['idempotency_key'])
        response = submit(client, '/ui/community/pledges', **{**values,
            'campaign_id': '', 'kind': 'SUPPLIES', 'description': description,
            'quantity': '2', 'unit': 'packets'})
        assert response.status_code == 200
        assert description in response.text
        assert response.headers['HX-Push-Url'] == '/community'
    assert keys[0] != keys[1]
    assert 'First general pledge' in response.text
    assert 'Second general pledge' in response.text
