"""Strict generic walk-forward evaluator and explicitly non-strict research design."""
from bisect import bisect_right
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from lebanon_fuel.forecasting.data import known_at,midnight,features_at,label_for,MarketFeatures
from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.domain import utc_timestamp


def strict_eligible(frame):
    required=['origin','feature_known_at','base_known_at','feature_vintage_certified','target_definition_certified']
    if any(c not in frame for c in required):raise ValueError('Strict input requires explicit knowledge-time and certification fields')
    # utc_timestamp rejects naive timestamps; pd.to_datetime alone would invent UTC.
    for col in ['origin','feature_known_at','base_known_at']:
        for value in frame[col].dropna():utc_timestamp(str(value))
    origin=pd.to_datetime(frame.origin,utc=True)
    return (frame.feature_vintage_certified.eq(True)&frame.target_definition_certified.eq(True)&
        (pd.to_datetime(frame.feature_known_at,utc=True)<origin)&
        (pd.to_datetime(frame.base_known_at,utc=True)<origin))


def walk_forward_strict(frame,origins,fit,predict,minimum_train=24):
    """Fit callback may tune using its purged training frame only; never receives future labels.

    Prediction callback receives feature/anchor columns only. Final holdout rows can
    be predicted but cannot subsequently enter training in this evaluator.
    """
    eligible=strict_eligible(frame);output=[];gates=[]
    for value in frame.label_known_at.dropna():utc_timestamp(str(value))
    if not eligible.any():
        return pd.DataFrame(),pd.DataFrame([dict(origin=utc_timestamp(str(o)),train_rows=0,eligible_predictions=0,status='abstain_no_strict_eligible_snapshot') for o in origins])
    for stamp in origins:
        origin=pd.Timestamp(utc_timestamp(str(stamp)))
        train=frame[eligible & (pd.to_datetime(frame.origin,utc=True)<origin)&
            (pd.to_datetime(frame.label_known_at,utc=True)<origin)&frame.partition.ne('final_holdout')].copy()
        test=frame[eligible & (pd.to_datetime(frame.origin,utc=True)==origin)].copy()
        if train.base_revision_id.nunique()<minimum_train or test.empty:
            gates.append(dict(origin=origin.isoformat(),train_rows=len(train),eligible_predictions=len(test),status='abstain_insufficient_strict_data'));continue
        model=fit(train)
        columns=[c for c in test if c.startswith('x_') or c in {'origin','horizon','base_revision_id','base_price_lbp_20l','sequence_index','day_index'}]
        prediction=predict(model,test[columns])
        for (_,row),p in zip(test.iterrows(),prediction):
            output.append(dict(origin=row.origin,base_revision_id=row.base_revision_id,prediction=float(p),
                maximum_train_label_known_at=train.label_known_at.max(),strict=True))
    return pd.DataFrame(output),pd.DataFrame(gates)


def research_design(root,protocol,config):
    """Construct challenge labels separately; never alter the Part 5 snapshots."""
    store=MarketStore(root);market=MarketFeatures(store,config);full=store.ledger()
    records=[];excluded=[];origin_rows=[]
    try:
        for regime in protocol['regimes']:
            rows=[r for r in full if regime['start']<=r['source_date']<=regime['challenge_end']]
            times=[known_at(r) for r in rows];at=times[0];end=midnight(regime['challenge_end'])
            while at<=end:
                index=bisect_right(times,at)-1;r=rows[index]
                if (at.date()-datetime.fromisoformat(r['source_date']).date()).days>config['maximum_gap_days']:
                    at+=timedelta(days=1);continue
                features=features_at(rows[:index+1],index,at,market,config)
                if features is None:at+=timedelta(days=1);continue
                partition='exposed_temporal_challenge' if at.date().isoformat()>=regime['challenge_start'] else 'development_history'
                common=dict(origin=at.astimezone(timezone.utc).isoformat(),origin_beirut=at.isoformat(),origin_date=at.date().isoformat(),
                    regime=regime['id'],sequence_index=index,day_index=(at-times[0]).days,partition=partition,**features)
                origin_rows.append(common)
                horizons=[h for h in protocol['horizons'] if h.startswith('day_') or at==times[index]]
                for horizon in horizons:
                    target,reason=label_for(rows,index,at,horizon,config)
                    if reason:excluded.append(dict(regime=regime['id'],origin=common['origin'],horizon=horizon,partition=partition,reason=reason));continue
                    if pd.Timestamp(target['label_end'])>pd.Timestamp(end+timedelta(days=1)):continue
                    records.append(dict(**common,horizon=horizon,**target))
                at+=timedelta(days=1)
    finally:store.close()
    return pd.DataFrame(records),pd.DataFrame(origin_rows),pd.DataFrame(excluded)


def strict_database_audit(root,origins):
    store=MarketStore(root)
    domestic=dict(store.db.execute('SELECT COUNT(*) n,COUNT(publication_timestamp) publication_clocks,COUNT(official_effective_date) effective_dates,MIN(first_retrieved_at) first_capture FROM observations').fetchone())
    market=dict(store.db.execute('SELECT COUNT(*) n,COUNT(publication_timestamp) publication_clocks,COUNT(vintage_timestamp) original_vintages,MIN(first_seen_at) first_capture FROM market_observations').fetchone())
    latest_origin=max(origins)
    counts={s:len(store.history(s,latest_origin,mode='strict')) for s in ['brent_spot','nyh_gasoline','eurusd','italy_gasoline_ex_tax','greece_gasoline_ex_tax','us_gasoline_stocks','us_crude_stocks','us_refinery_utilization']}
    domestic_count=store.db.execute('SELECT COUNT(*) FROM decision_versions WHERE created_at<?',(utc_timestamp(latest_origin),)).fetchone()[0]
    store.close()
    if domestic_count or any(counts.values()):raise ValueError('New strict evidence exists: review eligibility rather than reusing the empty-history finding')
    return dict(domestic=domestic,market=market,strict_market_counts_at_latest_historical_origin=counts,
        latest_historical_origin=latest_origin,domestic_versions_known_before_latest_origin=domestic_count,
        strict_historical_forecasts=0,strict_performance_metrics=None,
        reason='No captured domestic versions or original market vintages existed at any evaluated historical origin')


def strict_design_from_lineage(root,design):
    """Actual capture/version knowledge times, never assumed date lags."""
    import json
    store=MarketStore(root)
    versions={r['id']:dict(r) for r in store.db.execute('SELECT id,created_at,payload_json FROM decision_versions')}
    sightings={(r['observation_id'],r['capture_id']):r['available_at'] for r in store.db.execute('SELECT observation_id,capture_id,available_at FROM market_sightings')}
    store.close();rows=[];cache={}
    for r in design.to_dict('records'):
        key=(r['regime'],r['origin'])
        if key not in cache:
            times=[versions[i]['created_at'] for i in json.loads(r['domestic_provenance_json'])]
            times += [sightings[tuple(pair)] for pair in json.loads(r['market_provenance_json'])]
            cache[key]=max(times)
        r['feature_known_at']=cache[key];r['base_known_at']=versions[r['base_revision_id']]['created_at']
        r['feature_vintage_certified']=True  # the exact captured edition is known at the recorded time, which is AFTER historical origins
        r['label_known_at']=max(versions[r['target_revision_id']]['created_at'],versions[r['witness_revision_id']]['created_at'])
        r['target_definition_certified']=False  # Complete sequence / effective clocks have not been established.
        rows.append(r)
    return pd.DataFrame(rows)


def load_holdout(root, protocol):
    """Read the physical evaluation export; never rebuild or fill missing targets."""
    frame = pd.read_csv(Path(root)/protocol['design_path'])
    required = {'origin', 'horizon', 'regime', 'partition', 'label_end',
                'target_change_lbp_20l', 'max_assumed_market_available_at'}
    if not required.issubset(frame):
        raise ValueError('Holdout export is missing required lineage columns')
    for column in ('origin', 'label_end', 'max_assumed_market_available_at'):
        for value in frame[column].dropna():
            utc_timestamp(str(value))
    days = pd.to_datetime(frame.origin, utc=True).dt.tz_convert('Asia/Beirut').dt.strftime('%Y-%m-%d')
    if not days.between(protocol['evaluation_start'], protocol['evaluation_end']).all():
        raise ValueError('Holdout origins outside the frozen evaluation window')
    if not frame.regime.eq(protocol['regime']).all() or frame.partition.eq('development').any():
        raise ValueError('Unexpected development rows or regime in holdout')
    if frame.duplicated(['horizon', 'origin']).any():
        raise ValueError('Duplicate holdout targets')
    if not np.isfinite(frame.target_change_lbp_20l).all():
        raise ValueError('Missing or invalid holdout outcomes')
    if (pd.to_datetime(frame.max_assumed_market_available_at, utc=True) > pd.to_datetime(frame.origin, utc=True)).any():
        raise ValueError('Market feature availability exceeds forecast origin')
    return frame.sort_values(['origin', 'horizon'])


def walk_forward_bundle(bundle, targets, development):
    """Frozen point model; uncertainty only sees residuals matured before each origin.

    Models receive feature/anchor columns, never outcomes. Actual values are joined
    after prediction. Latest-vintage availability remains an explicit assumption.
    """
    from lebanon_fuel.forecasting.pipeline import forecast
    from lebanon_fuel.forecasting.uncertainty import past_predictions, calibrate_for_ovx_regime
    development = development.copy()
    targets = targets.copy()
    for frame in (development, targets):
        for name in ('origin', 'label_end'):
            frame[name] = [pd.Timestamp(utc_timestamp(str(v))).isoformat() for v in frame[name]]
    history = development.copy()
    cutoff = pd.Timestamp(bundle['fit_cutoff'])
    if targets.empty:
        return pd.DataFrame()
    if cutoff > pd.to_datetime(targets.origin, utc=True).min():
        raise ValueError('Bundle fit cutoff is after an evaluation origin')
    maximum = bundle.get('training_maximum_label_end')
    if not maximum or pd.Timestamp(maximum) >= cutoff:
        raise ValueError('Training labels were not purged before the fit cutoff')
    if len(development) and ((pd.to_datetime(development.origin, utc=True) >= cutoff).any() or
                            (pd.to_datetime(development.label_end, utc=True) >= cutoff).any()):
        raise ValueError('Development calibration includes holdout or unmatured labels')
    families = list(bundle['models']) + ['H_ensemble']
    results = []
    for origin, target in targets.groupby('origin', sort=True):
        available = past_predictions(history, origin)
        ovx_regime = target['ovx_regime'].iloc[0] if 'ovx_regime' in target else None
        calibration = {f: calibrate_for_ovx_regime(available[available.family.eq(f)], ovx_regime,
                                                   bundle['config']) for f in families}
        keep = [c for c in target if c.startswith('x_') or c in {
            'origin', 'origin_beirut', 'origin_date', 'regime', 'horizon', 'base_revision_id',
            'base_source_date', 'base_price_lbp_20l', 'base_status', 'sequence_index', 'day_index', 'partition',
            'ovx_regime', 'ovx_regime_basis'}]
        pred = forecast(bundle['models'], bundle['ensemble'], None, calibration, target[keep], bundle['config'])
        if pred.empty:
            continue
        labels = [c for c in target if c not in pred and not c.startswith('x_')]
        pred = pred.merge(target[['origin', 'horizon'] + labels], on=['origin', 'horizon'], validate='many_to_one')
        pred['fit_cutoff'] = bundle['fit_cutoff']
        pred['maximum_training_label_end'] = maximum
        pred['evaluation_kind'] = '2026_HOLDOUT_ASSUMED_CLOSE_LATEST_VINTAGE_CONDITIONAL_TARGETS'
        results.append(pred)
        history = pd.concat([history, pred], ignore_index=True)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()
