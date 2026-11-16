from contextlib import closing
from datetime import datetime, timedelta, timezone
import json

import pytest

from lebanon_fuel.domain import BEIRUT, Observation
from lebanon_fuel.storage.database import Store
from lebanon_fuel.validation import shadow
from lebanon_fuel.validation.decision_events import clock, select_event
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.validation.settlement import settle


def moment(day, hour=0):
    return datetime(2025, 1, day, hour, tzinfo=BEIRUT)


def event(key, day, *, i=1, exact=False):
    return dict(id=i, decision_key=key, verification_status='document_verified',
                publication_timestamp=moment(day).isoformat() if exact else None,
                effective_timestamp=moment(day).isoformat() if exact else None,
                payload_json=json.dumps({'reviewed_clock_dates': {
                    'publication_date': moment(day).date().isoformat(),
                    'effective_date': moment(day).date().isoformat()}}))


def test_date_only_next_decision_requires_proven_order_and_full_coverage():
    target = {'kind': 'decision', 'steps': 1}
    one, two = event('one', 2), event('two', 3, i=2)
    assert select_event([one, two], target, moment(1), moment(3)) == (one, 'matched_verified_outcome')
    assert select_event([one, two], target, moment(2, 11), moment(4))[1] == 'publication_order_unresolved'
    assert select_event([one, two], target, moment(1), moment(2, 11))[1] == 'publication_order_unresolved'
    assert select_event([one, event('other', 2, i=3)], target, moment(1), moment(3))[1] == 'ambiguous_simultaneous_announcements'
    assert clock(None, '2025-03-30').upper > clock(None, '2025-03-30').lower


def test_unrelated_timing_corrections_do_not_block_a_proven_target():
    target = {'kind': 'decision', 'steps': 1}
    old = [event('old', 1), event('old', 2, i=2)]
    next_row = event('target', 5, i=3)
    later = [event('later', 7, i=4), event('later', 8, i=5)]
    assert select_event(old + [next_row] + later, target, moment(4), moment(9))[0] == next_row
    assert select_event(old + [next_row, event('old', 5, i=6)], target, moment(4), moment(9))[0] is None
    same_day = {'kind': 'calendar', 'endpoint': moment(5, 13).isoformat()}
    assert select_event([next_row], same_day, moment(4), moment(9))[0] is None
    day_after = {'kind': 'calendar', 'endpoint': moment(6).isoformat()}
    assert select_event(old + [next_row], day_after, moment(4), moment(9))[0] == next_row


def test_settlement_accepts_reviewed_dates_without_creating_exact_timestamps(tmp_path):
    source_url = 'https://example.org/original-test-fixture.pdf'
    with closing(Store(tmp_path)) as source:
        raw_id = source.capture('official_document', source_url, b'fixture document', 'application/pdf',
                                retrieved_at=moment(3).isoformat())
        capture = source.capture('official_document', source_url, b'fixture transcription', 'text/csv',
                                 retrieved_at=moment(3).isoformat(), metadata={'evidence_capture_id': raw_id})
        source.ingest(capture, [Observation('official_document', '2025-01-02', 1100, source_url,
                                          {'reviewer': 'fixture', 'evidence_locator': 'fixture table'}, '1', document_verified=True,
                                          official_effective_date='2025-01-02', publication_date='2025-01-02')])
        source.reconcile()
        revision = source.ledger()[-1]['revision_id']
        obs = source.db.execute('SELECT id FROM observations').fetchone()[0]
    path = tmp_path / 'review.json'
    evidence = dict(reviewer='fixture', clock_evidence_url=source_url, outcomes=[
        dict(source_observation_id=obs, official_decision_key='fixture-1', price_lbp_20l=1100,
             available_at=datetime.now(timezone.utc).isoformat(), source_revision_id=revision)])
    path.write_text(json.dumps(evidence))
    first = settle(tmp_path, path)
    assert settle(tmp_path, path)['imported_outcome_ids'] == first['imported_outcome_ids']
    with closing(ForecastLedger(tmp_path / 'data/forecast_ledger.sqlite')) as ledger:
        row = ledger.db.execute('SELECT * FROM outcomes').fetchone()
        assert row['publication_timestamp'] is None and row['effective_timestamp'] is None
        assert json.loads(row['payload_json'])['original_captures'][0]['id'] == raw_id
    evidence['outcomes'][0]['source_revision_id'] = 999
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='Source revision'):
        settle(tmp_path, path)


def test_shadow_keeps_abstentions_separate_from_public_and_replays_before_label(tmp_path, monkeypatch):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/project.toml').write_text(
        '[validation]\nforecast_ledger="ledger.sqlite"\n[storage]\ndatabase="prices.sqlite"\n')
    manifest = dict(experiment_id='fixture', bundle_sha256='fixture', frozen_at='2025-01-01T00:00:00Z',
                    protocol=dict(candidates=['A_no_change'], anchor_maximum_age_days=10))
    monkeypatch.setattr(shadow, 'load_manifest', lambda *_args, **_kwargs: manifest)
    at = datetime.now(timezone.utc)
    today = at.astimezone(BEIRUT).date().isoformat()
    known_at = (at - timedelta(minutes=1)).isoformat()
    anchor = dict(source_date=today, verification_status='supplier_observed', price_lbp_20l=1000,
                  revision_id=1, version_known_at=known_at)
    monkeypatch.setattr(shadow, 'current_context', lambda *_: ([anchor], {}))
    with closing(ForecastLedger(tmp_path / 'ledger.sqlite')) as ledger:
        assert ledger.integrity()['forecasts'] == 0
    prospective = shadow.issue(tmp_path, tmp_path / 'unused')
    assert prospective['forecasts'][0]['prediction'] is None
    assert 'lacks official corroboration' in prospective['forecasts'][0]['reasons'][0]
    stats = shadow.report(tmp_path, tmp_path / 'unused')['models']['A_no_change']
    assert stats['attempts'] == 1 and stats['reviewed_metrics']['n'] == 0
    with closing(ForecastLedger(tmp_path / 'ledger.sqlite')) as ledger:
        assert ledger.db.execute('SELECT mode FROM forecasts').fetchone()[0] == shadow.MODE
        assert ledger.integrity()['hash_chain_valid']
    replayed = shadow.replay(tmp_path, tmp_path / 'unused', prospective['forecasts'][0]['target']['origin_beirut'])
    assert replayed['evidence'] == 'strict_replay_not_prospective'
    assert replayed['forecasts'][0]['reasons'] == prospective['forecasts'][0]['reasons']


def test_shadow_replays_captured_inputs_then_scores_the_next_reviewed_decision(tmp_path, monkeypatch):
    from lebanon_fuel.market.store import MarketStore
    from lebanon_fuel.storage import database
    from lebanon_fuel.validation import ledger as ledger_module

    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/project.toml').write_text(
        '[validation]\nforecast_ledger="ledger.sqlite"\n[storage]\ndatabase="prices.sqlite"\n')
    clock_now = [moment(2, 9)]
    monkeypatch.setattr(database, 'now_utc', lambda: clock_now[0].astimezone(timezone.utc).isoformat())
    monkeypatch.setattr(ledger_module, 'now', lambda: clock_now[0].astimezone(timezone.utc).isoformat())
    manifest = dict(experiment_id='fixture', bundle_sha256='fixture', frozen_at=moment(1).isoformat(),
                    protocol=dict(candidates=['A_no_change'], anchor_maximum_age_days=10,
                                  minimum_calibration_decisions=20, maximum_calibration_decisions=60))
    monkeypatch.setattr(shadow, 'load_manifest', lambda *_args, **_kwargs: manifest)

    def observed(key, price):
        date = clock_now[0].date().isoformat()
        url = 'https://example.org/' + key + '.pdf'
        with closing(Store(tmp_path, 'prices.sqlite')) as source:
            capture = source.capture('official_document', url, key.encode(), 'application/pdf')
            source.ingest(capture, [Observation('official_document', date, price, url,
                                                {'reviewer': 'fixture', 'evidence_locator': 'fixture price'},
                                                '1', document_verified=True, official_effective_date=date)])
            source.reconcile()
            return source.ledger()[-1]['revision_id']

    with closing(MarketStore(tmp_path, 'prices.sqlite')):
        pass
    base_revision = observed('base', 1000)
    with closing(ForecastLedger(tmp_path / 'ledger.sqlite')) as ledger:
        ledger.outcome('base', clock_now[0].isoformat(), 1000, 'https://example.org/base.pdf',
                       'document_verified', 'base-hash', {}, moment(2, 8).isoformat(), moment(2, 8).isoformat(), base_revision)
    clock_now[0] = origin = moment(2, 10)
    # This fixture has too few domestic inputs for a market model. Persistence
    # can still use the proven anchor and the same cutoff as the normal path.
    monkeypatch.setattr(shadow, 'strict_feature_frame', lambda *_: (_ for _ in ()).throw(ValueError('Short fixture')))
    snapshot, rows = shadow.forecast_at(tmp_path, manifest, origin)
    assert rows[0]['prediction'] == 0
    with closing(ForecastLedger(tmp_path / 'ledger.sqlite')) as ledger:
        row = rows[0]
        issued = ledger.issue_batch([dict(row, run_id='fixture-run', origin=origin.isoformat(),
                                         horizon='decision_1', mode=shadow.MODE, model_version='fixture',
                                         model_metadata={}, snapshot_payload=snapshot)])
    clock_now[0] = moment(3, 12)
    next_revision = observed('target', 1100)
    with closing(ForecastLedger(tmp_path / 'ledger.sqlite')) as ledger:
        ledger.outcome('target', clock_now[0].isoformat(), 1100, 'https://example.org/target.pdf',
                       'document_verified', 'target-hash', {}, moment(3, 8).isoformat(), moment(3, 8).isoformat(), next_revision)
        assert ledger.match(issued[0][0], dict(certified=True, evidence_url='https://example.org/coverage',
                                               **{'from': moment(2, 8).isoformat()},
                                               through=moment(3, 10).isoformat())) == 'matched_verified_outcome'
    replay = shadow.replay(tmp_path, tmp_path / 'unused', origin.isoformat())
    assert replay['snapshot']['latest_domestic_revision'] == base_revision
    assert replay['forecasts'][0]['base_price'] == 1000
    metric = shadow.report(tmp_path, tmp_path / 'unused')['models']['A_no_change']['reviewed_metrics']
    assert metric['n'] == 1 and metric['mae_lbp'] == 100 and metric['interval_n'] == 0
