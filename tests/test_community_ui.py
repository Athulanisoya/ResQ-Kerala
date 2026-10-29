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
    action = '/ui/community/campaigns/1/pledges'
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
        result = submit(operations_clients[name], action, **values, kind='MONEY', description=f'{name} support', quantity='100', unit='INR')
        assert result.status_code == 200, result.text
        assert f'{name} support' in operations_clients[name].get('/community', headers={'HX-Request': 'true'}).text


def test_no_campaign_state_explains_next_step_and_admin_creation_is_visible(operations_clients):
    citizen = operations_clients['citizen'].get('/community', headers={'HX-Request': 'true'})
    assert 'An administrator needs to open a campaign' in citizen.text
    assert '/ui/community/campaigns/1/pledges' not in citizen.text
    admin = operations_clients['admin'].get('/community', headers={'HX-Request': 'true'})
    assert 'href="#create-campaign"' in admin.text
    assert '<section id="create-campaign"' in admin.text
    assert '<summary>Create campaign</summary>' not in admin.text
    assert '<button class="button button-primary" type="submit"><span class="button-label">Create campaign</span>' in admin.text
    assert submit(operations_clients['admin'], '/ui/community/campaigns', title='New campaign', description='Support displaced families').status_code == 200
    assert '/ui/community/campaigns/1/pledges' in operations_clients['citizen'].get('/community', headers={'HX-Request': 'true'}).text
