"""Synthetic invariants and explicitly identified real-data integration checks."""
from datetime import date,timedelta
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest

from lebanon_fuel.forecasting.data import midnight,known_at,label_for,features_at,mature_training,feature_columns,MarketFeatures,ovx_features
from lebanon_fuel.forecasting.models import fit_model,InadequateData,official_structural_forecast,weights,inner_split
from lebanon_fuel.forecasting.uncertainty import past_predictions,calibrate,calibrate_for_ovx_regime,nonoverlapping,fit_ensemble,fit_direction
from lebanon_fuel.forecasting.pipeline import save_bundle,load_bundle,forecast

ROOT=Path(__file__).parents[2]
CONFIG=json.loads((ROOT/'config/forecasting_research.json').read_text())


def observations():
    return [dict(source_date=str(date(2024,1,1)+timedelta(days=7*i)),price_lbp_20l=1000000+1000*i,
                 revision_id=i,verification_status='archive_corroborated') for i in range(8)]


def test_calendar_price_is_not_a_daily_decision():
    rows=observations();origin=known_at(rows[0])
    label,reason=label_for(rows,0,origin,'day_1',CONFIG)
    assert reason is None and label['target_change_lbp_20l']==0 and label['observed_updates']==0
    assert label['witness_revision_id']==1 and pd.Timestamp(label['label_end'])==pd.Timestamp(known_at(rows[1]))
    event,_=label_for(rows,0,origin,'decision_1',CONFIG)
    assert event['target_change_lbp_20l']==1000 and event['observed_updates']==1


def test_calendar_endpoint_includes_record_known_exactly_then():
    rows=observations();label,_=label_for(rows,0,known_at(rows[0]),'day_7',CONFIG)
    assert label['target_revision_id']==1 and label['witness_revision_id']==2


def test_no_skipping_conflicts_or_missing_coverage():
    rows=observations();rows[1]['verification_status']='conflict'
    assert label_for(rows,0,known_at(rows[0]),'decision_2',CONFIG)[1]=='unverified_or_conflicting_path'
    rows=observations();rows[1]['source_date']='2024-01-20'
    assert label_for(rows[:2],0,known_at(rows[0]),'decision_1',CONFIG)[1]=='coverage_gap_over_limit'
    assert label_for(rows[:1],0,known_at(rows[0]),'day_1',CONFIG)[1]=='missing_calendar_coverage_witness'


def test_dst_calendar_horizon_uses_beirut_midnight():
    rows=[dict(source_date=d,price_lbp_20l=1000,revision_id=i,verification_status='archive_corroborated') for i,d in enumerate(['2024-03-28','2024-04-02','2024-04-09'])]
    lab,_=label_for(rows,0,midnight('2024-03-30'),'day_3',CONFIG)
    assert lab['endpoint']=='2024-04-02T03:00:00+03:00'


def test_domestic_features_ignore_future_values_and_short_tail_alignment():
    class Market:
        def at(self,at):return {'x_nyh_gasoline_value':100.,'x_nyh_gasoline_mean20':99.}
    rows=observations();origin=known_at(rows[4]);a=features_at(rows,4,origin,Market(),CONFIG)
    rows[5]['price_lbp_20l']=999999999;b=features_at(rows,4,origin,Market(),CONFIG)
    assert a['x_domestic_change_lag1']==1000 and a['x_domestic_change_lag3']==1000
    assert a==b


@pytest.mark.parametrize('status,expected', [
    ('provisional_corroborated', 1000.),
    ('archive_corroborated', 1000.),
    ('government_archive', 1000.),
    ('conflict', None),
    ('supplier_observed', None),
])
def test_domestic_lag_accepts_agreed_history_without_relaxing_targets(status, expected):
    class Market:
        def at(self, at):
            return {'x_nyh_gasoline_value': 100., 'x_nyh_gasoline_mean20': 99.}

    config = json.loads(json.dumps(CONFIG))
    rows = observations()
    rows[-2]['verification_status'] = status
    original_statuses = list(config['target_statuses'])
    result = features_at(rows, len(rows)-1, known_at(rows[-1]), Market(), config)
    if expected is None:
        assert np.isnan(result['x_domestic_change_lag1'])
    else:
        assert result['x_domestic_change_lag1'] == expected
        assert np.isfinite(result['x_domestic_change_lag1'])
    assert config['target_statuses'] == original_statuses
    # A usable input is not automatically an eligible historical target.
    if status == 'provisional_corroborated':
        assert label_for(rows, len(rows)-3, known_at(rows[-3]), 'decision_1', config)[1] == 'unverified_or_conflicting_path'


@pytest.mark.parametrize('bad_value', [0., -1000., np.nan, np.inf])
def test_domestic_lag_keeps_invalid_adjacent_prices_as_barriers(bad_value):
    class Market:
        def at(self, at):
            return {'x_nyh_gasoline_value': 100., 'x_nyh_gasoline_mean20': 99.}

    rows = observations()
    rows[-2].update(verification_status='provisional_corroborated', price_lbp_20l=bad_value)
    result = features_at(rows, len(rows)-1, known_at(rows[-1]), Market(), CONFIG)
    assert np.isnan(result['x_domestic_change_lag1'])


def test_domestic_lag_does_not_bridge_an_excessive_gap():
    class Market:
        def at(self, at):
            return {'x_nyh_gasoline_value': 100., 'x_nyh_gasoline_mean20': 99.}

    rows = observations()
    rows[-2]['verification_status'] = 'provisional_corroborated'
    rows[-1]['source_date'] = str(date.fromisoformat(rows[-2]['source_date']) + timedelta(days=CONFIG['maximum_gap_days']+1))
    result = features_at(rows, len(rows)-1, known_at(rows[-1]), Market(), CONFIG)
    assert np.isnan(result['x_domestic_change_lag1'])


def test_ovx_features_respect_origin_cutoff_and_optional_history():
    from datetime import datetime, timezone
    dates=pd.bdate_range('2025-01-01',periods=302)
    history=[dict(id=i,capture_id=1,value=20.+i,observation_date=d.date().isoformat(),
                  available_at=f'{d.date().isoformat()}T23:59:59+00:00',unit='percent_annualized')
             for i,d in enumerate(dates)]
    class Store:
        def history(self,series,origin,mode):
            assert (series,mode)==('cboe_ovx','as_of_close')
            return history
    config={'series':['cboe_ovx'],'market_availability_mode':'as_of_close'}
    market=MarketFeatures(Store(),config)
    cutoff=datetime.combine(dates[299].date(),datetime.max.time(),timezone.utc)
    features=market.at(cutoff)
    assert features['x_ovx_level']==319.
    assert features['x_ovx_5d_change']==5.
    assert features['x_ovx_20d_change']==20.
    assert features['x_ovx_252d_percentile']==100.
    assert features['ovx_regime']=='Stress' and features['x_ovx_regime']==3.
    assert 'x_ovx_level' in feature_columns(pd.DataFrame([features]))
    assert np.isnan(ovx_features([])['x_ovx_level'])


def test_ovx_historical_close_backfill_is_separate_from_strict_capture_time():
    from datetime import datetime, timezone
    day='2026-11-10'
    close=dict(id=1,capture_id=2,value=35.,observation_date=day,
               available_at='2026-11-10T23:59:59+00:00',captured_available_at='2026-11-13T12:00:00+00:00')
    captured=dict(close,available_at=close['captured_available_at'])
    class Store:
        def __init__(self,mode):self.mode=mode
        def history(self,series,origin,mode):return [close if mode=='as_of_close' else captured]
    origin=datetime.fromisoformat('2026-11-10T23:59:59+00:00')
    research=MarketFeatures(Store('as_of_close'),{'series':['cboe_ovx'],'market_availability_mode':'as_of_close'}).at(origin)
    strict=MarketFeatures(Store('strict'),{'series':['cboe_ovx'],'market_availability_mode':'strict'}).at(origin)
    assert research['x_ovx_level']==35.
    assert np.isnan(strict['x_ovx_level'])


def test_ovx_regime_calibration_uses_regime_only_with_enough_matured_cases():
    predictions=frame(90)
    predictions['family']='C_ridge'
    predictions['prediction']=0.
    predictions['ovx_regime']=['Stress' if i<60 else 'Normal' for i in range(len(predictions))]
    pooled=calibrate_for_ovx_regime(predictions,'Stress',CONFIG)
    assert pooled['ovx_regime_conditioning']=='regime_conditioned_matured_oof'
    assert pooled['requested_ovx_regime']=='Stress' and pooled['n']>=CONFIG['minimum_calibration']
    scarce=predictions.copy();scarce['ovx_regime']=['Stress' if i<12 else 'Normal' for i in range(len(scarce))]
    fallback=calibrate_for_ovx_regime(scarce,'Stress',CONFIG)
    assert fallback['ovx_regime_conditioning']=='pooled_fallback_insufficient_regime_residuals'
    assert fallback['n']>=pooled['n']


def frame(n=90):
    days=pd.date_range('2020-01-01',periods=n,freq='7D',tz='UTC')
    x=np.sin(np.arange(n)/7)
    return pd.DataFrame(dict(origin=days.astype(str),label_end=(days+pd.Timedelta(days=7)).astype(str),
        base_revision_id=np.arange(n),target_change_lbp_20l=np.round(1000*x/100)*100,
        x_structural_cost_gap=x,x_structural_delta_lbp_20l=x*1000,x_fiscal_shock_lag1=np.zeros(n),
        x_domestic_change_lag1=np.r_[0,1000*x[:-1]],x_brent_spot_return7=x/100,
        x_days_since_source_date=np.ones(n),x_interval_median=np.full(n,7),x_weekday=days.day_of_week,
        x_nyh_gasoline_lag7=100+x,sequence_index=np.arange(n),day_index=np.arange(n)*7,horizon='decision_1'))


def test_label_maturity_and_inner_purge():
    f=frame();cut=f.iloc[50].origin;train=mature_training(f,cut)
    assert pd.to_datetime(train.label_end,utc=True).max()<pd.Timestamp(cut)
    before,after=inner_split(f)
    assert pd.to_datetime(before.label_end,utc=True).max()<pd.to_datetime(after.origin,utc=True).min()


def test_daily_replication_does_not_inflate_weight_or_minimum_tree_sample():
    f=pd.concat([frame(30)]*10,ignore_index=True)
    assert weights(f).sum()==pytest.approx(30)
    with pytest.raises(InadequateData):fit_model('E_lightgbm',f,CONFIG)


def test_ridge_training_preprocessor_and_distributed_features():
    f=frame();model=fit_model('C_distributed',f.iloc[:70],CONFIG)
    assert 'x_nyh_gasoline_lag7' in model.columns
    assert 'x_nyh_gasoline_lag7' not in feature_columns(f)
    means=model.transform.steps[-1][1].mean_.copy()
    future=f.iloc[70:].copy();future['x_structural_cost_gap']=1e12
    model.predict(future)
    np.testing.assert_array_equal(means,model.transform.steps[-1][1].mean_)


def test_official_model_abstains_and_proxy_nonnegative_coefficient():
    assert official_structural_forecast(None,1000000)['predicted_change_lbp_20l'] is None
    f=frame();f['target_change_lbp_20l']=-f.x_structural_cost_gap*1000
    m=fit_model('B_structural_proxy',f,CONFIG)
    assert m.extra['structural_coefficients'][0]>=0


def test_sarimax_does_not_compress_missing_decisions():
    f=frame(90);f.loc[70:,'sequence_index']+=10
    with pytest.raises(InadequateData):fit_model('D_sarimax',f,CONFIG)


def predictions(n=70):
    f=frame(n);f['prediction']=0.;f['family']='A_no_change';f['raw_low']=np.nan;f['raw_high']=np.nan
    return f


def test_interval_calibration_requires_independent_enough_past_errors():
    p=predictions();past=past_predictions(p,p.iloc[50].origin)
    cal=calibrate(past,CONFIG)
    assert cal['n']>=20 and cal['radius'] is not None
    thin=nonoverlapping(past)
    ordered=thin.sort_values('origin')
    assert all(pd.Timestamp(a)<pd.Timestamp(b) for a,b in zip(ordered.label_end.iloc[:-1],ordered.origin.iloc[1:]))
    assert calibrate(p.iloc[:10],CONFIG)['radius'] is None


def test_ensemble_weights_use_only_supplied_prior_oof_and_sum_one():
    a=predictions();b=a.copy();b['family']='C_ridge';b['prediction']=b.target_change_lbp_20l*.9
    result=fit_ensemble(pd.concat([a,b]),{'A_no_change','C_ridge'},CONFIG)
    assert sum(result['weights'].values())==pytest.approx(1.)
    assert result['weights'].get('C_ridge',0)>.9
    assert fit_ensemble(pd.DataFrame(),{'A_no_change'},CONFIG)['status'].startswith('insufficient')


def test_exact_sign_probabilities_normalize_and_distinguish_zero():
    f=frame(100);d=fit_direction(f.iloc[:80]);p=d.predict(f.iloc[80:])
    assert p.shape==(20,3) and np.isfinite(p).all() and (p>=0).all()
    np.testing.assert_allclose(p.sum(axis=1),1)
    assert d.metadata['class_order']==['decrease','unchanged_price','increase']


@pytest.mark.parametrize('family',['A_no_change','A_mean','A_median','B_structural_proxy','C_ridge','C_distributed','D_sarimax','E_lightgbm','F_catboost','G_hybrid'])
def test_actual_historical_model_fit_predict_roundtrip(family,tmp_path):
    """Real downloaded observations, no sample count inferred from synthetic fixtures."""
    path=ROOT/'data/exports/forecasting/development_design.csv'
    if not path.exists():pytest.skip('Run fuel-forecast build to create actual-data integration fixture')
    data=pd.read_csv(path);g=data[(data.regime=='pre_crisis')&(data.horizon=='decision_1')].sort_values('origin')
    test=g.tail(1);train=mature_training(g,test.origin.iloc[0])
    model=fit_model(family,train,CONFIG);p=model.predict(test)
    assert len(p)==1 and np.isfinite(p).all()
    direction=fit_direction(train)
    bundle=dict(models={family:model},direction=direction,ensemble={'weights':{family:1.}},calibrations={})
    save_bundle(tmp_path,bundle);loaded=load_bundle(tmp_path)
    np.testing.assert_allclose(p,loaded['models'][family].predict(test))
    (tmp_path/'bundle.joblib').write_bytes(b'altered')
    with pytest.raises(ValueError):load_bundle(tmp_path)


def test_completed_artifacts_have_no_future_fit_labels():
    path=ROOT/'reports/forecasting/development_predictions.csv'
    if not path.exists():pytest.skip('Training outputs not created yet')
    d=pd.read_csv(path)
    assert (pd.to_datetime(d.maximum_training_label_end,utc=True)<pd.to_datetime(d.fit_cutoff,utc=True)).all()
    assert (pd.to_datetime(d.fit_cutoff,utc=True)<=pd.to_datetime(d.origin,utc=True)).all()
    cal=d[d.calibration_maximum_label_end.notna()]
    assert (pd.to_datetime(cal.calibration_maximum_label_end,utc=True)<pd.to_datetime(cal.origin,utc=True)).all()
    assert (d[d.regime=='pre_crisis'].origin<'2018').all()
    assert (d[d.regime=='recent_pre_fiscal'].origin<'2025').all()
    assert (d[d.regime=='stabilized_fx_2023_2026'].origin<'2026-06-01').all()
    assert not d.production_approved.any()


def calendar_predictions(n=180,horizon='day_1'):
    f=predictions(n)
    days=pd.date_range('2024-01-01',periods=n,freq='D',tz='UTC')
    f['origin']=days.astype(str);f['label_end']=(days+pd.Timedelta(days=3)).astype(str)
    f['base_revision_id']=np.arange(n)//7;f['horizon']=horizon
    f['target_change_lbp_20l']=np.where(days.day_of_week.isin([1,4]),30000.,0.)
    f['x_interval_median']=3.5
    return f


def test_calendar_calibration_keeps_days_with_same_base_and_never_collapses():
    from lebanon_fuel.forecasting.uncertainty import calibration_sample
    p=calendar_predictions()
    sampled,stride=calibration_sample(p)
    assert len(sampled)==60 and stride==1 and sampled.base_revision_id.nunique()<60
    assert len(pd.to_datetime(sampled.origin,utc=True).dt.day_of_week.unique())==7
    cal=calibrate(p,CONFIG)
    assert cal['radius']>=30000 and cal['minimum_half_width_lbp']>=5000
    p['target_change_lbp_20l']=p['prediction']=0.
    assert calibrate(p,CONFIG)['radius']==5000
    p['target_change_lbp_20l']=200000.
    assert calibrate(p,CONFIG)['minimum_half_width_lbp']==50000


def test_ovx_conditioned_calibration_exposes_empirical_p10_p90_residual_bounds():
    from lebanon_fuel.forecasting.uncertainty import calibrate_for_ovx_regime
    p=calendar_predictions(120)
    p['ovx_regime']='Stress'
    p['target_change_lbp_20l']=np.linspace(-90000,90000,len(p))
    cal=calibrate_for_ovx_regime(p,'Stress',CONFIG)
    assert cal['ovx_regime_conditioning']=='regime_conditioned_matured_oof'
    assert cal['residual_quantile_10'] <= cal['residual_quantile_90']
    assert cal['n']>=20 and cal['radius'] is not None


def test_seven_day_stride_does_not_alias_one_weekday():
    from lebanon_fuel.forecasting.uncertainty import calibration_sample
    sample,stride=calibration_sample(calendar_predictions(210,'day_14'))
    assert stride==7 and len(sample)>=20
    assert len(pd.to_datetime(sample.origin,utc=True).dt.day_of_week.unique())==7


def test_calibration_rejects_mixed_horizons_and_only_uses_matured_labels():
    p=calendar_predictions(100)
    cutoff=p.origin.iloc[80]
    cal=calibrate(p,CONFIG,cutoff=cutoff)
    assert pd.Timestamp(cal['maximum_label_end'])<pd.Timestamp(cutoff)
    changed=p.copy();changed.loc[pd.to_datetime(changed.label_end,utc=True)>=pd.Timestamp(cutoff),'target_change_lbp_20l']=1e9
    assert calibrate(changed,CONFIG,cutoff=cutoff)==cal
    p.loc[0,'horizon']='day_7'
    with pytest.raises(ValueError,match='one horizon'):calibrate(p,CONFIG)


def test_residual_probabilities_follow_magnitude_deadband_and_laplace_smoothing():
    from lebanon_fuel.forecasting.uncertainty import residual_probabilities,direction_class
    c={'residuals':[-3001.,-3000.,0.,3000.,3001.]}
    probability=residual_probabilities([-100000.,0.,100000.],c)
    assert ((probability>0)&(probability<1)).all()
    np.testing.assert_allclose(probability.sum(axis=1),1,atol=1e-15)
    np.testing.assert_allclose(probability[1],(np.array([1,3,1])+.03)/(5+.09))
    assert probability[0,0]>probability[1,0]>probability[2,0]
    assert probability[0,2]<probability[1,2]<probability[2,2]
    np.testing.assert_array_equal(direction_class([-3001,-3000,3000,3001]),[-1,0,0,1])
    assert np.isnan(residual_probabilities([0.],{})).all()


def test_structural_delta_constraints_shock_fill_and_hybrid_purge():
    f=frame(120);f['target_change_lbp_20l']=.8*f.x_structural_delta_lbp_20l+.2*f.x_domestic_change_lag1
    model=fit_model('B_structural_proxy',f,CONFIG)
    assert model.extra['structural_coefficients'][0]>=0
    assert model.extra['structural_columns'][0]=='x_structural_delta_lbp_20l'
    test=f.tail(3).copy();test['x_fiscal_shock_lag1']=np.nan
    np.testing.assert_allclose(model.predict(test),model.predict(test.fillna({'x_fiscal_shock_lag1':0})))
    hybrid=fit_model('G_hybrid',f,CONFIG)
    assert hybrid.extra['structural_version']==2 and hybrid.extra['cross_fitted_residual_rows']>0
    for fold in hybrid.extra['residual_folds']:
        assert pd.Timestamp(fold['maximum_base_fit_label_end'])<pd.Timestamp(fold['first_residual_origin'])


def test_walk_forward_residuals_do_not_use_current_or_future_outcomes():
    from lebanon_fuel.forecasting.pipeline import walk_calibration
    p=calendar_predictions(80)
    for column in ['interval_low','interval_high','calibration_maximum_label_end','p_decrease','p_unchanged_price','p_increase','p_no_change']:
        p[column]=None if 'label_end' in column else np.nan
    p['calibration_n']=0;p['probability_n']=0;p['probability_status']='unavailable';p['interval_kind']='unavailable'
    a=walk_calibration(p,p.iloc[:0],CONFIG)
    changed=p.copy();changed.loc[50:,'target_change_lbp_20l']+=1e8
    b=walk_calibration(changed,p.iloc[:0],CONFIG)
    columns=['interval_low','interval_high','p_decrease','p_no_change','p_increase','calibration_n']
    pd.testing.assert_frame_equal(a.loc[:50,columns],b.loc[:50,columns])
    ready=a[a.interval_low.notna()]
    assert len(ready)>0 and (ready.interval_high-ready.interval_low>=10000).all()
    assert (pd.to_datetime(ready.calibration_maximum_label_end,utc=True)<pd.to_datetime(ready.origin,utc=True)).all()


def test_forecast_uncertainty_is_model_specific_and_interval_kind_is_preserved():
    from lebanon_fuel.forecasting.models import Model
    p=frame(1);p['base_price_lbp_20l']=1000000;p['origin_beirut']=p.origin;p['ovx_regime']='Stress'
    models={'A_no_change':Model('A_no_change',extra={'constant':0.}),
            'A_mean':Model('A_mean',extra={'constant':50000.})}
    cal={'n':30,'radius':5000.,'residuals':[-1000,0,1000]*10,'status':'horizon_conditioned_past_oof_conformal_research',
         'requested_ovx_regime':'Stress','ovx_regime_conditioning':'regime_conditioned_matured_oof'}
    rows=forecast(models,{'weights':{}},None,{k:cal for k in models},p,CONFIG).set_index('family')
    assert rows.loc['A_mean','p_increase']>rows.loc['A_no_change','p_increase']
    assert rows.loc['A_no_change','interval_kind']=='past_oof_absolute_error_interval'
    assert rows.loc['A_no_change','p_no_change']==rows.loc['A_no_change','p_unchanged_price']
    assert rows.loc['A_no_change','calibration_ovx_regime']=='Stress'
    assert rows.loc['A_no_change','ovx_regime_conditioning']=='regime_conditioned_matured_oof'
