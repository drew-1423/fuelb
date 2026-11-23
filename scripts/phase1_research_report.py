"""Recompute descriptive research metrics and live readiness; never fit or tune."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import tomllib
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from lebanon_fuel.storage.database import Store
from lebanon_fuel.dashboard.data import market_and_prices, live_ledger_rows
from lebanon_fuel.dashboard.scenarios import simulate, anchored_simulate
from lebanon_fuel.forecasting.live import current_context,generate
from lebanon_fuel.validation.decision_tracking import apply_live_calibration,settle_supplier_updates,dashboard_evidence,BATCH,FORECASTS,protocol_start
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.automation.health import build


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False,default=str)+'\n')


def metrics(actual,point,base,low=None,high=None):
    actual,point,base=map(lambda x:np.asarray(x,dtype=float),(actual,point,base));n=len(actual)
    if not n:return dict(n=0,mae_lbp=None,rmse_lbp=None,bias_lbp=None,direction_hits=None)
    error=point-actual;change=actual-base;predchange=point-base
    direction=lambda x:np.where(x>3000,1,np.where(x < -3000,-1,0))
    typical=float(np.mean(abs(change)))
    result=dict(n=n,mae_lbp=float(np.mean(abs(error))),rmse_lbp=float(np.sqrt(np.mean(error**2))),
        bias_lbp=float(np.mean(error)),direction_hits=int(np.sum(direction(predchange)==direction(change))),
        direction_n=n,mean_absolute_actual_change_lbp=typical,
        error_over_typical_change=float(np.mean(abs(error))/typical) if typical else None)
    if low is not None:
        low,high=np.asarray(low,float),np.asarray(high,float);valid=np.isfinite(low)&np.isfinite(high)
        result['interval_n']=int(valid.sum())
        result['interval_coverage']=float(np.mean((actual[valid]>=base[valid]+low[valid])&(actual[valid]<=base[valid]+high[valid]))) if valid.any() else None
        result['interval_mean_width_lbp']=float(np.mean(high[valid]-low[valid])) if valid.any() else None
    return result


def run(root=ROOT):
    root=Path(root);folder=root/'reports/trust_phase1';cfg=tomllib.loads((root/'config/project.toml').read_text())
    archive=pd.read_csv(root/'reports/research/expanded_coverage/dashboard_predictions.csv')
    base=archive[archive.family.eq('A_no_change')].set_index(['origin','target_source_date']).predicted_endpoint_price_lbp_20l
    last=archive[archive.family.eq('Z_last_change')].set_index(['origin','target_source_date']).predicted_endpoint_price_lbp_20l
    g=archive[archive.family.eq('G_hybrid')].copy();g['base']=[base.loc[(r.origin,r.target_source_date)] for r in g.itertuples()]
    g['last_change']=[last.loc[(r.origin,r.target_source_date)]-b for r,b in zip(g.itertuples(),g.base)]
    evaluation=[]
    for family in ('G_hybrid','Z_last_change','A_no_change'):
        d=archive[archive.family.eq(family)].sort_values(['origin','target_source_date'])
        keys=list(zip(d.origin,d.target_source_date));b=[base.loc[k] for k in keys]
        evaluation.append(dict(family=family,**metrics(d.endpoint_price_lbp_20l,d.predicted_endpoint_price_lbp_20l,b)))
    dev=pd.read_csv(root/'reports/forecasting/development_predictions.csv',usecols=['origin','horizon','regime','target_change_lbp_20l'])
    sample=dev[dev.horizon.eq('decision_1')&dev.regime.eq('stabilized_fx_2023_2026')].drop_duplicates('origin').target_change_lbp_20l.abs()
    cutoff=max(10000.,float(sample.quantile(.75)))
    changes=abs(g.endpoint_price_lbp_20l-g.base)
    segmented={name:metrics(d.endpoint_price_lbp_20l,d.predicted_endpoint_price_lbp_20l,d.base) for name,d in [
        ('quiet_or_normal',g[changes<cutoff]),('volatile_development_p75',g[changes>=cutoff]),('large_prior_move_proxy_not_verified_fiscal_decree',g[g.last_change.abs()>150000])]}
    holdout=pd.read_csv(root/'reports/model_validation/research_walk_forward_predictions.csv')
    horizons={}
    for h in ['decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30']:
        d=holdout[holdout.horizon.eq(h)&holdout.family.eq('G_hybrid')]
        horizons[h]=dict(point=metrics(d.endpoint_price_lbp_20l,d.predicted_endpoint_price_lbp_20l,d.base_price_lbp_20l),intervals={})
        for level,lo,hi in [('90','interval_low','interval_high'),('80','interval_80_low','interval_80_high')]:
            horizons[h]['intervals'][level]=metrics(d.endpoint_price_lbp_20l,d.predicted_endpoint_price_lbp_20l,d.base_price_lbp_20l,d[lo],d[hi])
    dump(folder/'evaluation.json',dict(evidence='Retrospective latest-vintage conditional archive research. All periods previously inspected; no untouched final test and no production approval.',
        dates=[g.target_source_date.min(),g.target_source_date.max()],shared_origin_comparisons=evaluation,
        segmentation=segmented,volatile_threshold_lbp=cutoff,threshold_source='development-only 75th percentile of absolute next-decision changes; floor 10000',
        regulatory_limit='No complete verified dated regulatory map; large-move proxy is not a verified fiscal-event evaluation.',
        historical_saved_holdout_by_horizon=horizons,model_tuning_performed=False))
    ledger_path=root/cfg['validation']['forecast_ledger']
    with closing(ForecastLedger(ledger_path)) as ledger:
        before=ledger.integrity();tail_before=ledger.db.execute('SELECT record_hash FROM forecasts ORDER BY id DESC LIMIT 1').fetchone()[0]
    with closing(Store(root,readonly=True)) as source:
        settled=settle_supplier_updates(root,cfg,source)
    at=datetime.now(timezone.utc);records,histories=current_context(root,cfg,at)
    policy=json.loads((root/'config/live_forecasting.json').read_text());decision=json.loads((root/cfg['validation']['decision_file']).read_text())
    forecast=generate(root,cfg,policy,decision,records,histories,at)
    apply_live_calibration(root,ledger_path,forecast['forecasts'],at.isoformat())
    readiness={r['horizon']:r.get('public_calibration',dict(status='abstained',reasons=r['critical_missing_inputs'])) for r in forecast['forecasts']}
    dump(folder/'calibration_readiness.json',dict(as_of=at.isoformat(),horizons=readiness,point_forecasts_generated=True,forecasts_written=False))
    view=dashboard_evidence(root,ledger_path)
    with closing(ForecastLedger(ledger_path)) as ledger:
        counts={}
        for r in ledger.db.execute(BATCH+FORECASTS.replace("WHERE f.horizon='decision_1'","WHERE 1=1"),{'start':protocol_start(root)}):
            group=counts.setdefault(r['horizon'],dict(attempts=0,hybrid_issued=0,abstentions=0,reasons={}))
            group['attempts']+=1;group['hybrid_issued']+=int(r['status']=='issued' and r['family']=='G_hybrid');group['abstentions']+=int(r['status']=='abstained')
            for reason in json.loads(r['reason_json']):group['reasons'][reason]=group['reasons'].get(reason,0)+1
        after=ledger.integrity();tail_after=ledger.db.execute('SELECT record_hash FROM forecasts ORDER BY id DESC LIMIT 1').fetchone()[0]
    assert before['forecasts']==after['forecasts'] and tail_before==tail_after and after['hash_chain_valid']
    prospective=[]
    for kind in ['official_match','provisional_match']:
        for cohort in ['government_backed','provisional']:
            cases=[r for r in view['cases'] if r['kind']==kind and r['cohort']==cohort]
            prospective.append(dict(evidence=kind,anchor_cohort=cohort,**metrics([r['actual'] for r in cases],[r['forecast'] for r in cases],[r['base'] for r in cases])))
    dump(folder/'prospective.json',dict(as_of=at.isoformat(),attempt_counts=counts,denominator='Complete scheduled/manual refresh attempts, not time uptime or independent decisions.',
        next_decision_scores=prospective,settlement_statuses=settled,forecast_hash_chain_preserved=True,counts_before=before,counts_after=after))
    template=json.loads((root/'config/structural_scenario_before_vat.json').read_text())
    latest=records[-1];product=histories['nyh_gasoline'][-1]['value']
    base_inputs=dict(product=product,fx=89500,freight=30,vat_percent=11,charge=300000,charge_taxable=True)
    original=simulate(template,**base_inputs,now=at)
    scenarios={}
    for name,inputs in [('unchanged',base_inputs),('fx_100000',dict(base_inputs,fx=100000)),('product_plus_10',dict(base_inputs,product=product+10))]:
        scenarios[name]=anchored_simulate(template,anchor=latest,baseline_inputs=base_inputs,scenario_inputs=inputs,now=at)
    dump(folder/'scenario_reconciliation.json',dict(original_unanchored=original,observed_anchor=latest,baseline_inputs=base_inputs,scenarios=scenarios))
    snap=market_and_prices(root,root/cfg['storage']['database'])
    # Read an actually issued row; dry-run generation is not an issuance clock.
    issued=live_ledger_rows(ledger_path,at=at.isoformat())
    next_rows=issued[issued.horizon.eq('decision_1')]
    row=next_rows.iloc[-1].to_dict() if len(next_rows) else None
    dump(folder/'health_contract.json',build(root,snap,row))
    print(json.dumps(dict(research_cases=len(g),live_next_decision_outcomes=len(view['cases']),horizons=len(readiness),settlement_statuses=settled),indent=2))


if __name__=='__main__':run()
