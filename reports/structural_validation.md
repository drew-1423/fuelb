# Part 4 validation

Generated from the preserved originals and SQLite data. Research protocol: `feb1b1d9d3d570a51c3e4a84261bdd60533e73662f592a0813cfe4469240724c`. Reproduce with `fuel-structure research` and `fuel-structure report`.

## Three official annex accounting checks

**This is same-document arithmetic, not prediction accuracy.** Each input component is published alongside the target price. Verified original annex dates: 2021-09-17 through 2025-05-29; n=3. All three pretax and VAT totals reconcile exactly. Unrounded pump-price MAE is **2.7333 LBP/20 L**, maximum 3.30, signed bias -0.5333. No rounding rule was fitted. No consecutive-annex change/direction sample exists.

| Document date | Official price | Unrounded reconstruction | Error LBP/20 L |
|---|---|---|---|
| 2021-09-17 | 174300 | 174303.30 | 3.30 |
| 2023-05-12 | 1635000 | 1634996.70 | -3.30 |
| 2025-05-29 | 1489000 | 1488998.40 | -1.60 |

The printed USD × FX does not exactly reproduce printed goods LBP in two annexes. This prevents claiming an exact authenticated upstream reconstruction. Component source URLs and hashes are in `data/manual/structural_annexes.json`.

## Strict historical forecast gate

**Eligible real-time structural/proxy evaluation sample: 0.** Neither archived market releases nor target publication instants are established. Earliest stored market availability is 2026-11-10T19:28:28.107081+00:00; earliest target retrieval is 2026-11-10T19:04:20.867602+00:00. Both follow the historical test dates. No real-time accuracy or current official-price forecast is certified.

## Retrospective chronological proxy study

This study uses **latest captured historical editions with assumed release delays**. Outcomes are official-archive prices or document/corroborated entries, not all individually authenticated original decisions. The target is the next adjacent eligible source-date record conditional on its known date; it is not a certified next-decision timing forecast. Gaps over 14 days and adjacent ineligible/conflicting records are excluded. Actual historical source release times, vintage revisions and same-day decision order remain unresolved.

The design contains 433 real eligible observation pairs across two separately fitted segments; 208 pairs within these segments were excluded. Target quality counts: `{'archive_corroborated': 420, 'government_archive': 13}`. No values were imputed. All candidates use identical rows within each regime. Target release is assumed no earlier than the next local day for reuse; market availability uses Part 3's 14-day EIA assumption plus candidate lags. Origins are 00:00 Asia/Beirut on the target source date.

The candidate grid is two series (NYH gasoline and Brent), averages of 1/5/10/20 market observations, and 0/7/14 extra calendar-day delays. Linear, three-block distributed-lag, rolling-40 and asymmetric models are compared with persistence and expanding mean-change drift. The distributed blocks add 0/7/14 days to the candidate delay. Averaging uses actual available quotes and rejects stale/long-gap windows. These are empirical proxy transforms, not official observation windows.

Validation selects one configuration per family and one overall champion. Selected configurations are saved **before final-test calculation**. Final-test coefficients update using earlier outcomes only; lags/windows/family stay frozen. The pre-crisis validation year is 2017, final test Jan 2018–Aug 2019. The recent segment validates on 2024 and tests Jan–28 May 2025. No final-test outcome is used for tuning. Training scaling is fitted afresh within each chronological fold.

### Final chronological test metrics — research only

All error figures are LBP/20 L; positive bias is overprediction. Direction uses exact up/unchanged/down, including unchanged decisions. Because both predicted and actual changes subtract the same previous observed price, change MAE equals price MAE algebraically; it is not a second independent success measure.

| Segment | Validation-chosen configuration | Champion | n | First | Last | Price/change MAE | Bias | Direction fraction | Interval n | 90% coverage | Mean width |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pre_crisis | persistence | False | 86 | 2018-01-10 | 2019-08-28 | 290.70 | 4.65 | 0.14 | 86 | 0.93 | 1,153.49 |
| pre_crisis | drift | False | 86 | 2018-01-10 | 2019-08-28 | 294.49 | -11.18 | 0.38 | 86 | 0.90 | 1,132.55 |
| pre_crisis | linear:nyh_gasoline:w5:lag0 | False | 86 | 2018-01-10 | 2019-08-28 | 220.76 | -4.86 | 0.64 | 86 | 0.86 | 882.70 |
| pre_crisis | distributed_lag:nyh_gasoline:w10:lag0 | False | 86 | 2018-01-10 | 2019-08-28 | 181.79 | -0.93 | 0.72 | 86 | 0.88 | 756.80 |
| pre_crisis | rolling_linear:nyh_gasoline:w10:lag0 | False | 86 | 2018-01-10 | 2019-08-28 | 193.94 | 21.38 | 0.73 | 86 | 0.91 | 776.77 |
| pre_crisis | asymmetric:nyh_gasoline:w10:lag0 | True | 86 | 2018-01-10 | 2019-08-28 | 185.24 | -4.26 | 0.71 | 86 | 0.92 | 764.15 |
| recent_pre_fiscal | persistence | False | 19 | 2025-01-07 | 2025-05-20 | 14,526.32 | 5,578.95 | 0.00 | 19 | 0.89 | 47,157.89 |
| recent_pre_fiscal | drift | False | 19 | 2025-01-07 | 2025-05-20 | 14,273.75 | 3,447.61 | 0.63 | 19 | 0.89 | 46,691.55 |
| recent_pre_fiscal | linear:nyh_gasoline:w1:lag0 | False | 19 | 2025-01-07 | 2025-05-20 | 13,392.29 | 3,004.34 | 0.58 | 19 | 0.95 | 50,183.36 |
| recent_pre_fiscal | distributed_lag:nyh_gasoline:w1:lag0 | False | 19 | 2025-01-07 | 2025-05-20 | 13,186.91 | 3,029.26 | 0.68 | 19 | 0.95 | 49,929.80 |
| recent_pre_fiscal | rolling_linear:nyh_gasoline:w1:lag0 | False | 19 | 2025-01-07 | 2025-05-20 | 13,456.13 | 3,068.72 | 0.74 | 19 | 0.95 | 48,827.04 |
| recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | True | 19 | 2025-01-07 | 2025-05-20 | 14,492.04 | 4,452.22 | 0.53 | 19 | 0.84 | 46,169.43 |

### Uncertainty

Intervals use only the last 40 earlier one-step prequential absolute residuals, require at least 20, and use the finite-sample higher order statistic for nominal 90% coverage. Calibration can include previously realized test outcomes, never the current/future target. Lower price bounds are clipped at zero. Dependent time-series errors, selected models and regime shifts violate simple exchangeability guarantees: measured coverage is reported, not promised. Do not apply these research intervals to the current fiscal regime. The structural engine's input-bound range is a separate, uncalibrated conditional scenario range.

## Training-only diagnostics

| Segment | Initial train n | First | Last | CUSUM p | Rise slope | Fall slope | Rise/fall p |
|---|---|---|---|---|---|---|---|
| pre_crisis | 185 | 2012-01-02 | 2016-12-28 | 0.34 | 23.44 | 54.17 | 0.19 |
| recent_pre_fiscal | 65 | 2023-05-16 | 2023-12-29 | 0.00 | 1,153.59 | 894.46 | 0.80 |

Slopes are LBP/20 L change per USD/bbl change in the fixed NYH proxy specification. CUSUM does not date a regulatory break. Rise/fall tests use HC1 and remain vulnerable to serial dependence, omitted FX/policy and proxy basis. ECM gate details are in `training_diagnostics.json`; irregular and incomplete samples must not be interpolated into a cointegration result.

## Interpretation and readiness

The three annex checks establish a working dated cost engine. The proxy experiment quantifies what these particular historical datasets support, with separate regimes and held-out dates. It does not identify the statutory averaging window, causal transmission lag, current margins or a deployable structural forecast. Prefer the validation-selected simple baseline whenever a challenger fails to improve validation. Final-test performance is disclosed for all selected family representatives without changing that choice.

Before a production next-decision estimate: obtain a current original annex and legal parameters, the authorized refined assessment and cutoff/window, goods FX and import costs, original release vintages and target timestamps. Current proxy input observations are recorded in the run manifest. Paid Med gasoline/freight data would reduce product/geographic basis uncertainty but would still need the actual retail formula and information-time history.
