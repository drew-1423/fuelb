# Forecasting methodology

Status: original Part 1 research design, 10 November 2026. Part 4 now implements dated cost accounting and explicitly retrospective statistical comparisons; see [transmission research](structural_transmission.md) and [validation](../reports/structural_validation.md). No certified real-time accuracy claim exists. The primary target is the next official 95-octane pricing **decision**, including a decision with unchanged price. The next nonzero price change is a separate event target with potentially later timing.

## Targets and horizons

| Horizon | Recommended starting method | Main uncertainty |
| --- | --- | --- |
| Next decision | Last verified price baseline; evidenced structural nowcast when current components/window are known; regularized distributed-lag/ARX residual challenger | Cutoff/window, FX, tax/margin intervention, decision timing |
| Subsequent decisions | Recursive or direct event-horizon econometric forecasts; structural cost scenarios | Unknown future refined benchmarks, FX, policy and compounding errors |
| 7 calendar days | Distribution over decisions within seven days and price effective at the endpoint; include no-decision path | Holiday/exceptional schedule, unobserved inputs |
| 30 calendar days | Probabilistic commodity/FX/policy paths passed through validated regime rules; broad calibrated intervals | Regime change, basis risk and nonlinear cost shocks |

## Hybrid components

1. **Structural model:** versioned tax/cost/FX/rounding parameters from dated official evidence. Reproduce annex totals before forecasting. Unknown parameters disable a claim of exact formula replication; a statistical proxy must be labelled.
2. **Econometrics:** start with persistence, drift where justified, regularized ARX/distributed lags and small SARIMAX models. Test stationarity/cointegration assumptions on training data. Candidate lag lengths and window choice are hyperparameters, not discovered laws.
3. **Machine learning:** LightGBM/CatBoost are optional challengers for nonlinear interactions, not default winners. Restrict complexity, thread counts and feature count for the limited event sample. Tree categorical ordering is not chronological backtesting.
4. **Commodities:** distinguish refined Mediterranean products, crude, cracks, freight and insurance; align quotation definitions and release availability. This is a later stage, not Part 2 implementation.
5. **News classification:** optional labels for enacted policy, proposals, outages and freight risks. Retain article version, publication and first-seen timestamps, text provenance and classifier version. Human/legal verification controls formula changes. News is neither a fabricated price input nor an automatic policy enactment signal.
6. **Probabilistic outputs:** price and change quantiles plus up/unchanged/down probabilities. Calibrate on preceding observations only, assess interval width and empirical coverage by horizon/regime. Stress scenarios are conditional narratives; probabilities require evidence and calibration.

## Validation protocol

Use an immutable as-of dataset: an input and its revision must have been available by the forecast origin. A historical date alone does not establish that availability. Unknown release times require conservative lagging and sensitivity runs. Freeze a final chronological holdout before selection. Within earlier data, use nested chronological expanding/rolling evaluations, purge labels overlapping validation windows and fit all transforms, imputers, feature selection and tuning inside training folds. For 7/30-day targets, exclude training labels whose realization is later than the origin. Splits must be calendar/event aware because decision intervals vary.

[Scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) documents time ordering and its equal-spacing limitation; [its leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html) motivates training-only transforms (rolling documentation, inspected 2026-11-10). A library splitter alone does not solve publication-time leakage.

Compare models on identical eligible origins/information sets. Report MAE and RMSE in LBP/20 L, change error, directional balanced accuracy with unchanged class, sample counts/dates, calibration, interval scores, pinball loss and Brier score where applicable. Scale-relative errors use training-only denominators. Use time-block uncertainty for comparisons; overlapping targets are dependent. Report omitted/conflicting origins and results by regime. Choose the simpler model unless repeatable validation gains exceed uncertainty and operational cost.

Historical source dates, disputed observations, gaps and uncertain regimes currently prevent a defensible institutional backtest. Part 2 improves the evidence base; international data and later audited evaluation remain prerequisites for model readiness.
