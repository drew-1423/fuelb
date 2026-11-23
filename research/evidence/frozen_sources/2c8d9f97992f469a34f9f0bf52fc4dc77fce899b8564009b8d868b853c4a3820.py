"""Observed shock subsets versus synthetic sensitivity/control tests: never mix their evidence."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import numpy as np
import pandas as pd
from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.forecasting.data import MarketFeatures,BEIRUT
from lebanon_fuel.forecasting.pipeline import load_bundle,dump,digest
from .metrics import score
from .policy import gate
from .ledger import ForecastLedger,now


def run(root):
    root=Path(root);folder=root/'reports/model_validation';protocol=json.loads((root/'config/validation_protocol.json').read_text())
    predictions=pd.read_csv(folder/'research_walk_forward_predictions.csv');subsets=[]
    for (regime,horizon,family),g in predictions.groupby(['regime','horizon','family']):
        for flag in ['rapid_increase','rapid_decline','high_volatility']:
            selected=g[g[flag]]
            subsets.append(dict(regime=regime,horizon=horizon,family=family,stress=flag,
                **(score(selected) if len(selected) else {'n':0,'change_mae_lbp':None,'direction_accuracy':None}),
                evidence='observed_latest_vintage_research_subset'))
    pd.DataFrame(subsets).to_csv(folder/'historical_stress_metrics.csv',index=False)
    store=MarketStore(root);records=store.ledger();cfg=json.loads((root/'config/forecasting_research.json').read_text());market=MarketFeatures(store,cfg)
    regimes=[]
    for name,start,end in [('subsidy_fx_crisis','2019-09-01','2023-05-11'),('fiscal_policy_outside_training','2025-05-29','2026-11-11')]:
        rows=[r for r in records if start<=r['source_date']<=end]
        regimes.append(dict(regime=name,start=start,end=end,source_records=len(rows),eligible_archive_records=sum(r['verification_status'] in cfg['target_statuses'] for r in rows),
            evaluated_forecasts=0,measured_error=None,status='out_of_domain_abstain',
            note='Analytical evidence boundary, not certification of every legal effective date'))
    dump(folder/'policy_stress_coverage.json',regimes)
    snapshots=pd.read_csv(root/'data/exports/forecasting/origin_features.csv');sensitivity=[]
    for regime in ['pre_crisis','recent_pre_fiscal']:
        for horizon in protocol['selection_horizons']:
            bundle=load_bundle(root/'data/models/part5'/regime/horizon)
            original=snapshots[(snapshots.regime==regime)&(pd.to_datetime(snapshots.origin,utc=True)==pd.Timestamp(bundle['fit_cutoff']))].copy();original['horizon']=horizon
            at=datetime.fromisoformat(original.origin.iloc[0])
            for shock in protocol['stress']['synthetic_shocks']+[None]:
                changed=original.copy();scenario='all_market_missing' if shock is None else f'latest_available_product_and_crude_quote_shock_{shock:+.0%}'
                if shock is None:
                    for col in changed:
                        if col.startswith(('x_nyh','x_brent','x_eurusd','x_italy','x_greece','x_us_','x_structural')):changed[col]=np.nan
                else:
                    altered=deepcopy(market);altered.cache={}
                    for sid in ['nyh_gasoline','brent_spot']:
                        h=altered.histories[sid];eligible=[i for i,r in enumerate(h) if datetime.fromisoformat(r['available_at'])<=at]
                        if eligible:h[eligible[-1]]['value']*=1+shock
                    feature=altered.at(at)
                    for key,value in feature.items():
                        if key.startswith('x_'):changed[key]=value
                    changed['x_structural_cost_gap']=changed.x_nyh_gasoline_value-changed.x_nyh_gasoline_mean20
                for family,model in bundle['models'].items():
                    base=float(model.predict(original)[0]);stressed=float(model.predict(changed)[0])
                    sensitivity.append(dict(regime=regime,horizon=horizon,family=family,origin=original.origin.iloc[0],scenario=scenario,
                        baseline_prediction=base if np.isfinite(base) else None,stressed_prediction=stressed if np.isfinite(stressed) else None,
                        output_change=stressed-base if np.isfinite(stressed) and np.isfinite(base) else None,
                        raw_model_returns_number=bool(np.isfinite(stressed)),actual_price=None,measured_accuracy=None,
                        evidence='synthetic_input_sensitivity_not_observed_event',production_allowed=False))
    pd.DataFrame(sensitivity).to_csv(folder/'synthetic_sensitivity.csv',index=False)
    # Isolated gate tests use an explicitly hypothetical approved fixture to test each reason independently.
    at=datetime.now(timezone.utc);origin=at.isoformat();before=(at-timedelta(hours=2)).isoformat()
    anchor={'official_verified':True,'known_at':before,'effective_at':before}
    current_market={'brent_spot':{'value':100,'available_at':before,'observation_date':(at-timedelta(days=1)).date().isoformat(),'vintage_certified':True}}
    model={'approved':True,'supported_regimes':['fixture'],'required_market':['brent_spot'],'intervals_validated':False,'probabilities_validated':False}
    context={'regime':'fixture','complete_decision_coverage':True,'maximum_market_age_days':21};controls=[]
    for scenario in ['control','missing_market','stale_market','future_input','fx_disruption','tax_change','government_intervention','input_out_of_support','wrong_regime','unverified_anchor']:
        a=deepcopy(anchor);m=deepcopy(current_market);c=deepcopy(context)
        if scenario=='missing_market':m={}
        elif scenario=='stale_market':m['brent_spot']['observation_date']=(at-timedelta(days=60)).date().isoformat()
        elif scenario=='future_input':m['brent_spot']['available_at']=(at+timedelta(hours=1)).isoformat()
        elif scenario=='wrong_regime':c['regime']='new_regime'
        elif scenario=='unverified_anchor':a['official_verified']=False
        elif scenario!='control':c[scenario]=True
        result=gate(origin,a,m,model,c);expected='eligible' if scenario=='control' else 'abstain'
        assert result['status']==expected
        controls.append(dict(scenario=scenario,evidence='synthetic_gate_fixture_not_production_approval',passed=True,**result))
    dump(folder/'stress_gate_checks.json',controls)
    # Real current inputs: record honest abstentions prospectively, never a fabricated price.
    latest=max((r for r in records if r['price_lbp_20l'] is not None),key=lambda r:r['source_date'])
    real_market={}
    for sid in ['brent_spot','nyh_gasoline']:
        h=store.history(sid,origin,'strict')
        if h:
            r=h[-1];real_market[sid]={k:r[k] for k in ['id','capture_id','value','unit','observation_date','available_at','source_url']}
            real_market[sid]['vintage_certified']=True  # Actual captured edition is known now; no historical-original claim.
    store.close()
    real_anchor=dict(price=latest['price_lbp_20l'],source_date=latest['source_date'],revision_id=latest['revision_id'],
        official_verified=latest['verification_status']=='document_verified',known_at=latest['retrieved_at'],effective_at=None)
    real_context={'regime':'current_2026_unverified_policy','complete_decision_coverage':False,'maximum_market_age_days':21}
    real_model={'approved':False,'supported_regimes':['pre_crisis','recent_pre_fiscal'],'required_market':['brent_spot','nyh_gasoline']}
    decision=gate(origin,real_anchor,real_market,real_model,real_context)
    ledger=ForecastLedger(root/'data/forecast_ledger.sqlite');selection=digest(folder/'production_selection.json');model_id='part6-decision-'+selection
    ledger.model(model_id,{'decision_sha256':selection,'approved':False})
    snapshot_id=ledger.snapshot(origin,'prospective',{'anchor':real_anchor,'market':real_market,'validation_decision':selection})
    ids=[]
    for horizon in protocol['horizons']:
        kind,steps=horizon.split('_');target={'kind':'decision' if kind=='decision' else 'calendar','steps':int(steps),'base_revision_id':latest['revision_id']}
        if kind=='day':target['endpoint']=(at.astimezone(BEIRUT)+timedelta(days=int(steps))).isoformat()
        ids.append(ledger.issue('part6-current-'+origin,origin,'prospective',model_id,snapshot_id,horizon,target,latest['price_lbp_20l'],reasons=decision['reasons']))
    dump(folder/'current_abstentions.json',dict(origin=origin,forecast_ids=ids,anchor=real_anchor,available_market_inputs=real_market,**decision))
    dump(folder/'ledger_integrity.json',ledger.integrity());ledger.close()
    return dict(observed_stress_groups=len(subsets),synthetic_sensitivity_cases=len(sensitivity),gate_checks=len(controls),prospective_abstentions=len(ids))
