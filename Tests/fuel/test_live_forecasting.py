"""All synthetic data stays in temporary directories; live data is never changed by fixtures."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import shutil

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge

from lebanon_fuel.forecasting import live
from lebanon_fuel.forecasting.models import Model, preprocess
from lebanon_fuel.forecasting.pipeline import save_bundle
from lebanon_fuel.forecasting.uncertainty import DirectionModel, residual_probabilities
from lebanon_fuel.automation import forecast
from lebanon_fuel.dashboard import data
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.structural.engine import parameters
from lebanon_fuel.domain import BEIRUT

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def context(tmp_path):
    shutil.copytree(ROOT/'config', tmp_path/'config')
    at = datetime.now(timezone.utc)-timedelta(seconds=1)
    records = [dict(source_date=(at-timedelta(days=13-3*i)).date().isoformat(), price_lbp_20l=1000000+i*10000,
                    revision_id=i+1, verification_status='archive_corroborated',
                    version_known_at=(at-timedelta(hours=1)).isoformat()) for i in range(5)]
    histories = {sid:[dict(id=i+1,capture_id=1,value=80+i,unit='USD/bbl',
                         observation_date=(at-timedelta(days=30-i)).date().isoformat(),
                         available_at=(at-timedelta(days=30-i)+timedelta(hours=1)).isoformat()) for i in range(30)]
                 for sid in ['brent_spot','nyh_gasoline']}
    cfg = data.config(tmp_path)
    policy = dict(anchor_maximum_age_days=10, quantitative_candidates=[],structural_requests={})
    decision = dict(production_approved=False, selection={})
    return tmp_path, cfg, policy, decision, records, histories, at


def candidate(context):
    root, cfg, policy, decision, records, histories, at = context
    frame = pd.DataFrame({'x_domestic_change_lag1':[-10000.,0.,10000.,20000.]})
    transform = preprocess(); features = transform.fit_transform(frame)
    model = Model('C_ridge', list(frame), transform, Ridge(alpha=1).fit(features, [-9000.,0.,9000.,18000.]))
    directory = root/'data/models/fixture'
    save_bundle(directory, dict(models={'C_ridge':model}, direction=DirectionModel(np.array([.2,.3,.5]),{'fixture':True}),
                               calibrations={'C_ridge':dict(n=20,radius=10000.,residuals=np.linspace(-20000,20000,20).tolist(),
                                   maximum_label_end=(at-timedelta(days=2)).isoformat())},
                               fit_cutoff=(at-timedelta(days=20)).isoformat()))
    row = dict(horizon='decision_1',valid_through=None,
               path='data/models/fixture',artifact_sha256=sha256((directory/'bundle.joblib').read_bytes()).hexdigest(),
               family='C_ridge', model_version='synthetic-reviewed-v1', regime='fixture',development_mae=1,
               required_market=['brent_spot','nyh_gasoline'],performance=None)
    policy['quantitative_candidates']=[row]
    return row


def approve(context, row):
    root, cfg, policy, decision, records, histories, at = context
    cfg['forecasting']['enabled']=cfg['validation']['production_approved']=True
    records[-1].update(verification_status='document_verified',effective_timestamp=(at-timedelta(days=1)).isoformat())
    decision.update(production_approved=True, decided_at=(at-timedelta(hours=1)).isoformat(),selection={'decision_1':dict(
        production_model=row['model_version'],family='C_ridge',artifact_sha256=row['artifact_sha256'],complete_decision_coverage=True,
        review_evidence='Synthetic unit-test review, never used for the real project',
        calibration=dict(n=20,radius=10000.,residuals=np.linspace(-20000,20000,20).tolist(),maximum_label_end=(at-timedelta(days=2)).isoformat()))})


def issued(context):
    return live.generate(*context)['forecasts'][0]


def test_tier_one_requires_reviewed_artifact_and_returns_saved_uncertainty(context):
    row = candidate(context); approve(context,row)
    result = issued(context)
    assert result['tier']==1 and result['label']=='VALIDATED FORECAST'
    assert result['predicted_change'] > 0
    assert result['interval'][1]-result['interval'][0] == 20000
    assert 0 < min(result['probabilities']) < max(result['probabilities']) < 1
    assert sum(result['probabilities']) == pytest.approx(1.)


def test_tier_two_works_when_production_is_rejected(context):
    candidate(context)
    result = issued(context)
    assert result['tier']==2 and result['label']=='QUANTITATIVE MODEL FORECAST'
    assert result['predicted_price']>context[4][-1]['price_lbp_20l']
    assert result['interval'][1]>result['interval'][0]
    assert sum(result['probabilities']) == pytest.approx(1.)
    assert result['validation_status']=='unapproved_research'


def test_tier_two_accepts_eia_spot_lag_of_eight_to_fourteen_days(context):
    candidate(context)
    root,cfg,policy,decision,records,histories,at=context
    today=at.astimezone(BEIRUT).date()
    for rows in histories.values():
        for i,row in enumerate(rows):
            row['observation_date']=(today-timedelta(days=39-i)).isoformat()
            row['available_at']=(at-timedelta(minutes=10)).isoformat()
    result=issued(context)
    assert result['tier']==2
    assert {row['series'] for row in result['lagged_market_inputs']}=={'brent_spot','nyh_gasoline'}
    assert all(8<=row['age_calendar_days']<=14 for row in result['lagged_market_inputs'])


def test_spot_inputs_older_than_fourteen_days_fall_back_consistently(context):
    candidate(context)
    root,cfg,policy,decision,records,histories,at=context
    today=at.astimezone(BEIRUT).date()
    for rows in histories.values():
        for i,row in enumerate(rows):
            row['observation_date']=(today-timedelta(days=44-i)).isoformat()
            row['available_at']=(at-timedelta(minutes=10)).isoformat()
    forecasts=live.generate(*context)['forecasts']
    assert all(row['tier']==4 for row in forecasts)
    assert {row['predicted_change'] for row in forecasts}=={0.}
    assert all(row['interval'] is None and row['probabilities'] is None for row in forecasts)


def test_tier_two_uses_supported_current_ovx_regime_calibration(context):
    from lebanon_fuel.forecasting.pipeline import load_bundle
    from lebanon_fuel.forecasting.data import midnight

    row=candidate(context)
    root, cfg, policy, decision, records, histories, at=context
    path=root/row['path']
    bundle=load_bundle(path)
    residuals=[-25000.,-10000.,0.,10000.,25000.]*6
    bundle['calibrations_by_ovx_regime']={'C_ridge':{'Stress':dict(n=30,radius=20000.,residuals=residuals,
        maximum_label_end=(at-timedelta(days=2)).isoformat(),status='horizon_conditioned_past_oof_conformal_research',
        requested_ovx_regime='Stress',ovx_regime_conditioning='regime_conditioned_matured_oof')}}
    save_bundle(path,bundle)
    row['artifact_sha256']=sha256((path/'bundle.joblib').read_bytes()).hexdigest()
    row['required_market']=['brent_spot','nyh_gasoline']
    policy['quantitative_candidates']=[row]
    days=pd.bdate_range(end=(at.astimezone(BEIRUT).date()-timedelta(days=1)).isoformat(),periods=300)
    histories['cboe_ovx']=[dict(id=i,capture_id=9,value=30.+i,unit='percent_annualized',
        observation_date=day.date().isoformat(),available_at=f'{day.date().isoformat()}T23:59:59+00:00')
        for i,day in enumerate(days)]
    result=issued(context)
    assert result['tier']==2 and result['ovx_regime']=='Stress'
    assert result['ovx_regime_conditioning']=='regime_conditioned_matured_oof'
    assert result['calibration_ovx_regime']=='Stress'
    assert result['interval']==[result['predicted_change']-20000.,result['predicted_change']+20000.]


def test_tier_three_uses_dated_structural_engine(context):
    root, cfg, policy, decision, records, histories, at = context
    request=json.loads((ROOT/'config/structural_scenario_before_vat.json').read_text())
    day=(at+timedelta(days=2)).date().isoformat()
    request.update(forecast_horizon='decision_1',origin=at.isoformat(),effective_date=day,expires_at=(at+timedelta(hours=6)).isoformat())
    for _,p,_ in parameters(request):
        p.update(valid_from=day,valid_to=day,known_at=(at-timedelta(hours=1)).isoformat())
    (root/'request.json').write_text(json.dumps(request))
    policy['structural_requests']['decision_1']='request.json'
    result=issued(context)
    assert result['tier']==3 and result['label']=='STRUCTURAL ESTIMATE'
    assert result['predicted_price']==float(result['structural_output']['price_lbp_20l'])
    assert result['interval'] is result['probabilities'] is None
    assert result['structural_output']['uncertainty']['probability'] is None


def test_tier_four_future_targets_use_real_anchor_and_no_fake_schedule(context):
    results=live.generate(*context)['forecasts']
    assert len(results)==8 and all(r['tier']==4 for r in results)
    assert results[0]['predicted_price']==1040000
    assert results[0]['predicted_change']==0 and results[0]['endpoint'] is None
    for row in results:
        assert row['percentage_change']==pytest.approx(100*row['predicted_change']/1040000)
        assert row['predicted_change']==0 and row['predicted_price']==1040000
        if row['horizon'].startswith('day_'):
            assert pd.Timestamp(row['endpoint'])>pd.Timestamp(context[-1])
        assert row['probabilities'] is row['interval'] is None


@pytest.mark.parametrize('failure', ['stale','conflict','supplier','future_knowledge','future_date','negative'])
def test_invalid_anchor_never_falls_back_to_older_price(context,failure):
    row=context[4][-1];at=context[-1]
    if failure=='stale':row['source_date']=(at-timedelta(days=20)).date().isoformat()
    if failure=='conflict':row['verification_status']='conflict'
    if failure=='supplier':row['verification_status']='supplier_observed'
    if failure=='future_knowledge':row['version_known_at']=(at+timedelta(days=1)).isoformat()
    if failure=='future_date':row['source_date']=(at.astimezone(BEIRUT)+timedelta(days=1)).date().isoformat()
    if failure=='negative':row['price_lbp_20l']=-1
    result=issued(context)
    assert result['tier'] is None and result['predicted_price'] is None
    assert result['critical_missing_inputs']


@pytest.mark.parametrize('failure',['regime','checksum','stale_market','future_market','missing_feature','invalid_calibration'])
def test_invalid_quantitative_inputs_fall_through_with_reason(context,failure):
    row=candidate(context)
    if failure=='regime':row['valid_through']='2000-01-01'
    if failure=='checksum':row['artifact_sha256']='incorrect'
    if failure=='stale_market':context[5]['brent_spot'][-1]['observation_date']='2000-01-01'
    if failure=='future_market':context[5]['brent_spot'][-1]['available_at']=(context[-1]+timedelta(days=1)).isoformat()
    if failure=='missing_feature':context[4][-2]['verification_status']='conflict'
    if failure=='invalid_calibration':
        approve(context,row)
        context[3]['selection']['decision_1']['calibration']['radius']=-1
    result=issued(context)
    assert result['tier']==4
    assert result['attempts'][0 if failure=='invalid_calibration' else 1]['reasons']


def test_strict_features_exclude_unavailable_and_stale_commodity_history(context):
    root,_,_,_,records,histories,at=context
    before=live.strict_feature_frame(root,records,histories,at,'decision_1')
    histories['brent_spot'].append(dict(histories['brent_spot'][-1],value=999, available_at=(at+timedelta(days=1)).isoformat()))
    after=live.strict_feature_frame(root,records,histories,at,'decision_1')
    assert after.x_brent_spot_value.iloc[0]==before.x_brent_spot_value.iloc[0]


@pytest.mark.parametrize('tier',[1,2,4])
def test_refresh_persists_and_dashboard_reads_each_label(context,monkeypatch,tier):
    root,cfg,policy,decision,records,histories,at=context
    if tier in (1,2):
        row=candidate(context)
        if tier==1:approve(context,row)
    (root/'config/live_forecasting.json').write_text(json.dumps(policy))
    path=root/cfg['validation']['decision_file'];path.parent.mkdir(parents=True)
    path.write_text(json.dumps(decision))
    monkeypatch.setattr(forecast,'now',lambda:at)
    monkeypatch.setattr(forecast,'current_context',lambda *args:(records,histories))
    result=forecast.refresh(root,cfg,'synthetic')
    assert len(result['forecast_ids'])==8
    path=root/cfg['validation']['forecast_ledger']
    with closing(ForecastLedger(path)) as ledger:
        assert ledger.integrity()['hash_chain_valid']
        with pytest.raises(Exception,match='immutable'):
            ledger.db.execute('UPDATE forecasts SET predicted_price=1')
    rows=pd.concat([data.ledger_rows(path,'decision_1',mode) for mode in ('prospective','prospective_research')])
    current=data.live_forecasts(rows,cfg,decision,'decision_1',records[-1],at=at+timedelta(seconds=30))
    assert len(current)==1 and current.iloc[0].forecast_label==live.LABELS[tier]
    assert data.live_forecasts(rows,cfg,decision,'decision_1',dict(records[-1],revision_id=999),at=at+timedelta(seconds=30)).empty
    assert data.live_forecasts(rows,cfg,decision,'decision_1',records[-1],at=at+timedelta(days=1)).empty


def test_tuesday_friday_schedule_is_estimated_and_timezone_aware():
    records=[dict(source_date=d,verification_status='archive_corroborated') for d in ['2026-11-03','2026-11-06','2026-11-10']]
    result=live.estimate_next_decision_date(records,datetime(2026,11,12,21,tzinfo=BEIRUT))
    assert result['dates']==dict(decision_1='2026-11-13',decision_2='2026-11-17',decision_4='2026-11-24')
    assert result['schedule_basis']=='Empirical Tue/Fri Ministry cadence'
    assert result['estimated'] is True and result['interval_n']==2
    with pytest.raises(ValueError):live.estimate_next_decision_date(records,datetime(2026,11,12))
    records.append(dict(source_date='2026-11-11',verification_status='conflict'))
    assert live.estimate_next_decision_date(records,datetime(2026,11,12,tzinfo=BEIRUT))['dates']==result['dates']


def test_dynamic_validity_keeps_2026_models_and_routes_eighth_day_spot_to_tier_two(context):
    candidate(context)
    assert issued(context)['tier']==2
    at=context[-1]
    context[5]['nyh_gasoline'][-1]['observation_date']=(at.astimezone(BEIRUT).date()-timedelta(days=8)).isoformat()
    result=issued(context)
    assert result['tier']==2
    assert any(row['series']=='nyh_gasoline' and row['age_calendar_days']==8
               for row in result['lagged_market_inputs'])
    assert result['market_input_mode']=='strict_captured_vintage'


def test_driver_components_reconcile_to_real_bundles():
    from lebanon_fuel.forecasting.pipeline import load_bundle
    directory=ROOT/'data/models/part5/stabilized_fx_2023_2026/decision_1'
    if not directory.exists():pytest.skip('Trained models unavailable')
    bundle=load_bundle(directory)
    frame=pd.read_csv(ROOT/'data/exports/forecasting/development_design.csv')
    frame=frame[frame.regime.eq('stabilized_fx_2023_2026')&frame.horizon.eq('decision_1')].dropna(subset=['x_structural_delta_lbp_20l','x_domestic_change_lag1']).tail(1)
    for family in ['B_structural_proxy','C_ridge','E_lightgbm','F_catboost','G_hybrid','H_ensemble']:
        result=live.driver_contributions(bundle,family,frame)
        total=sum(result[k] for k in ('commodity_pass_through','lagged_domestic_momentum','fiscal_shock','other_features','baseline_intercept'))
        assert total==pytest.approx(live.model_prediction(bundle,family,frame),abs=.1)


def test_calibration_cannot_use_future_outcomes(context):
    row=candidate(context);approve(context,row)
    context[3]['selection']['decision_1']['calibration']['maximum_label_end']=(context[-1]+timedelta(days=1)).isoformat()
    assert issued(context)['tier']==4


def test_small_calibration_does_not_invent_interval(context):
    row=candidate(context)
    context[3]['selection']['decision_1']=dict(family='C_ridge',artifact_sha256=row['artifact_sha256'],
        calibration=dict(n=6,radius=None,residuals=[-10000,0,1000,5000,2000,-1000]))
    result=issued(context)
    assert result['tier']==2 and result['interval'] is None
    assert sum(result['probabilities'])==pytest.approx(1.)
    assert 'Insufficient' in result['uncertainty']


def test_live_historical_windows_use_captured_vintage_without_release_penalty(context):
    root,_,_,_,records,histories,at=context
    for history in histories.values():
        for row in history:row['available_at']=(at-timedelta(minutes=10)).isoformat()
    frame=live.strict_feature_frame(root,records,histories,at,'decision_1')
    assert np.isfinite(frame.x_structural_delta_lbp_20l.iloc[0])
    assert frame.x_nyh_gasoline_value.iloc[0]==histories['nyh_gasoline'][-1]['value']
    for row in histories['nyh_gasoline']:row['available_at']=(at+timedelta(minutes=10)).isoformat()
    later=live.strict_feature_frame(root,records,histories,at,'decision_1')
    assert np.isnan(later.x_structural_delta_lbp_20l.iloc[0])


@pytest.mark.parametrize('target,expected', [
    ({'scheduled_effective':'2026-11-13','decision_date':'2026-11-17'},'2026-11-13'),
    ({'scheduled_effective':None,'decision_date':'2026-11-17'},'2026-11-17'),
    ({'decision_effective_at':'2026-11-13T08:00:00+02:00'},'2026-11-13T08:00:00+02:00'),
    ({},None),
])
def test_dashboard_reads_estimated_dates_and_legacy_records(tmp_path,target,expected):
    path=tmp_path/'ledger.sqlite'
    with closing(ForecastLedger(path)) as ledger:
        ledger.model('fixture',{'fixture':True})
        origin='2026-11-12T00:00:00+00:00'
        snapshot=ledger.snapshot(origin,'retrospective_research',{'fixture':True})
        ledger.issue('fixture',origin,'retrospective_research','fixture',snapshot,'decision_1',
                     dict(target,kind='decision',steps=1),1000000,0)
    row=data.ledger_rows(path,'decision_1','retrospective_research').iloc[0]
    assert row.scheduled_effective==expected
    if expected and len(expected)==10:
        displayed=data.beirut_time(row.scheduled_effective)
        assert displayed.endswith('(date only)') and ':' not in displayed


def test_date_only_display_keeps_calendar_date_without_assuming_a_clock():
    assert data.beirut_time('2026-11-13')=='13 Nov 2026 (date only)'
    assert data.beirut_time('2026-11-13T08:00:00+00:00')=='13 Nov 2026 10:00 EET'
    assert data.beirut_time(None)=='Unavailable'


def test_atomic_batch_issuance_handles_slow_inference_and_prevents_partial_runs(context, monkeypatch):
    root, cfg, policy, decision, records, histories, at = context
    (root / 'config/live_forecasting.json').write_text(json.dumps(policy))
    decision_path = root / cfg['validation']['decision_file']
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(json.dumps(decision))

    monkeypatch.setattr(forecast, 'now', lambda: at)
    monkeypatch.setattr(forecast, 'current_context', lambda *args: (records, histories))
    import lebanon_fuel.validation.ledger as ledger_mod
    monkeypatch.setattr(ledger_mod, 'now', lambda: (at + timedelta(seconds=90)).isoformat())

    result = forecast.refresh(root, cfg, 'slow-run')
    assert len(result['forecast_ids']) == 8
    ledger_path = root / cfg['validation']['forecast_ledger']
    with closing(ForecastLedger(ledger_path)) as ledger:
        assert ledger.integrity()['hash_chain_valid']
        assert ledger.db.execute('SELECT COUNT(*) FROM forecasts WHERE run_id=?', ('slow-run',)).fetchone()[0] == 8

    with closing(ForecastLedger(ledger_path)) as ledger:
        base_items = [
            dict(
                run_id='aborted-run', origin=at.isoformat(), mode='prospective_research',
                model_version='atomic-test-v1', model_metadata={'tier': 4},
                snapshot_payload={'anchor': records[-1]}, horizon=h,
                target={'kind': 'decision', 'steps': 1}, base_price=1040000.0,
                prediction=0.0 if idx < 3 else -2000000.0,
            )
            for idx, h in enumerate(['decision_1', 'decision_2', 'decision_4', 'day_1'])
        ]
        with pytest.raises(ValueError, match='Invalid price forecast'):
            ledger.issue_batch(base_items)
        assert ledger.db.execute('SELECT COUNT(*) FROM forecasts WHERE run_id=?', ('aborted-run',)).fetchone()[0] == 0
        assert ledger.integrity()['hash_chain_valid']



def test_provisional_anchor_can_issue_point_estimate_without_production_or_uncertainty(context):
    from lebanon_fuel.domain import PROVISIONAL_PRICE
    row = candidate(context)
    approve(context, row)
    record = context[4][-1]
    record.update(verification_status=PROVISIONAL_PRICE,
                  corroborating_sources=[{'id': 'ipt'}, {'id': 'taqtek'}])
    result = issued(context)
    assert result['tier'] == 2
    assert result['anchor_verification'] == PROVISIONAL_PRICE
    assert result['anchor_sources'] == record['corroborating_sources']
    assert result['predicted_price'] == pytest.approx(record['price_lbp_20l'] + result['predicted_change'])
    assert result['interval'] is None and result['probabilities'] is None
    assert live.anchor_check(context[4], context[-1], 10)[0] is None


def test_government_anchor_keeps_previous_source_agreed_change(context):
    from lebanon_fuel.domain import PROVISIONAL_PRICE
    root, _, _, _, records, histories, at = context
    records[-2].update(verification_status=PROVISIONAL_PRICE,
                      corroborating_sources=[{"id": "ipt"}, {"id": "taqtek"}],
                      price_lbp_20l=2391000)
    records[-1].update(verification_status="archive_corroborated", price_lbp_20l=2343000)
    frame = live.strict_feature_frame(root, records, histories, at, "decision_1")
    assert frame.x_domestic_change_lag1.iloc[0] == -48000
    assert records[-2]["verification_status"] == PROVISIONAL_PRICE

    records[-2]["verification_status"] = "supplier_observed"
    frame = live.strict_feature_frame(root, records, histories, at, "decision_1")
    assert np.isnan(frame.x_domestic_change_lag1.iloc[0])
