"""Frozen development models evaluated sequentially on the physical 2026 holdout."""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import numpy as np
import pandas as pd
from lebanon_fuel.forecasting.models import weights
from lebanon_fuel.forecasting.pipeline import load_bundle, dump, digest, metrics
from lebanon_fuel.forecasting.uncertainty import (past_predictions, calibrate,
    available_ovx_regime_calibrations, direction_class)
from .backtest import load_holdout, walk_forward_bundle
from .ledger import ForecastLedger, now


class LastChange:
    def predict(self,frame):
        result=[]
        for row in frame.itertuples():
            kind,n=row.horizon.split('_');factor=int(n) if kind=='decision' else int(n)/max(row.x_interval_median,1)
            result.append(row.x_domestic_change_lag1*factor)
        return np.array(result)
    def quantiles(self,frame):return None


class Brent:
    def __init__(self,train):
        x=(train.x_brent_spot_value-train.x_brent_spot_mean20).to_numpy(float);y=train.target_change_lbp_20l.to_numpy(float);w=weights(train)
        ok=np.isfinite(x)&np.isfinite(y);denom=np.sum(w[ok]*x[ok]**2)
        self.slope=max(0,float(np.sum(w[ok]*x[ok]*y[ok])/denom)) if ok.sum()>=12 and denom>0 else None
    def predict(self,frame):
        if self.slope is None:return np.full(len(frame),np.nan)
        return self.slope*(frame.x_brent_spot_value-frame.x_brent_spot_mean20).to_numpy(float)
    def quantiles(self,frame):return None



def ranked(frame):
    frame = frame.copy()
    frame['_coverage_distance'] = abs(frame.interval_coverage-.9)
    return frame.sort_values(['mae', 'brier_multiclass', '_coverage_distance', 'family'], na_position='last')


def select_horizon(comparison, development, protocol, certified=False):
    """Lowest common-origin MAE wins; promotion is a separate, explicit decision."""
    quantitative = protocol['quantitative_families']
    source = comparison if len(comparison) else development
    ranking = ranked(source)
    quant = ranking[ranking.family.isin(quantitative)]
    if quant.empty:
        raise ValueError('No quantitative model with measured development performance')
    best = quant.iloc[0]
    reasons = []
    baselines = {}
    approval = protocol['approval']
    performance_pass = bool(len(comparison))
    for name in protocol['required_baselines']:
        rows = comparison[comparison.family.eq(name)] if len(comparison) else comparison
        baseline = float(rows.iloc[0].mae) if len(rows) else None
        baselines[name] = baseline
        if baseline is None or best.mae > baseline*(1+approval['mae_relative_tolerance'])+approval['mae_absolute_tolerance_lbp']:
            performance_pass = False
            reasons.append('Does not match or beat '+name+' within the prespecified 1% tolerance')
    coverage = best.interval_coverage if len(comparison) else np.nan
    if not (np.isfinite(coverage) and approval['coverage_minimum'] <= coverage <= approval['coverage_maximum'] and best.interval_n == best.n):
        performance_pass = False
        reasons.append('90% interval coverage does not meet 80%–98% on every evaluated prediction')
    if not len(comparison):
        reasons.append('No usable holdout outcomes; selection uses development OOF only')
    effective_n = (
        int(best.unique_base_decisions)
        if len(comparison) and 'unique_base_decisions' in best and pd.notna(best.unique_base_decisions)
        else (int(best.n) if len(comparison) else 0)
    )
    if not len(comparison) or effective_n < approval['minimum_holdout_origins']:
        reasons.append(f"Fewer than {approval['minimum_holdout_origins']} distinct holdout base decisions; evidence too small for Tier 1")
    if approval['require_certified_target_coverage'] and not certified:
        reasons.append('Official effective clocks and complete target sequence are uncertified')
    approved = bool(performance_pass and effective_n >= approval['minimum_holdout_origins'] and certified)
    return dict(family=best.family, overall_best_family=ranking.iloc[0].family,
                selection_basis='holdout_common_origins' if len(comparison) else 'development_only_no_holdout_targets',
                production_approved=approved, statistical_criteria_pass=performance_pass,
                tier=1 if approved else 2, reasons=reasons,
                baselines=baselines, performance=clean(best.drop(labels=['_coverage_distance']).to_dict()) if len(comparison) else None,
                development_performance=clean(development[development.family.eq(best.family)].iloc[0].to_dict()))


def clean(value):
    """JSON null for unavailable metrics, never nonstandard NaN or invented zeros."""
    if isinstance(value, dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):return [clean(v) for v in value]
    if isinstance(value, np.generic):value=value.item()
    if isinstance(value, float) and not np.isfinite(value):return None
    return value


def common_origins(pred, core_families):
    """Return origins shared by full-coverage core families so sparse models do not shrink the evaluation set."""
    core = pred[pred.family.isin(core_families)]
    if core.empty:
        return set(pred.origin)
    groups = [set(g.origin) for _, g in core.groupby('family')]
    max_n = max(len(g) for g in groups)
    full_groups = [g for g in groups if len(g) == max_n]
    return set.intersection(*(full_groups or groups))


def validation_metrics(predictions):
    result = metrics(predictions)
    # Compatibility columns for dashboard consumers; class metrics use ±3000 LBP.
    result['change_mae_lbp'] = result.mae
    result['price_mae_lbp'] = result.mae
    result['change_rmse_lbp'] = result.rmse
    result['distinct_base_decisions'] = result.unique_base_decisions
    result['interval_width_lbp'] = result.interval_mean_width
    return result


def run(root):
    root=Path(root);folder=root/'reports/model_validation';folder.mkdir(parents=True, exist_ok=True)
    protocol_path=root/'config/validation_protocol.json';protocol=json.loads(protocol_path.read_text())
    run_id='holdout2026-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    # Preserve prior published reports while refreshing the stable output paths.
    archive=folder/'archive'/run_id
    archive.mkdir(parents=True)
    for p in folder.iterdir():
        if p.is_file():shutil.copy2(p,archive/p.name)
    design=load_holdout(root,protocol)
    development=pd.read_csv(root/protocol['development_predictions'])
    development=development[development.regime.eq(protocol['regime'])].copy()
    devmetrics=pd.read_csv(root/'reports/forecasting/model_metrics.csv')
    devmetrics=devmetrics[devmetrics.regime.eq(protocol['regime'])]
    paths={h:root/'data/models/part5'/protocol['regime']/h for h in protocol['horizons']}
    hashes={h:digest(path/'bundle.joblib') for h,path in paths.items()}
    source_paths=[*sorted((root/'src/lebanon_fuel/validation').glob('*.py')),
                  *sorted((root/'src/lebanon_fuel/forecasting').glob('*.py'))]
    manifest=dict(run_id=run_id,created_at=now(),protocol=protocol,protocol_sha256=digest(protocol_path),
        design_path=protocol['design_path'],design_sha256=digest(root/protocol['design_path']),
        development_predictions_sha256=digest(root/protocol['development_predictions']),artifact_sha256=hashes,
        source_sha256={str(p.relative_to(root)):digest(p) for p in source_paths},
        target_rows=len(design),target_counts=design.groupby('horizon').size().to_dict(),
        historical_vintage_certification=False,holdout_used_for_selection=True)
    dump(folder/'input_manifest.json',manifest)
    dump(archive/'protocol_before_evaluation.json',manifest)
    predictions=[];coverage=[];selection={};candidates=[];comparisons=[];bins=[]
    for horizon in protocol['horizons']:
        bundle=load_bundle(paths[horizon]);targets=design[design.horizon.eq(horizon)].copy()
        previous=development[development.horizon.eq(horizon)].copy()
        pred=walk_forward_bundle(bundle, targets, previous)
        families=list(bundle['models'])+['H_ensemble']
        for family in sorted(set(bundle['config']['families'])|set(families)|{'B_official_structural'}):
            n=int(pred.family.eq(family).sum()) if len(pred) else 0
            coverage.append(dict(horizon=horizon,family=family,eligible_origin_n=len(targets),predictions_n=n,
                reason='' if n else ('no_holdout_targets' if targets.empty else bundle['gates'].get(family,'dated_official_formula_inputs_missing'))))
        measured=pd.DataFrame()
        all_measured=pd.DataFrame()
        if len(pred):
            predictions.append(pred)
            all_measured=validation_metrics(pred)
            ids=common_origins(pred, protocol['quantitative_families']+protocol['required_baselines'])
            measured=validation_metrics(pred[pred.origin.isin(ids)])
            comparisons.append(measured)
            for family,g in pred.groupby('family'):
                for name,code in [('decrease',-1),('unchanged_price',0),('increase',1)]:
                    probabilities=g['p_'+name]
                    for i in range(5):
                        use=probabilities.ge(i/5)&(probabilities.lt((i+1)/5) if i<4 else probabilities.le(1))
                        if use.any():bins.append(dict(horizon=horizon,family=family,event=name,n=int(use.sum()),
                            mean_predicted=float(probabilities[use].mean()),observed_frequency=float(np.mean(direction_class(g.loc[use,'target_change_lbp_20l'])==code))))
        dev=devmetrics[devmetrics.horizon.eq(horizon)&devmetrics.family.isin(families)]
        certified=bool(len(targets) and targets.effective_price_certified.eq(True).all())
        chosen=select_horizon(measured,dev,protocol,certified)
        family=chosen['family'];model_version=f"part3-{hashes[horizon][:20]}-{horizon}-{family}"
        # Updated residuals are only for future live forecasts, never retroactively applied.
        pool=pd.concat([previous,pred],ignore_index=True) if len(pred) else previous
        available=past_predictions(pool,now())
        calibration=calibrate(available[available.family.eq(family)],bundle['config'])
        regime_calibrations=available_ovx_regime_calibrations(available[available.family.eq(family)],bundle['config'])
        errors=np.asarray(calibration['residuals'],float)
        quantiles={str(q):float(np.quantile(errors,q)) if len(errors) else None for q in (.05,.95)}
        all_perf=None
        if len(all_measured):
            fam_rows=all_measured[all_measured.family.eq(family)]
            if len(fam_rows):all_perf=clean(fam_rows.iloc[0].to_dict())
        chosen.update(model_version=model_version,production_model=model_version if chosen['production_approved'] else None,
            quantitative_model=model_version,artifact_sha256=hashes[horizon],path=str(paths[horizon].relative_to(root)),
            holdout_n=int(chosen['performance']['n']) if chosen['performance'] else 0,
            all_origin_performance=all_perf,
            mae_lbp=chosen['performance']['mae'] if chosen['performance'] else None,
            directional_accuracy=chosen['performance']['direction_accuracy'] if chosen['performance'] else None,
            empirical_residual_quantiles=quantiles,calibration=calibration,
            calibrations_by_ovx_regime=regime_calibrations,
            complete_decision_coverage=certified,review_evidence='reports/model_validation/part3_validation_report.md',
            required_market=['nyh_gasoline','brent_spot'])
        selection[horizon]=chosen
        candidates.append(dict(horizon=horizon,regime=protocol['regime'],family=family,model_version=model_version,
            path=chosen['path'],artifact_sha256=hashes[horizon],valid_through=None,
            validity='dynamic_input_freshness',required_market=chosen['required_market'],
            development_mae=chosen['development_performance']['mae'],performance=chosen['performance'],
            all_origin_performance=all_perf,
            selection_basis=chosen['selection_basis']))
        print(horizon, 'holdout targets',len(targets),'selected',family,'tier',chosen['tier'],flush=True)
    allpred=pd.concat(predictions,ignore_index=True)
    allpred.to_csv(folder/'research_walk_forward_predictions.csv',index=False)
    validation_metrics(allpred).to_csv(folder/'metrics.csv',index=False)
    pd.concat(comparisons,ignore_index=True).to_csv(folder/'common_origin_metrics.csv',index=False)
    pd.DataFrame(coverage).to_csv(folder/'model_coverage.csv',index=False)
    pd.DataFrame(bins).to_csv(folder/'probability_reliability.csv',index=False)
    decision=dict(protocol_version=protocol['version'],decided_at=now(),run_id=run_id,
        production_approved=any(x['production_approved'] for x in selection.values()),selection=selection,
        evidence=protocol['evidence'],holdout_used_for_selection=True)
    dump(folder/'production_selection.json',clean(decision))
    dump(root/'config/live_forecasting.json',dict(version='2026-dynamic-v1',**protocol['live'],
        quantitative_candidates=candidates,structural_requests={},
        uncertainty_policy='Model-specific matured residuals; missing calibration stays unavailable',
        schedule_policy='Empirical weekdays, date estimates only; holidays and extraordinary updates unknown'))
    project=root/'config/project.toml';settings=project.read_text()
    settings=settings.replace('enabled = false','enabled = true')
    settings=settings.replace('production_approved = true','production_approved = false')
    if decision['production_approved']:settings=settings.replace('production_approved = false','production_approved = true')
    project.write_text(settings)
    ledger=ForecastLedger(root/'data/forecast_ledger.sqlite')
    integrity=ledger.integrity();ledger.close();dump(folder/'ledger_integrity.json',integrity)
    completion=dict(run_id=run_id,completed_at=now(),prediction_rows=len(allpred),
        distinct_origin_horizon_cases=len(allpred.drop_duplicates(['horizon','origin'])),
        strict_n=0,holdout_used_for_selection=True,
        part5_models_unchanged=all(digest(path/'bundle.joblib')==hashes[h] for h,path in paths.items()),
        design_unchanged=digest(root/protocol['design_path'])==manifest['design_sha256'],
        production_approved=decision['production_approved'])
    dump(folder/'completion.json',completion)
    return completion


def finalize(root):
    """Reporting never changes selection or reopens the holdout for tuning."""
    from .reporting import report
    return report(root)
