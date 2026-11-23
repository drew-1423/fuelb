---
name: independent-model-auditor
description: Independently audit a Lebanese fuel-price forecasting model, backtest, or accuracy claim for validity, leakage, assumptions, and calibration.
---

# Independent Model Auditor

Use this skill when asked to independently review an existing forecast, its implementation, evaluation, or reported performance. Keep the review separate from the model author's rationale until you have checked the evidence.

- Reconstruct the target, forecast origins, horizons, data cutoff, and information available at each origin. Trace revisions, release timestamps, target alignment, lagging, aggregation, and preprocessing for look-ahead or leakage.
- Re-derive key equations and inspect code paths for unit, currency, scaling, log/level, difference/reconstruction, and interval errors. Check financial assumptions against the pricing mechanism and rules valid for the evaluated dates.
- Examine chronological fold construction, tuning boundaries, feature selection, benchmark choice, comparability of evaluation windows, regime changes, and sample size. Identify repeated reuse of the test period or selective metric/date reporting.
- Assess uncertainty intervals with out-of-sample coverage and width by horizon. Check whether calibration used future or evaluation observations, and whether conclusions are supported across relevant periods.
- Tie every finding to reproducible evidence: file/line, formula, data row, or backtest result. Separate confirmed defects from risks and unanswered questions; state likely impact and severity. Recalculate claims when practical and suggest a focused correction.
- Judge the forecast against a credible simple baseline and its stated use. Do not infer reliability from a single metric or make claims beyond the audited data and period.

Activate for requested independent scrutiny or when a material model-performance claim needs verification. Use `time-series-forecasting` for ordinary model development and iteration.
