"""Dashboard data contracts and real-artifact UI integration."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from lebanon_fuel.dashboard import data
from lebanon_fuel.dashboard import charts
from lebanon_fuel.dashboard.scenarios import simulate
from lebanon_fuel.validation.ledger import ForecastLedger

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/lebanon_fuel/dashboard/app.py"


def test_cached_file_version_tracks_nanosecond_mtime(tmp_path):
    path=tmp_path/'issued_live_forecasts.json'
    path.write_text('{"origin":"first"}')
    before=data.file_version(path)
    stat=path.stat()
    os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000))
    assert data.file_version(path)!=before


def test_readonly_data_and_verified_anchor():
    settings = data.config(ROOT)
    db, _ = data.database_paths(ROOT, settings)
    result = data.market_and_prices(ROOT, db)
    latest, previous = data.anchors(result["prices"])
    assert latest["verification_status"] in data.VERIFIED
    assert latest["source_date"] > previous["source_date"]
    assert result["histories"]["brent_spot"][-1]["unit"] == "USD/bbl"
    assert result["latest_capture"]


def test_volatility_summary_uses_observed_ovx_closes():
    days = pd.bdate_range('2025-11-01', periods=252)
    history = [dict(observation_date=day.date().isoformat(), value=float(i+1),
                    retrieved_at='2026-11-13T12:00:00+00:00', source_url='https://fred.stlouisfed.org/series/OVXCLS')
               for i, day in enumerate(days)]
    result = data.volatility_summary(history)
    assert result['change_5d'] == 5.
    assert result['percentile_252d'] == 100.
    assert result['regime'] == 'Stress'
    assert data.volatility_summary([]) is None


def test_ovx_chart_shows_trailing_year_regime_thresholds():
    days = pd.bdate_range('2025-11-01', periods=252)
    history = [dict(observation_date=day.date().isoformat(), value=float(i + 1), source_url='')
               for i, day in enumerate(days)]
    fig = charts.ovx_history_chart(history)
    assert len(fig.layout.shapes) == 3
    annotations = [item.text for item in fig.layout.annotations]
    assert any('p25 · Low / Normal' in text for text in annotations)
    assert any('p75 · Elevated' in text for text in annotations)
    assert any('p90 · Stress' in text for text in annotations)
    assert fig.layout.font.family == 'Inter, system-ui, sans-serif'


def test_file_version_tracks_atomic_json_replacement(tmp_path):
    path = tmp_path / 'options_chain_latest.json'
    path.write_text('{"version":1}')
    first = data.file_version(path)
    path.write_text('{"version":2}')
    path.touch()
    assert data.file_version(path) != first


def test_production_gate_rejects_replay_and_superseded_issuance():
    settings = {"forecasting": {"enabled": True}, "validation": {"production_approved": True}}
    decision = {"production_approved": True, "selection": {"decision_1": {"production_model": "approved"}}}
    rows = pd.DataFrame([
        dict(id=1, mode="retrospective_research", model_version="approved", approved=1, status="issued", predicted_price=200, actual_price=180),
        dict(id=2, mode="prospective", model_version="approved", approved=1, status="issued", predicted_price=300, actual_price=None),
        dict(id=3, mode="prospective", model_version="approved", approved=1, status="abstained", predicted_price=None, actual_price=None),
    ])
    rows["origin"] = datetime.now(timezone.utc).isoformat()
    rows["created_at"] = rows["origin"]
    assert data.approved_forecasts(rows, settings, decision, "decision_1").empty
    assert data.approved_forecasts(rows.iloc[:2], settings, decision, "decision_1").iloc[0].id == 2
    decision["production_approved"] = False
    assert data.approved_forecasts(rows.iloc[:2], settings, decision, "decision_1").empty


def test_market_refresh_failure_is_surfaced(monkeypatch):
    monkeypatch.setenv("LEBANON_FUEL_WRITER", "local")
    def unavailable(args, **kwargs):
        assert args[-2:] == ["--source", "eia"]
        return subprocess.CompletedProcess(args, 1, "", "Source unavailable")
    monkeypatch.setattr(subprocess, "run", unavailable)
    assert data.refresh_source(ROOT, "eia") == (False, "Source unavailable")


def test_scenario_uses_structural_engine_and_explicit_tax_base():
    template = data.read_json(ROOT / "config/structural_scenario_before_vat.json")
    kwargs = dict(product=110, fx=89700, freight=30, vat_percent=11, charge=300000,
                  now=datetime(2026, 11, 11, tzinfo=timezone.utc))
    a = simulate(template, charge_taxable=True, **kwargs)
    b = simulate(template, charge_taxable=False, brent=100, spread=10, **kwargs)
    assert float(a["price_lbp_20l"]) - float(b["price_lbp_20l"]) == pytest.approx(33000)
    assert a["mode"] == "scenario"
    assert a["uncertainty"]["probability"] is None
    assert template["benchmark"]["low"]


def test_dashboard_views_and_interactions(monkeypatch):
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LEBANON_FUEL_ROOT", str(ROOT))
    monkeypatch.setenv("LEBANON_FUEL_ADMIN_PASSCODE", "test-owner-passcode")
    monkeypatch.setenv("LEBANON_FUEL_ACTIONS_TOKEN", "test-token")
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert app.metric[0].label == "Current recorded price"
    settings = data.config(ROOT)
    db, ledger = data.database_paths(ROOT, settings)
    latest_record = data.market_and_prices(ROOT, db)['prices'][-1]
    saved = data.live_ledger_rows(ledger)
    expected = data.live_forecasts(saved[saved.horizon.eq('decision_1')], settings,
                                   data.read_json(ROOT/settings['validation']['decision_file']),
                                   'decision_1', latest_record)
    if expected.empty:
        assert any('No current absolute-price forecast' in warning.value for warning in app.warning)
        assert next(m for m in app.metric if m.label == 'Predicted price').value == 'Awaiting eligible inputs'
    else:
        row = expected.iloc[0]
        assert next(m for m in app.metric if m.label == 'Predicted price').value == f'{row.predicted_price:,.0f} LBP'
        assert any("Hybrid" in item.value for item in app.info)
    app.radio(key="perspective").set_value("📊 Market & Intelligence").run()
    app.radio(key="view").set_value("Price & forecasts").run()
    for label in data.HORIZONS:
        app.radio(key="price_horizon").set_value(label).run()
        app.checkbox(key="show_replay").set_value(True).run()
        assert not app.exception and app.get("plotly_chart")
    for view in ["Global markets", "Analyst report", "Model performance", "Volatility & options", "Data quality"]:
        perspective = '📊 Market & Intelligence' if view in ('Global markets','Analyst report') else '🔬 Quantitative & Governance'
        app.radio(key="perspective").set_value(perspective).run()
        app.radio(key="view").set_value(view).run()
        assert not app.exception and not app.error
    app.radio(key="view").set_value("Model performance").run()
    assert not app.exception
    assert any(button.label == "Open the backtest chart" for button in app.button)
    assert all(metric.label != "Direction accuracy" for metric in app.metric)
    next(button for button in app.button if button.label == "Open the backtest chart").click().run()
    assert app.radio(key="quant_detail").value == "Backtesting"
    assert not app.exception and app.get("plotly_chart")
    assert all(selector.label != "Model" for selector in app.selectbox)
    app.radio(key="view").set_value("Decision timeline").run()
    assert not app.exception
    assert any(heading.value == "Recorded gasoline price updates" for heading in app.subheader)
    app.radio(key="view").set_value("Volatility & options").run()
    assert {"Latest OVX close", "5-trading-session change", "252-close percentile", "Volatility regime"} <= {m.label for m in app.metric}
    assert app.get("plotly_chart")
    assert any("one-standard-deviation crude-oil move" in item.value for item in app.caption)
    assert any("higher than about" in item.value for item in app.caption)
    assert any("options-chain JSON import is optional" in item.value for item in app.info)
    app.radio(key="view").set_value("Data quality").run()
    app.sidebar.text_input(key="admin_passcode_entered").set_value("test-owner-passcode").run()
    monkeypatch.setattr(data, "refresh_source", lambda root, source: (False, "Source unavailable"))
    next(b for b in app.button if b.label == "Refresh selected source").click().run()
    assert any("refresh cycle reported a failure" in w.value for w in app.warning)
    app.radio(key="perspective").set_value("🚗 Driver Pulse").run()
    app.radio(key="view").set_value("Scenario simulator").run()
    app.radio(key='scenario_calculation_mode').set_value('Illustrative May 2025 cost reconstruction').run()
    next(b for b in app.button if b.label == "Calculate scenario").click().run()
    assert not app.exception
    assert any("Hypothetical price" in m.label for m in app.metric)
    next(r for r in app.radio if r.label == "Refined gasoline input").set_value("Brent plus assumed product spread").run()
    next(b for b in app.button if b.label == "Calculate scenario").click().run()
    assert not app.exception
    assert any("Effective scenario product quote" in c.value for c in app.caption)


def test_public_dashboard_hides_legacy_uncertainty_without_live_evidence(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LEBANON_FUEL_ROOT", str(ROOT))
    anchor = dict(revision_id=7, source_date=datetime.now(data.BEIRUT).date().isoformat(),
                  verification_status='archive_corroborated', price_lbp_20l=2445000,
                  official_effective_date=None)
    spec = dict(tier=2, label='QUANTITATIVE MODEL FORECAST', base_revision_id=7,
                methodology='Fixture', validation_status='unapproved_research',
                uncertainty='Nominal interval', performance={'n': 2, 'mae': 2000,
                'direction_accuracy': 1, 'first_origin': '2026-08-01', 'last_origin': '2026-09-01'},
                critical_missing_inputs=[], attempts=[], future_market_assumption='Fixture',
                percentage_change=-1.68, calibration_n=60)
    now = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    batch = pd.DataFrame([
        dict(id=i, horizon=horizon, mode='prospective_research', status='issued', approved=0,
             predicted_price=2403920, predicted_change=-41080, actual_price=None,
             origin=now, created_at=now, target_json=json.dumps(spec), base_price=2445000,
             interval_low=-63300, interval_high=-18860, probabilities_json='[0.982,0.001,0.017]',
             endpoint=None, scheduled_effective='2026-11-17' if horizon == 'decision_1' else None,
             model_version='fixture-experimental', family='G_hybrid', snapshot_id='fixture')
        for i, horizon in enumerate(data.EXPECTED_HORIZONS, 1)
    ])
    monkeypatch.setattr(data, 'live_ledger_rows', lambda path, *, at: batch)
    monkeypatch.setattr(data, 'market_and_prices', lambda root, path: {
        'prices': [anchor], 'market': {'series': {}}, 'latest_capture': now,
    })
    # Use a distinct snapshot cache key from the real-artifact integration test.
    real_version = data.file_version
    monkeypatch.setattr(data, 'file_version', lambda path: ('low-sample-fixture', real_version(path)))

    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert not any(m.label.endswith('probability') for m in app.metric)
    assert any('Range validation needs 30 matched outcomes' in c.value for c in app.caption)
    assert not any('98.2%' in c.value for c in app.markdown)
    app.radio(key="perspective").set_value("📊 Market & Intelligence").run()
    app.radio(key="view").set_value("Analyst report").run()
    assert not app.exception
    assert any('Directional probabilities are awaiting calibrated live evidence' in item.value for item in app.markdown)
    assert not any('98.2%' in item.value for item in app.markdown)


def test_incomplete_batch_cannot_replace_complete_issuance(tmp_path, monkeypatch):
    from lebanon_fuel.validation import ledger as storage

    path = tmp_path / 'ledger.sqlite'
    at = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    complete = at - timedelta(hours=2)
    partial = at - timedelta(hours=1)
    settings = {'forecasting': {'maximum_forecast_age_hours': 12},
                'collection': {'stale_after_days': 10}}
    anchor = {'source_date': '2026-11-10', 'revision_id': 7,
              'verification_status': 'archive_corroborated'}

    with closing(ForecastLedger(path)) as db:
        db.model('baseline', {'family': 'Z_last_change'})
        db.model('quantitative', {'family': 'G_hybrid'})
        db.model('abstention', {'family': None})

        def issue(run, origin, horizons, model, change, tier):
            monkeypatch.setattr(storage, 'now', lambda: origin.isoformat())
            mode = 'prospective_research'
            snapshot = db.snapshot(origin.isoformat(), mode, {'run': run})
            for horizon in horizons:
                db.issue(run, origin.isoformat(), mode, model, snapshot, horizon,
                         {'base_revision_id': 7, 'tier': tier, 'label': model},
                         2_445_000, prediction=change)

        issue('complete', complete, data.EXPECTED_HORIZONS, 'baseline', -47_000, 4)
        issue('failed', partial, data.EXPECTED_HORIZONS[:3], 'quantitative', -41_080, 2)
        # Same origin with a different run ID cannot fill the failed run's gaps.
        issue('unrelated', partial, data.EXPECTED_HORIZONS[3:], 'quantitative', 0, 2)

        rows = data.live_ledger_rows(path, at=at)
        assert rows.run_id.unique().tolist() == ['complete']
        assert set(rows.horizon) == set(data.EXPECTED_HORIZONS)
        latest = data.live_forecasts(rows[rows.horizon.eq('decision_1')], settings, {},
                                     'decision_1', anchor, at=at)
        assert latest.iloc[0].predicted_price == 2_398_000
        assert data.live_forecasts(latest, settings, {}, 'decision_1', anchor,
                                   at=at + timedelta(hours=12)).empty
        assert data.ledger_rows(path, 'decision_1', 'prospective_research').iloc[0].run_id == 'complete'

        issue('failed', partial, data.EXPECTED_HORIZONS[3:], 'quantitative', 0, 2)
        assert data.live_ledger_rows(path, at=at).run_id.unique().tolist() == ['failed']
        assert data.live_ledger_rows(path, at=complete - timedelta(seconds=1)).empty
        issue('abstained', at, data.EXPECTED_HORIZONS, 'abstention', None, None)
        assert data.live_ledger_rows(path, at=at).empty


def test_independent_forecast_markers_keep_each_target_once():
    from lebanon_fuel.dashboard.charts import history_chart

    prices = [dict(source_date='2026-11-10', price_lbp_20l=2445000,
                   verification_status='archive_corroborated', official_effective_date=None)]
    rows = pd.DataFrame([
        dict(endpoint=None, scheduled_effective='2026-11-13', predicted_price=2398000),
        *[dict(endpoint=f'2026-11-{day}T00:00:00+02:00', scheduled_effective=None,
               predicted_price=2445000) for day in (19, 22, 26)],
    ], index=[0, 0, 0, 0])
    rows = rows.assign(origin='2026-11-12T00:00:00+00:00', base_price=2445000,
                       interval_low=None, interval_high=None, forecast_tier=4,
                       forecast_label='BASELINE FORECAST')
    fig = history_chart(prices, pd.DataFrame(), rows)
    traces = [trace for trace in fig.data if trace.name.startswith('BASELINE FORECAST')]
    assert len(traces) == 2
    assert [list(t.y) for t in traces] == [[2398000], [2445000] * 3]
    assert all(t.mode == 'markers' and t.fill is None and not t.error_y.visible for t in traces)
    assert pd.Timestamp(traces[0].x[0]) == pd.Timestamp('2026-11-13')
    assert all(list(t.x) == sorted(t.x) for t in traces)


def test_single_supported_interval_draws_only_target_whisker():
    from lebanon_fuel.dashboard.charts import history_chart

    from test_dashboard_phase2 import forecast_fixture
    item=forecast_fixture('decision_1')
    item.update(predicted_price=2400000,base_price=2445000,interval_low=-65000,interval_high=-15000)
    rows=pd.DataFrame([item])
    fig = history_chart([], pd.DataFrame(), rows)
    trace = fig.data[-1]
    assert list(trace.y) == [2400000]
    assert list(trace.error_y.array) == [30000]
    assert list(trace.error_y.arrayminus) == [20000]
    assert all(t.fill is None for t in fig.data)


@pytest.mark.parametrize(('tier', 'holdout_n', 'expected'), [
    (2, 2, 'Insufficient sample'), (1, 9, 'Insufficient sample'),
    (2, None, 'Insufficient sample'), (2, 10, 'Available'), (4, 10, 'Not calibrated'),
])
def test_saved_quantitative_probability_and_driver_presentation(tier, holdout_n, expected):
    row = pd.Series(dict(target_json=json.dumps({'tier': tier, 'schedule_estimated': True,
        'calibration_n': 60, 'performance': {'n': holdout_n},
        'driver_contributions': {'commodity_pass_through': -12000,
                                 'lagged_domestic_momentum': -8000, 'baseline_intercept': 1000}}),
        probabilities_json='[0.982,0.001,0.017]', base_price=2445000, predicted_price=2426000,
        predicted_change=-19000, interval_low=-40000, interval_high=2000, scheduled_effective='2026-11-13'))
    result = data.forecast_view(row)
    assert result['probability_status'] == expected
    assert result['probabilities'] == ([.982, .001, .017] if expected == 'Available' else None)
    assert result['bounds'] == ([2405000, 2447000] if tier != 4 else None)
    assert sum(r['LBP / 20 L'] for r in result['drivers']) == -19000
    assert result['usd_equivalent'] == pytest.approx(2426000 / 89500)
    assert result['schedule'] == '13 Nov 2026 (Fri cadence)'


def test_analyst_brief_reports_all_origin_and_common_origin_metrics():
    from lebanon_fuel.dashboard.analyst import brief
    decision = {
        'selection': {
            'decision_1': {
                'family': 'G_hybrid',
                'performance': {'mae': 366.0, 'direction_accuracy': 1.0, 'n': 2, 'distinct_base_decisions': 2},
                'all_origin_performance': {'mae': 18951.0, 'direction_accuracy': 0.75, 'n': 4},
                'reasons': ['Fewer than 20 distinct holdout base decisions; evidence too small for Tier 1'],
            }
        }
    }
    report = brief(None, None, {'series': {}}, None, decision)
    perf_text = report['Historical model performance']
    assert 'all-origin MAE 18,951 LBP / 20 L, direction accuracy 75.0%, n=4' in perf_text
    assert 'common-origin MAE 366 LBP / 20 L, n=2' in perf_text


def test_public_passcode_gate_blocks_unauthenticated_refresh(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LEBANON_FUEL_ROOT", str(ROOT))
    monkeypatch.setenv("LEBANON_FUEL_ADMIN_PASSCODE", "secret-owner-code")
    monkeypatch.setenv("LEBANON_FUEL_ACTIONS_TOKEN", "test-token")
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    next(b for b in app.button if b.key == "overview_refresh").click().run()
    assert any("Public read-only mode" in w.value for w in app.warning)
    app.sidebar.text_input(key="admin_passcode_entered").set_value("secret-owner-code").run()
    assert any("Unlocked · live refresh enabled" in c.value for c in app.sidebar.caption)


def test_cloud_without_token_offers_github_refresh(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LEBANON_FUEL_ROOT", str(ROOT))
    monkeypatch.setenv("LEBANON_FUEL_ADMIN_PASSCODE", "unused-passcode")
    monkeypatch.setenv("LEBANON_FUEL_WRITER", "github_actions")
    monkeypatch.delenv("LEBANON_FUEL_ACTIONS_TOKEN", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert not any(button.key == 'overview_refresh' for button in app.button)
    assert any(button.proto.label == 'Open GitHub refresh' for button in app.get('link_button'))


@pytest.mark.parametrize(('expected', 'entered', 'authorized'), [
    ('', '', False), ('', 'anything', False),
    ('owner-secret', '', False), ('owner-secret', 'wrong', False),
    ('owner-secret', 'owner-secret', True),
])
def test_refresh_authorization_fails_closed_before_starting_workers(expected, entered, authorized):
    import ast
    from types import SimpleNamespace

    tree = ast.parse(APP.read_text())
    names = {'_refresh_authorized', 'start_background_refresh'}
    functions = ast.Module(body=[node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    def unexpected_manager_access():
        pytest.fail('An unauthorized refresh reached the worker manager')
    namespace = {'_configured_passcode': lambda: expected,
                 'st': SimpleNamespace(session_state={'admin_passcode_entered': entered}),
                 '_refresh_manager': unexpected_manager_access}
    exec(compile(functions, str(APP), 'exec'), namespace)
    assert namespace['_refresh_authorized']() is authorized
    if not authorized:
        assert namespace['start_background_refresh'](ROOT) is False


def test_display_currency_and_empirical_cadence_are_explicit():
    values = data.currency_values(2343000, -31800)
    assert values['usd_20l'] == pytest.approx(26.1787709497)
    assert values['lbp_liter'] == 117150
    assert values['usd_liter'] == pytest.approx(1.3089385475)
    assert values['change_usd'] == pytest.approx(-31800 / 89500)
    rows = [dict(source_date=day, verification_status='archive_corroborated', price_lbp_20l=2300000)
            for day in ['2026-11-06', '2026-11-10', '2026-11-11']]
    rows += [dict(rows[-1]), dict(rows[-1], source_date='2026-11-20')]
    context = data.decree_hazard_context(rows, '2026-11-19', '2026-11-20')
    assert context['sample_size'] == 3 and context['tue_fri_share'] == pytest.approx(2/3)
    assert context['projected_date'].isoformat() == '2026-11-20'
    assert data.decree_hazard_context([], '2026-11-19')['tue_fri_share'] is None
    assert data.refresh_poll_seconds(True) == 2
    assert data.refresh_poll_seconds(False) == 60


def test_refresh_fragment_changes_polling_with_the_shared_worker():
    import ast
    import threading
    from types import SimpleNamespace
    tree = ast.parse(APP.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'refresh_status')
    manager = {'lock': threading.Lock(), 'running': False}
    intervals = []
    def fragment(*, run_every):
        intervals.append(run_every)
        return lambda render: lambda *args: None
    scope = {'_refresh_manager': lambda: manager, 'data': data,
             'st': SimpleNamespace(fragment=fragment), '_render_refresh_status': lambda *args: None}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(APP), 'exec'), scope)
    for running in (False, True, False):
        manager['running'] = running
        scope['refresh_status']({})
    assert intervals == [60, 2, 60]


@pytest.mark.parametrize('journal', ['DELETE', 'WAL'])
def test_concurrent_dashboard_reads_wait_for_writer_and_checkpoint(tmp_path, journal):
    import threading
    import time
    from lebanon_fuel.storage.database import Store, sqlite_connection

    with closing(Store(tmp_path)) as store:
        path = tmp_path / 'data/lebanon_fuel.sqlite'
        store.db.execute(f'PRAGMA journal_mode={journal}')
        assert store.db.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
    locked = threading.Event()
    errors = []
    def write():
        try:
            with closing(sqlite_connection(path)) as writer:
                writer.execute('BEGIN EXCLUSIVE')
                writer.execute('UPDATE sources SET priority=priority')
                locked.set()
                time.sleep(.2)
                writer.commit()
                if journal == 'WAL':
                    writer.execute('PRAGMA wal_checkpoint(PASSIVE)')
        except Exception as exc:
            errors.append(exc)
            locked.set()
    worker = threading.Thread(target=write)
    worker.start()
    try:
        assert locked.wait(3)
        with closing(Store(tmp_path, readonly=True)) as reader:
            assert reader.db.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
            assert reader.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0] > 0
            with pytest.raises(Exception, match='readonly'):
                reader.db.execute('UPDATE sources SET priority=priority')
    finally:
        worker.join(3)
    assert not worker.is_alive() and not errors


def test_macro_scenarios_use_exact_inputs_and_keep_missing_data_honest():
    from lebanon_fuel.dashboard.scenarios import macro_preset
    spike = macro_preset('Middle East Geopolitical Spike')
    assert (spike['scenario_brent'],spike['scenario_spread'],spike['scenario_product']) == (95,18,113)
    slump = macro_preset('Global Demand Slump')
    assert slump['scenario_brent'] == 65 and slump['scenario_spread'] == 10
    assert macro_preset('Currency Devaluation Shock',product=100)['scenario_fx'] == 100000
    baseline = macro_preset('Status Quo Baseline',product=102,brent=80)
    assert baseline['scenario_product'] == 102 and baseline['scenario_fx'] == 89500
    with pytest.raises(ValueError,match='stored refined'):
        macro_preset('Status Quo Baseline')


def test_briefing_has_real_price_math_and_no_invented_publication_time():
    from lebanon_fuel.dashboard.experience import briefing
    record=dict(price_lbp_20l=2343000,verification_status='archive_corroborated',source_date='2026-11-17')
    row=dict(predicted_change=-31800,predicted_price=2311200,base_price=2343000,origin='2026-11-19T12:00:00+00:00',
        scheduled_effective='2026-11-20',created_at='2026-11-19T12:00:00+00:00',record_hash='a'*64,
        target_json=json.dumps({'tier':2}),probabilities_json=None,interval_low=None,interval_high=None)
    text=briefing(record,row,data.config(ROOT))
    assert '2,343,000 LBP (~$26.18' in text and '2,311,200 LBP' in text
    assert '−$0.36' in text and 'time unconfirmed' in text and '9:00' not in text
    assert 'WAIT TO REFUEL' not in text and '?forecast='+('a'*64) in text
    assert 'expires' in text and 'production approval withheld' in text


def test_released_conformal_bands_render_and_unreleased_bands_stay_hidden():
    from test_dashboard_phase2 import forecast_fixture
    rows=pd.DataFrame([forecast_fixture('day_7'),forecast_fixture('day_14')])
    f=charts.history_chart([],pd.DataFrame(),rows)
    ribbons=[t for t in f.data if t.fill=='tonexty']
    assert len(ribbons)==2 and all('calibrated pointwise' in t.name for t in ribbons)
    rows['target_json']=json.dumps({'tier':4})
    f=charts.history_chart([],pd.DataFrame(),rows)
    assert not any(t.fill=='tonexty' for t in f.data)
