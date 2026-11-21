# Local operations and maintenance

Part 8 adds a native per-user macOS LaunchAgent. It runs the project Python environment without Codex or a paid API. It collects sources, reconciles prices, records forecast checks, matches reviewed outcomes, updates monitoring, writes an analyst report, and backs up evidence. **Part 6 still withholds numerical production forecasting.**

## Launch and refresh

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
.venv/bin/python -m streamlit run src/lebanon_fuel/dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

Open <http://127.0.0.1:8501>. Keep this terminal open while using the dashboard. Closing it does not stop the data scheduler. The dashboard listens only on loopback.

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
# Full refresh in this terminal, honoring source cooldowns
.venv/bin/python -m lebanon_fuel.automation.cli run
# One source, followed by reconciliation and all local checks
.venv/bin/python -m lebanon_fuel.automation.cli run --source ipt
# Local reports and forecast checks, without network collection
.venv/bin/python -m lebanon_fuel.automation.cli run --offline
# Request a refresh by the installed macOS job
.venv/bin/python -m lebanon_fuel.automation.cli kick
# Native scheduler status and the last completed cycle
.venv/bin/python -m lebanon_fuel.automation.cli status
```

The dashboard's Data quality page has single-source and full-cycle refresh buttons using this same pipeline and lock. Exit status 1 means a failed/degraded operation, 2 means a manual refresh was already running, and 0 means completion or a scheduled wake that was not due. A completed cycle can still contain financial warnings and forecast abstentions. A successful capture does not prove that a new price was published. Retained data always keeps its original observation dates.

## Schedule and native job lifecycle

The installed file is `~/Library/LaunchAgents/com.andrew.lebanon-fuel.refresh.plist`; a copy is under `data/launchd/`. Edit `config/automation.toml` to change the schedule and thresholds. The native job wakes every five minutes. Python evaluates `Asia/Beirut`, independently of the Mac's display timezone. Normal refreshes occur every six hours, with hourly weekday 09:00–12:00 checks. These are operator watch windows, **not verified official announcement appointments**. Set `announcement_windows = []` to disable them.

IPT and ministry requests are limited to hourly collection; Taqtek, EIA, the Commission and the Fed to once per 24 hours. Existing collectors pause at least three seconds between same-host requests. Access denials and HTTP 429 stop the affected source and impose at least a 24-hour pause, extended by a longer `Retry-After`. No challenge bypass or unverified alternative endpoint is attempted. Other sources and local checks continue. A terminated collector is recorded as failed.

The ministry refresh defaults to a rolling 120-day search. Older evidence remains stored. Run an occasional supervised full archive collection using the Part 2 commands, while the scheduler is stopped. Neither sparse search results nor successful retrieval establish a complete official decision sequence.

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
# Generate and validate the plist only
.venv/bin/python -m lebanon_fuel.automation.cli prepare
# Install/reload after changing poll_seconds or moving the project
.venv/bin/python -m lebanon_fuel.automation.cli install
# Remove this project's scheduled job
.venv/bin/python -m lebanon_fuel.automation.cli uninstall
```

Ordinary schedule/threshold edits apply on the next wake; a changed native polling interval requires reinstall. Installation/removal refuses to interrupt a running refresh. `kick` preserves a request if launchd delays startup and never kills an active job. The native job only runs while the user is logged in. It cannot collect while the Mac is asleep or off; overdue work becomes eligible on a later wake. Missed intervals are not filled with invented records. Apple documents the per-user lifecycle in [Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html), inspected 11 November 2026, publication date unstated.

## Logs and accountability

| Artifact | Purpose |
| --- | --- |
| `data/lebanon_fuel.sqlite`, `data/raw/` | Original captures, domestic/market observations and revisions |
| `data/forecast_ledger.sqlite` | Immutable predictions, abstentions, inputs, actual revisions and evaluations |
| `data/operations.sqlite` | Append-only cycle, step, source, backup and fatal-error events |
| `reports/operations/runs/<run-id>/` | Progress, result, monitoring snapshot and report per cycle |
| `reports/operations/latest_run.json` | Most recent completed cycle, timings and failures |
| `reports/operations/monitoring.json` | Freshness, conflicts, policy-review status and prospective metrics |
| `reports/operations/current_forecast_check.json` | Current gate reasons, ledger IDs and real inputs |
| `reports/latest_analyst_report.md` | Latest generated commentary |
| `data/logs/launchd.out.log`, `launchd.err.log` | Native process output and startup errors |

An interrupted process leaves its journal and progress file; the next cycle identifies unfinished cycles. The operating-system lock releases on process exit. Database integrity failure blocks collection and forecasting. Keep sufficient disk space. Raw captures, forecasts, backups and logs are not automatically deleted; retention is a deliberate maintenance task. Separate-storage backups are needed for disk-loss protection.

## Monitoring and approval rules

Live metrics use only prospectively created numerical forecasts matched to reviewed official outcomes. Retrospective scores remain in Part 6. The latest actual revision per forecast is used without erasing earlier evaluations. Monitoring retains one latest issuance per distinct official decision, alongside all-issuance metrics. No live accuracy is reported with zero settled numerical forecasts.

Default review triggers require at least 30 distinct official outcomes and use a trailing window of 60. Review is requested if MAE exceeds 50,000 LBP/20 L or the no-change baseline by more than 10%, absolute bias exceeds 20,000, direction accuracy is below 50%, interval coverage differs from its declared level by more than 10 percentage points, or a class's probability calibration error exceeds 0.15. Interval/probability checks need their own sample minimum. These are configurable operating rules, not statistical guarantees or model-promotion criteria. Consider dependence, policy regimes and class imbalance during review.

Immediate review is required for stale verified prices, changed policy assumptions, new captured ministry fuel/tax headlines, growing conflicts, stale/missing inputs, or absolute seven-day market moves above 10%. Headline monitoring is partial, keyword-based and capture-timestamped. It does not infer enacted law or claim complete policy surveillance. Maintain `config/policy_review.json` with a named reviewer, actual date and original legal evidence. Do not mark unresolved rules reviewed merely to dismiss warnings.

Retraining requires a frozen development protocol and more admissible evidence. Recalibration needs time-valid residuals and a fresh assessment period. Neither automatically replaces a model. The current operational forecast adapter records **abstentions** because no model was approved. Configuration flags cannot activate a numerical issuer. Numerical production issuance remains unfinished and needs a separately reviewed adapter, approved immutable model registration, certified current policy/target timing and validated uncertainty.

## Match future official outcomes

Follow `docs/model_validation.md` to import original PDFs and prepare a named-reviewer manifest with publication/effective clocks and complete official coverage. Put its path in `[settlement].reviewed_manifest` in `config/automation.toml`. Every cycle imports reviewed outcomes, matches issued prospective forecasts and revisits price corrections. Actual/evaluation revisions append. Conflicting clocks suspend matching. Date-only supplier observations are not automatically authenticated. Without reviewed coverage, matching remains pending. Future knowledge timestamps and future complete-coverage attestations are rejected.

## Backup, recovery and checks

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
.venv/bin/python -m lebanon_fuel.automation.cli audit
.venv/bin/python -m lebanon_fuel.automation.cli backup
# Substitute the directory printed by backup
.venv/bin/python -m lebanon_fuel.automation.cli verify-backup data/backups/<timestamp>
.venv/bin/python scripts/verify_backup_restore.py data/backups/<timestamp>
.venv/bin/python -m pytest Tests/fuel -q
.venv/bin/python scripts/audit_structural_artifacts.py
.venv/bin/python scripts/audit_forecasting_artifacts.py
.venv/bin/python scripts/audit_validation_artifacts.py
.venv/bin/python -m pip check
```

At most once daily, a completed cycle creates SQLite online copies and an archive of captures, models, research, exports, reports, configuration, project code and tests. It checks copied databases and writes checksums. Copy the whole backup directory off-device. Retention is manual. Back up the source database, forecast ledger, raw captures and model artifacts together.

For recovery, stop the scheduler and dashboard, verify the selected backup, and create a **new recovery directory**. Extract its trusted `artifacts.tar.gz` there and copy its `.sqlite` files into `data/`. Recreate the environment and run audit/tests before switching projects and reinstalling the scheduler. Do not overwrite the working project as an initial restore test. Some historical provenance contains absolute paths; retain that evidence. Online backups are individually consistent. The shared runner lock supplies cross-file consistency for documented operations; avoid simultaneous legacy/manual writes.

The tested Apple Silicon environment uses CPython 3.13.12 and `requirements-dashboard-lock.txt`, which includes the forecasting dependency locks. For a fresh installation:

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
brew install libomp
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dashboard-lock.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
```

Load only trusted locally generated joblib artifacts after checksum validation. Joblib is executable serialization, not a safe format for untrusted downloads. No automatic dependency upgrade, remote model download, paid API call or external publication is scheduled.

## November 2026 audited baseline

The active source database at `data/lebanon_fuel.sqlite` was rebuilt from the
capture files whose SHA-256 digests matched the source ledger. The migration
preserved original observation and capture IDs and their evidence clocks where
the original first sighting survived. Decision revisions were reconciled at
cutover with new IDs. The baseline manifest records the source commit, archive
checksums, retained counts and cutover time. The exclusion list records every
capture left behind because its original bytes could not be verified.

The compressed original source database in `data/legacy/` preserves the
pre-cutover rows and revision IDs for frozen research audits. The immutable
forecast ledger also retains pre-cutover issuances and evaluations.
The prospective protocol starts a new cohort at the cutover. Historical model
audits use the sealed legacy database and continue checking the original
artifact checksums. The refresh job verifies every capture referenced by the
active database. Passing that check establishes evidence integrity for the
active data. Model approval and uncertainty calibration have separate gates.

To reproduce the candidate and exclusion list, check out the source commit
recorded in `config/audited_baseline.json` into an isolated checkout. Use the
current `scripts/build_audited_baseline.py` with the current project on
`PYTHONPATH`. Set `--root` to the isolated checkout, `--output` to a new
directory, and `--source-commit` to the same recorded commit. The builder
writes a separate candidate and archive. Reconciliation time and revision
fingerprints should be interpreted with the candidate's own manifest.
