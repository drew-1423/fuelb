# Part 6 validation and forecast accountability

This document preserves the Part 6 protocol and findings. Parts 7 and 8 subsequently added the dashboard and native operating workflow without changing the rejection decision. Current instructions are in [operations](operations.md); the dated final status is in [the final report](../reports/final_project_report.md).

Decision: **no production model approved**. Start with [the model validation report](../reports/model_validation_report.md). Strict historical prediction count is zero; numerical results are explicitly exposed latest-vintage research challenges. The final prospective holdout has no outcomes yet. Part 7 has not started.

## Reproduce

Use the executed Part 5 environment in `requirements-forecasting-lock.txt`; validation introduces no new dependency or paid API.

```bash
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/fuel-validate run
.venv/bin/fuel-validate stress
.venv/bin/fuel-validate report
.venv/bin/fuel-validate ledger-check
.venv/bin/python scripts/audit_validation_artifacts.py
.venv/bin/python -m pytest Tests/fuel -q
```

`run` reads the frozen protocol and source data, keeps Part 5 artifacts unchanged, writes separate Part 6 models/reports and appends explicitly retrospective forecasts to the permanent ledger. Re-execution creates another named research run; it cannot erase the earlier run or transform it into an originally issued forecast. Repeated reproduction is not new holdout evidence. Do not change model settings in response to the challenge outcomes and reuse those outcomes as a fresh test.

`stress` scores observed input-state subsets, runs synthetic perturbations, and records eight current prospective abstentions with actual input snapshots. Repeated executions append new current checks. It does not schedule a recurring job. `report` only reads completed results and recomputes diagnostic tables; it does not fit models or revise forecasts.

## Separate evidence paths

| Path | Behavior |
| --- | --- |
| `validation/backtest.py:walk_forward_strict` | Requires aware actual knowledge timestamps, certified captured editions/target definitions, strict `< origin` joins, purged training labels and explicit partitions. Prediction callbacks receive only input/anchor columns. Final-holdout labels are never subsequently added to training. |
| `strict_design_from_lineage` | Reads real market sighting and domestic reconciliation-version times. These occur in November 2026, after every historical origin. Official sequence/effective-clock certification is absent; actual execution abstains. It does not turn date-only rows into certified timestamps. |
| `validation/runner.py` | Separately evaluates exposed 2018–2019/2025 research challenges under Part 5 assumptions. Fixed refit schedule and algorithms; all supervised steps use matured past labels under the declared assumptions. |
| `validation/metrics.py` | Independent equations and sample counts; common-origin baseline comparisons, class reliability, dependent block-bootstrap diagnostics. |
| `validation/policy.py` | Operational guard checks approval, regime, anchor knowledge/effect, required market knowledge/observation age and FX/tax/intervention risks. Failures abstain. |

The source adapter deliberately fails closed if new strict evidence appears without a reviewed eligibility update. The generic strict evaluator can evaluate a subsequently certified design; current date-only/late-capture records do not satisfy its contract. A captured edition can establish knowledge from its capture time forward even without an original release clock; it cannot establish knowledge at an earlier historical origin. A target’s future actual value is used only for evaluation or later matured training, never in its input snapshot.

## Chronology and final holdout

Part 5 development ends in 2017 / 2024. The Part 6 research challenge spans 2018-01-01–2019-08-31 and 2025-01-01–2025-05-28. Refits are frozen in `config/validation_protocol.json`; previous-quarter outcomes can enter subsequent **research** training only after maturity. Inner ridge tuning remains inside each training period. H weights and intervals use earlier matured OOF records only. No new hyperparameter or calibration repair was selected from challenge results.

Those challenge periods were already examined in Part 4. `research/evidence/validation_protocol_freeze.json` records the start of a separate **prospective final holdout**. No completed outcome from it has been scored or used for fitting. Future validation should predeclare its size/end, model versions and collection coverage before admitting outcomes. Current requirements include at least 100 strict final origins, evidence across regimes, defensible uncertainty and fresh-holdout provenance; those thresholds are governance choices, not sufficient statistical proof by themselves.

## Metrics and uncertainty

`metrics.csv` gives each statistic’s applicable count. Error/classification rows have `n`, probability rows have `probability_n`, interval rows have `interval_n`, class recall/precision have actual/predicted class counts. Distinct base decisions and evaluation dates are reported alongside daily rows. Price MAE equals change MAE when both use the same base anchor. The binary no-change accuracy can be misleading with imbalanced classes; recall/precision and Brier scores are also supplied.

The shared direction classifier is compared separately with training-only class frequencies and always-unchanged probabilities. Reliability bins and ECE are descriptive, not certificates. Nominal 90% prediction intervals fail in several horizons; absent intervals remain absent. No 95% prediction interval is advertised. Calibration thinning is confirmed to skew the retained sample toward zero changes and is rejected for operational use.

An additional numerical check found extra order-statistic conservatism: with 20 distinct residual magnitudes 1–20, the code's `quantile(ceil(21×0.9)/20, method='higher')` returns 20; direct selection of sorted residual `k=ceil(21×0.9)` returns 19. This makes that radius wider, so it does not explain the observed undercoverage. The scored implementation is preserved; the convention should be stated explicitly in any revised calibration method. [NumPy's quantile documentation](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html), inspected 2026-11-11, specifies the interpolation/order convention. [Romano, Patterson and Candès (2019)](https://arxiv.org/abs/1905.03222) provides the underlying conformalized-quantile methodology; its guarantee cannot be transferred to this selected, dependent residual sample without its assumptions.

Log-loss calculations clip numerical probabilities to `1e-12` before taking logarithms; the exactly unchanged deterministic baseline would otherwise have infinite loss on a change. Brier scores use the original probabilities and are not clipped.

Paired comparison intervals use circular blocks of base-decision average loss differences, 1,000 draws, fixed seed, nominal 90%, and prespecified minimum effective sample. They describe uncertainty in a **mean loss difference**, not a future price. Dependence, irregular gaps, regime drift, model multiplicity and prior test exposure limit inference; no confirmatory significance claim or production promotion follows from them. Tiny recent samples produce no inference interval.

Primary methods documentation, inspected 2026-11-11 (rolling publication date not stated): [scikit-learn probability calibration](https://scikit-learn.org/stable/modules/calibration.html) explains reliability curves and why Brier score includes more than calibration; [arch time-series bootstrap documentation](https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html) describes circular/stationary blocks. The project implements its small bootstrap directly with NumPy; `arch` is not an added dependency. Method documentation does not establish the assumptions needed for this dataset.

## Permanent ledger schema

SQLite file: `data/forecast_ledger.sqlite`.

| Table | Immutable content |
| --- | --- |
| `snapshots` | Content hash, creation time, forecast origin/mode, base and available feature/market inputs with source IDs |
| `models` | Artifact hash/identity, creation time, metadata and approval state; current API registers research models only |
| `forecasts` | True creation timestamp; origin; issuance mode; model and snapshot references; horizon/target rule; base/predicted price; predicted change; optional **change** interval and decrease/unchanged/increase probabilities; abstention reasons; hash chain |
| `outcomes` | Original decision key, publication/effective/available timestamps, observed price, source URL/revision/hash and evidence; corrections append |
| `evaluations` | Forecast/outcome links, signed price error, actual change, interval hit, direction hit and supersession link |
| `match_attempts` | Match time, status and reviewed coverage evidence |

Forecast interval endpoints are in change units; add the immutable base price to obtain price endpoints. Errors are forecast minus actual. A revision appends another evaluation and references the superseded evaluation; it does not change the forecast. All tables reject update/delete. The hash chain covers original forecast values, but SQLite and local files are not externally notarized storage. Back up both SQLite databases, raw captures, source/model code, model artifacts and manifests together. Do not delete old artifacts to reduce a report’s sample size.

Modes are explicit:

- `retrospective_research`: generated today using historical research assumptions; never claimed to have been issued historically.
- `strict_replay`: replay from genuinely certified historical information; currently zero actual admissible forecasts.
- `prospective_research`: generated now for future outcomes, marked unapproved for production. It permits prospective evidence collection once data/target gates are satisfied; approval is not a prerequisite for conducting properly gated research.
- `prospective`: production-facing numerical issuance requires an approved model. Current entries are abstentions, so no price, interval or probability is fabricated.

The low-level ledger is an accountability store, not a substitute for the operational guard. Call the guard before prospective research or operational issuance. Current data/regime gates still block numerical research outputs. `created_at` is assigned by the ledger; a prospective origin more than one minute away from creation is rejected. Past forecasts cannot be relabeled as prospective by supplying a historical timestamp.

## Match actual decisions

Do not guess an announcement/effective clock from a date-only archive. First ingest/review the original official observation through the source pipeline. Then prepare a local JSON manifest with:

- `reviewer` and `clock_evidence_url` for the original publication/effective-time evidence;
- `outcomes`: each contains `source_observation_id`, `official_decision_key`, `price_lbp_20l`, aware ISO `publication_timestamp`, `effective_timestamp`, `available_at`, and optional `source_revision_id`;
- `coverage`: `certified: true`, aware `from`/`through`, and `evidence_url` attesting the complete decision sequence over the interval;
- `forecast_ids` to match.

```bash
.venv/bin/fuel-validate settle --manifest /absolute/path/to/reviewed_outcomes.json
```

The importer checks the stored original-document verification, value/unit, capture knowledge time and known effective-date consistency. The evidence/reviewer fields are attestations requiring genuine review; providing a URL string alone is not proof. No such current outcome manifest was fabricated in this stage.

For event targets the matcher chooses the kth unique verified publication after origin. Equal-clock ambiguity blocks matching. Corrections use the same official key and append versions. Calendar targets use the last verified effective price **published by the endpoint** with complete coverage through that endpoint; a later backdated announcement does not become information known earlier. With no update, the verified base anchor can settle a calendar target. Without coverage or clocks, the match remains pending. Research replay evaluations are a separate kind and cannot settle a prospective official forecast.

A correction to a decision's publication/effective clock can change target ordering. The current matcher conservatively suspends automatic matching if the outcome registry contains contradictory clocks for a stable decision key; it preserves the evidence and requests review. Price-only revisions with unchanged clocks can append an updated evaluation automatically. No conflicting clock is silently selected by insertion order.

## Reports and stage boundary

- `reports/model_validation_report.md`: decision, findings and full interpretation.
- `reports/model_comparison_report.md`: descriptive best models and sample counts.
- `reports/probability_calibration_analysis.md`: probability comparisons and calibration selection defect.
- `reports/stress_testing_report.md`: observed stress metrics and separate synthetic checks.
- `reports/model_validation/`: per-origin outputs, actual timing gates, fit logs, coverage, baseline comparisons, source hashes, ledger checks and current abstentions.

The reported strict count is zero and every production selection is null. These are explicit unresolved evidence limits, not missing values to fill with research accuracy. Part 6 is complete as a risk review; production remains rejected and Part 7 remains unstarted.
