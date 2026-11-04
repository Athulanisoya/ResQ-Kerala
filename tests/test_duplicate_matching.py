"""Explainable duplicate suggestions, labelled error measurement and manual links."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.incident import Incident
from backend.models.review_assistance import DuplicateLink
from backend.services.duplicate_service import compare_reports
from scripts.evaluate_duplicates import DEFAULT_DATASET, evaluate


def pair(case_id):
    fixture = json.loads(DEFAULT_DATASET.read_text(encoding='utf-8'))
    case = next(case for case in fixture['cases'] if case['id'] == case_id)
    base = datetime.fromisoformat(fixture['base_time'])
    rows = []
    for index, values in enumerate((case['first'], case['second']), 1):
        rows.append(SimpleNamespace(id=index, report_reference=f'SYNTHETIC-{index}',
                                    location=values['location'], message=values['message'],
                                    created_at=base + timedelta(hours=values.get('hours_from_base', 0)),
                                    status='SUBMITTED', people_affected=2, help_required='Rescue'))
    return rows


@pytest.mark.parametrize('case_id', ['P01-english-rewording', 'P02-locality-alias', 'P03-english-malayalam',
                                   'P04-spelling-alias', 'P05-malayalam-repeat', 'P06-forward-72h-boundary',
                                   'P07-backward-72h-boundary', 'P08-multilingual-medical'])
def test_alias_language_and_inclusive_time_window_suggestions_are_explained(case_id):
    first, second = pair(case_id)
    match = compare_reports(first, second)
    assert match is not None, case_id
    assert len(match['reasons']) >= 3
    assert match['time_gap_hours'] <= 72
    assert len(match['source_hash']) == len(match['candidate_hash']) == 64
    assert match['message'] == second.message and match['location'] == second.location
    assert match['method'] == 'gazetteer_aliases+time_window+bilingual_event_concepts'


@pytest.mark.parametrize('case_id', ['N01-different-localities', 'N02-forward-outside-window',
                                   'N03-backward-outside-window', 'N04-english-negation',
                                   'N05-malayalam-negation', 'N06-separate-addresses', 'N07-separate-needs',
                                   'N08-unsupported-different-locations', 'N09-same-place-different-disaster',
                                   'N10-ambiguous-written-alias'])
def test_distinct_places_events_outside_window_and_negation_are_not_suggested(case_id):
    assert compare_reports(*pair(case_id)) is None, case_id


def test_labelled_evaluation_reports_every_observed_miss_and_false_match():
    result = evaluate()
    assert result['examples'] == len(result['cases'])
    assert sum(result['counts'].values()) == result['examples']
    assert result['false_match_ids'] == [row['id'] for row in result['cases'] if row['outcome'] == 'false_positives']
    assert result['missed_duplicate_ids'] == [row['id'] for row in result['cases'] if row['outcome'] == 'false_negatives']
    assert any('not general semantic embeddings' in text for text in result['limitations'])
    assert any('not estimate real-world accuracy' in text or 'do not estimate real-world accuracy' in text for text in result['limitations'])


def test_evaluation_precision_recall_and_failure_ids_are_computed_from_independent_labels(tmp_path):
    cases = []
    for identity, duplicate, predicted in [('TP', True, True), ('FN', True, False), ('FP', False, True), ('TN', False, False)]:
        cases.append({'id': identity, 'duplicate': duplicate,
                      'first': {'location': 'Aluva', 'message': 'Original synthetic report'},
                      'second': {'location': 'Aluva', 'message': 'suggested' if predicted else 'not suggested'}})
    path = tmp_path / 'labels.json'
    path.write_text(json.dumps({'dataset_id': 'independent-evaluator-test', 'base_time': '2026-10-28T06:00:00+00:00', 'cases': cases}), encoding='utf-8')
    result = evaluate(path, comparator=lambda first, second: {'similarity': 1, 'reasons': ['Synthetic classifier result']} if second.message == 'suggested' else None)
    assert result['counts'] == dict(true_positives=1, false_positives=1, true_negatives=1, false_negatives=1)
    assert result['precision'] == result['recall'] == result['f1'] == .5
    assert result['false_match_ids'] == ['FP'] and result['missed_duplicate_ids'] == ['FN']


def seed_reports(api, *, filler=0):
    base = datetime(2026, 10, 28, 6, tzinfo=timezone.utc)
    with api.sessions() as db:
        first = Incident(report_reference='SYNTHETIC-DUP-SOURCE', user_id=api.users['citizen'],
                         message='Children are trapped inside a flooded house. Rescue needed.', location='Chengannur',
                         status='SUBMITTED', people_affected=2, help_required='Rescue', created_at=base)
        second = Incident(report_reference='SYNTHETIC-DUP-CANDIDATE', user_id=api.users['citizen'],
                          message='Children are trapped inside a flooded house. Rescue needed now.', location='Chenganoor',
                          status='UNDER_REVIEW', people_affected=2, help_required='Rescue', created_at=base + timedelta(hours=1))
        db.add_all([first, second])
        db.flush()
        ids = first.id, second.id
        db.add_all([Incident(report_reference=f'SYNTHETIC-UNRELATED-{index}', user_id=api.users['citizen'],
                             message=f'Unrelated synthetic supply request {index}.', location='Kollam',
                             status='SUBMITTED', created_at=base + timedelta(hours=2, seconds=index)) for index in range(filler)])
        db.commit()
    return ids


def snapshots(api, ids):
    with api.sessions() as db:
        return [(row.id, row.message, row.location, row.status, row.user_id, row.team_id, row.updated_at)
                for row in db.scalars(select(Incident).where(Incident.id.in_(ids)).order_by(Incident.id))]


def test_candidate_search_reaches_old_reports_beyond_the_newest_thousand_without_linking_or_mutation(api):
    first, second = seed_reports(api, filler=1005)
    original = snapshots(api, [first, second])
    candidates = api.client.get(f'/api/admin/incidents/{first}/possible-duplicates', headers=api.headers('admin'))
    assert candidates.status_code == 200, candidates.text
    assert [row['id'] for row in candidates.json()] == [second]
    assert candidates.json()[0]['link'] is None
    assert snapshots(api, [first, second]) == original
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DuplicateLink)) == 0


def test_only_an_explicit_admin_confirmation_creates_one_idempotent_bidirectional_link(api):
    first, second = seed_reports(api)
    original = snapshots(api, [first, second])
    candidate = api.client.get(f'/api/admin/incidents/{first}/possible-duplicates', headers=api.headers('admin')).json()[0]
    path = f'/api/admin/incidents/{first}/duplicate-links'
    assert api.client.get(path, headers=api.headers('admin')).json() == []
    payload = {'candidate_id': second, 'source_hash': candidate['source_hash'], 'candidate_hash': candidate['candidate_hash'], 'note': 'Reviewed both originals.'}
    confirmed = api.client.post(path, headers=api.headers('admin'), json=payload)
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()['confirmed_by'] == api.users['admin']
    repeated = api.client.post(path, headers=api.headers('admin'), json=payload)
    assert repeated.status_code in {200, 201} and repeated.json() == confirmed.json()
    reverse = api.client.post(f'/api/admin/incidents/{second}/duplicate-links', headers=api.headers('admin'), json={
        **payload, 'candidate_id': first, 'source_hash': candidate['candidate_hash'], 'candidate_hash': candidate['source_hash'],
    })
    assert reverse.status_code in {200, 201} and reverse.json() == confirmed.json()
    links = api.client.get(f'/api/admin/incidents/{second}/duplicate-links', headers=api.headers('admin')).json()
    assert len(links) == 1 and links[0]['incident_id'] == first
    assert snapshots(api, [first, second]) == original
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DuplicateLink)) == 1
        assert db.scalar(select(func.count()).select_from(Incident)) == 2


def test_stale_comparison_and_self_link_are_rejected_without_a_link(api):
    first, second = seed_reports(api)
    candidate = api.client.get(f'/api/admin/incidents/{first}/possible-duplicates', headers=api.headers('admin')).json()[0]
    path = f'/api/admin/incidents/{first}/duplicate-links'
    payload = {'candidate_id': second, 'source_hash': candidate['source_hash'], 'candidate_hash': candidate['candidate_hash']}
    with api.sessions() as db:
        db.get(Incident, second).message += ' Updated details confirmed.'
        db.commit()
    assert api.client.post(path, headers=api.headers('admin'), json=payload).status_code == 409
    assert api.client.post(path, headers=api.headers('admin'), json={**payload, 'candidate_id': first}).status_code == 422
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(DuplicateLink)) == 0


@pytest.mark.parametrize('role,expected', [(None, 401), ('citizen', 403), ('response_team', 403)])
def test_suggestions_and_manual_links_are_admin_only(api, role, expected):
    first, second = seed_reports(api)
    candidate = api.client.get(f'/api/admin/incidents/{first}/possible-duplicates', headers=api.headers('admin')).json()[0]
    headers = api.headers(role) if role else {}
    root = f'/api/admin/incidents/{first}'
    assert api.client.get(root + '/possible-duplicates', headers=headers).status_code == expected
    assert api.client.get(root + '/duplicate-links', headers=headers).status_code == expected
    assert api.client.post(root + '/duplicate-links', headers=headers, json={
        'candidate_id': second, 'source_hash': candidate['source_hash'], 'candidate_hash': candidate['candidate_hash'],
    }).status_code == expected
