# Estimated transmission relationships — Part 4

These estimates use genuine historical observations, latest captured editions and **assumed availability**. They are not official government parameters, identified causal pass-through or certified real-time forecasts. Full validation and final results are in `../reports/structural_validation.md`.

## Equations and timing

For adjacent eligible domestic source dates d and d−1, define `y_d = P_d − P_(d−1)`. For proxy s, trailing mean over w actual market observations and additional calendar lag l, define `M_(s,w,l)(t)` using only observations with the Part 3 assumed availability no later than `t−l`. EIA's assumed 14-day release delay is **already included**, before l. Set `x_d = M(origin_d) − M(origin_(d−1))`; the old origin is midnight on the previous source date, not a retrospectively optimized market cutoff.

- Persistence: `y_hat=0`.
- Drift: expanding training mean of prior y.
- Linear: `y_hat = a + b*x_d`.
- Distributed lag: `y_hat = a + b0*x_(d,l) + b1*x_(d,l+7) + b2*x_(d,l+14)`. These overlapping quote-change windows can be collinear; coefficients are predictive sensitivities rather than identified economic lag weights.
- Rolling linear: same equation fitted to the latest 40 eligible training pairs, or all available past pairs if fewer after the minimum 24.
- Asymmetric: `y_hat = a + b_up*max(x_d,0) + b_down*min(x_d,0)`. Negative x remains negative; b_down is a slope, not the size of a fall.

OLS uses training-only centering/scaling and least squares; fitted coefficients are converted back to original units. The raw coefficient/intercept, rank, scaling and training dates are recorded with each prediction. The saved final-origin values are tabulated in `estimated_transmission_parameters.csv`; no coefficient is promoted into the dated official component table. The latter is `structural_parameters.csv`.

Observed next price is reconstructed as `P_(d−1)+y_hat`. No arbitrary price-rounding adjustment or final-target residual is used. Identical origins are required for all family comparisons. The observed decision calendar is conditioned upon: this experiment does not predict when an announcement will occur.

## Findings from validation and held-out dates

| Segment | Validation-only selection | Final sample | Mean absolute error, selected / persistence, LBP per 20 L | Interpretation |
|---|---|---:|---:|---|
| Pre-crisis research segment | NYH asymmetric, 10 quotes, no extra lag | 86; 10 Jan 2018–28 Aug 2019 | 185.24 / 290.70 | Useful retrospective association; no proof of the official window or asymmetric pricing conduct |
| Recent segment before fiscal changes | Brent asymmetric, 20 quotes, 14 extra days | 19; 7 Jan–20 May 2025 | 14,492.04 / 14,526.32 | Only 0.24% improvement over persistence; worse than drift (14,273.75). No persuasive practical improvement |

The latter choice uses at least the 14-day assumed data delay plus 14 extra days and a 20-observation average. It must **not** be described as an empirically established 14-day Lebanese transmission delay. The two regimes choose different proxies/windows; the small recent validation sample (26 dates) and 98 candidates create selection risk. All failed candidates remain visible. The best final-test family is not retrospectively declared the winner.

There is no strong evidence of rise/fall asymmetry in the fixed training-only one-quote NYH diagnostic: p=0.1894 before the crisis and p=0.8009 in the later sample. These tests use HC1 and do not address all time dependence. Recent training CUSUM p=0.00161 signals possible parameter instability under its assumptions; it does not locate a policy break or prove its cause. Pre-crisis p=0.34186 is a failure to detect instability, not proof of constancy.

## ECM and inferential limits

The existing selected event sequence fails the declared regular-sample ECM gate; it has irregular intervals and gaps, and the later period lacks complete goods FX. No error-correction coefficients are estimated or claimed. A supported long-run equation, regular compatible observations and training-only integration/cointegration evidence are prerequisites in this implementation. This conservative gate does not assert that every possible irregular-time ECM is mathematically impossible.

Method references, rolling official documentation inspected 11 November 2026: [ADF](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html), [Engle–Granger cointegration](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html), [CUSUM of OLS residuals](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.breaks_cusumolsresid.html). Diagnostic assumptions and statistical uncertainty prevent causal or regulatory interpretations. A full pricing-FX history and authorized refined assessments could change the admissible research design.
