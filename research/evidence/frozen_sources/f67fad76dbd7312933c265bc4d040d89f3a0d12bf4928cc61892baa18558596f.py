"""Human-readable Part 5 development findings and identical-origin comparisons."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from .pipeline import metrics,digest,dump


def table(frame,columns):
    def cell(v):
        if isinstance(v,float):return '—' if not np.isfinite(v) else f'{v:,.2f}'
        return str(v)
    return '\n'.join(['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |']+
                     ['| '+' | '.join(cell(r[c]) for c in columns)+' |' for _,r in frame.iterrows()])


def common_metrics(predictions):
    parts=[]
    for (regime,horizon),g in predictions.groupby(['regime','horizon']):
        for scope in ['all_available_families','core_excluding_sarimax']:
            use=g if scope=='all_available_families' else g[g.family!='D_sarimax']
            sets=[set(f.origin) for _,f in use.groupby('family')]
            common=set.intersection(*sets)
            if not common:continue
            m=metrics(use[use.origin.isin(common)]);m['comparison_scope']=scope
            parts.append(m)
    return pd.concat(parts,ignore_index=True)


def report(root):
    from .uncertainty import direction_class
    root=Path(root);folder=root/'reports/forecasting'
    predictions=pd.read_csv(folder/'development_predictions.csv')
    summary=pd.read_csv(folder/'model_metrics.csv');availability=pd.read_csv(folder/'model_availability.csv')
    coverage=pd.read_csv(folder/'target_coverage.csv')
    manifest=json.loads((folder/'run_manifest.json').read_text())
    common=common_metrics(predictions);common.to_csv(folder/'common_origin_metrics.csv',index=False)
    reliability=[]
    for (regime,horizon,family),g in predictions.groupby(['regime','horizon','family']):
        g=g[g[['p_decrease','p_no_change','p_increase']].notna().all(axis=1)]
        actual=direction_class(g.target_change_lbp_20l)
        for column,sign in [('p_decrease',-1),('p_no_change',0),('p_increase',1)]:
            bins=np.minimum((g[column]*10).astype(int),9)
            for band in sorted(bins.unique()):
                use=bins==band
                reliability.append(dict(regime=regime,horizon=horizon,family=family,probability=column,bin_low=band/10,bin_high=(band+1)/10,
                    n=int(use.sum()),mean_probability=float(g.loc[use,column].mean()),observed_frequency=float((actual[use]==sign).mean())))
    pd.DataFrame(reliability).to_csv(folder/'direction_reliability.csv',index=False)
    failures=summary[(summary.interval_n>0)&(summary.interval_coverage<.85)]
    failures.to_csv(folder/'interval_calibration_failures.csv',index=False)
    horizons=['decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30']
    ensemble=summary[summary.family.eq('H_ensemble')].set_index('horizon').reindex(horizons).reset_index()
    ensemble.to_csv(folder/'horizon_summary.csv',index=False)
    paired=[]
    for horizon,g in predictions.groupby('horizon'):
        h=g[g.family.eq('H_ensemble')].set_index('origin')
        for name in ['A_no_change','Z_last_change','B_structural_proxy','C_ridge']:
            other=g[g.family.eq(name)].set_index('origin');index=h.index.intersection(other.index)
            if len(index):
                paired.append(dict(horizon=horizon,baseline=name,n=len(index),
                    ensemble_mae=float(abs(h.loc[index].prediction-h.loc[index].target_change_lbp_20l).mean()),
                    baseline_mae=float(abs(other.loc[index].prediction-other.loc[index].target_change_lbp_20l).mean())))
    paired=pd.DataFrame(paired);paired.to_csv(folder/'ensemble_baseline_comparisons.csv',index=False)
    missing=availability[availability.status.eq('abstained')]
    ready=predictions.calibration_n.ge(20)&predictions.p_increase.notna()
    bad_width=int(((predictions.interval_high-predictions.interval_low)<=0).sum())
    title='# Part 2: development retraining and uncertainty assessment\n\n'
    text=title+f'''Generated {manifest['completed_at']}. Units: LBP per 20 liters. **Research outputs; no production approval or winner.**

## Data and chronology

Only `data/exports/forecasting/development_design.csv` was read for model data. The unified `stabilized_fx_2023_2026` subset contains {int(coverage.rows.sum()):,} labeled origin/horizon rows. Point-model folds begin 2024-06-01, 2025-01-01 and 2025-09-01. Final fits use labels matured before the 2026-06-01 Beirut cutoff. The latest usable feature origin in this input is **{manifest['data_last_origin']}** and the latest label maturity is **{manifest['data_maximum_label_end']}**. No eligible 2026 development labels exist; the cutoff is not evidence of 2026 training observations. The June–November evaluation export was not read, fitted or scored.

EIA spot proxies use the explicit same-day 23:59:59 UTC research availability assumption. Their latest captured editions do not establish original historical vintages or verified release times. Official announcement/effective timing and complete decision coverage remain unresolved. Training inputs, code/package hashes, runtime protocol and fold purges are recorded in `part2_protocol_freeze.json`, `training_inputs.json` and `fold_log.json`.

The optional `cboe_ovx` inputs are Cboe OVX closes distributed through FRED's `OVXCLS` series. Features are the latest annualized OVX level, five- and twenty-observation absolute changes in volatility percentage points, and a rolling percentile among 252 observed closes. Percentile regimes use fixed descriptive cutoffs (below 25 Low, below 75 Normal, below 90 Elevated, otherwise Stress); they are not calibrated gasoline-volatility states. Historical design rows use the configured `as_of_close` assumption, while live feature construction uses only captures known before the forecast origin.

## Models

A retains simple statistical baselines. B estimates differential structural pass-through, with a nonnegative coefficient on `x_structural_delta_lbp_20l`; lag and shock coefficients may have either sign. Missing shock flags use the requested zero convention, which is a modeling assumption rather than proof that no fiscal change occurred. G fits a correction to purged, chronologically cross-fitted B residuals, using strongly regularized Ridge for small residual samples and shallow LightGBM only when its sample gate permits. E and F retain distinct-decision sample requirements; D retains sequence and convergence requirements.

H fits nonnegative weights summing to one by minimizing prior OOF MAE over eligible B/C/E/F/G/Z candidates on identical origins. Weights stay fixed during each outer fold. Insufficient earlier OOF evidence yields an explicitly labeled no-change baseline. Final weights are development-derived and await independent validation.

{manifest['saved_bundles']} final horizon bundles were saved and reloaded. Historical preliminary rows are preserved OOF predictions from their original fold models, not predictions backdated from the final fit. Serialization smoke checks are not accuracy tests. The live adapter consumes the optional OVX features; its separate evidence gates still control whether it emits a quantitative forecast.

## Eight-horizon ensemble results

Each row is H's full available OOF sample, including early baseline-fallback periods. Direction uses a ±3,000 LBP deadband. Brier is the three-class sum-of-squared probability error (range 0–2), on its own nonmissing sample. Probability and interval sample sizes differ from the point sample.

{table(ensemble,['horizon','n','mae','direction_accuracy','brier_multiclass','probability_n','interval_coverage','interval_n','interval_mean_width'])}

## All model families

{table(summary,['horizon','family','n','mae','direction_accuracy','brier_multiclass','probability_n','interval_coverage','interval_n'])}

Families without admissible fits or OOF cases are not assigned invented errors. Final fit exclusions:

{table(missing,['horizon','family','train_base_decisions','reason'])}

Identical-origin ensemble comparisons:

{table(paired,['horizon','baseline','n','ensemble_mae','baseline_mae'])}

## Calibration procedure and limits

At each forecast origin, use only strictly earlier OOF predictions with labels already matured. Residuals are **actual minus prediction**, separately for each model and horizon. Calendar cases are no longer deduplicated by base decision. Keep at most 60 observations, one per k-calendar-day stride bucket, with k=floor(h_days/2), minimum 1. Decision horizons use the median past observed decision interval to express h in days. Rotating weekday priority avoids the fixed-weekday alias of a 7-day stride. Missing days mean equal representation cannot be guaranteed; per-bundle weekday counts are retained. The samples remain temporally dependent.

The 90% symmetric split-conformal radius uses the finite-sample order statistic of absolute residuals and the floor max(5,000, 0.25 × trailing-20 matured OOF MAE). At least 20 sampled residuals are required for a numeric calibrated candidate interval. Insufficient samples stay unavailable. **{bad_width} nonpositive-width intervals** were emitted. Raw LightGBM quantiles remain diagnostic and do not bypass the floor.

For each point prediction, classify prediction plus each empirical residual into decrease (<−3,000), no_change (within ±3,000 inclusive), or increase (>3,000). Apply additive Dirichlet/Laplace pseudo-count α=0.03: (class_count+α)/(M+3α). All emitted probabilities are strictly between zero and one and sum to one. The deadband is a user-specified research tolerance, **not a verified Ministry rounding rule**. No residuals means no probability estimate. Estimates with fewer than 20 residuals are explicitly small-sample and unvalidated. {int(ready.sum()):,} model-origin probability rows have at least 20 calibration residuals; all reported Brier scores state their actual sample size.

The procedure does not establish calibration by name: inspect empirical coverage, width, Brier scores and `direction_reliability.csv` before approval. {len(failures)} model/horizon groups with measured coverage below 85% are flagged in `interval_calibration_failures.csv`. The 85% flag is diagnostic, not an approval threshold. Regime shifts, selected archive coverage, overlapping targets and approximate market availability invalidate an unconditional exchangeability guarantee.

Part 2 ends here. No held-out 2026 performance or production improvement is claimed.
'''
    path=folder/'part2_retraining_report.md';path.write_text(text)
    (root/'reports/forecasting_development.md').write_text(text)
    # Report-derived tables supersede earlier versions after the training run.
    # Keep the training-time source snapshot and identify this separate report pass.
    manifest['report_code_sha256']=digest(Path(__file__))
    manifest['output_hashes']={p.name:digest(p) for p in sorted(folder.glob('*.csv'))}
    manifest['report_sha256']=digest(path)
    dump(folder/'run_manifest.json',manifest)
    return dict(report=str(path),horizons=len(ensemble),model_metric_groups=len(summary),zero_width_intervals=bad_width,production_winner=None)
