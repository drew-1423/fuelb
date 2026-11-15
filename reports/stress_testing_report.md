# Stress testing

Observed historical results and synthetic engineering checks are separate. See [the validation report](model_validation_report.md#stress-and-reliability-limits).

| regime | stress | n | change_mae_lbp | direction_accuracy |
| --- | --- | --- | --- | --- |
| pre_crisis | rapid_increase | 1 | 57.54 | 1.00 |
| pre_crisis | rapid_decline | 1 | 220.77 | 1.00 |
| pre_crisis | high_volatility | 7 | 138.90 | 0.86 |
| recent_pre_fiscal | rapid_increase | 0 | — | — |
| recent_pre_fiscal | rapid_decline | 1 | 14,908.10 | 1.00 |
| recent_pre_fiscal | high_volatility | 0 | — | — |

`model_validation/synthetic_sensitivity.csv` records 162 hypothetical input perturbations, with no invented actual prices. `stress_gate_checks.json` records ten isolated guard checks. `policy_stress_coverage.json` reports out-of-domain source coverage and zero model evaluations for unsupported FX/subsidy/fiscal regimes. Current forecasts abstain; uncertainty is not supplied when unsupported.
