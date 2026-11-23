"""Frozen-protocol, chronological proxy research. Never a real-time backtest."""
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import itertools
import json
import math
import numpy as np
import pandas as pd

from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.market.catalog import SERIES

WARNING = 'RETROSPECTIVE_LATEST_VINTAGE_NOT_REAL_TIME_BACKTEST'


def origin(day):
    return datetime.fromisoformat(day).replace(tzinfo=ZoneInfo('Asia/Beirut')).isoformat()


class MarketWindows:
    def __init__(self, rows, spec):
        self.rows = rows; self.spec = spec
        self.available = np.array([datetime.fromisoformat(r['available_at']).timestamp() for r in rows])
        self.values = np.array([r['value'] for r in rows])

    def mean(self, at, window, extra_lag):
        cutoff = datetime.fromisoformat(at)-timedelta(days=extra_lag)
        stop = int(np.searchsorted(self.available, cutoff.timestamp(), side='right'))
        if stop < window:
            return None
        rows = self.rows[stop-window:stop]
        # A known old value is not automatically a usable current quotation.
        if (cutoff-datetime.fromisoformat(rows[-1]['available_at'])).total_seconds() > self.spec.stale_days*86400:
            return None
        days = [datetime.fromisoformat(r['observation_date']) for r in rows]
        if any((b-a).days > 7 for a,b in zip(days,days[1:])):
            return None
        return float(self.values[stop-window:stop].mean()), rows


def candidate_grid(config):
    result = [dict(id=k,family=k,series=None,window=None,lag=None) for k in ('persistence','drift')]
    for family,sid,window,lag in itertools.product(
            ('linear','distributed_lag','rolling_linear','asymmetric'),config['series'],
            config['averaging_windows_observations'],config['additional_lags_calendar_days']):
        result.append(dict(id=f'{family}:{sid}:w{window}:lag{lag}',family=family,series=sid,window=window,lag=lag))
    return result


def feature_key(sid, window, lag):
    return f'delta__{sid}__w{window}__lag{lag}'


def build_dataset(store, config):
    ledger = store.ledger()
    latest = max(r['first_seen_at'] for r in store.db.execute('SELECT first_seen_at FROM market_observations'))
    windows = {sid:MarketWindows(store.history(sid,latest,mode='research'),SERIES[sid]) for sid in config['series']}
    lags = sorted({lag+offset for lag in config['additional_lags_calendar_days'] for offset in (0,7,14)})
    rows, excluded = [], []
    for previous,current in zip(ledger,ledger[1:]):
        day = current['source_date']
        regime = next((r for r in config['regimes'] if r['start'] <= previous['source_date'] < day <= r['end']),None)
        if regime is None:
            continue
        reason = None
        if current['verification_status'] not in config['target_statuses'] or previous['verification_status'] not in config['target_statuses']:
            reason='current_or_adjacent_prior_target_not_eligible'
        if (datetime.fromisoformat(day)-datetime.fromisoformat(previous['source_date'])).days > 14:
            reason='gap_over_14_days'
        if reason:
            excluded.append(dict(date=day,regime=regime['id'],reason=reason));continue
        at, before = origin(day), origin(previous['source_date'])
        row = dict(date=day,origin=at,previous_date=previous['source_date'],regime=regime['id'],
                   actual=float(current['price_lbp_20l']),previous=float(previous['price_lbp_20l']),
                   target_revision_id=current['revision_id'],previous_revision_id=previous['revision_id'],
                   target_status=current['verification_status'],previous_status=previous['verification_status'],
                   target_source_url=current['source_url'],target_observation_id=current['chosen_observation_id'],
                   information_status=WARNING,strict_backtest_eligible=False)
        row['change']=row['actual']-row['previous']
        provenance=set();max_available=[]
        for sid,w,lag in itertools.product(config['series'],config['averaging_windows_observations'],lags):
            now, old = windows[sid].mean(at,w,lag), windows[sid].mean(before,w,lag)
            if now is None or old is None:
                reason='missing_or_stale_market_window';break
            row[feature_key(sid,w,lag)] = now[0]-old[0]
            for data in (now[1],old[1]):
                for r in data:provenance.add((r['id'],r['capture_id']))
                max_available.append(data[-1]['available_at'])
        if reason:
            excluded.append(dict(date=day,regime=regime['id'],reason=reason));continue
        row['market_observation_capture_ids']=json.dumps(sorted(provenance))
        row['max_assumed_market_available_at']=max(max_available,key=lambda x:datetime.fromisoformat(x))
        assert datetime.fromisoformat(row['max_assumed_market_available_at']) <= datetime.fromisoformat(at)
        rows.append(row)
    return pd.DataFrame(rows),pd.DataFrame(excluded)


def design(frame, candidate):
    family = candidate['family']
    if family in {'persistence','drift'}:
        return np.empty((len(frame),0)), []
    sid,w,lag = candidate['series'],candidate['window'],candidate['lag']
    key = feature_key(sid,w,lag)
    if family == 'distributed_lag':
        keys = [feature_key(sid,w,lag+i) for i in (0,7,14)]
        return frame[keys].to_numpy(float),keys
    x = frame[key].to_numpy(float)
    if family == 'asymmetric':
        return np.column_stack((np.maximum(x,0),np.minimum(x,0))),['positive_'+key,'negative_'+key]
    return x.reshape(-1,1),[key]


def fit_predict(train, current, candidate, config):
    """Transforms and coefficients use only supplied past training labels."""
    if len(train) == 0 or max(train.date) >= current.date.iloc[0]:
        raise ValueError('Training labels must strictly precede prediction date')
    family = candidate['family']
    if family == 'persistence':
        return 0.,dict(intercept=0.,slopes={},n=len(train))
    if family == 'rolling_linear':
        train = train.tail(config['rolling_training_observations'])
    y = train.change.to_numpy(float)
    if family == 'drift':
        return float(y.mean()),dict(intercept=float(y.mean()),slopes={},n=len(train))
    x, names = design(train,candidate);new,_ = design(current,candidate)
    center=x.mean(axis=0);scale=x.std(axis=0);scale[scale==0]=1
    z=np.column_stack((np.ones(len(x)),(x-center)/scale))
    beta,_,rank,_=np.linalg.lstsq(z,y,rcond=None)
    slopes=beta[1:]/scale;intercept=float(beta[0]-center@slopes)
    prediction=float(intercept+new[0]@slopes)
    return prediction,dict(intercept=intercept,slopes=dict(zip(names,slopes.tolist())),n=len(train),rank=int(rank),
                           train_start=train.date.iloc[0],train_end=train.date.iloc[-1],scaler_mean=center.tolist(),scaler_std=scale.tolist())


def chronological_predictions(frame,candidate,config):
    results=[];errors=[]
    for i in range(config['minimum_train'],len(frame)):
        current=frame.iloc[[i]];r=current.iloc[0]
        change,fit=fit_predict(frame.iloc[:i],current,candidate,config)
        estimate=r.previous+change
        history=errors[-config['calibration_window']:]
        radius=None
        if len(history)>=config['minimum_calibration']:
            order=math.ceil((len(history)+1)*config['nominal_interval_coverage'])
            if order<=len(history):radius=float(sorted(history)[order-1])
        result=dict(date=r.date,origin=r.origin,regime=r.regime,model=candidate['id'],family=candidate['family'],
                    actual=r.actual,previous=r.previous,predicted=estimate,actual_change=r.change,predicted_change=change,
                    error=estimate-r.actual,lower=None if radius is None else max(0,estimate-radius),
                    upper=None if radius is None else estimate+radius,calibration_n=len(history),
                    train_n=fit['n'],train_end=frame.date.iloc[i-1],target_status=r.target_status,
                    target_revision_id=int(r.target_revision_id),previous_revision_id=int(r.previous_revision_id),
                    parameters_json=json.dumps(fit),information_status=WARNING)
        results.append(result)
        errors.append(abs(result['error'])) # only after prediction and its interval have been recorded
    return pd.DataFrame(results)


def metrics(frame):
    error=frame.predicted-frame.actual
    interval=frame.dropna(subset=['lower','upper'])
    changed=frame.actual_change!=0
    return dict(n=len(frame),start=frame.date.min(),end=frame.date.max(),
                mae_lbp_20l=float(abs(error).mean()),rmse_lbp_20l=float(np.sqrt((error**2).mean())),
                bias_lbp_20l=float(error.mean()),change_mae_lbp_20l=float(abs(frame.predicted_change-frame.actual_change).mean()),
                direction_accuracy=float((np.sign(frame.predicted_change)==np.sign(frame.actual_change)).mean()),
                changed_n=int(changed.sum()),direction_accuracy_nonzero=float((np.sign(frame.loc[changed,'predicted_change'])==np.sign(frame.loc[changed,'actual_change'])).mean()) if changed.any() else None,
                interval_n=len(interval),coverage_90=float(((interval.actual>=interval.lower)&(interval.actual<=interval.upper)).mean()) if len(interval) else None,
                mean_interval_width=float((interval.upper-interval.lower).mean()) if len(interval) else None,
                median_abs_error=float(abs(error).median()),max_abs_error=float(abs(error).max()))


def ecm_gate(dates, log_price, log_market):
    """No missing-time compression or artificial price interpolation for ECM tests."""
    from statsmodels.tsa.stattools import adfuller,coint
    gaps=np.diff(pd.to_datetime(dates).to_numpy()).astype('timedelta64[D]').astype(int)
    if len(dates)<60 or not np.all(gaps==7):
        return dict(eligible=False,reason='Requires >=60 consecutive weekly actual observations; irregular decisions cannot be silently regularized',n=len(dates))
    p_y=float(adfuller(log_price,autolag='AIC')[1]);p_x=float(adfuller(log_market,autolag='AIC')[1])
    p_dy=float(adfuller(np.diff(log_price),autolag='AIC')[1]);p_dx=float(adfuller(np.diff(log_market),autolag='AIC')[1])
    p_coint=float(coint(log_price,log_market,autolag='aic')[1])
    eligible=p_y>.05 and p_x>.05 and p_dy<.05 and p_dx<.05 and p_coint<.05
    return dict(eligible=eligible,n=len(dates),level_adf_p=[p_y,p_x],difference_adf_p=[p_dy,p_dx],cointegration_p=p_coint,
                reason='Statistical screen only; evidence for an economic long-run equation and historical FX is also required')


def training_diagnostics(store,frame,regime,config):
    from statsmodels.stats.diagnostic import breaks_cusumolsresid
    from statsmodels.api import OLS,add_constant
    train=frame[frame.date<regime['validation_start']]
    c=dict(family='linear',series='nyh_gasoline',window=1,lag=0)
    x,names=design(train,c);ols=OLS(train.change.to_numpy(),add_constant(x,has_constant='add')).fit()
    stat,pvalue,critical=breaks_cusumolsresid(ols.resid,ddof=2)
    asym=dict(c,family='asymmetric');ax,_=design(train,asym)
    # HC1 is a diagnostic for heteroskedasticity; event dependence remains a limitation.
    a=OLS(train.change.to_numpy(),add_constant(ax,has_constant='add')).fit(cov_type='HC1')
    asymmetry=a.t_test([0,1,-1])
    latest=store.db.execute('SELECT MAX(first_seen_at) FROM market_observations').fetchone()[0]
    mw=MarketWindows(store.history('nyh_gasoline',latest,mode='research'),SERIES['nyh_gasoline'])
    market=[mw.mean(origin(d),1,0)[0] for d in train.date]
    gate=ecm_gate(train.date.to_list(),np.log(train.actual.to_numpy()),np.log(market))
    return dict(regime=regime['id'],train_n=len(train),train_start=train.date.min(),train_end=train.date.max(),
                cusum_stat=float(stat),cusum_p=float(pvalue),cusum_status='Diagnostic, not a dated policy break or forecast feature',
                asymmetry_slope_positive=float(a.params[1]),asymmetry_slope_negative=float(a.params[2]),
                asymmetry_difference_p=float(np.asarray(asymmetry.pvalue).item()),
                asymmetry_status='Training only, HC1; small samples, serial dependence and proxy basis prevent causal interpretation',ecm=gate)


def run(root):
    root=Path(root)
    protocol_path=root/'config/structural_research.json';protocol_bytes=protocol_path.read_bytes()
    config=json.loads(protocol_bytes);freeze=json.loads((root/'research/evidence/structural_protocol_freeze.json').read_text())
    if sha256(protocol_bytes).hexdigest()!=freeze['sha256']:
        raise ValueError('Frozen protocol changed: use a separately versioned experiment')
    out=root/'reports/structural';out.mkdir(parents=True,exist_ok=True)
    export=root/'data/exports/structural';export.mkdir(parents=True,exist_ok=True)
    store=MarketStore(root)
    try:
        frame,excluded=build_dataset(store,config)
        frame.to_csv(export/'research_design_matrix.csv',index=False);excluded.to_csv(out/'excluded_observations.csv',index=False)
        candidates=candidate_grid(config);tuning=[];selection=[];diagnostics=[];byregime={}
        for regime in config['regimes']:
            f=frame[frame.regime==regime['id']].sort_values('date').reset_index(drop=True)
            pretest=f[f.date<regime['test_start']]
            diagnostics.append(training_diagnostics(store,f,regime,config))
            results=[]
            for candidate in candidates:
                preds=chronological_predictions(pretest,candidate,config)
                validation=preds[preds.date>=regime['validation_start']]
                if len(validation)==0:raise ValueError('No validation observations')
                entry=dict(regime=regime['id'],**candidate,**metrics(validation))
                tuning.append(entry);results.append(entry)
            family_winners=[]
            for family in config['families']:
                best=min((r for r in results if r['family']==family),key=lambda r:(r['mae_lbp_20l'],r['id']))
                family_winners.append(best)
            champion=min(family_winners,key=lambda r:(r['mae_lbp_20l'],r['id']))
            selection.append(dict(regime=regime['id'],champion=champion['id'],family_winners=[r['id'] for r in family_winners],
                                  selection_period=[regime['validation_start'],pretest.date.max()],
                                  test_period=[regime['test_start'],regime['end']]))
            byregime[regime['id']]=f
        # This artifact is saved BEFORE evaluating final-test outcomes.
        selection_path=out/'selection_frozen_before_test.json'
        if selection_path.exists():
            if json.loads(selection_path.read_text())['selection'] != selection:
                raise ValueError('Selection changed after holdout use: create a new declared experiment')
        else:
            selection_path.write_text(json.dumps(dict(protocol_sha256=freeze['sha256'],
                        selected_at=datetime.now(ZoneInfo('UTC')).isoformat(),selection=selection),indent=2))
        pd.DataFrame(tuning).to_csv(out/'validation_grid.csv',index=False)
        final=[];score=[]
        for sel,regime in zip(selection,config['regimes']):
            for model in sel['family_winners']:
                candidate=next(c for c in candidates if c['id']==model)
                pred=chronological_predictions(byregime[regime['id']],candidate,config)
                pred=pred[pred.date>=regime['test_start']].copy()
                pred['selected_on_validation']=model==sel['champion'];final.append(pred)
                score.append(dict(regime=regime['id'],model=model,selected_on_validation=model==sel['champion'],**metrics(pred)))
        final=pd.concat(final,ignore_index=True)
        final.to_csv(export/'historical_proxy_predictions_RESEARCH_ONLY.csv',index=False)
        pd.DataFrame(score).to_csv(out/'test_metrics.csv',index=False)
        (out/'training_diagnostics.json').write_text(json.dumps(diagnostics,indent=2))
        strict_counts={sid:len(store.history(sid,origin(frame.date.max()),mode='strict')) for sid in config['series']}
        # A zero count at the latest origin proves zero eligible history at all earlier origins.
        earliest_market=store.db.execute('SELECT MIN(available_at) FROM market_sightings').fetchone()[0]
        earliest_target=store.db.execute('SELECT MIN(first_retrieved_at) FROM observations').fetchone()[0]
        current=[]
        for sid in config['series']:
            h=store.history(sid,datetime.now(ZoneInfo('UTC')).isoformat(),mode='strict')
            if h:current.append({k:h[-1][k] for k in ('series_id','observation_date','value','unit','available_at','source_url')})
        manifest=dict(created_at=datetime.now(ZoneInfo('UTC')).isoformat(),information_status=WARNING,protocol_sha256=freeze['sha256'],
                      rows=len(frame),regime_rows=frame.groupby('regime').size().to_dict(),excluded_rows=len(excluded),
                      strict_market_counts_at_last_origin=strict_counts,strict_evaluation_n=0 if not any(strict_counts.values()) else None,
                      earliest_market_knowledge_time=earliest_market,earliest_target_capture_time=earliest_target,
                      dataset_sha256=sha256((export/'research_design_matrix.csv').read_bytes()).hexdigest(),
                      target_status_counts=frame.target_status.value_counts().to_dict(),current_proxy_inputs=current,
                      metrics=score,selection=selection)
        (out/'run_manifest.json').write_text(json.dumps(manifest,indent=2))
        return manifest
    finally:store.close()
