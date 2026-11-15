# Final financial and technical audit

Review date 11 November 2026, Asia/Beirut. Scope is the Lebanon gasoline Python project through Part 8. The review recomputes evidence separately from model fitting, but the same development agent performed it. It is **not an external or organizationally independent certification**.

## Audit decision

The data, dashboard and native operational workflow are functional. Numerical production forecasts remain rejected. Zero strict historical predictions and zero fresh final-holdout outcomes support a current-regime accuracy claim. The operational forecast adapter records immutable abstentions, and configuration flags cannot promote an unapproved model. Existing retrospective predictions and uncertainty results are preserved.

## Financial calculations

| Area | Finding and evidence | Disposition |
| --- | --- | --- |
| Primary domestic unit | Valid eligible observations are positive LBP/20 L. `automation/maintenance.py` checks every stored eligible observation. | Passed unit/positivity audit; source accuracy still needs review. |
| Product conversions | `structural/engine.py` converts USD/bbl × 1000 / 158.987294928 to USD/kL, USD/metric ton × density in kg/L to USD/kL, and LBP/kL ÷ 50 to LBP/20 L. EIA USD/US gallon × 42 gives USD/bbl. | Independent arithmetic checks and existing unit tests passed. |
| FX | The cost engine multiplies USD/kL by explicit LBP/USD. EUR/USD is USD per EUR. The dated 89,700 customer-payment rate is not asserted to be a current formula rate. | Current official formula FX remains unresolved; no invented rate series. |
| Freight | The engine rejects additional freight for CIF inputs. All freight in scenarios is explicit. | Double-counting guard verified. |
| Taxes/margins | VAT applies only to explicitly taxable components. A 300,000 LBP charge adds 33,000 additional LBP VAT at an assumed 11% only when marked taxable. Historical annex inputs retain validity/evidence fields. | Scenario arithmetic passed; current statutory rates/bases remain unverified. |
| Rounding | Only documented-as-hypothetical increments are supported. | No exact official rounding rule claimed. |
| Historical annex reconciliation | Three original annexes have 2.733333 LBP/20 L mean absolute unrounded reconciliation discrepancy, with maximum 3.30. | Same-document accounting, **not forecast accuracy**. |
| Benchmark identity | Brent is crude, NYH gasoline is a US product proxy, and EC Euro-super prices are retail proxies excluding tax. The NYH-minus-Brent spread is cross-region gross price spread. | None is presented as Mediterranean 95 wholesale gasoline or net refinery margin. |
| Regimes | Currency/subsidy crisis and unresolved post-May-2025 fiscal periods are excluded from pooled model fitting. Research regime labels are analytical boundaries. | No claim that historical rules still apply. |
| Information time | Stored capture knowledge is distinct from source date and publication/effective times. Original historic market vintages are missing. | Zero admissible strict historical forecasts; retrospective scores labeled accordingly. |
| Error equations | Forecast minus actual is signed error; price and change MAE coincide when using the same anchor. All stored evaluation differences were checked. | Zero arithmetic mismatches. |
| Probabilities | Three probabilities must be finite, in [0,1], and sum to one. Monitoring scores actual outcomes and reports sample counts. | No current numerical probabilities issued. |
| Uncertainty | Candidate nominal 90% intervals showed substantial calendar-horizon undercoverage. Structural input bounds are conditional sensitivity ranges. | No 95% interval or current calibrated confidence claim. Existing bad intervals were not retroactively replaced. |

Dated primary evidence and URLs remain in [the evidence register](../research/verified_assumptions.md), [structural equation](../research/structural_pricing_equation.md), [regime review](../research/regulatory_regimes.md), and [market source register](../research/international_market_sources.md). Those documents explicitly distinguish verified historical facts, secondary reports, proposals and unresolved current inputs.

## Confirmed defects corrected in Part 8

| Severity | Defect | Correction and verification |
| --- | --- | --- |
| High operational risk | Two concurrent forecast writers could read the same previous hash before inserting. | `validation/ledger.py` now acquires an SQLite immediate write transaction around the tail read and insert. A 24-writer concurrent test verifies a single valid chain. |
| High financial-control risk | A future outcome knowledge timestamp or future complete-coverage attestation could enter settlement. | Future knowledge and future coverage are rejected. Regression tests exercise both cases. Future effective dates remain distinct from knowledge time. |
| Medium disclosure risk | A later abstention from the operating guard, expired forecast, or missing issuance clock could leave an older selected forecast eligible for display. | Dashboard requires the current selected issuance, aware creation/origin clocks, an unexpired endpoint and the configured maximum age. Later guard abstentions suppress earlier values. |
| Medium data-contract risk | Abstentions could carry probabilities or intervals, and base-price validation was incomplete. | Abstentions reject numerical uncertainty; base prices must be finite and positive. Historical records are not rewritten. |
| Medium operational risk | Dashboard collection and a future scheduler could overlap without coordinated locking. | Both refresh routes share the new OS-level lock, source cooldowns and bounded collectors. Legacy standalone collectors must be used only during supervised maintenance. |
| Low configuration risk | Reviewed settlement used hard-coded database locations. | It now respects the project's configured source database and ledger paths. |
| Low usability defect found during native testing | `launchctl kickstart` can wait during launchd's startup throttle. | Manual requests persist until consumed. A timeout is reported as queued; the actual native job subsequently completed. The initial failure event is retained. |

## Technical controls and measured execution

All source HTTP requests use the existing public-source clients and captured robots/access decisions. Public source downloads preserve raw bytes and hashes. Sources are collected sequentially, with a configurable timeout and denial cooldown. Failures do not silently overwrite existing values. Reconciliation preserves conflicts. No credentials, root daemon, remote publication, or network-exposed dashboard was added.

The installed job is `com.andrew.lebanon-fuel.refresh` in the logged-in user's launchd domain. Its interpreter and project paths are absolute. The default cadence is six hours, with hourly weekday morning watch windows. Five-minute native wakes check whether work is due. The job does not invoke Codex. Sleep/logout/power loss remain explicit service limits.

Native run `ops-20261111T162738-c78b7337` ran from 16:27:38 to 16:29:50 UTC on 11 November 2026. All six source collectors succeeded. IPT parsed 1,312 rows, ministry 5 within the configured rolling search, Taqtek 914, EIA 24,395, EC 2,184 and Fed 7,265. New immutable source observations were 0, 1, 0, 0, 2 and 0 respectively. Parsed row counts are not unique decisions. The additional ministry record was dated 28 July 2026; it was not a newly announced November decision. The Commission observation dates reached 9 November 2026.

Native run `ops-20261111T163121-a9b8ebba` then honored all source cooldowns, completed report refreshes, and preserved eight further abstentions. Its local cycle took approximately 43 seconds, including chart/report regeneration and integrity checks. Core dashboard reads are cached for 60 seconds with database/WAL invalidation; saved metrics are cached by file version. No expensive model fitting occurs during refresh or UI rendering.

The integrity audit checked all three SQLite databases and foreign keys, 111 distinct raw artifacts, 33,562 valid normalized market rows, 109 saved model files, all 44,928 stored evaluations, and the forecast chain. See [machine-readable integrity results](operations/final_integrity_audit.json). Saved model checksums are verified without loading untrusted files. Joblib loading remains limited to trusted locally produced artifacts and is not treated as a safe external format.

The running dashboard was inspected through the browser. The Data quality screen showed the completed native cycle at 18:32 Beirut, 42 quarantined dates, 3,169 missing publication clocks, 3,166 unknown effective dates, zero verified prospective outcomes and withheld production approval. Existing UI integration tests also exercise every view, four forecast horizons, scenarios and refresh failures.

## Remaining risks and approval requirements

- Current government formula, benchmark symbol/window, pricing FX, taxes, margins and complete announcement/effective timing remain unresolved.
- The government archive is stale and incomplete; supplier agreement is weaker than an original official decision. Forty-two disputed dates remain quarantined.
- Licensed Mediterranean product/freight histories and original publication vintages are absent.
- Calendar calibration defects and repeated use of historical challenge periods prohibit production confidence claims. Small recent samples do not establish stable performance.
- Headline monitoring is partial and cannot replace review of original policy instruments.
- Backups are local until the operator copies them to separate storage. Raw records, audit history, reports and backups grow without automatic pruning.
- A local user with filesystem write access can tamper with code, manifests or databases. Hashes and immutable triggers detect ordinary damage; this is not externally notarized or adversary-proof storage.
- No numeric production issuer, current-policy approved model or automated legal-document certification is provided. A new reviewed deployment is required before numerical production forecasting.

The reproducible verification command is `.venv/bin/python scripts/verify_production.py`. Its actual results and execution times are saved in [final verification](operations/final_verification.json): **141 tests passed in 29.29 seconds**, with all artifact audits, operations integrity and dependency compatibility checks passing. A backup was actually restored into a new temporary directory. All three recovered databases, 111 raw artifacts, 109 model files and the forecast chain passed verification; [recovery evidence](operations/backup_restore_check.json) records the paths and timestamps. The native scheduler was subsequently confirmed installed with last exit code 0. Reboot/logout and prolonged unattended operation were not empirically tested. No model was retrained or selected from the final audit results.

## Audit remediation update (14 November 2026)

* **Atomic live forecast issuance (`F-02`):** `ForecastLedger.issue_batch()` (`src/lebanon_fuel/validation/ledger.py`) and `automation/forecast.py` now validate and commit all eight horizons in a single `BEGIN IMMEDIATE` SQLite transaction with a 300-second batch origin window, preventing partial multi-horizon runs.
* **Holdout comparison, Tier 1 gating & reporting (`F-04`, `F-05`):** `validation/runner.py` intersects common origins only across full-coverage core families (preventing sparse baselines from dropping holdout origins), enforces `unique_base_decisions >= 20` for Tier 1 approval, and records `all_origin_performance` alongside `performance`; `dashboard/analyst.py` reports both when they differ.
* **Official PDF & FX promotion (`F-06`):** Decision #245 (`2023-05-12`, `1,635,000 LBP/20 L`, FX `94,500 LBP/USD`, `capture_id=128`) is now promoted via `data/manual/official_20230512.csv` and `data/manual/official_payment_fx_20230512.csv` (4 `document_verified` domestic records and 2 `lbp_payment_fx` observations in `data/lebanon_fuel.sqlite`).
* **FRED OVX attribution (`F-07`):** `collect_fred_ovx()` and FRED-format `collect_ovx_csv_input()` now record `source_id='market_fred_ovx'` rather than `market_cboe`.
* **Strict-availability snapshot (`F-08`):** `reports/model_validation/strict_availability.json` has been refreshed from `data/lebanon_fuel.sqlite` (`domestic.n=3175`, `effective_dates=4`, `market.n=38773`); historical strict forecasts remain `0` and production approval remains withheld.
