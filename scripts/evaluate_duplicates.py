"""Measure duplicate suggestions against labelled synthetic English/Malayalam pairs.

This evaluation does not connect to the database, create links or change reports.
The matching vocabulary is bounded and the examples are not field validation.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


DEFAULT_DATASET = Path(__file__).resolve().parents[1] / 'data' / 'evaluation' / 'duplicate_pairs.json'


def _report(values, identity, base_time):
    return SimpleNamespace(id=identity, report_reference=f'SYNTHETIC-{identity}',
                           location=values['location'], message=values['message'],
                           created_at=base_time + timedelta(hours=float(values.get('hours_from_base', 0))),
                           status='SUBMITTED', people_affected=values.get('people_affected'),
                           help_required=values.get('help_required'))


def evaluate(dataset=DEFAULT_DATASET, *, comparator=None):
    from backend.services.duplicate_service import DEFAULT_WINDOW_HOURS
    if comparator is None:
        from backend.services.duplicate_service import compare_reports
        comparator = compare_reports
    dataset = Path(dataset)
    raw = dataset.read_bytes()
    fixture = json.loads(raw)
    base_time = datetime.fromisoformat(fixture['base_time'])
    if base_time.tzinfo is None:
        raise ValueError('The evaluation base time must include a timezone.')
    cases = fixture['cases']
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Provide non-empty cases with unique IDs.')
    counts = dict(true_positives=0, false_positives=0, true_negatives=0, false_negatives=0)
    results = []
    for index, case in enumerate(cases, 1):
        if type(case.get('duplicate')) is not bool:
            raise ValueError(f"Case {case['id']} requires a boolean duplicate label.")
        first = _report(case['first'], index * 2, base_time)
        second = _report(case['second'], index * 2 + 1, base_time)
        match = comparator(first, second)
        expected, suggested = case['duplicate'], match is not None
        outcome = ('true_positives' if suggested else 'false_negatives') if expected else ('false_positives' if suggested else 'true_negatives')
        counts[outcome] += 1
        results.append({'id': case['id'], 'category': case.get('category'), 'expected_duplicate': expected,
                        'suggested_duplicate': suggested, 'outcome': outcome, 'annotation': case.get('reason'),
                        'similarity': match.get('similarity') if match else None,
                        'reasons': match.get('reasons', []) if match else []})
    tp, fp, fn = counts['true_positives'], counts['false_positives'], counts['false_negatives']
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else 0.0
    return {'dataset_id': fixture['dataset_id'], 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
            'evaluated_at': datetime.now(timezone.utc).isoformat(), 'examples': len(results),
            'time_window_hours': DEFAULT_WINDOW_HOURS, 'method': 'gazetteer_aliases+time_window+bilingual_event_concepts',
            'counts': counts, 'precision': round(precision, 6) if precision is not None else None,
            'recall': round(recall, 6) if recall is not None else None, 'f1': round(f1, 6),
            'false_match_ids': [row['id'] for row in results if row['outcome'] == 'false_positives'],
            'missed_duplicate_ids': [row['id'] for row in results if row['outcome'] == 'false_negatives'],
            'limitations': ['Synthetic, hand-labelled examples do not estimate real-world accuracy.',
                           'This matcher uses a finite English/Malayalam event-concept vocabulary, not general semantic embeddings.',
                           'Romanised Malayalam, unlisted synonyms, ambiguous localities and distinct households can produce missed or false suggestions.',
                           'The 72-hour candidate policy can miss repeat reports of longer events. Administrator review remains required.'],
            'cases': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--output', type=Path, help='Optionally write the same JSON to a UTF-8 file.')
    args = parser.parse_args()
    report = evaluate(args.dataset)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # ASCII escaping also works in the default Windows terminal encoding.
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
