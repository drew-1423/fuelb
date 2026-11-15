---
name: time-series-forecasting
description: Design or evaluate forecasts for Lebanese gasoline prices using leakage-safe chronological validation, meaningful baselines, and calibrated uncertainty.
---

# Time Series Forecasting

Use this skill when building or comparing forecasts for this project's Lebanese fuel-price target.

- Specify target, unit, publication/effective date, forecast origin, horizon, and intended use before modeling. Respect when each input would actually have been available; distinguish event dates from release dates.
- Use chronological walk-forward or expanding/rolling-window backtests that mirror the intended forecast cadence. Keep every preprocessing, feature-selection, and tuning step inside each training fold. Never use random shuffling or future revisions/features in validation.
- Establish simple persistence, seasonal, or policy-rule baselines where appropriate. Compare econometric and machine-learning models on identical origins, horizons, and information sets; justify complexity with out-of-sample gains.
- Report errors in interpretable units and suitable scale-aware metrics, with sample size and evaluation dates. Avoid percentage metrics when the target can be zero or their denominator makes them misleading. Do not present in-sample fit as forecast accuracy.
- Produce prediction intervals or distributions when uncertainty matters. Calibrate using training-only residuals or a time-valid calibration window, then report empirical coverage and width by horizon and relevant regime; do not imply that uncalibrated intervals are guarantees.
- Preserve reproducible forecast origins, feature availability, fold boundaries, fitted transformations, model settings, and predictions. Discuss structural breaks and policy changes rather than assuming historical relationships remain stable.

Activate for model design, forecast evaluation, or uncertainty estimation for this project. For a genuinely independent assessment of an existing model or its claims, use `independent-model-auditor`.
