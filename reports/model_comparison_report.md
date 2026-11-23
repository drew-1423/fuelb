# Model comparison

**No production selection.** Descriptive common-origin results:

| regime | horizon | descriptive_best | n | distinct_base_decisions | mae_lbp | direction_accuracy | no_change_mae_lbp | production_approved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pre_crisis | day_30 | C_ridge | 565 | 81 | 842.46 | 0.66 | 1,062.65 | False |
| pre_crisis | day_7 | Z_last_change | 588 | 84 | 154.42 | 0.72 | 289.80 | False |
| pre_crisis | decision_1 | Z_last_change | 85 | 85 | 150.59 | 0.73 | 291.76 | False |
| recent_pre_fiscal | day_30 | A_mean | 9 | 2 | 34,763.07 | 1.00 | 58,666.67 | False |
| recent_pre_fiscal | day_7 | G_hybrid | 46 | 11 | 23,337.51 | 0.54 | 27,304.35 | False |
| recent_pre_fiscal | decision_1 | Z_last_change | 15 | 15 | 11,066.67 | 0.87 | 15,866.67 | False |

See [the validation report](model_validation_report.md) for baseline definitions, sample restrictions and uncertainty. `model_validation/baseline_comparisons.csv` compares every emitted family with every required baseline; official structural inputs are explicitly unavailable.
