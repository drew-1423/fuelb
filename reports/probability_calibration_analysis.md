# Probability and interval validation

No probability or interval system is approved. See [the validation report](model_validation_report.md#uncertainty-verdict).

| regime | probability_model | n | distinct_base_decisions | brier_multiclass | brier_no_change | log_loss |
| --- | --- | --- | --- | --- | --- | --- |
| pre_crisis | shared_direction | 86 | 86 | 0.39 | 0.12 | 0.70 |
| pre_crisis | training_class_frequency | 86 | 86 | 0.62 | 0.12 | 1.01 |
| pre_crisis | always_no_change | 86 | 86 | 1.72 | 0.86 | 23.78 |
| recent_pre_fiscal | shared_direction | 19 | 19 | 0.45 | 0.00 | 0.70 |
| recent_pre_fiscal | training_class_frequency | 19 | 19 | 0.49 | 0.00 | 0.73 |
| recent_pre_fiscal | always_no_change | 19 | 19 | 2.00 | 1.00 | 27.63 |

Calibration failure mechanism:

| regime | horizon | cutoff | eligible_error_n | retained_n | all_zero_change_fraction | retained_zero_change_fraction |
| --- | --- | --- | --- | --- | --- | --- |
| pre_crisis | day_1 | 2016-01-01T00:00:00+02:00 | 239 | 37 | 0.90 | 1.00 |
| pre_crisis | day_1 | 2017-01-01T00:00:00+02:00 | 361 | 58 | 0.90 | 1.00 |
| pre_crisis | day_3 | 2016-01-01T00:00:00+02:00 | 223 | 36 | 0.68 | 1.00 |
| pre_crisis | day_3 | 2017-01-01T00:00:00+02:00 | 325 | 55 | 0.69 | 0.98 |
| recent_pre_fiscal | day_1 | 2024-04-01T00:00:00+03:00 | 141 | 40 | 0.73 | 0.97 |
| recent_pre_fiscal | day_1 | 2024-08-01T00:00:00+03:00 | 141 | 40 | 0.73 | 0.97 |
| recent_pre_fiscal | day_3 | 2024-04-01T00:00:00+03:00 | 137 | 20 | 0.18 | 0.90 |
| recent_pre_fiscal | day_3 | 2024-08-01T00:00:00+03:00 | 137 | 20 | 0.18 | 0.90 |

All horizons, class bins, ECE, interval counts and widths are exported under `model_validation/`. Repeated point-model rows share one direction classifier. No 95% prediction interval is claimed.
