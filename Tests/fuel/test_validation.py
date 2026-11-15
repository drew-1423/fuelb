"""Independent validation invariants; synthetic fixtures are never reported as price observations."""
from datetime import datetime,timedelta,timezone
import json
import sqlite3
import numpy as np
import pandas as pd
import pytest
from lebanon_fuel.validation.backtest import strict_eligible,walk_forward_strict
from lebanon_fuel.validation.metrics import score,bootstrap_difference
from lebanon_fuel.validation.ledger import ForecastLedger,now
from lebanon_fuel.validation.policy import gate
from lebanon_fuel.validation.runner import LastChange,Brent


def design():
    days=pd.date_range('2020-01-01',periods=40,tz='UTC')
    return pd.DataFrame(dict(origin=days.astype(str),feature_known_at=(days-pd.Timedelta(hours=1)).astype(str),
        base_known_at=(days-pd.Timedelta(hours=2)).astype(str),label_known_at=(days+pd.Timedelta(days=3)).astype(str),
        feature_vintage_certified=True,target_definition_certified=True,partition='training',base_revision_id=range(40),
        base_price_lbp_20l=1000,x_past=range(40),target_change_lbp_20l=range(40),horizon='decision_1'))


def test_strict_timestamps_are_before_and_not_naive():
    d=design();assert strict_eligible(d).all()
    d.loc[0,'feature_known_at']=d.loc[0,'origin'];assert not strict_eligible(d).iloc[0]
    d.loc[1,'feature_known_at']='2020-01-01T00:00:00'
    with pytest.raises(ValueError):strict_eligible(d)


def test_strict_walker_purges_future_labels_and_sealed_holdout():
    d=design();d.loc[25:,'partition']='final_holdout';seen=[]
    def fit(train):
        seen.append(train.copy());return train.target_change_lbp_20l.mean()
    def predict(model,features):
        assert 'target_change_lbp_20l' not in features and 'label_known_at' not in features
        return np.repeat(model,len(features))
    a,_=walk_forward_strict(d,d.origin.iloc[30:],fit,predict,minimum_train=10)
    assert all((x.partition!='final_holdout').all() for x in seen)
    for f,at in zip(seen,d.origin.iloc[30:]):assert pd.to_datetime(f.label_known_at,utc=True).max()<pd.Timestamp(at)
    d.loc[30:,'target_change_lbp_20l']=999999
    b,_=walk_forward_strict(d,d.origin.iloc[30:],fit,predict,minimum_train=10)
    np.testing.assert_array_equal(a.prediction,b.prediction)


def test_strict_walker_never_calls_fit_for_unavailable_vintages():
    d=design();d['feature_vintage_certified']=False
    def fail(_):raise AssertionError('Must not fit')
    predictions,gates=walk_forward_strict(d,d.origin.tail(3),fail,fail,minimum_train=10)
    assert predictions.empty and len(gates)==3


def test_metric_equations_and_counts():
    f=pd.DataFrame(dict(target_change_lbp_20l=[0,100,-100],prediction=[0,50,50],base_price_lbp_20l=[1000]*3,
        origin=['2020-01-01','2020-01-02','2020-01-03'],base_revision_id=[1,2,3],
        p_decrease=[0,.1,.5],p_unchanged_price=[1,.1,.1],p_increase=[0,.8,.4],interval_low=[0,0,np.nan],interval_high=[0,100,np.nan]))
    s=score(f)
    assert s['n']==3 and s['change_mae_lbp']==pytest.approx(200/3) and s['price_mae_lbp']==s['change_mae_lbp']
    assert s['direction_accuracy']==pytest.approx(2/3) and s['point_no_change_accuracy']==1
    assert s['interval_n']==2 and s['interval_coverage']==1 and s['interval_width_lbp']==50
    assert s['brier_multiclass']==pytest.approx((0+.06+.42)/3)


def test_bootstrap_reproducible_and_constant_difference():
    a=bootstrap_difference(np.full(50,-10.),5);b=bootstrap_difference(np.full(50,-10.),5)
    np.testing.assert_array_equal(a,b);np.testing.assert_allclose(a,[-10,-10])


def test_conformal_floor_and_finite_sample_rank():
    from lebanon_fuel.forecasting.uncertainty import calibrate
    days=pd.date_range('2020-01-01',periods=20,freq='7D',tz='UTC')
    p=pd.DataFrame(dict(origin=days.astype(str),label_end=(days+pd.Timedelta(days=1)).astype(str),base_revision_id=range(20),
        target_change_lbp_20l=np.arange(1,21)*1000, prediction=0.,horizon='day_1',family='fixture'))
    result=calibrate(p,{'calibration_max':80,'minimum_calibration':20,'coverage':.9})
    k=int(np.ceil((20+1)*.9));standard_order_statistic=np.sort(p.target_change_lbp_20l)[k-1]
    assert standard_order_statistic==19000 and result['radius']==19000


def test_baselines_do_not_use_realized_number_of_decisions():
    f=pd.DataFrame(dict(horizon=['decision_2','day_7'],x_interval_median=[5,7],x_domestic_change_lag1=[100,100],observed_updates=[99,99]))
    np.testing.assert_allclose(LastChange().predict(f),[200,100])


def make_ledger(tmp_path,kind='decision'):
    s=ForecastLedger(tmp_path/'ledger.sqlite');s.model('fixture',{'fixture':True})
    origin='2025-01-01T00:00:00+00:00';snap=s.snapshot(origin,'strict_replay',{'base':1000})
    target={'kind':kind,'steps':1}
    if kind=='calendar':target['endpoint']='2025-01-02T00:00:00+00:00'
    fid=s.issue('fixture',origin,'strict_replay','fixture',snap,'decision_1' if kind=='decision' else 'day_1',target,1000,100,[0,200],[.1,.2,.7])
    return s,fid


def outcome(s,key='one',price=1100,published='2025-01-02T00:00:00+00:00',effective='2025-01-02T00:00:00+00:00',hash='v1'):
    return s.outcome(key,'2025-01-03T00:00:00+00:00',price,'https://example.org/fixture','document_verified',hash,{'fixture':True},published,effective)


def test_ledger_immutable_original_forecast_and_hash_chain(tmp_path):
    s,fid=make_ledger(tmp_path)
    assert s.integrity()['hash_chain_valid']
    for sql in ['UPDATE forecasts SET predicted_price=1','DELETE FROM forecasts','UPDATE snapshots SET mode="prospective"']:
        with pytest.raises(sqlite3.IntegrityError):s.db.execute(sql)
    assert s.db.execute('SELECT predicted_price FROM forecasts').fetchone()[0]==1100
    s.close()


def test_no_backdated_prospective_claim_or_unapproved_numeric_forecast(tmp_path):
    s=ForecastLedger(tmp_path/'ledger.sqlite');s.model('fixture',{})
    old='2020-01-01T00:00:00+00:00';snap=s.snapshot(old,'prospective',{})
    with pytest.raises(ValueError):s.issue('r',old,'prospective','fixture',snap,'day_1',{'kind':'calendar'},1000,0)
    current=now();snap=s.snapshot(current,'prospective',{})
    with pytest.raises(ValueError):s.issue('r',current,'prospective','fixture',snap,'day_1',{'kind':'calendar'},1000,0)
    s.issue('r',current,'prospective','fixture',snap,'day_1',{'kind':'calendar'},1000,None,reasons=['unapproved'])
    assert s.integrity()['forecasts']==1;s.close()


def test_no_outcome_leak_in_input_snapshot(tmp_path):
    s=ForecastLedger(tmp_path/'ledger.sqlite')
    with pytest.raises(ValueError):s.snapshot(now(),'retrospective_research',{'target_change_lbp_20l':100})
    s.close()


def test_signed_zero_does_not_break_persisted_hash(tmp_path):
    s=ForecastLedger(tmp_path/'ledger.sqlite');s.model('fixture',{})
    origin='2025-01-01T00:00:00+00:00';snap=s.snapshot(origin,'retrospective_research',{})
    s.issue('r',origin,'retrospective_research','fixture',snap,'decision_1',{'kind':'decision','steps':1},1000,-0.0,[-0.0,0.0])
    assert s.integrity()['hash_chain_valid'];s.close()


def test_prospective_research_can_be_logged_without_production_approval(tmp_path):
    s=ForecastLedger(tmp_path/'ledger.sqlite');s.model('fixture',{'research_only':True})
    origin=now();snap=s.snapshot(origin,'prospective_research',{'fixture':True})
    fid=s.issue('fixture',origin,'prospective_research','fixture',snap,'decision_1',{'kind':'decision','steps':1},1000,0)
    assert s.db.execute('SELECT mode FROM forecasts WHERE id=?',(fid,)).fetchone()[0]=='prospective_research'
    s.close()


def test_ambiguous_same_time_decisions_do_not_auto_match(tmp_path):
    s,fid=make_ledger(tmp_path);outcome(s,key='one');outcome(s,key='two',price=1200)
    status=s.match(fid,{'certified':True,'from':'2025-01-01T00:00:00+00:00','through':'2025-01-03T00:00:00+00:00','evidence_url':'https://example.org/fixture'})
    assert status=='ambiguous_simultaneous_announcements'
    assert s.integrity()['evaluations']==0;s.close()


def test_corrected_clock_cannot_silently_reorder_target(tmp_path):
    s,fid=make_ledger(tmp_path);outcome(s)
    outcome(s,hash='clock-correction',published='2025-01-02T01:00:00+00:00')
    status=s.match(fid,{'certified':True,'from':'2025-01-01T00:00:00+00:00','through':'2025-01-03T00:00:00+00:00','evidence_url':'https://example.org/fixture'})
    assert status=='timing_revision_requires_review' and s.integrity()['evaluations']==0;s.close()


def test_backdated_effect_does_not_leak_into_calendar_endpoint(tmp_path):
    s,fid=make_ledger(tmp_path,'calendar')
    outcome(s,key='anchor',price=1000,published='2024-12-31T12:00:00+00:00',effective='2024-12-31T12:00:00+00:00')
    outcome(s,key='late',price=1500,published='2025-01-03T00:00:00+00:00',effective='2025-01-01T12:00:00+00:00')
    status=s.match(fid,{'certified':True,'from':'2025-01-01T00:00:00+00:00','through':'2025-01-03T00:00:00+00:00','evidence_url':'https://example.org/fixture'})
    assert status=='matched_verified_outcome'
    assert s.db.execute('SELECT actual_change FROM evaluations').fetchone()[0]==0;s.close()


def test_settlement_import_requires_original_document_clock_and_value_evidence(tmp_path):
    from lebanon_fuel.storage.database import Store
    from lebanon_fuel.domain import Observation
    from lebanon_fuel.validation.settlement import settle
    s=Store(tmp_path)
    cap=s.capture('official_document','https://example.org/official-fixture',b'fixture','text/plain',http_status=200,retrieved_at='2025-01-02T12:00:00+00:00')
    s.ingest(cap,[Observation('official_document','2025-01-02',1100,'https://example.org/official-fixture',
        {'reviewer':'test fixture','evidence_locator':'fixture paragraph'},'1',document_verified=True,
        official_effective_date='2025-01-02',publication_timestamp='2025-01-02T10:00:00+00:00')])
    oid=s.db.execute('SELECT id FROM observations').fetchone()[0];s.close()
    manifest={'reviewer':'fixture reviewer','clock_evidence_url':'https://example.org/clock-fixture','outcomes':[
        {'source_observation_id':oid,'official_decision_key':'fixture-1','price_lbp_20l':1100,'publication_timestamp':'2025-01-02T10:00:00+00:00',
         'effective_timestamp':'2025-01-02T10:00:00+00:00','available_at':'2025-01-02T13:00:00+00:00'}]}
    path=tmp_path/'outcomes.json';path.write_text(json.dumps(manifest));assert len(settle(tmp_path,path)['imported_outcome_ids'])==1
    manifest['outcomes'][0]['effective_timestamp']='2025-01-01T10:00:00+00:00';path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):settle(tmp_path,path)
    manifest['outcomes'][0]['effective_timestamp']='2025-01-02T10:00:00+00:00';manifest['outcomes'][0]['available_at']='2025-01-02T11:00:00+00:00';path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):settle(tmp_path,path)


def test_real_validation_artifacts_fit_cutoffs_and_production_rejection():
    from pathlib import Path
    root=Path(__file__).parents[2];path=root/'reports/model_validation/research_walk_forward_predictions.csv'
    if not path.exists():pytest.skip('Run the actual validation pipeline first')
    p=pd.read_csv(path)
    assert (pd.to_datetime(p.maximum_training_label_end,utc=True)<pd.to_datetime(p.fit_cutoff,utc=True)).all()
    assert (pd.to_datetime(p.fit_cutoff,utc=True)<=pd.to_datetime(p.origin,utc=True)).all()
    c=p[p.calibration_maximum_label_end.notna()]
    assert (pd.to_datetime(c.calibration_maximum_label_end,utc=True)<pd.to_datetime(c.origin,utc=True)).all()
    selection=json.loads((root/'reports/model_validation/production_selection.json').read_text())
    assert selection['production_approved'] is False
    assert len(selection['selection'])==8
    assert all(v['quantitative_model'] and v['artifact_sha256'] for v in selection['selection'].values())
    assert all(v['tier']==2 for v in selection['selection'].values())


def test_actual_matching_requires_complete_coverage_and_preserves_revisions(tmp_path):
    s,fid=make_ledger(tmp_path);outcome(s)
    assert s.match(fid,{})=='awaiting_verified_complete_coverage'
    certificate={'certified':True,'from':'2025-01-01T00:00:00+00:00','through':'2025-01-03T00:00:00+00:00','evidence_url':'https://example.org/complete-fixture'}
    assert s.match(fid,certificate)=='matched_verified_outcome'
    outcome(s,price=1200,hash='revision2')
    assert s.match(fid,certificate)=='matched_verified_outcome'
    rows=s.db.execute('SELECT prediction_error,supersedes_id FROM evaluations ORDER BY id').fetchall()
    assert len(rows)==2 and rows[0][0]==0 and rows[1][0]==-100 and rows[1][1] is not None
    assert s.db.execute('SELECT predicted_price FROM forecasts').fetchone()[0]==1100;s.close()


def test_calendar_no_update_matches_verified_prevailing_anchor(tmp_path):
    s,fid=make_ledger(tmp_path,'calendar');outcome(s,price=1000,published='2024-12-31T12:00:00+00:00',effective='2024-12-31T12:00:00+00:00')
    assert s.match(fid,{'certified':True,'from':'2025-01-01T00:00:00+00:00','through':'2025-01-02T00:00:00+00:00','evidence_url':'https://example.org/fixture'})=='matched_verified_outcome'
    assert s.db.execute('SELECT actual_change FROM evaluations').fetchone()[0]==0;s.close()


def test_gating_missing_stale_future_policy_and_regime():
    stamp='2025-02-01T00:00:00+00:00';anchor={'official_verified':True,'known_at':'2025-01-31T12:00:00+00:00','effective_at':'2025-01-31T12:00:00+00:00'}
    model={'approved':True,'supported_regimes':['fixture'],'required_market':['brent_spot']}
    context={'regime':'fixture','complete_decision_coverage':True}
    row={'value':100,'available_at':'2025-01-31T12:00:00+00:00','observation_date':'2025-01-30','vintage_certified':True}
    assert gate(stamp,anchor,{'brent_spot':row},model,context)['status']=='eligible'
    assert gate(stamp,anchor,{},model,context)['status']=='abstain'
    row['observation_date']='2024-01-01';assert 'brent_spot_stale_observation' in gate(stamp,anchor,{'brent_spot':row},model,context)['reasons']
    context['tax_change']=True;assert 'tax_change_requires_review' in gate(stamp,anchor,{'brent_spot':row},model,context)['reasons']


def test_selection_tiebreakers_and_promotion_require_evidence():
    from lebanon_fuel.validation.runner import select_horizon
    protocol={'quantitative_families':['C_ridge','E_lightgbm'], 'required_baselines':['A_no_change','Z_last_change'],
              'approval':dict(mae_relative_tolerance=.01,mae_absolute_tolerance_lbp=0.,coverage_minimum=.8,
                              coverage_maximum=.98,minimum_holdout_origins=20,require_certified_target_coverage=True)}
    frame=pd.DataFrame([dict(family=f,mae=100.,brier_multiclass=b,interval_coverage=c,interval_n=40,n=40)
                        for f,b,c in [('A_no_change',.6,.9),('Z_last_change',.6,.9),('C_ridge',.4,.85),('E_lightgbm',.4,.9)]])
    chosen=select_horizon(frame,frame,protocol,certified=True)
    assert chosen['family']=='E_lightgbm' and chosen['production_approved']
    assert not select_horizon(frame,frame,protocol,certified=False)['production_approved']
    frame.loc[frame.family.eq('E_lightgbm'),'mae']=102
    assert select_horizon(frame,frame,protocol,certified=True)['family']=='C_ridge'
    missing=select_horizon(frame.iloc[:0],frame,protocol)
    assert missing['tier']==2 and missing['performance'] is None
    assert missing['selection_basis']=='development_only_no_holdout_targets'


def test_frozen_walk_forward_never_exposes_outcomes_to_prediction():
    from lebanon_fuel.validation.backtest import walk_forward_bundle
    class FixedModel:
        def predict(self,frame):
            assert 'target_change_lbp_20l' not in frame and 'label_end' not in frame
            return np.zeros(len(frame))
        def quantiles(self,frame):return None
    days=pd.date_range('2026-01-01',periods=25,tz='UTC')
    previous=pd.DataFrame(dict(origin=days.astype(str),label_end=(days+pd.Timedelta(days=1)).astype(str),
        base_revision_id=range(25),target_change_lbp_20l=np.arange(25)*1000.,prediction=0.,family='A_no_change',horizon='day_1'))
    targets=pd.DataFrame(dict(origin=['2026-06-01T00:00:00+00:00','2026-06-02T00:00:00+00:00'],
        label_end=['2026-06-04T00:00:00+00:00']*2,base_revision_id=[30,30],base_price_lbp_20l=[1000000]*2,
        target_change_lbp_20l=[0,50000],horizon='day_1',regime='fixture',x_only_past=[1,2]))
    bundle=dict(models={'A_no_change':FixedModel()},ensemble={'weights':{}},config={'minimum_calibration':20,'coverage':.9},
        fit_cutoff='2026-05-31T00:00:00+00:00',training_maximum_label_end='2026-01-26T00:00:00+00:00')
    a=walk_forward_bundle(bundle,targets,previous)
    targets['target_change_lbp_20l']=999999
    b=walk_forward_bundle(bundle,targets,previous)
    for col in ['prediction','interval_low','interval_high','p_increase']:
        np.testing.assert_allclose(a[col],b[col])
    assert (pd.to_datetime(a.calibration_maximum_label_end,utc=True)<pd.to_datetime(a.origin,utc=True)).all()
    bad=previous.copy();bad.loc[0,'label_end']='2026-06-02T00:00:00+00:00'
    with pytest.raises(ValueError,match='Development calibration'):
        walk_forward_bundle(bundle,targets,bad)


def test_physical_holdout_integrity_and_missing_horizons():
    from pathlib import Path
    from lebanon_fuel.validation.backtest import load_holdout
    from lebanon_fuel.forecasting.pipeline import digest
    root=Path(__file__).parents[2]
    protocol=json.loads((root/'config/validation_protocol.json').read_text())
    frame=load_holdout(root,protocol)
    manifest=json.loads((root/'reports/model_validation/input_manifest.json').read_text())
    assert digest(root/protocol['design_path'])==manifest['design_sha256']
    assert len(frame)==sum(manifest['target_counts'].values())
    decision=json.loads((root/'reports/model_validation/production_selection.json').read_text())
    for h,s in decision['selection'].items():
        assert s['holdout_n']<=len(frame[frame.horizon.eq(h)])
        assert digest(root/s['path']/'bundle.joblib')==s['artifact_sha256']
        if frame[frame.horizon.eq(h)].empty:
            assert s['mae_lbp'] is None and s['production_approved'] is False


def test_market_report_preserves_blocked_collection_and_unknown_counts():
    from lebanon_fuel.market.reports import collection_summary
    detail={'results':[
        {'series':'brent_spot','parsed_rows':12,'new_observations':2},
        {'series':'rbob_futures','status':'unavailable','reason':'Request denied by robots policy',
         'new_observations':0,'fallback_series':'nyh_gasoline','stored_fallback_rows':9171,
         'fallback_latest_date':'2026-11-03'}]}
    original=json.dumps(detail,sort_keys=True)
    note=collection_summary(detail)
    assert '12 rows parsed across 1/2 results' in note and '2 new observations' in note
    assert 'rbob_futures: unavailable' in note and 'Request denied by robots policy' in note
    assert 'Stored fallback: nyh_gasoline (latest 2026-11-03)' in note
    assert '9171 rows parsed' not in note and '9,171 rows parsed' not in note
    assert json.dumps(detail,sort_keys=True)==original
    note=collection_summary({'results':[detail['results'][1]]})
    assert 'rows parsed: unavailable' in note and '0 rows parsed' not in note
    assert collection_summary({'error':'Source unavailable'})=='Source unavailable'


def test_select_horizon_uses_unique_base_decisions_and_common_origins_ignores_sparse_models():
    from lebanon_fuel.validation.runner import select_horizon, common_origins
    protocol={'quantitative_families':['C_ridge','G_hybrid'], 'required_baselines':['A_no_change','Z_last_change'],
              'approval':dict(mae_relative_tolerance=.01,mae_absolute_tolerance_lbp=0.,coverage_minimum=.8,
                              coverage_maximum=.98,minimum_holdout_origins=20,require_certified_target_coverage=True)}
    frame=pd.DataFrame([dict(family=f,mae=100.,brier_multiclass=.4,interval_coverage=.9,interval_n=40,n=40,unique_base_decisions=10)
                        for f in ['A_no_change','Z_last_change','C_ridge','G_hybrid']])
    chosen=select_horizon(frame,frame,protocol,certified=True)
    assert not chosen['production_approved'] and chosen['tier']==2
    assert any('distinct holdout base decisions' in r for r in chosen['reasons'])

    pred=pd.DataFrame([
        *[dict(family='A_no_change',origin=f'2026-11-0{i}') for i in (1,2,3,4)],
        *[dict(family='G_hybrid',origin=f'2026-11-0{i}') for i in (1,2,3,4)],
        *[dict(family='Z_last_change',origin=f'2026-11-0{i}') for i in (2,4)],
    ])
    assert common_origins(pred, protocol['quantitative_families']+protocol['required_baselines'])=={f'2026-11-0{i}' for i in (1,2,3,4)}
