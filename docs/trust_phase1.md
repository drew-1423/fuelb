# Phase 1 — forecast trust and reproducibility

This phase extends evaluation and scenario accounting without fitting or replacing any production model. G_hybrid remains the public forecaster. Software tests and mechanical integrity checks do not establish forecasting accuracy.

## Outcome policy

Original forecasts, models, snapshots, outcomes and evaluations remain immutable. Corrections append new match attempts/evaluations; historical predictions are never rewritten.

- Official evaluations retain reviewed publication/effective clocks and certified complete-coverage matching through the existing official settlement mechanism.
- Supplier evaluations are a separate provisional evidence stratum. Starting-price evidence and outcome evidence are independent: a government-backed anchor may have a supplier-consensus outcome.
- Decision horizons require the next 1, 2 or 4 consecutive corroborated dated records. Every intervening record must have matching IPT and either TotalEnergies or Taqtek evidence, dates after issuance, capture receipts after issuance, no conflict and gaps at most seven days. These are conditional recorded-price targets, not certified counts of all official decrees.
- Calendar horizons require a corroborated observation on the endpoint's Beirut date, both receipts before the endpoint, and a later corroborated witness. Missing dates do not create zero changes. They do not certify that the quotation became officially effective at a particular time. Absence of sufficient clocks/evidence is an unscored target, not a failure to predict a fabricated actual.
- Calendar endpoints that have not passed remain immature. Ambiguous same-day decision ordering is excluded. Contradictory sources revoke provisional eligibility while preserving original evaluation rows.

## Calibration policy

Each horizon, exact model artifact, starting-price evidence cohort and outcome-evidence stratum is calibrated separately. Official and conditional supplier targets are not pooled. A sufficiently supported official stratum is preferred; otherwise a qualifying supplier stratum remains explicitly provisional.

Repeated refreshes for one target date count once. Greedy chronological sampling retains nonoverlapping forecast-to-label-information intervals. This is conservative: it reduces overlapping labels and information reuse, but cannot prove independent residuals or eliminate regime drift.

Calibration uses at least 30 matured observations and the latest 60 eligible residuals. Each prequential coverage test uses strictly earlier matured labels. At least 20 nonoverlapping chronological coverage tests are required before release. At two decisions per week, collecting this evidence can take months, especially for long calendar horizons.

80% and 90% radii are independently computed with the finite-sample conformal order statistic ceil((n+1)*coverage), with a 5,000 LBP half-width floor. The floor is a conservative resolution safeguard, not a proof of coverage. The 80% band is never inferred by scaling the 90% band. Release tolerances are 70–90% empirical coverage for nominal 80%, and 80–98% for nominal 90%; sample sizes and empirical coverage remain visible. These tolerances are governance choices, not guarantees under dependent or changing regimes. Absolute lower price bounds are clipped at 1 LBP, so bounds remain positive. Radii are nested when both are released.

Readiness is emitted for all eight horizons, including missing-evidence reasons, eligible sample counts, evidence categories, coverage counts, width and separate level statuses. Fallback forecasts do not acquire fabricated numerical uncertainty. No directional probabilities are released by this phase.

## Scenario accounting

The May 2025 cost scaffold remains available as an **illustrative, unanchored** reconstruction. It is not asserted to be a current official tariff.

The default anchored result is:

`recorded anchor + structural_model(scenario inputs) - structural_model(baseline inputs)`

Unchanged inputs reproduce the recorded anchor exactly. The latest record cannot be skipped if disputed. The anchor must be current and eligible, and the UI requires a sufficiently fresh stored product proxy. Pricing FX is an explicit hypothetical model input; USD display conversion is a separate assumption.

Cargo, freight, other USD import costs, LBP cost scaffold charges, VAT, retail/transport assumptions, rounding and the anchor reconciliation residual are shown separately. The unexplained residual is held constant in the scenario and is not an official duty, margin or a proven stable economic parameter. A separately documented distribution margin is unavailable. Material accounting differences raise an error; sub-micro-LBP Decimal precision reconciliation is explicitly identified. No scenario probability is supplied.

## Durable writer and ownership

`config/project.toml` defaults dashboard refreshes to GitHub Actions. Streamlit does not start a local scraping/issuance subprocess in that mode. Scheduled jobs commit raw captures with their SQLite references, exports and reports even when collection/audit steps fail; the job subsequently reports failure. Concurrency prevents overlapping refresh jobs. Direct CLI runs remain available on a persistent local checkout.

An owner-triggered cloud refresh requires the server-side `LEBANON_FUEL_ACTIONS_TOKEN` secret, authorized for workflow dispatch on `drew-1423/fuelb`. Do not place it in source control or send it to the browser. Configure it as a root Streamlit secret/environment variable. Owner dashboard authorization must also pass. A successful dispatch means **queued**, not updated observations; the UI continues showing the previous committed snapshot until the durable run completes.

Without that secret, scheduled refreshes still run and owner-triggered requests fail closed with an explanation. No credential or new permission is provisioned by this phase. Local persistent operators can explicitly set `LEBANON_FUEL_WRITER=local`. User-facing alerts and external notifications are Phase 2 work.

## Frozen provenance and current releases

Historical run manifests and production model files are unchanged. Original source bytes recoverable from Git history are archived under `research/evidence/frozen_sources/` and checked against their original SHA-256 identities. Some original training/evaluation source versions predate available Git history and remain explicitly cataloged as unrecovered; their hashes are preserved, not reconstructed.

Current code identity, model identity and the immutable manifest references are verified separately. Replaying saved predictions and their metrics remains an audit requirement. A UI change requires a new current release attestation; it does not rewrite the historical run.

The exact frozen development CSV was originally ignored and too large for an ordinary Git blob. A deterministic gzip archive retains its exact original bytes and SHA-256, allowing CI to restore it without rebuilding targets using today's source revisions.

`reports/releases/current.json` is a checksum attestation, not a digital signature or model approval. Local candidates bind a base commit plus exact source/model identities. CI binds `GITHUB_SHA` and uploads its attestation and actual results as a commit-named artifact. Data-only refresh commits can share a source identity. Do not claim a deployed exact-commit attestation solely from the local candidate file.

Commands, from the project root:

```sh
PYTHONPATH=src .venv/bin/python -m lebanon_fuel.automation.release prepare-design
PYTHONPATH=src .venv/bin/python -m lebanon_fuel.automation.release create --base-commit <reviewed-base-commit>
PYTHONPATH=src .venv/bin/python -m lebanon_fuel.automation.release verify
PYTHONPATH=src .venv/bin/python -m pytest Tests/fuel -q
PYTHONPATH=src .venv/bin/python scripts/verify_production.py
PYTHONPATH=src .venv/bin/python scripts/phase1_research_report.py
```

The research report appends legitimate outcome evaluations in the local ledger but never changes saved forecasts. Run it on a consistent backup when generating independent reports. It does not fit models or issue new forecasts.

## Phase 2 handoff

Consume `automation.health.build()` for distinct feed, anchor, forecast, calibration, integrity and release statuses and clocks. Consume each forecast's `public_calibration.levels` and `reports/operations/calibration_readiness.json` for readiness. Use `anchored_simulate()` for consumer scenarios and retain `simulate()` only as an explicitly illustrative advanced option.

Complete the consumer hierarchy, readable health badges, permanent forecast links, optional opt-in alerts and expanded browser QA in Phase 2. Do not enable bands, probabilities or production approval merely because rendering/tests pass. Remaining original capture loss and original source gaps must remain visible.
