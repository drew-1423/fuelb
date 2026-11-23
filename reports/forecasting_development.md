# Part 2: development retraining and uncertainty assessment

Generated 2026-11-13T19:02:34.463609+00:00. Units: LBP per 20 liters. **Research outputs; no production approval or winner.**

## Data and chronology

Only `data/exports/forecasting/development_design.csv` was read for model data. The unified `stabilized_fx_2023_2026` subset contains 2,391 labeled origin/horizon rows. Point-model folds begin 2024-06-01, 2025-01-01 and 2025-09-01. Final fits use labels matured before the 2026-06-01 Beirut cutoff. The latest usable feature origin in this input is **2025-12-21T01:00:00+00:00** and the latest label maturity is **2025-12-22T22:00:00+00:00**. No eligible 2026 development labels exist; the cutoff is not evidence of 2026 training observations. The June–November evaluation export was not read, fitted or scored.

EIA spot proxies use the explicit same-day 23:59:59 UTC research availability assumption. Their latest captured editions do not establish original historical vintages or verified release times. Official announcement/effective timing and complete decision coverage remain unresolved. Training inputs, code/package hashes, runtime protocol and fold purges are recorded in `part2_protocol_freeze.json`, `training_inputs.json` and `fold_log.json`.

The optional `cboe_ovx` inputs are Cboe OVX closes distributed through FRED's `OVXCLS` series. Features are the latest annualized OVX level, five- and twenty-observation absolute changes in volatility percentage points, and a rolling percentile among 252 observed closes. Percentile regimes use fixed descriptive cutoffs (below 25 Low, below 75 Normal, below 90 Elevated, otherwise Stress); they are not calibrated gasoline-volatility states. Historical design rows use the configured `as_of_close` assumption, while live feature construction uses only captures known before the forecast origin.

## Models

A retains simple statistical baselines. B estimates differential structural pass-through, with a nonnegative coefficient on `x_structural_delta_lbp_20l`; lag and shock coefficients may have either sign. Missing shock flags use the requested zero convention, which is a modeling assumption rather than proof that no fiscal change occurred. G fits a correction to purged, chronologically cross-fitted B residuals, using strongly regularized Ridge for small residual samples and shallow LightGBM only when its sample gate permits. E and F retain distinct-decision sample requirements; D retains sequence and convergence requirements.

H fits nonnegative weights summing to one by minimizing prior OOF MAE over eligible B/C/E/F/G/Z candidates on identical origins. Weights stay fixed during each outer fold. Insufficient earlier OOF evidence yields an explicitly labeled no-change baseline. Final weights are development-derived and await independent validation.

8 final horizon bundles were saved and reloaded. Historical preliminary rows are preserved OOF predictions from their original fold models, not predictions backdated from the final fit. Serialization smoke checks are not accuracy tests. The live adapter consumes the optional OVX features; its separate evidence gates still control whether it emits a quantitative forecast.

## Eight-horizon ensemble results

Each row is H's full available OOF sample, including early baseline-fallback periods. Direction uses a ±3,000 LBP deadband. Brier is the three-class sum-of-squared probability error (range 0–2), on its own nonmissing sample. Probability and interval sample sizes differ from the point sample.

| horizon | n | mae | direction_accuracy | brier_multiclass | probability_n | interval_coverage | interval_n | interval_mean_width |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| decision_1 | 66 | 9,949.05 | 0.32 | 0.69 | 65 | 0.96 | 46 | 49,869.57 |
| decision_2 | 55 | 21,092.08 | 0.18 | 0.79 | 53 | 0.93 | 29 | 113,448.28 |
| decision_4 | 39 | 41,763.48 | 0.10 | 0.66 | 37 | — | 0 | — |
| day_1 | 248 | 2,530.22 | 0.85 | 0.26 | 244 | 0.92 | 224 | 20,100.34 |
| day_3 | 224 | 8,076.26 | 0.51 | 0.65 | 220 | 0.91 | 202 | 42,487.60 |
| day_7 | 179 | 18,819.03 | 0.23 | 0.76 | 175 | 0.91 | 124 | 100,838.71 |
| day_14 | 133 | 38,045.89 | 0.07 | 0.68 | 130 | 1.00 | 20 | 152,000.00 |
| day_30 | 72 | 59,291.67 | 0.04 | 0.77 | 61 | — | 0 | — |

## All model families

| horizon | family | n | mae | direction_accuracy | brier_multiclass | probability_n | interval_coverage | interval_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| day_1 | A_mean | 248 | 2,629.12 | 0.85 | 0.26 | 244 | 0.92 | 224 |
| day_1 | A_median | 248 | 2,346.77 | 0.85 | 0.26 | 244 | 0.92 | 224 |
| day_1 | A_no_change | 248 | 2,346.77 | 0.85 | 0.26 | 244 | 0.92 | 224 |
| day_1 | B_structural_proxy | 248 | 3,647.35 | 0.73 | 0.45 | 244 | 0.90 | 224 |
| day_1 | C_distributed | 248 | 3,397.84 | 0.83 | 0.34 | 244 | 0.91 | 224 |
| day_1 | C_ridge | 248 | 3,413.58 | 0.82 | 0.34 | 244 | 0.91 | 224 |
| day_1 | D_sarimax | 92 | 3,362.60 | 0.71 | 0.49 | 88 | 0.94 | 68 |
| day_1 | E_lightgbm | 248 | 3,170.05 | 0.81 | 0.26 | 244 | 0.91 | 224 |
| day_1 | F_catboost | 248 | 3,029.84 | 0.81 | 0.28 | 244 | 0.92 | 224 |
| day_1 | G_hybrid | 248 | 4,156.55 | 0.67 | 0.54 | 244 | 0.91 | 224 |
| day_1 | H_ensemble | 248 | 2,530.22 | 0.85 | 0.26 | 244 | 0.92 | 224 |
| day_1 | Z_last_change | 205 | 4,299.30 | 0.60 | 0.58 | 202 | 0.91 | 182 |
| day_14 | A_mean | 133 | 35,301.11 | 0.62 | 0.66 | 130 | 1.00 | 20 |
| day_14 | A_median | 133 | 39,466.17 | 0.22 | 0.68 | 130 | 1.00 | 20 |
| day_14 | A_no_change | 133 | 34,977.44 | 0.05 | 0.61 | 130 | 1.00 | 20 |
| day_14 | B_structural_proxy | 133 | 38,585.14 | 0.67 | 0.49 | 130 | 1.00 | 20 |
| day_14 | C_distributed | 133 | 69,181.46 | 0.31 | 0.71 | 130 | 1.00 | 20 |
| day_14 | C_ridge | 133 | 66,204.41 | 0.35 | 0.75 | 130 | 1.00 | 20 |
| day_14 | D_sarimax | 22 | 52,394.57 | 0.14 | 0.58 | 10 | — | 0 |
| day_14 | E_lightgbm | 133 | 37,334.18 | 0.47 | 0.55 | 130 | 1.00 | 20 |
| day_14 | F_catboost | 133 | 35,888.83 | 0.51 | 0.59 | 130 | 1.00 | 20 |
| day_14 | G_hybrid | 133 | 57,949.06 | 0.40 | 0.54 | 130 | 1.00 | 20 |
| day_14 | H_ensemble | 133 | 38,045.89 | 0.07 | 0.68 | 130 | 1.00 | 20 |
| day_14 | Z_last_change | 112 | 46,061.01 | 0.70 | 0.43 | 105 | — | 0 |
| day_3 | A_mean | 224 | 8,276.27 | 0.51 | 0.64 | 220 | 0.91 | 202 |
| day_3 | A_median | 224 | 7,705.36 | 0.51 | 0.63 | 220 | 0.92 | 202 |
| day_3 | A_no_change | 224 | 7,705.36 | 0.51 | 0.63 | 220 | 0.92 | 202 |
| day_3 | B_structural_proxy | 224 | 8,744.39 | 0.48 | 0.71 | 220 | 0.93 | 202 |
| day_3 | C_distributed | 224 | 9,869.17 | 0.38 | 0.87 | 220 | 0.89 | 202 |
| day_3 | C_ridge | 224 | 9,252.69 | 0.41 | 0.83 | 220 | 0.88 | 202 |
| day_3 | D_sarimax | 78 | 16,531.73 | 0.03 | 1.13 | 74 | 1.00 | 56 |
| day_3 | E_lightgbm | 224 | 7,959.46 | 0.51 | 0.73 | 220 | 0.87 | 202 |
| day_3 | F_catboost | 224 | 8,867.06 | 0.44 | 0.73 | 220 | 0.90 | 202 |
| day_3 | G_hybrid | 224 | 10,032.62 | 0.41 | 0.83 | 220 | 0.92 | 202 |
| day_3 | H_ensemble | 224 | 8,076.26 | 0.51 | 0.65 | 220 | 0.91 | 202 |
| day_3 | Z_last_change | 187 | 9,280.75 | 0.52 | 0.74 | 183 | 0.89 | 161 |
| day_30 | A_mean | 72 | 56,030.95 | 0.67 | 0.77 | 61 | — | 0 |
| day_30 | A_median | 72 | 55,597.22 | 0.67 | 0.77 | 61 | — | 0 |
| day_30 | A_no_change | 72 | 59,291.67 | 0.04 | 0.77 | 61 | — | 0 |
| day_30 | B_structural_proxy | 72 | 68,611.58 | 0.51 | 0.75 | 61 | — | 0 |
| day_30 | C_distributed | 72 | 216,039.89 | 0.29 | 1.07 | 61 | — | 0 |
| day_30 | C_ridge | 72 | 213,951.84 | 0.29 | 1.10 | 61 | — | 0 |
| day_30 | G_hybrid | 72 | 110,907.46 | 0.32 | 0.70 | 61 | — | 0 |
| day_30 | H_ensemble | 72 | 59,291.67 | 0.04 | 0.77 | 61 | — | 0 |
| day_30 | Z_last_change | 66 | 116,247.84 | 0.41 | 0.78 | 57 | — | 0 |
| day_7 | A_mean | 182 | 18,317.55 | 0.20 | 0.77 | 178 | 0.91 | 127 |
| day_7 | A_median | 182 | 18,038.46 | 0.23 | 0.73 | 178 | 0.91 | 127 |
| day_7 | A_no_change | 182 | 17,708.79 | 0.23 | 0.72 | 178 | 0.91 | 127 |
| day_7 | B_structural_proxy | 182 | 17,939.51 | 0.54 | 0.61 | 178 | 0.88 | 127 |
| day_7 | C_distributed | 182 | 21,285.08 | 0.37 | 0.76 | 178 | 0.87 | 127 |
| day_7 | C_ridge | 182 | 21,452.87 | 0.37 | 0.76 | 178 | 0.88 | 127 |
| day_7 | D_sarimax | 53 | 33,125.36 | 0.06 | 1.03 | 49 | — | 0 |
| day_7 | E_lightgbm | 182 | 16,186.43 | 0.58 | 0.63 | 178 | 0.88 | 127 |
| day_7 | F_catboost | 182 | 17,979.96 | 0.48 | 0.67 | 178 | 0.86 | 127 |
| day_7 | G_hybrid | 182 | 21,763.87 | 0.47 | 0.65 | 178 | 0.83 | 127 |
| day_7 | H_ensemble | 179 | 18,819.03 | 0.23 | 0.76 | 175 | 0.91 | 124 |
| day_7 | Z_last_change | 154 | 21,559.52 | 0.67 | 0.65 | 147 | 0.88 | 94 |
| decision_1 | A_mean | 69 | 10,796.01 | 0.30 | 0.73 | 68 | 0.94 | 49 |
| decision_1 | A_median | 69 | 10,666.67 | 0.30 | 0.69 | 68 | 0.94 | 49 |
| decision_1 | A_no_change | 69 | 10,637.68 | 0.30 | 0.69 | 68 | 0.94 | 49 |
| decision_1 | B_structural_proxy | 69 | 9,484.64 | 0.54 | 0.55 | 68 | 0.94 | 49 |
| decision_1 | C_distributed | 69 | 11,072.87 | 0.36 | 0.71 | 68 | 0.90 | 49 |
| decision_1 | C_ridge | 69 | 11,177.24 | 0.35 | 0.71 | 68 | 0.90 | 49 |
| decision_1 | E_lightgbm | 69 | 8,801.02 | 0.48 | 0.61 | 68 | 0.88 | 49 |
| decision_1 | F_catboost | 69 | 10,062.84 | 0.39 | 0.68 | 68 | 0.92 | 49 |
| decision_1 | G_hybrid | 69 | 10,658.63 | 0.48 | 0.62 | 68 | 0.90 | 49 |
| decision_1 | H_ensemble | 66 | 9,949.05 | 0.32 | 0.69 | 65 | 0.96 | 46 |
| decision_1 | Z_last_change | 57 | 9,771.93 | 0.63 | 0.61 | 56 | 0.92 | 37 |
| decision_2 | A_mean | 57 | 19,298.08 | 0.39 | 0.77 | 55 | 0.94 | 31 |
| decision_2 | A_median | 57 | 18,964.91 | 0.21 | 0.71 | 55 | 0.94 | 31 |
| decision_2 | A_no_change | 57 | 18,894.74 | 0.21 | 0.71 | 55 | 0.94 | 31 |
| decision_2 | B_structural_proxy | 57 | 17,733.29 | 0.56 | 0.64 | 55 | 0.90 | 31 |
| decision_2 | C_distributed | 57 | 22,723.86 | 0.35 | 0.74 | 55 | 0.94 | 31 |
| decision_2 | C_ridge | 57 | 22,976.82 | 0.33 | 0.74 | 55 | 0.90 | 31 |
| decision_2 | E_lightgbm | 57 | 16,310.03 | 0.53 | 0.68 | 55 | 0.84 | 31 |
| decision_2 | F_catboost | 57 | 19,401.65 | 0.35 | 0.74 | 55 | 0.94 | 31 |
| decision_2 | G_hybrid | 57 | 22,570.27 | 0.37 | 0.71 | 55 | 0.90 | 31 |
| decision_2 | H_ensemble | 55 | 21,092.08 | 0.18 | 0.79 | 53 | 0.93 | 29 |
| decision_2 | Z_last_change | 48 | 21,270.83 | 0.62 | 0.60 | 47 | 0.88 | 25 |
| decision_4 | A_mean | 40 | 36,755.76 | 0.62 | 0.62 | 38 | — | 0 |
| decision_4 | A_median | 40 | 40,025.00 | 0.23 | 0.62 | 38 | — | 0 |
| decision_4 | A_no_change | 40 | 36,425.00 | 0.05 | 0.58 | 38 | — | 0 |
| decision_4 | B_structural_proxy | 40 | 37,939.76 | 0.62 | 0.56 | 38 | — | 0 |
| decision_4 | C_distributed | 40 | 64,977.11 | 0.33 | 0.74 | 38 | — | 0 |
| decision_4 | C_ridge | 40 | 64,301.05 | 0.33 | 0.74 | 38 | — | 0 |
| decision_4 | E_lightgbm | 40 | 36,856.07 | 0.47 | 0.57 | 38 | — | 0 |
| decision_4 | F_catboost | 40 | 37,660.36 | 0.45 | 0.64 | 38 | — | 0 |
| decision_4 | G_hybrid | 40 | 57,053.69 | 0.38 | 0.68 | 38 | — | 0 |
| decision_4 | H_ensemble | 39 | 41,763.48 | 0.10 | 0.66 | 37 | — | 0 |
| decision_4 | Z_last_change | 34 | 52,558.82 | 0.68 | 0.65 | 33 | — | 0 |

Families without admissible fits or OOF cases are not assigned invented errors. Final fit exclusions:

| horizon | family | train_base_decisions | reason |
| --- | --- | --- | --- |
| decision_1 | D_sarimax | 145 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| decision_1 | B_official_structural | 145 | Missing complete dated official parameters |
| decision_2 | D_sarimax | 130 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| decision_2 | B_official_structural | 130 | Missing complete dated official parameters |
| decision_4 | D_sarimax | 107 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| decision_4 | B_official_structural | 107 | Missing complete dated official parameters |
| day_1 | D_sarimax | 145 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| day_1 | B_official_structural | 145 | Missing complete dated official parameters |
| day_3 | D_sarimax | 139 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| day_3 | B_official_structural | 139 | Missing complete dated official parameters |
| day_7 | D_sarimax | 118 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| day_7 | B_official_structural | 118 | Missing complete dated official parameters |
| day_14 | D_sarimax | 99 | Latest contiguous sequence has fewer than minimum SARIMAX observations |
| day_14 | B_official_structural | 99 | Missing complete dated official parameters |
| day_30 | B_official_structural | 71 | Missing complete dated official parameters |

Identical-origin ensemble comparisons:

| horizon | baseline | n | ensemble_mae | baseline_mae |
| --- | --- | --- | --- | --- |
| day_1 | A_no_change | 248 | 2,530.22 | 2,346.77 |
| day_1 | Z_last_change | 205 | 2,570.78 | 4,299.30 |
| day_1 | B_structural_proxy | 248 | 2,530.22 | 3,647.35 |
| day_1 | C_ridge | 248 | 2,530.22 | 3,413.58 |
| day_14 | A_no_change | 133 | 38,045.89 | 34,977.44 |
| day_14 | Z_last_change | 112 | 39,620.62 | 46,061.01 |
| day_14 | B_structural_proxy | 133 | 38,045.89 | 38,585.14 |
| day_14 | C_ridge | 133 | 38,045.89 | 66,204.41 |
| day_3 | A_no_change | 224 | 8,076.26 | 7,705.36 |
| day_3 | Z_last_change | 187 | 8,198.20 | 9,280.75 |
| day_3 | B_structural_proxy | 224 | 8,076.26 | 8,744.39 |
| day_3 | C_ridge | 224 | 8,076.26 | 9,252.69 |
| day_30 | A_no_change | 72 | 59,291.67 | 59,291.67 |
| day_30 | Z_last_change | 66 | 55,893.94 | 116,247.84 |
| day_30 | B_structural_proxy | 72 | 59,291.67 | 68,611.58 |
| day_30 | C_ridge | 72 | 59,291.67 | 213,951.84 |
| day_7 | A_no_change | 179 | 18,819.03 | 17,837.99 |
| day_7 | Z_last_change | 154 | 19,633.81 | 21,559.52 |
| day_7 | B_structural_proxy | 179 | 18,819.03 | 17,991.43 |
| day_7 | C_ridge | 179 | 18,819.03 | 21,431.40 |
| decision_1 | A_no_change | 66 | 9,949.05 | 10,030.30 |
| decision_1 | Z_last_change | 57 | 9,923.46 | 9,771.93 |
| decision_1 | B_structural_proxy | 66 | 9,949.05 | 8,823.62 |
| decision_1 | C_ridge | 66 | 9,949.05 | 10,718.83 |
| decision_2 | A_no_change | 55 | 21,092.08 | 19,054.55 |
| decision_2 | Z_last_change | 48 | 21,647.17 | 21,270.83 |
| decision_2 | B_structural_proxy | 55 | 21,092.08 | 17,685.48 |
| decision_2 | C_ridge | 55 | 21,092.08 | 23,248.51 |
| decision_4 | A_no_change | 39 | 41,763.48 | 37,000.00 |
| decision_4 | Z_last_change | 34 | 43,022.81 | 52,558.82 |
| decision_4 | B_structural_proxy | 39 | 41,763.48 | 38,529.29 |
| decision_4 | C_ridge | 39 | 41,763.48 | 65,286.76 |

## Calibration procedure and limits

At each forecast origin, use only strictly earlier OOF predictions with labels already matured. Residuals are **actual minus prediction**, separately for each model and horizon. Calendar cases are no longer deduplicated by base decision. Keep at most 60 observations, one per k-calendar-day stride bucket, with k=floor(h_days/2), minimum 1. Decision horizons use the median past observed decision interval to express h in days. Rotating weekday priority avoids the fixed-weekday alias of a 7-day stride. Missing days mean equal representation cannot be guaranteed; per-bundle weekday counts are retained. The samples remain temporally dependent.

The 90% symmetric split-conformal radius uses the finite-sample order statistic of absolute residuals and the floor max(5,000, 0.25 × trailing-20 matured OOF MAE). At least 20 sampled residuals are required for a numeric calibrated candidate interval. Insufficient samples stay unavailable. **0 nonpositive-width intervals** were emitted. Raw LightGBM quantiles remain diagnostic and do not bypass the floor.

For each point prediction, classify prediction plus each empirical residual into decrease (<−3,000), no_change (within ±3,000 inclusive), or increase (>3,000). Apply additive Dirichlet/Laplace pseudo-count α=0.03: (class_count+α)/(M+3α). All emitted probabilities are strictly between zero and one and sum to one. The deadband is a user-specified research tolerance, **not a verified Ministry rounding rule**. No residuals means no probability estimate. Estimates with fewer than 20 residuals are explicitly small-sample and unvalidated. 7,145 model-origin probability rows have at least 20 calibration residuals; all reported Brier scores state their actual sample size.

The procedure does not establish calibration by name: inspect empirical coverage, width, Brier scores and `direction_reliability.csv` before approval. 2 model/horizon groups with measured coverage below 85% are flagged in `interval_calibration_failures.csv`. The 85% flag is diagnostic, not an approval threshold. Regime shifts, selected archive coverage, overlapping targets and approximate market availability invalidate an unconditional exchangeability guarantee.

Part 2 ends here. No held-out 2026 performance or production improvement is claimed.
