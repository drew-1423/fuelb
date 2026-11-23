# Durable refresh storage and recovery

The six-hour refresh uses private-by-repository GitHub Releases as durable snapshot storage. SQLite databases and original raw captures are stored as checksummed, compressed release assets split into parts below 64 MiB. Git contains only the small release manifest, dashboard exports, and widget snapshot; operational databases and raw captures are blocked from staging. GitHub's workflow token publishes releases, so this design needs no external storage account or billing setup.

The Streamlit read-only dashboard loads its SQLite snapshot from the release manifest into a generation-isolated local cache. It does not need database or capture blobs in the Git checkout. Verification and refresh workflows hydrate the published databases and captures before running their strict audits.

Generated forecasting feature caches are excluded from the deploy checkout and recreated by `fuel-forecast build` before a local research retrain. Archived per-run JSON is excluded from the checkout; the operation history remains in the published SQLite snapshots and earlier reports remain in Git history.

## Audited starting state

Read-only baseline captured on 23 November 2026 before this change:

| Database | Bytes | Relevant rows |
| --- | ---: | --- |
| `data/lebanon_fuel.sqlite` | 102,313,984 | 719 capture rows, 1,375 decision revisions, 3,204 domestic observations, 38,791 market observations |
| `data/forecast_ledger.sqlite` | 85,594,112 | 45,451 forecasts, 44,964 evaluations, 744 input snapshots, 120 outcomes |
| `data/operations.sqlite` | 8,388,608 | 1,064 operation events |

The strict audit passed before and after implementation: all three SQLite integrity and foreign-key checks passed; 287 raw files matched their recorded checksums; 38,507 normalized market observations passed unit conversion checks; 744 input snapshots passed hashes; 45,451 forecast ledger entries passed hash-chain verification; and all 44,964 evaluations passed arithmetic checks. No database schema or existing financial row was changed by this storage update.

## Publication and recovery guarantees

- The workflow's concurrency lock prevents overlapping scheduled and manual writers. The local refresh lock also rejects a second writer.
- Publication requires both a successful collection run and a successful strict integrity audit. A failed or partial run cannot publish a new release pointer or widget.
- Each refresh makes online SQLite backups, writes source captures into a compressed archive, and records each asset and database SHA-256 digest in a run-specific manifest.
- The release assets are uploaded and downloaded back for checksum and full restore verification before one Git commit updates the manifest and the unchanged three-value widget snapshot together.
- A failed upload or restore leaves the previous manifest/widget commit active. A partial, unreferenced release may remain as evidence; the next successful run creates a new release.
- Forecast abstentions stay null in the widget. The dashboard and widget continue reading the most recently published snapshot when a later run fails.
- Retried identical forecast issuance is idempotent; a different payload under the same issuance identity is rejected. The existing ledger hash chain is unchanged.
- Failed-run evidence is retained as a GitHub Actions artifact for 14 days. It is diagnostic only and is not used as durable storage.

## GitHub storage limits and growth

Each GitHub Release may have up to 1,000 assets, and each asset must be under 2 GiB. The project splits assets into 64 MiB parts and validates the asset count before publishing. GitHub documents no total size limit for a release. See [GitHub's release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

A release is created every six hours, so total stored snapshots will grow. The workflow reports the cumulative release-asset size and warns at 8 GiB. It does not automatically delete releases or evidence. Review storage growth and recovery needs periodically; retain manifests/releases needed for recovery. Because this repository is public, release assets are publicly downloadable, as were the tracked source data and databases.

## Verify or restore

In a clean checkout with project dependencies installed, restore the latest release and verify it:

```sh
PYTHONPATH=src python -m lebanon_fuel.automation.publication hydrate
PYTHONPATH=src python -m lebanon_fuel.automation.cli audit
```

To recover an earlier generation, check out the commit containing its manifest and run `publication hydrate --root /path/to/recovery-checkout --manifest /path/to/manifest.json`. Review the matching release and run the integrity audit before using the restored copy. Restore into a clean checkout; hydration refuses to overwrite local financial data whose checksum differs.

For local collection after restore, set `LEBANON_FUEL_LOCAL_STORAGE=1` and use the existing local writer. The old release format remains supported and does not require a migration or data rewrite.

## First refresh after merge

No account, billing page, repository secret, or Streamlit secret is needed. After merging this change, manually run **Actions → Refresh Lebanon Fuel Data → Run workflow** once. Confirm the collection, integrity audit, release upload, remote restore verification, manifest/widget commit, and widget verification all pass. Until that run succeeds, the existing published snapshot remains the one served by the dashboard.
