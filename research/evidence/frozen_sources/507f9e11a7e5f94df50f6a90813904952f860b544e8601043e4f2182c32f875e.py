"""2026 validation report generated from measured holdout results and decisions."""
from pathlib import Path
import json
import pandas as pd
from lebanon_fuel.forecasting.reporting import table
from lebanon_fuel.forecasting.pipeline import dump, digest


def report(root):
    root=Path(root);folder=root/'reports/model_validation'
    decision=json.loads((folder/'production_selection.json').read_text())
    manifest=json.loads((folder/'input_manifest.json').read_text())
    completion=json.loads((folder/'completion.json').read_text())
    if digest(root/manifest['design_path']) != manifest['design_sha256']:
        raise ValueError('Evaluation design changed after validation')
    metrics=pd.read_csv(folder/'metrics.csv');rows=[]
    for horizon,spec in decision['selection'].items():
        m=spec.get('performance') or {}
        rows.append(dict(horizon=horizon,selected=spec['family'],tier=spec['tier'],
            n=spec['holdout_n'],mae_lbp=m.get('mae'),rmse_lbp=m.get('rmse'),
            direction_accuracy=m.get('direction_accuracy'),
            brier=m.get('brier_multiclass'),probability_n=m.get('probability_n',0),
            coverage_90=m.get('interval_coverage'),interval_n=m.get('interval_n',0),
            coverage_80_p10_p90=m.get('interval_80_coverage'),interval_80_n=m.get('interval_80_n',0),
            calibration_n=spec['calibration']['n'],selection_basis=spec['selection_basis']))
    selected=pd.DataFrame(rows);selected.to_csv(folder/'horizon_summary.csv',index=False)
    comparison=[]
    for horizon,spec in decision['selection'].items():
        for family,mae in spec['baselines'].items():
            comparison.append(dict(horizon=horizon,selected=spec['family'],baseline=family,
                n=spec['holdout_n'],selected_mae=spec['mae_lbp'],baseline_mae=mae,
                difference=spec['mae_lbp']-mae if spec['mae_lbp'] is not None and mae is not None else None))
    pd.DataFrame(comparison).to_csv(folder/'baseline_comparisons.csv',index=False)
    text=f'''# 2026 walk-forward evaluation and live model registration

Evaluation window: **2026-06-01 through 2026-11-10**, using the physical `{manifest['design_path']}`.
Actual usable targets: **{manifest['target_rows']}**, yielding **{completion['prediction_rows']} model predictions**.
Tier 1 approved: **{decision['production_approved']}**. Every registered quantitative selection is recorded with its artifact SHA-256, version, calibration residuals, measured scores and reasons in `production_selection.json`.

## Selected models and measured evidence

{table(selected,list(selected.columns))}

Unavailable scores are missing evidence, not zero error. Decision 4, day 14 and day 30 have no holdout outcomes; their selections use development OOF rankings only. Counts refer to conditional archive targets, not independent verified official decisions. The same base decision can contribute several calendar origins. All model-family scores and availability gates are in `metrics.csv` and `model_coverage.csv`.

## Chronological protocol

The Part 2 models, transformations, hyperparameters and convex ensemble weights remain frozen at the development cutoff, June 1, 2026 Beirut time. Actual matured training labels end in 2025 because eligible 2026 development targets are missing. No holdout target is fitted into a point model. At each subsequent evaluation origin, uncertainty uses development OOF residuals plus only earlier evaluation residuals whose target/witness has matured strictly before that origin. The feature-only prediction input excludes outcomes; labels are joined after prediction. Bundle and design hashes are checked and preserved.

This is a fixed-model walk-forward evaluation with sequential uncertainty calibration, not an expanding point-model retraining experiment. Historical daily market availability uses the explicitly requested **23:59:59 UTC observation-day close** assumption, with no 14-day daily lag. The source workbook vintages and exact historical publication times remain unverified. It is therefore not a strict original-vintage backtest. Calendar targets are conditional prevailing archive prices; gaps and unknown effective clocks are not filled with invented observations.

Selection uses lowest MAE on identical available origins, then lowest Brier and closest interval coverage to 90%. Quantitative candidates are separately compared with no-change and last-change baselines with a prespecified 1% MAE tolerance. Tier 1 requires complete intervals with 80%–98% empirical coverage, at least 20 origins, and certified official target coverage. These evidence gates prevent promotion from one or a few observations. Tier 2 registrations allow quantitative research forecasts when current inputs pass freshness checks. Selection consumes the holdout: future claims of final independent accuracy require new prospective outcomes. No external independent certification is claimed.

## Uncertainty and directional classes

Probabilities are model-specific empirical distributions of predicted change plus past residuals, with additive alpha=0.03 smoothing. Order is decrease, no change, increase. No change means within ±3,000 LBP/20 L; this is the requested classification tolerance, not a verified Ministry rounding rule. Brier and direction metrics use this same deadband; exact-sign accuracy is separately exported.

Nominal 90% symmetric conformal bounds use horizon-conditioned trailing 60 stride-sampled matured errors and a half-width floor of max(5,000 LBP, 0.25 × trailing-20 MAE). Where at least 20 matured OOF residuals exist in the current OVX regime, calibration is conditioned on that regime; otherwise the pooled horizon/model calibration is retained. OVX is an oil-volatility proxy, not Lebanese gasoline volatility, and regimes with no adequate sample are not assigned a separate interval. The 30-day model has only six residuals: even the finite-sample 90% conformal rank exceeds six, so a defensible finite 90% interval cannot be supplied. Its probabilities are a small-sample empirical estimate, not validated confidence. Other nominal bounds do not imply a guarantee under time dependence or regime change. `probability_reliability.csv` contains separate class bins for each model.

The report also records empirical **central 80% p10/p90 residual interval coverage** separately from the nominal 90% symmetric interval. These asymmetric p10/p90 bands use the same origin-specific OVX calibration distribution and minimum half-width floor; they are not relabeled as 90% intervals.

## Live behavior and limitations

Live quantitative candidates use the new 2026 bundle hashes with no fixed 2025 expiration. Each run requires a verified domestic anchor at most 10 calendar days old and required Brent/NYH spot inputs at most 7 calendar days old. Failed freshness checks retain explicit reasons and fall through to the labeled structural/baseline hierarchy. Missing probabilities or intervals are never converted to fabricated confidence.

Historical feature windows use observation closes within a vintage actually captured before the live origin. This permits trailing-window calculations from known historical quotes without pretending that the capture existed at historical backtest origins. OVX features use only those close-eligible rows and remain unavailable until enough history exists for the 252-close percentile. NYH gasoline and Brent are geographic/product proxies, not licensed Mediterranean gasoline assessments. The structural delta's fixed FX, VAT and bank-fee assumptions are research inputs, not verified current fiscal parameters.

Announcement dates are date-only estimates from the last 20 verified intervals and weekday frequencies. Where supported, the estimator projects Tuesday/Friday dates. It does not assert a published Ministry schedule, clock time, holiday adjustment or extraordinary announcement. Driver contributions reconcile to the point forecast using linear terms or tree SHAP and ensemble weights; they are statistical attributions, not measured causal effects.

## Baseline comparison

{table(pd.DataFrame(comparison),list(pd.DataFrame(comparison).columns))}

No formal significance test is justified by the sparse holdout sample. The earliest usable holdout origins occur in August despite the requested June start. Missing coverage remains visible in the input counts. The forecast ledger schema and immutable hash-chain protections are unchanged; historical forecasts are never revised.

## Artifacts and checks

- `input_manifest.json`: protocol, code/data/model hashes captured before evaluation.
- `research_walk_forward_predictions.csv`: actual historical predictions and maturity cutoffs.
- `metrics.csv`, `common_origin_metrics.csv`, `horizon_summary.csv`: measured results with denominators.
- `production_selection.json`: artifact-specific registrations and reasons.
- `ledger_integrity.json`: audit-chain verification.
- Prior report files are preserved in `archive/{manifest['run_id']}/`.

Models unchanged: **{completion['part5_models_unchanged']}**. Evaluation design unchanged: **{completion['design_unchanged']}**.
'''
    (folder/'part3_validation_report.md').write_text(text)
    (root/'reports/model_validation_report.md').write_text(text)
    dump(folder/'report_manifest.json',dict(report_sha256=digest(folder/'part3_validation_report.md'),
        run_id=manifest['run_id'],production_approved=decision['production_approved']))
    return dict(report=str(folder/'part3_validation_report.md'),production_approved=decision['production_approved'],
                measured_horizons=int((selected.n>0).sum()),registered_horizons=len(selected))
