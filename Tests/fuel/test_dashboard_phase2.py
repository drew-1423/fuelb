"""Synthetic UI contracts are never treated as market observations or model evidence."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import sqlite3

import pandas as pd
import pytest

from lebanon_fuel.dashboard import experience as ux,charts,data

ROOT=Path(__file__).resolve().parents[2]
APP=ROOT/'src/lebanon_fuel/dashboard/app.py'


def forecast_fixture(horizon='day_7'):
    origin=datetime(2026,11,19,12,tzinfo=timezone.utc)
    days=int(horizon.split('_')[1])
    levels={str(n):dict(status='released',nominal=n/100,calibration_n=60,evaluation_n=25) for n in (80,90)}
    proof=dict(horizon=horizon,artifact='test-artifact',calibration_n=60,evaluation_n=25,
        minimum_calibration_n=30,minimum_evaluation_n=20,radius=50000,radius_80=30000,levels=levels)
    spec=dict(tier=2,family='G_hybrid',artifact_sha256='test-artifact',public_calibration=proof,
              interval_80=[-73000,-13000],base_source_date='2026-11-17')
    return dict(id=days,horizon=horizon,origin=origin.isoformat(),created_at=origin.isoformat(),record_hash='a'*64,
        endpoint=(origin+timedelta(days=days)).isoformat() if horizon.startswith('day_') else None,
        scheduled_effective=(origin+timedelta(days=days)).date().isoformat(),predicted_price=2300000,base_price=2343000,
        predicted_change=-43000,interval_low=-93000,interval_high=7000,forecast_tier=2,forecast_label='QUANTITATIVE MODEL FORECAST',
        probabilities_json=None,target_json=json.dumps(spec),snapshot_id='shared',run_id='run',model_version='test-model')


@pytest.mark.parametrize('slug',list(ux.SLUGS)+['unknown'])
def test_shared_routes_always_have_valid_perspective(slug):
    perspective,view=ux.destination(slug)
    assert view in ux.PERSPECTIVES[perspective]


def test_latest_conflict_or_single_quote_never_replaced_with_older_price():
    at=datetime(2026,11,20,tzinfo=timezone.utc)
    old=dict(source_date='2026-11-17',price_lbp_20l=2343000,verification_status='archive_corroborated')
    for status in ('conflict','supplier_observed'):
        eligible,reason=ux.current_price([old,dict(old,source_date='2026-11-19',verification_status=status)],at=at)
        assert eligible is None
        assert ('one station' if status=='supplier_observed' else 'Sources disagree') in reason
    eligible,_=ux.current_price([old],at=at)
    assert eligible['age_days']==3
    assert ux.current_price([old],at=at+timedelta(days=20))[0] is None


def test_refresh_request_failure_is_not_reported_as_failed_collection():
    message=data.refresh_result_message((False,'Read-only dashboard: owner-triggered refresh needs the LEBANON_FUEL_ACTIONS_TOKEN secret.'))
    assert 'no collection was attempted' in message
    assert 'Scheduled collection continues' in message
    assert 'Collection failed' not in message


def test_unavailable_forecast_does_not_claim_zero_calibration_cases():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string('from lebanon_fuel.dashboard.driver import range_status\nrange_status(None)').run()
    assert not app.exception
    assert any('current eligible forecast' in item.value for item in app.info)
    assert all('0 matched cases' not in item.value for item in app.info)


@pytest.mark.parametrize('mutation',['horizon','artifact','level','sample','reverse','nonfinite','tier'])
def test_uncertainty_requires_exact_release_and_finite_saved_bounds(mutation):
    row=forecast_fixture();spec=json.loads(row['target_json'])
    assert ux.released_bounds(row,80)==(2270000,2330000)
    if mutation=='horizon':spec['public_calibration']['horizon']='decision_1'
    if mutation=='artifact':spec['public_calibration']['artifact']='other'
    if mutation=='level':spec['public_calibration']['levels']['80']['status']='withheld'
    if mutation=='sample':spec['public_calibration']['levels']['80']['evaluation_n']=2
    if mutation=='reverse':spec['interval_80']=[1000,-1000]
    if mutation=='nonfinite':spec['interval_80']=[float('nan'),1]
    if mutation=='tier':spec['tier']=4
    row['target_json']=json.dumps(spec)
    assert ux.released_bounds(row,80) is None


@pytest.mark.parametrize('split',['snapshot','artifact','anchor','missing_horizon','unsupported_endpoint','kind'])
def test_fan_never_bridges_incompatible_or_missing_endpoints(split):
    rows=[forecast_fixture('day_7'),forecast_fixture('day_14')]
    if split=='snapshot':rows[1]['snapshot_id']='other'
    if split=='anchor':rows[1]['base_price']+=1000
    if split=='artifact':
        spec=json.loads(rows[1]['target_json']);spec['artifact_sha256']='other';rows[1]['target_json']=json.dumps(spec)
    if split=='missing_horizon':rows[1]=forecast_fixture('day_30')
    if split=='kind':rows[1]=forecast_fixture('decision_2')
    if split=='unsupported_endpoint':
        middle=forecast_fixture('day_14');middle['target_json']=json.dumps({'tier':4})
        rows=[rows[0],middle,forecast_fixture('day_30')]
    f=charts.history_chart([],pd.DataFrame(),pd.DataFrame(rows))
    assert not any(t.fill=='tonexty' for t in f.data)


def test_ribbon_uses_both_saved_bounds_and_never_zero_width_anchor():
    rows=[forecast_fixture('day_7'),forecast_fixture('day_14')]
    f=charts.history_chart([],pd.DataFrame(),pd.DataFrame(rows))
    bands=[t for t in f.data if t.fill=='tonexty']
    assert len(bands)==2
    assert all(len(t.x)==2 for t in bands)
    assert all('customdata[1]' in t.hovertemplate and 'customdata[2]' in t.hovertemplate for t in bands)
    single=charts.decision_chart(pd.Series(forecast_fixture('decision_1')))
    assert not any(t.fill=='tonexty' for t in single.data)
    assert 'estimated date' in single.layout.xaxis.ticktext[-1]
    assert not any('00:00' in t for t in single.layout.xaxis.ticktext)
    assert any(t.error_y.visible is not False and t.error_y.array is not None for t in single.data)


def test_alerts_are_deduplicated_and_expired_thresholds_do_not_prompt_action():
    row=forecast_fixture('decision_1');health={'checks':{k:{'status':'warning','reasons':[]} for k in ('forecast','domestic_anchor','required_feeds')}}
    records=[dict(source_date='2026-11-17',price_lbp_20l=2343000,verification_status='archive_corroborated',retrieved_at=row['origin'])]
    ops=dict(status='failed',started_at=row['origin'],finished_at=row['created_at'])
    a=ux.alerts(records,row,health,ops,30000);b=ux.alerts(records,dict(row,id=999,origin='2026-11-19T15:00:00+00:00'),health,ops,30000)
    assert {r['id'] for r in a}=={r['id'] for r in b}
    assert len(a)==len({r['id'] for r in a})==2
    health['checks']['forecast']['status']='failed'
    c=ux.alerts(records,row,health,ops,30000)
    assert 'threshold' not in {r['kind'] for r in c} and 'unavailable' in {r['kind'] for r in c}


def test_an_eighty_percent_only_release_is_not_reported_as_no_range():
    from streamlit.testing.v1 import AppTest
    row=forecast_fixture('decision_1');spec=json.loads(row['target_json'])
    spec['public_calibration']['levels']['90']['status']='withheld';spec['public_calibration']['radius']=None
    row['target_json']=json.dumps(spec);row['interval_low']=row['interval_high']=None
    source='from lebanon_fuel.dashboard.driver import range_status\nrange_status('+repr(row)+')'
    app=AppTest.from_string(source).run()
    assert not app.exception and not app.info
    assert any('80% pointwise prediction range' in item.value for item in app.markdown)
    text=ux.briefing(None,row,{'forecasting':{'maximum_forecast_age_hours':12}})
    assert 'No released prediction range' not in text


def test_forecast_link_is_exact_and_accessible_without_current_feeds(monkeypatch):
    from streamlit.testing.v1 import AppTest
    settings=data.config(ROOT);_,path=data.database_paths(ROOT,settings)
    with sqlite3.connect(path) as db:
        h=db.execute("SELECT f.record_hash FROM forecasts f JOIN models m ON m.id=f.model_version WHERE f.status='issued' AND f.mode='prospective_research' AND json_extract(m.metadata_json,'$.family')='G_hybrid' ORDER BY f.id DESC LIMIT 1").fetchone()[0]
    before=ux.saved_forecast(path,h)
    assert before and before['record_hash']==h and 'inputs' in before['snapshot']
    assert ux.saved_forecast(path,'0'*64) is None
    with pytest.raises(ValueError):ux.saved_forecast(path,"' OR 1=1")
    monkeypatch.setenv('LEBANON_FUEL_ROOT',str(ROOT))
    monkeypatch.setattr(data,'market_and_prices',lambda *a:pytest.fail('Immutable forecast page accessed live feeds'))
    app=AppTest.from_file(str(APP),default_timeout=20);app.query_params['forecast']=h;app.run()
    assert not app.exception
    assert next(m for m in app.metric if m.label=='Original predicted price').value==f'{before["predicted_price"]:,.0f} LBP / 20 L'
    if before.get('endpoint'):
        assert any(data.beirut_time(before['endpoint']) in c.value for c in app.caption)
    assert ux.saved_forecast(path,h)['predicted_price']==before['predicted_price']


def test_routes_preserve_tank_and_alert_inputs_and_acknowledge_once(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('LEBANON_FUEL_ROOT',str(ROOT))
    app=AppTest.from_file(str(APP),default_timeout=20);app.query_params['view']='alerts';app.run()
    assert not app.exception and app.radio(key='view').value=='Alerts'
    app.number_input(key='alert_threshold').set_value(10000).run()
    buttons=[b for b in app.button if b.label=='Acknowledge']
    if buttons:
        key=buttons[0].key;buttons[0].click().run()
        assert key not in [b.key for b in app.button]
    app.radio(key='view').set_value('Overview').run()
    if any(n.key=='tank_liters' for n in app.number_input):
        assert app.number_input(key='tank_liters').value == 20
        next(b for b in app.button if b.label == '+20 L').click().run()
        assert app.number_input(key='tank_liters').value == 40
        assert any('For 20 L' in c.value for c in app.caption)
        app.number_input(key='tank_liters').set_value(70)
        next(b for b in app.button if b.label == 'Calculate').click().run()
        assert any('For 70 L' in c.value for c in app.caption)
    app.radio(key='view').set_value('Alerts').run()
    assert app.number_input(key='alert_threshold').value==10000
    app.radio(key='view').set_value('Overview').run()
    if any(n.key=='tank_liters' for n in app.number_input):assert app.number_input(key='tank_liters').value==70
    assert not app.exception


def test_submitted_scenario_survives_multiple_perspective_switches(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('LEBANON_FUEL_ROOT',str(ROOT))
    app=AppTest.from_file(str(APP),default_timeout=20);app.query_params['view']='calculator';app.run()
    app.number_input(key='scenario_freight').set_value(35)
    next(b for b in app.button if b.label=='Calculate scenario').click().run()
    assert not app.exception
    app.radio(key='perspective').set_value('🔬 Quantitative & Governance').run()
    app.radio(key='perspective').set_value('📊 Market & Intelligence').run()
    app.radio(key='perspective').set_value('🚗 Fuel Prices').run()
    app.radio(key='view').set_value('Scenario simulator').run()
    assert not app.exception and app.number_input(key='scenario_freight').value==35
