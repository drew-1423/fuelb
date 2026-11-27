"""Prospective forecasts with explicit evidence tiers and immutable input lineage."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from collections import Counter
from hashlib import sha256
import json
import math
import sqlite3

import numpy as np
import pandas as pd

from lebanon_fuel.domain import BEIRUT, VERIFIED, PROVISIONAL_PRICE, current_price_history, supplier_agreement
from lebanon_fuel.market.catalog import SERIES
from lebanon_fuel.market.store import MarketStore, close_availability
from lebanon_fuel.structural.engine import price
from lebanon_fuel.validation.policy import gate
from lebanon_fuel.validation.live_score import update_records
from .data import MarketFeatures, features_at
from .pipeline import load_bundle
from .uncertainty import residual_probabilities
from .models import structural_matrix

LABELS = {1: 'VALIDATED FORECAST', 2: 'QUANTITATIVE MODEL FORECAST',
          3: 'STRUCTURAL ESTIMATE', 4: 'BASELINE FORECAST'}
HORIZONS = ('decision_1', 'decision_2', 'decision_4', 'day_1', 'day_3', 'day_7', 'day_14', 'day_30')


def current_context(root, settings, at):
    """Actual capture/reconciliation clocks bound every input used now."""
    with closing(MarketStore(root, settings['storage']['database'], readonly=True)) as store:
        records = []
        for row in store.db.execute('''SELECT d.* FROM decision_versions d JOIN
            (SELECT source_date,MAX(id) id FROM decision_versions WHERE created_at<? GROUP BY source_date) v
            ON d.id=v.id ORDER BY d.source_date''', (at.isoformat(),)):
            records.append(dict(json.loads(row['payload_json']), revision_id=row['id'], version_known_at=row['created_at']))
        histories = {sid: store.history(sid, at.isoformat(), 'captured') for sid in SERIES}
    # A reviewed settlement document can supply clocks absent from archive rows.
    # Tie it to the exact source revision and retain the review's actual knowledge time.
    ledger_path = root/settings['validation']['forecast_ledger']
    if records and ledger_path.exists():
        with closing(sqlite3.connect(f'{ledger_path.as_uri()}?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            reviewed = db.execute('''SELECT * FROM outcomes WHERE source_revision_id=?
                AND verification_status='document_verified' AND publication_timestamp IS NOT NULL
                AND effective_timestamp IS NOT NULL AND available_at<? AND created_at<? ORDER BY id DESC LIMIT 1''',
                (records[-1]['revision_id'], at.isoformat(), at.isoformat())).fetchone()
            if reviewed and reviewed['price']==records[-1]['price_lbp_20l']:
                records[-1].update(verification_status='document_verified',
                    effective_timestamp=reviewed['effective_timestamp'],publication_timestamp=reviewed['publication_timestamp'],
                    reviewed_outcome_id=reviewed['id'],
                    version_known_at=max(records[-1]['version_known_at'],reviewed['available_at'],reviewed['created_at']))
    return records, histories


def anchor_check(records, at, maximum_age, *, allow_provisional=False):
    if not records:
        return None, 'No Lebanese price observations. Collect IPT and the official ministry archive.'
    latest = records[-1]
    # Never step backwards over a newer disputed or supplier-only observation.
    eligible = VERIFIED | ({PROVISIONAL_PRICE} if allow_provisional else set())
    if latest['verification_status'] not in eligible or not latest.get('price_lbp_20l') or not math.isfinite(latest['price_lbp_20l']) or latest['price_lbp_20l'] <= 0:
        if allow_provisional:
            return None, 'The newest price needs independent corroboration or has conflicting values.'
        return None, 'The latest price lacks official corroboration or has conflicting values. Verify its original ministry decision.'
    if latest['verification_status'] == PROVISIONAL_PRICE:
        sources = {row['id'] for row in latest.get('corroborating_sources', [])}
        if not supplier_agreement(sources):
            return None, 'The provisional price needs matching IPT and a second dated source.'
    age = (at.astimezone(BEIRUT).date() - date.fromisoformat(latest['source_date'])).days
    if age < 0 or age > maximum_age:
        return None, 'The latest eligible price is stale or future-dated. Collect a current price and reconcile it with an independent source.'
    known = latest.get('version_known_at') or latest.get('retrieved_at')
    if not known or datetime.fromisoformat(known) >= at:
        return None, 'The verified price was unavailable at the forecast origin. Refresh after reconciliation.'
    return latest, None


def strict_feature_frame(root, records, histories, at, horizon):
    config = json.loads((root/'config/forecasting_research.json').read_text())
    # A source-agreed historical price stays eligible after the next
    # government-backed update. Otherwise the preceding change becomes NaN.
    config['target_statuses'] = sorted(set(config['target_statuses']) | {PROVISIONAL_PRICE})
    # A supplementary archive may repeat the last corroborated station price
    # between two real updates. It is evidence of the same price, not another
    # pricing event, so it must not break the latest domestic change. Keep
    # differing or uncorroborated observations as barriers to inference.
    feature_records = update_records(records)
    kept = {id(row) for row in feature_records}
    ignored_revisions = [row.get('revision_id') for row in records if id(row) not in kept]
    market = MarketFeatures.__new__(MarketFeatures)
    market.config, market.cache, market.mode = config, {}, 'as_of_close'
    market.histories = {}
    for sid in config['series']:
        rows = []
        for row in histories.get(sid, []):
            # Only vintages captured before NOW may enter a live forecast. Within
            # that vintage, historical window endpoints use observation closes.
            if pd.Timestamp(row['available_at']) >= pd.Timestamp(at):
                continue
            window_at = datetime.fromisoformat(close_availability(row['observation_date'], SERIES[sid]))
            if row.get('publication_timestamp'):
                window_at = max(window_at, datetime.fromisoformat(row['publication_timestamp']))
            if window_at >= at:
                continue
            rows.append(dict(row, captured_available_at=row['available_at'], available_at=window_at.isoformat(),
                             availability_basis='historical_close_window_in_vintage_captured_before_live_origin'))
        market.histories[sid] = sorted(rows, key=lambda r: r['observation_date'])
    market.timestamps = {sid: np.array([datetime.fromisoformat(r['available_at']).timestamp() for r in history])
                         for sid, history in market.histories.items()}
    values = features_at(feature_records, len(feature_records)-1, at.astimezone(BEIRUT), market, config)
    if values is None:
        raise ValueError('Insufficient verified domestic feature history')
    values.update(horizon=horizon, origin=at.isoformat(), sequence_index=len(records)-1,
                  day_index=(at.date()-date(1970,1,1)).days,
                  ignored_redundant_supplementary_revisions=ignored_revisions)
    return pd.DataFrame([values])


def model_prediction(bundle, family, frame):
    if family == 'H_ensemble':
        weights = bundle['ensemble']['weights']
        if not weights or any(w < 0 for w in weights.values()) or not math.isclose(sum(weights.values()), 1.):
            raise ValueError('Invalid saved ensemble weights')
        return sum(float(bundle['models'][f].predict(frame)[0])*w for f,w in weights.items())
    return float(bundle['models'][family].predict(frame)[0])


def quantitative(root, candidate, frame, anchor, market, at, maximum_market_age_days=7,
                 allow_lagged_spot=False, lagged_spot_maximum_age_days=14):
    if candidate['family'] == 'D_sarimax':
        raise ValueError('SARIMAX needs a reviewed live sequence-index bridge')
    expiry = candidate.get('valid_through')
    if expiry and at.astimezone(BEIRUT).date().isoformat() > expiry:
        raise ValueError('Saved quantitative model has an explicit legacy expiry')
    path = root/candidate['path']
    if sha256((path/'bundle.joblib').read_bytes()).hexdigest() != candidate['artifact_sha256']:
        raise ValueError('Quantitative artifact checksum mismatch')
    bundle = load_bundle(path)
    if pd.Timestamp(bundle['fit_cutoff']) >= pd.Timestamp(at):
        raise ValueError('Model was fitted after the forecast origin')
    lagged_inputs=[]
    for sid in candidate['required_market']:
        row = market.get(sid)
        age=(at.astimezone(BEIRUT).date()-date.fromisoformat(row['observation_date'])).days if row else None
        lagged_spot=(allow_lagged_spot and sid in {'nyh_gasoline','brent_spot'}
                     and row is not None and maximum_market_age_days < age <= lagged_spot_maximum_age_days)
        maximum_age=lagged_spot_maximum_age_days if lagged_spot else maximum_market_age_days
        if not row or age is None or not 0 <= age <= maximum_age or pd.Timestamp(row['available_at']) >= pd.Timestamp(at):
            raise ValueError(f'Missing or stale required commodity input (maximum {maximum_age} days): '+sid)
        if lagged_spot:
            lagged_inputs.append(dict(series=sid,observation_date=row['observation_date'],age_calendar_days=age,
                                      status='lagged_spot_8_14d'))
    family = candidate['family']
    members = list(bundle['ensemble']['weights']) if family == 'H_ensemble' else [family]
    # Sparse optional features use the transformations fitted in development.
    # Critical commodity/anchor inputs cannot be rescued by median imputation.
    if not np.isfinite(frame.x_domestic_change_lag1.iloc[0]):
        raise ValueError('Required quantitative features unavailable: domestic change')
    if any(f in {'B_structural_proxy','G_hybrid'} for f in members) and not np.isfinite(frame.x_structural_delta_lbp_20l.iloc[0]):
        raise ValueError('Required quantitative features unavailable: structural delta')
    change = model_prediction(bundle, family, frame)
    if not math.isfinite(change) or anchor['price_lbp_20l']+change <= 0:
        raise ValueError('Model produced an invalid absolute price')
    return change, bundle, lagged_inputs


def driver_contributions(bundle, family, frame):
    """Exact additive model attributions in LBP/20 L; not causal financial claims."""
    keys = ('commodity_pass_through','lagged_domestic_momentum','fiscal_shock','other_features','baseline_intercept')
    result = dict.fromkeys(keys, 0.)
    if family == 'H_ensemble':
        for name, weight in bundle['ensemble']['weights'].items():
            part = driver_contributions(bundle,name,frame)
            for key in keys:result[key] += weight*part[key]
    else:
        model = bundle['models'][family]
        if family.startswith('A_'):
            result['baseline_intercept'] = float(model.extra['constant'])
        elif family == 'Z_last_change':
            result['lagged_domestic_momentum'] = float(model.predict(frame)[0])
        else:
            if family in {'B_structural_proxy','G_hybrid'}:
                values = structural_matrix(frame,model.extra['structural_fill_values'])[0]*model.extra['structural_coefficients']
                for key,value in zip(keys[:3],values):result[key] += float(value)
                result['baseline_intercept'] += float(model.extra['intercept_lbp'])
            if family != 'B_structural_proxy':
                transformed = model.transform.transform(frame[model.columns])
                names = model.transform.get_feature_names_out(model.columns)
                fitted = model.fitted
                if hasattr(fitted,'coef_'):
                    contributions = transformed[0]*fitted.coef_
                    intercept = float(fitted.intercept_)
                elif hasattr(fitted,'booster_'):
                    shap = np.asarray(fitted.booster_.predict(transformed,pred_contrib=True))[0]
                    contributions,intercept = shap[:-1],float(shap[-1])
                else:
                    from catboost import Pool
                    shap = fitted.get_feature_importance(Pool(transformed),type='ShapValues')[0]
                    contributions,intercept = shap[:-1],float(shap[-1])
                result['baseline_intercept'] += intercept
                for name,value in zip(names,contributions):
                    if any(s in name for s in ('brent','nyh','rbob','gasoil','refined_gasoline','structural')):
                        key='commodity_pass_through'
                    elif 'domestic_change' in name:key='lagged_domestic_momentum'
                    elif 'fiscal_shock' in name:key='fiscal_shock'
                    else:key='other_features'
                    result[key] += float(value)
    if not math.isclose(sum(result.values()),model_prediction(bundle,family,frame),rel_tol=1e-6,abs_tol=.1):
        raise ValueError('Driver contribution reconciliation failed')
    result.update(unit='LBP/20L',method='Exact linear contributions / tree SHAP, ensemble weighted; statistical attribution, not causation')
    return result


def estimate_next_decision_date(records, origin_beirut):
    """Return date-only projections from the last 20 verified decision intervals.

    A cadence estimate is not a government notice or an effective-time assertion.
    No holiday calendar or extraordinary-announcement evidence is available here.
    """
    if origin_beirut.tzinfo is None:raise ValueError('Schedule origin must be timezone-aware')
    local = origin_beirut.astimezone(BEIRUT)
    dates = sorted({date.fromisoformat(r['source_date']) for r in records
        if r['verification_status'] in VERIFIED and date.fromisoformat(r['source_date']) <= local.date()
        and (not r.get('version_known_at') or pd.Timestamp(r['version_known_at']) < pd.Timestamp(local))})[-21:]
    intervals = [(b-a).days for a,b in zip(dates,dates[1:])]
    frequencies = Counter(d.weekday() for d in dates)
    supported = len(dates)>=3 and frequencies[1]>0 and frequencies[4]>0 and (frequencies[1]+frequencies[4])/len(dates)>=.5
    weekdays = [1,4] if supported else [d for d,_ in frequencies.most_common(2) if d<5]
    basis = 'Empirical Tue/Fri Ministry cadence' if supported else 'Sparse empirical weekday estimate; standard Tue/Fri cadence unconfirmed'
    if not weekdays:
        return dict(dates={},schedule_basis='Insufficient verified scheduling observations',interval_n=len(intervals),estimated=True)
    cursor = max(local.date(), dates[-1]);future=[]
    while len(future)<4:
        cursor += timedelta(days=1)
        if cursor.weekday() in weekdays:future.append(cursor.isoformat())
    return dict(dates={f'decision_{n}':future[n-1] for n in (1,2,4)},schedule_basis=basis,
                interval_n=len(intervals),median_interval_days=float(np.median(intervals)) if intervals else None,
                weekday_counts={str(k):v for k,v in frequencies.items()},estimated=True,
                limitations='Date estimates only; announcement times, holidays and extraordinary decisions are unknown')


def structural(root, request_path, horizon, at):
    request = json.loads((root/request_path).read_text())
    if request.get('forecast_horizon') != horizon:
        raise ValueError('Structural inputs do not describe this forecast horizon')
    if request.get('mode') == 'reconciliation':
        raise ValueError('Historical annex reconciliation cannot serve as a future forecast')
    if pd.Timestamp(request['origin']) > pd.Timestamp(at) or pd.Timestamp(request['expires_at']) < pd.Timestamp(at):
        raise ValueError('Structural inputs are future-dated or expired')
    if horizon.startswith('day_') and request['effective_date'] != (at.astimezone(BEIRUT)+timedelta(days=int(horizon.split('_')[1]))).date().isoformat():
        raise ValueError('Structural scenario does not describe the target calendar date')
    request['origin'] = at.isoformat()
    result = price(request)
    return float(result['price_lbp_20l']), result


def historical_error(root, family, horizon):
    path = root/'reports/model_validation/metrics.csv'
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    subset = frame[(frame.regime=='stabilized_fx_2023_2026') & (frame.horizon==horizon) & (frame.family==family)]
    if subset.empty:
        return None
    row = subset.iloc[0]
    return dict(n=int(row.n), distinct_base_decisions=int(row.distinct_base_decisions),
                mae_lbp=float(row.change_mae_lbp), direction_accuracy=float(row.direction_accuracy),
                first_origin=row.first_origin, last_origin=row.last_origin,
                evidence='2026 conditional archive holdout; assumed close availability, sparse outcomes, selected on this sample.',
                source='reports/model_validation/metrics.csv')


def baseline(records, anchor, horizon):
    # Tier 4 has no fresh market or structural evidence. Extrapolating one old
    # move across several decisions conflicts with a flat calendar baseline.
    # Use the same persistence assumption at every horizon until better inputs
    # support a dated event path.
    return 0.0, 'A_no_change', 'Persistence of the latest verified price. Central assumption of no net change through the target horizon.'


def generate(root, settings, config, decision, records, histories, at, *, research_sensitivity=False):
    records = current_price_history(records)
    anchor, problem = anchor_check(records, at, config['anchor_maximum_age_days'], allow_provisional=True)
    provisional = bool(anchor and anchor['verification_status'] == PROVISIONAL_PRICE)
    market = {sid: dict(history[-1], vintage_certified=True) for sid, history in histories.items() if history}
    results = []
    pinned = config.get('pinned_family')
    schedule = estimate_next_decision_date(records, at)
    for horizon in HORIZONS:
        kind, steps = horizon.split('_')
        endpoint = (at.astimezone(BEIRUT)+timedelta(days=int(steps))).isoformat() if kind=='day' else None
        output = dict(horizon=horizon, origin=at.isoformat(), endpoint=endpoint,
                      target_label=f'Price after {steps} recorded update(s)' if kind=='decision' else f'Prevailing price in {steps} calendar days',
                      decision_date=schedule['dates'].get(horizon), scheduled_effective=schedule['dates'].get(horizon),
                      schedule_basis=schedule['schedule_basis'] if kind=='decision' else None,
                      schedule_estimated=kind=='decision', schedule_details=schedule if kind=='decision' else None, tier=None, label='FORECAST UNAVAILABLE', status='abstain',
                      predicted_price=None, predicted_change=None, percentage_change=None,
                      interval=None, probabilities=None, uncertainty='Unavailable', attempts=[], critical_missing_inputs=[])
        if pinned:
            output['pinned_family'] = pinned
        if problem:
            output['critical_missing_inputs'] = [problem]
            results.append(output)
            continue
        missing = ['Exact publication/effective clocks and complete official decision sequence are unresolved.',
                   'Current tax/FX formula and licensed Mediterranean gasoline assessment are unavailable.']
        candidates = sorted((c for c in config['quantitative_candidates'] if c['horizon']==horizon
                             and (not pinned or c['family']==pinned)), key=lambda c:c['development_mae'])
        frame = None
        for tier in (1, 2):
            errors = []
            if tier == 1 and provisional:
                errors.append('Provisional price anchors support research estimates only')
            elif tier==1 and not (settings['forecasting']['enabled'] and settings['validation']['production_approved'] and decision.get('production_approved')):
                errors.append('No approved production model in the validation decision')
            else:
                for candidate in candidates:
                    if tier==1 and decision.get('selection',{}).get(horizon,{}).get('production_model') != candidate['model_version']:
                        continue
                    try:
                        if frame is None:
                            frame = strict_feature_frame(root, records, histories, at, horizon)
                        if tier==1:
                            spec = decision['selection'][horizon]
                            if not spec.get('review_evidence') or not decision.get('decided_at') or pd.Timestamp(decision['decided_at']) >= pd.Timestamp(at):
                                raise ValueError('Artifact-specific dated review evidence is missing')
                            if spec.get('artifact_sha256') != candidate['artifact_sha256']:
                                raise ValueError('Approved artifact does not match saved model')
                            production_gate = gate(at.isoformat(), dict(official_verified=anchor['verification_status']=='document_verified',
                                known_at=anchor.get('version_known_at'), effective_at=anchor.get('effective_timestamp')),
                                market, dict(approved=True,supported_regimes=[candidate['regime']],required_market=candidate['required_market']),
                                dict(regime=candidate['regime'],complete_decision_coverage=spec.get('complete_decision_coverage',False),
                                     maximum_market_age_days=config.get('market_maximum_age_days',7)))
                            if production_gate['status'] != 'eligible':
                                raise ValueError(', '.join(production_gate['reasons']))
                        change, bundle, lagged_inputs = quantitative(
                            root,candidate,frame,anchor,market,at,
                            config.get('market_maximum_age_days',7),allow_lagged_spot=(tier==2),
                            lagged_spot_maximum_age_days=config.get('tier2_lagged_spot_maximum_age_days',14))
                        selected = dict(tier=tier, methodology=candidate['family'], family=candidate['family'],
                                      model_version=candidate['model_version'], artifact_sha256=candidate['artifact_sha256'],
                                      predicted_change=change, performance=candidate['performance'],
                                      market_input_mode='strict_captured_vintage',lagged_market_inputs=lagged_inputs)
                        spec = decision.get('selection',{}).get(horizon,{})
                        # The selection calibration is tied to this exact model artifact.
                        matches = spec.get('artifact_sha256')==candidate['artifact_sha256'] and spec.get('family')==candidate['family']
                        current_regime = frame.iloc[0].get('ovx_regime')
                        regime_calibration = bundle.get('calibrations_by_ovx_regime',{}).get(candidate['family'],{}).get(current_regime)
                        if matches:
                            calibration = spec.get('calibrations_by_ovx_regime',{}).get(current_regime) or spec.get('calibration',{})
                        elif regime_calibration and regime_calibration.get('radius') is not None:
                            calibration = regime_calibration
                        else:
                            calibration = bundle.get('calibrations',{}).get(candidate['family'],{})
                        maximum = calibration.get('maximum_label_end')
                        if maximum and pd.Timestamp(maximum)>=pd.Timestamp(at):
                            raise ValueError('Calibration contains outcomes unavailable at forecast origin')
                        radius = calibration.get('radius')
                        if radius is not None:
                            radius = float(radius)
                            if not math.isfinite(radius) or radius < 5000:raise ValueError('Invalid conformal interval radius')
                            selected.update(interval=[change-radius,change+radius],interval_nominal=.9,
                                uncertainty='90% nominal horizon-conditioned conformal interval; empirical coverage is sample dependent')
                            residuals=np.asarray(calibration.get('residuals',[]),float)
                            if len(residuals) and np.isfinite(residuals).all():
                                floor=float(calibration.get('minimum_half_width_lbp',5000.))
                                q10=float(calibration.get('residual_quantile_10',np.quantile(residuals,.10,method='lower')))
                                q90=float(calibration.get('residual_quantile_90',np.quantile(residuals,.90,method='higher')))
                                selected['interval_80']=[change+min(q10,-floor),change+max(q90,floor)]
                                selected['interval_80_nominal']=.8
                        else:
                            selected['uncertainty']='Insufficient matured residuals for a finite calibrated 90% interval'
                        probabilities=residual_probabilities([change],calibration)[0]
                        if np.isfinite(probabilities).all():selected['probabilities']=[float(p) for p in probabilities]
                        selected.update(calibration_n=calibration.get('n',0),
                            calibration_maximum_label_end=maximum,probability_deadband_lbp=3000,
                            probability_order=['decrease','no_change','increase'],
                            probability_status=calibration.get('status','unavailable'),
                            ovx_regime=current_regime,
                            ovx_regime_conditioning=calibration.get('ovx_regime_conditioning','pooled_calibration'),
                            calibration_ovx_regime=calibration.get('requested_ovx_regime'),
                            driver_contributions=driver_contributions(bundle,candidate['family'],frame))
                        if tier==1 and (radius is None or selected.get('probabilities') is None):
                            raise ValueError('Approved uncertainty evidence is incomplete')
                        if research_sensitivity and candidate['family'] == 'G_hybrid':
                            # Research challenger using the same bundle and available inputs.
                            # Zero the single lag feature, keeping other lag variables intact.
                            counterfactual = frame.assign(x_domestic_change_lag1=0.0)
                            try:
                                challenger = anchor['price_lbp_20l'] + model_prediction(bundle, 'G_hybrid', counterfactual)
                                if math.isfinite(challenger) and challenger > 0:
                                    selected['shadow_zero_domestic_lag1_price'] = challenger
                            except (ValueError, KeyError, TypeError, RuntimeError, ArithmeticError):
                                pass  # A missing challenger never changes the public forecast.
                        output.update(selected)
                        break
                    except (ValueError, KeyError, OSError, ImportError, TypeError, RuntimeError, ArithmeticError, IndexError) as exc:
                        errors.append(str(exc))
            output['attempts'].append(dict(tier=tier,reasons=sorted(set(errors)) or ([] if output['tier'] else ['No eligible artifact registered'])))
            if output['tier']:
                break
        if not output['tier'] and pinned:
            output['critical_missing_inputs'] = output['attempts'][-1]['reasons']
            results.append(output)
            continue
        if not output['tier'] and not provisional:
            request = config.get('structural_requests',{}).get(horizon)
            try:
                if not request:raise ValueError('Missing current benchmark window, pricing FX, freight and dated tax/margin inputs')
                estimated, details = structural(root,request,horizon,at)
                output.update(tier=3,methodology='Dated structural cost engine with explicit scenario inputs',family='structural',
                              model_version='structural-live-v1',predicted_change=estimated-anchor['price_lbp_20l'],structural_output=details,
                              uncertainty='Conditional input sensitivity; probability coverage unmeasured')
            except (ValueError, KeyError, OSError, TypeError, ArithmeticError) as exc:
                output['attempts'].append(dict(tier=3,reasons=[str(exc)]))
        if not output['tier']:
            change, family, methodology = baseline(records,anchor,horizon)
            output.update(tier=4,methodology=methodology,family=family,model_version='baseline-live-v1-'+family,
                          predicted_change=change,performance=historical_error(root,family,horizon))
        output.update(status='issued', label=LABELS[output['tier']], base_price=anchor['price_lbp_20l'],
                      base_source_date=anchor['source_date'],base_revision_id=anchor['revision_id'],
                      anchor_verification=anchor['verification_status'],
                      predicted_price=anchor['price_lbp_20l']+output['predicted_change'],
                      percentage_change=100*output['predicted_change']/anchor['price_lbp_20l'],
                      validation_status='production_validated' if output['tier']==1 else 'unapproved_research',
                      critical_missing_inputs=[] if output['tier']==1 else missing,
                      future_market_assumption='Future commodity prices are unknown. No numerical market path is supplied. Policy and commodity shocks may change the result.')
        if output['tier'] == 4:
            output['interval']=output['probabilities']=None
            if provisional:
                output['methodology'] = 'Persistence of the latest price supported by matching dated sources.'
            output['uncertainty']='No calibrated prediction interval or directional probabilities available. Historical MAE describes the cited research sample only.'
        if provisional:
            output['label'] += ' · PROVISIONAL PRICE ANCHOR'
            output['anchor_sources'] = anchor.get('corroborating_sources', [])
            output['critical_missing_inputs'] = [
                'IPT and another dated source agree on the starting price.',
                *output['critical_missing_inputs']]
            for key in ('interval', 'interval_nominal', 'interval_80', 'interval_80_nominal', 'probabilities'):
                output.pop(key, None)
            output.update(interval=None, probabilities=None,
                          uncertainty='No intervals or probabilities validated for a provisional price anchor.')
        results.append(output)
    primary = results[0]
    reasons = [problem] if problem else primary['critical_missing_inputs'] if pinned and primary['status'] != 'issued' else []
    return dict(origin=at.isoformat(), anchor=anchor, forecasts=results, available_market_inputs=market,
                status='issued' if any(row['status'] == 'issued' for row in results) else 'abstain', reasons=reasons)
