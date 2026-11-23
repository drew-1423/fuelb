# Part 5 quantitative forecasting

Status: development implementation completed on 11 November 2026. Results are in [the development report](../reports/forecasting_development.md). Live forecasting remains disabled. Part 6 has not run.

## Install and reproduce

Executed on native Apple Silicon macOS with CPython 3.13.12. LightGBM requires the macOS OpenMP runtime; `brew install libomp` was executed successfully (libomp 23.1.4). No GPU, paid API or language-model service is required. The lockfile records the executed environment, including CatBoost's Plotly dependency; the separate dashboard extra is not installed or validated by this stage.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-forecasting-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/fuel-forecast build
.venv/bin/fuel-forecast train
.venv/bin/fuel-forecast news-ablation
.venv/bin/fuel-forecast report
.venv/bin/fuel-forecast preview --regime recent_pre_fiscal --horizon decision_1
.venv/bin/fuel-forecast forecast-gate
.venv/bin/python -m pytest Tests/fuel -q
.venv/bin/python scripts/audit_forecasting_artifacts.py
```

Collection is separate: `.venv/bin/fuel-forecast news` fetches the two verified EIA feeds with the existing access-control and rate-limit policy. Repeated successful captures preserve sightings and revisions. No recurring job is registered. Training uses existing local observations and does not download data. It replaces the Part 5 run artifacts; preserve a completed run directory before a deliberate research change. Parts 1–4 outputs are not rewritten by this command.

## Targets and clocks

Let `P(o)` be the latest eligible source-record price assumed known at origin `o`.

- `decision_k`, k = 1, 2, 4: `P(kth following recorded decision) − P(o)`. Origins are the midnight after each source date. An intervening invalid/conflicting record makes the path ineligible. These are not guaranteed to be the kth actual official decisions if the archive missed an announcement.
- `day_d`, d = 1, 3, 7, 14, 30: last eligible record assumed known at the endpoint minus `P(o)`. Origins are daily Beirut midnights. The endpoint is a local calendar-date shift, including DST. A price between announcements is a **conditional derived prevailing value**, not an invented raw daily observation. A following record must witness coverage; the label matures only after that witness and the endpoint.

The archive provides source dates, usually neither original publication instants nor established effective dates. Research assumes availability at the following Asia/Beirut midnight; this assumption is never written into source publication fields. Market features use Part 3's conservative assumed release delays and latest downloaded editions. Strict original-vintage historical availability remains unsupported. Missing official or Lebanese holiday schedules are not replaced by a fabricated daily announcement schedule.

Forecast exports contain UTC/Beirut origin, base revision/date/price/status, horizon, target interpretation, calendar endpoint where applicable, price-change estimate, conditional endpoint-price estimate, uncertainty status and production gate. An empirical waiting-time estimate from past intervals is separate from price forecasts and is not an official announcement date. Zero change and no announcement are distinct events.

## Training boundaries

The protocol `config/forecasting_research.json` was hashed before construction/fitting. An implementation supplement was frozen before the first fits. `training_inputs.json` records actual feature/design/code hashes and package versions. The final stage records later output-only changes separately; no model setting was selected after viewing performance.

| Stratum | Development target period | Expanding fold origins |
| --- | --- | --- |
| Pre-crisis | 2012 through 2017 | 2015-01-01, 2016-01-01, 2017-01-01 |
| Recent pre-fiscal | 2023-05-12 through 2024 | 2023-10-01, 2024-04-01, 2024-08-01 |

Each fold is a fixed-parameter deployment block: later predictions may use newly available past features, but parameters stay fixed until the next fold. Every fitting label, ensemble-weight label and calibration label must mature **strictly before** the fold origin. Overlapping calendar and event targets are purged at boundaries; chronological inner tuning applies the same rule. There is no shuffled cross-validation. Repeated daily rows receive inverse-base-decision-count weights; minimum ML sample size counts unique base revisions. Scaling is fit on training rows only. Source gaps/conflicts can exclude a target retrospectively, so measured accuracy is conditional on archive eligibility.

The 2018–2019 and 2025 target periods do not enter Part 5 fitting, tuning, weighting, calibration or performance tables. Part 4 already reported results from those periods; disclose that exposure during Part 6. No present-day parameter extrapolation from either historical nominal-LBP stratum is approved.

## Model cards

| Family | Implementation and constraint |
| --- | --- |
| A | Zero cumulative change; base-weighted historical mean and median at each horizon. Required for every comparison. |
| B official | Calls the Part 4 Decimal engine. Requires dated benchmark/FX/cost/tax coverage and explicit future-input scenarios. Missing inputs cause abstention. Same-annex arithmetic is not forecast validation. |
| B structural proxy | `ΔP = max(0, β̂) × (latest NYH gasoline − trailing 20-quote mean)`. Weighted least squares through zero, trained separately per horizon/regime. β has units `(LBP/20 L)/(USD/bbl)` and combines transmission/basis/FX effects. This is a constant-policy, flat-future-market pressure scenario, **not an official parameter or FX estimate**. |
| C | Ridge with training-only median imputation/missingness flags/scaling; chronological purged inner MAE selects α in {1,10,100}. Distributed variant adds 7/14-calendar-day commodity lags. Default strong regularization if the inner split is too small. |
| D | Direct-horizon regression with SARIMAX AR(1) errors and four exogenous features. Minimum latest contiguous run 40; gaps are not compressed. Stationarity enforced; nonconvergence abstains. Event index and daily calendar index are separate. Exogenous inputs are current known snapshots; no future realized prices enter multi-step state projection. |
| E | LightGBM, 80 trees, depth 3, minimum leaf 20, learning rate .04, L2 10, deterministic CPU/two threads. Separate .05/.95 quantile fits. Minimum 60 distinct base decisions. |
| F | CatBoost, 80 trees, depth 3, learning rate .04, L2 10, RMSE, fixed seed, two CPU threads. Minimum 60 distinct base decisions. |
| G | Positive structural proxy plus LightGBM correction. Base residuals are cross-fitted from earlier temporal blocks, with maturity purging; at least 24 distinct residual base decisions and 60 overall. Final base slope uses the whole eligible training period. |
| H | Per-horizon/regime convex weights minimize base-weighted MAE of earlier matured OOF predictions on common origins. Minimum 20 distinct base decisions. Prefer the first prespecified simpler single model within 2% of the blend; no-history fallback is explicitly no-change. |

The free product feature is **New York Harbor regular gasoline**, not Mediterranean 95 RON. Brent is a crude proxy. Italy/Greece ex-tax prices are retail proxies. NYH minus Brent is a cross-region/product spread, not realized refinery profit. No licensed Med, freight, current tax or continuous official pricing-FX series has been fabricated. EUR/USD is observed separately and is never interpreted as USD/LBP. Policy separation is through explicit historical strata; unknown regulatory dates are not feature flags asserted as legal fact.

Other features: domestic change lags, trailing mean/volatility, observed pricing intervals and elapsed time, weekday/month, commodity returns/momentum/means/lags, U.S. inventories/utilization and EUR/USD movements. Market provenance records observation/capture IDs. Missing features may be imputed with training medians plus flags; targets and historical prices are never imputed. Tree feature importance is not a causal attribution.

## Uncertainty and model comparison

Every comparison reports origin count, distinct base decisions, MAE, RMSE, bias, sign accuracy and baseline coverage. No MAPE is used for zero changes. Pairwise baseline comparisons share exact origins; `common_origin_metrics.csv` supplies all-family and core-family intersections. Do not compare headline errors across different nominal currency regimes or unequal origins.

Intervals use matured earlier OOF errors: minimum 20, maximum 80 nonoverlapping windows, at most one per base decision, finite-sample higher 90% empirical quantile. E can expand its fitted quantile interval using earlier nonconformity errors. Serial dependence, regime drift and deterministic thinning prevent a finite-sample coverage guarantee. All bounds are experimental candidates. The report explicitly discloses observed short-calendar ensemble undercoverage and degenerate intervals; failed candidates remain visible for audit and are not approved for use. Long horizons often lack enough calibration examples.

Direction probabilities use a separate shared exact-sign model. A regularized logistic fit and a later purged holdout estimate one temperature when there are at least 30 fit and 20 calibration base decisions; otherwise weighted Jeffreys-smoothed historical frequencies are marked uncalibrated. It does not refit the classifier after estimating temperature. Scores include multiclass Brier and log loss; percentages are model estimates, not guarantees. Point-model sign and the separate classifier can disagree. No unchanged-price tolerance is invented.

## Artifacts

- `data/exports/forecasting/`: immutable-in-run design and origin-feature CSV snapshots, with lineage. These are derived research records, not additional observed prices.
- `data/models/part5/<regime>/<horizon>/`: bundled transformations/models/direction/ensemble/calibration; native LightGBM/CatBoost files; JSON evidence manifest. Sixteen bundles, with family-specific abstentions.
- `reports/forecasting/`: per-origin development predictions, all metrics, common-origin comparisons, fit/calibration logs, exclusions, preliminary historical forecasts, current gates, news findings and hashes.
- `reports/forecasting_development.md`: human-readable findings; `research/quantitative_forecasting_protocol.md`: study limitations and evidence.

Only load trusted local model bundles. A hash detects accidental changes, not malicious pickle content. `preview` validates the saved feature snapshot hash and reproduces the historical fit origin; it does not silently use today's date. Updating data requires a new development run and review. Current official output remains an abstention until the missing source/parameter/regime and independent validation gates are resolved.

## Technical references

Rolling documentation inspected 2026-11-11; publication dates are not stated: [statsmodels SARIMAX](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html), [scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html), [LightGBM parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html), [macOS installation](https://lightgbm.readthedocs.io/en/stable/Installation-Guide.html), [CatBoost installation](https://catboost.ai/docs/en/concepts/python-installation). These document software behavior; they do not validate this project's economic assumptions or accuracy.
