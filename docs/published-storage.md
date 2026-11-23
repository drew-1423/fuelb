# Refresh storage and recovery

The refresh runs every six hours and also supports a manual run from GitHub Actions. The workflow downloads the last published release, restores all three SQLite files and the original captures, collects new observations, runs the existing forecast pipeline, and executes the financial and database integrity audit.

## What is published

- Each refresh writes online SQLite backups and the original captured files to separate compressed archives. The archives are split into 64 MiB parts and uploaded to an immutable, run-specific GitHub Release. Each part and each database has a SHA-256 digest.
- The workflow downloads and verifies the complete release before pushing a Git commit. That one commit publishes the release pointer and the widget JSON together. The widget keeps its existing URL and three-element format.
- SQLite files and raw captures are never staged by refresh. Their existing Git copies serve as the bootstrap for the first successful publish. The staged-blob guard rejects any new blob at 95 MiB and warns at 50 MiB.
- The dashboard reads only the database parts and opens them from a directory named by the manifest checksum. A reader either opens a complete checked snapshot or reports a storage error. The dashboard flags publication age after 12 hours. Existing forecast freshness rules still apply.
- The GitHub Actions token is sufficient for this public repository. No external storage account, extra credential, or Git LFS is required. Storage releases and their contents are public, as were the tracked source data and databases.

A cycle with an isolated source failure can still publish an audited snapshot if every processing step completed and the widget matches that cycle. GitHub Actions reports the run as degraded. Failed processing, an integrity error, or a changed branch head blocks the commit. Unpublished data and the refresh reports are available in the failed run's evidence artifact for 14 days. Existing collectors retain their source-specific cooldown and timeout behavior. The publisher retries transient HTTP failures and Git pushes when the branch has not moved.

## Download and verify a copy

Use a clean checkout, with the project dependencies installed.

```sh
PYTHONPATH=src python -m lebanon_fuel.automation.publication hydrate
PYTHONPATH=src python -m lebanon_fuel.automation.cli audit
```

To recover an earlier generation, obtain that release's `manifest.json` and run `publication hydrate --root /path/to/recovery-checkout --manifest /path/to/manifest.json`. Review its corresponding Git commit and run the audit before using the copy. Use a separate checkout for recovery because hydration installs the snapshot at the configured canonical paths. For local collection from a hydrated checkout set `LEBANON_FUEL_LOCAL_STORAGE=1` and select the local writer.

Retain the referenced releases and periodically copy recent releases and their Git commit IDs off GitHub. Release storage and the public widget still share a GitHub dependency. Each part is well below GitHub's per-asset limit. Each separate release can hold up to 1,000 assets. Monitor release sizes, runner disk space, and download time as the history grows.

## November 23 failure

Collection, forecast processing, and the strict integrity audit completed. GitHub rejected the commit containing a 104.11 MB gasoline database and warned about the 81.94 MB ledger. The last published price database had zero free pages. A copy-only VACUUM reduced it from 102,313,984 to 99,778,560 bytes. That temporary headroom would disappear as captures, source sightings, and ledger entries accumulated. The original files were left in place and backup integrity, checksums, and table counts were checked.
