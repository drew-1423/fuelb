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
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert app.metric[0].label == "Last government-archive price"
    settings = data.config(ROOT)
    db, ledger = data.database_paths(ROOT, settings)
    latest_record = data.market_and_prices(ROOT, db)['prices'][-1]
    saved = data.live_ledger_rows(ledger)
    expected = data.live_forecasts(saved[saved.horizon.eq('decision_1')], settings,
                                   data.read_json(ROOT/settings['validation']['decision_file']),
                                   'decision_1', latest_record)
    if expected.empty:
        assert any('No current absolute-price forecast' in warning.value for warning in app.warning)
        assert not any(m.label == 'Predicted price' for m in app.metric)
    else:
        row = expected.iloc[0]
        assert next(m for m in app.metric if m.label == 'Predicted price').value == f'{row.predicted_price:,.0f}'
        assert any(row.forecast_label in item.value for item in app.info)
    app.radio(key="view").set_value("Price & forecasts").run()
    for label in data.HORIZONS:
        app.radio(key="price_horizon").set_value(label).run()
        app.checkbox(key="show_replay").set_value(True).run()
        assert not app.exception and app.get("plotly_chart")
    for view in ["Global markets", "Analyst report", "Model performance", "Volatility & options", "Data quality"]:
        app.radio(key="view").set_value(view).run()
        assert not app.exception and not app.error
    app.radio(key="view").set_value("Model performance").run()
    assert not app.exception
    assert any(button.label == "Open the backtest chart" for button in app.button)
    assert all(metric.label != "Direction accuracy" for metric in app.metric)
    next(button for button in app.button if button.label == "Open the backtest chart").click().run()
    assert app.radio(key="view").value == "Backtesting"
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
    assert any("Collection failed" in e.value for e in app.error)
    app.radio(key="view").set_value("Scenario simulator").run()
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
    assert any('awaiting validated live outcomes' in c.value for c in app.caption)
    assert next(m for m in app.metric if m.label == '90% prediction interval').value == 'Awaiting live evidence'
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

    rows = pd.DataFrame([
        dict(endpoint=None, scheduled_effective='2026-11-13', origin='2026-11-12T00:00:00+00:00',
             predicted_price=2400000, base_price=2445000, interval_low=-65000, interval_high=-15000,
             forecast_tier=2, forecast_label='QUANTITATIVE MODEL FORECAST'),
    ])
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
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    next(b for b in app.button if b.key == "overview_refresh").click().run()
    assert any("Public read-only mode" in w.value for w in app.warning)
    app.sidebar.text_input(key="admin_passcode_entered").set_value("secret-owner-code").run()
    assert any("Unlocked · live refresh enabled" in c.value for c in app.sidebar.caption)


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
