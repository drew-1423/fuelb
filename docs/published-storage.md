# Durable refresh storage and recovery

The six-hour workflow treats SQLite and original source captures as operational financial records. It writes versioned snapshots to a private S3-compatible object store, verifies each stored object and a full restore, then publishes the small storage manifest and the unchanged widget JSON together in one Git commit. Git is not used for growing database or raw-capture files. The last successfully published manifest remains active whenever collection, integrity checks, upload, remote verification, or Git publication fails.

## Audited starting state

Read-only baseline captured on 23 November 2026 before these changes:

| Database | Bytes | Relevant rows |
| --- | ---: | --- |
| `data/lebanon_fuel.sqlite` | 102,313,984 | 719 capture rows, 1,375 decision revisions, 3,204 domestic observations, 38,791 market observations |
| `data/forecast_ledger.sqlite` | 85,594,112 | 45,451 forecasts, 44,964 evaluations, 744 input snapshots, 120 outcomes |
| `data/operations.sqlite` | 8,388,608 | 1,064 operation events |

The strict audit passed before and after implementation. SQLite integrity and foreign-key checks passed for all three databases; 287 raw files matched their recorded checksums; 38,507 valid normalized market observations passed unit conversion checks; the 744 input snapshots passed their hashes; the 45,451 forecast ledger entries passed hash-chain verification; and all 44,964 evaluations passed arithmetic checks. No database schema or existing financial row was changed for this storage update.

New snapshots contain online SQLite backups, checksums, and references to raw evidence keyed by its SHA-256 digest. Identical raw captures share one immutable object while retaining each original capture path in the manifest. Each database snapshot has a unique run ID and is immutable. Retries can safely reuse an already verified content-addressed capture. GitHub Release snapshots created by the previous format remain readable for migration and rollback.

## Configure Cloudflare R2

The object store is private. Do not enable a public bucket URL. The Streamlit server downloads the verified database snapshot with a read-only key; the workflow writes with a separate key.

1. Create an R2 bucket, for example `fuelb-data`.
2. Create one R2 token restricted to this bucket with Object Read & Write. Create a second token restricted to the same bucket with Object Read only. Keep both bucket access policies private.
3. Copy the account S3 endpoint from the R2 dashboard. It has the form `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
4. In the GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

   - `FUEL_STORAGE_ENDPOINT_URL` — the account S3 endpoint.
   - `FUEL_STORAGE_BUCKET` — `fuelb-data` or the bucket name you chose.
   - `FUEL_STORAGE_ACCESS_KEY_ID` — the read/write token's access key ID.
   - `FUEL_STORAGE_SECRET_ACCESS_KEY` — the read/write token's secret access key.

5. In Streamlit Community Cloud, open **Manage app → Settings → Secrets** and add the read-only token:

   ```toml
   [fuel_storage]
   endpoint_url = "https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
   bucket = "fuelb-data"
   access_key_id = "READ_ONLY_ACCESS_KEY_ID"
   secret_access_key = "READ_ONLY_SECRET_ACCESS_KEY"
   ```

   Do not place either key in source files or GitHub variables. The app obtains the endpoint and bucket from the checksummed public manifest; its R2 key only has read permission.

6. Merge this change, then manually run **Actions → Refresh Lebanon Fuel Data → Run workflow** once. Confirm the run completes the object upload, read-back, full restore, integrity audit, Git publication, and widget verification steps. Only then is the dashboard using the durable object-store snapshot.

The workflow stops before collection if its write credentials are absent. It never falls back to publishing full snapshots as GitHub Release assets. Until the first successful R2 publication, the previously published GitHub Release pointer remains readable and visible as the last successful snapshot.

## Publication and recovery guarantees

- The workflow's concurrency lock prevents overlapping scheduled and manual writers. The local refresh lock also rejects a second writer.
- A publication gate requires both collection and strict integrity audit to succeed. Forecast abstentions are preserved as null widget predictions; they are not treated as collection failures.
- A new manifest refers only to a unique, immutable run snapshot and SHA-256-addressed raw captures. The widget's existing URL and three-number JSON array are unchanged.
- Objects are uploaded and read back before a Git commit changes the manifest. A partial upload cannot change the current pointer. A failed Git push leaves the previous pointer active.
- After each successful upload, the workflow measures the `fuelb/` object prefix and warns at 8 GiB so storage growth can be reviewed before the R2 free allowance is exhausted. It does not automatically delete snapshots.
- The object-store API keys must remain available for the dashboard and recovery. Preserve bucket contents and credentials outside the repository. Do not add automatic object deletion or lifecycle expiry: the bucket contains recovery snapshots and referenced original evidence.
- GitHub Actions keeps failed-run evidence for 14 days. This is diagnostic support, not the durable database store.

To restore the latest snapshot in a clean checkout, install requirements and set the read-only object-store credentials in the environment (or configure them in Streamlit secrets), then run:

```sh
PYTHONPATH=src python -m lebanon_fuel.automation.publication hydrate
PYTHONPATH=src python -m lebanon_fuel.automation.cli audit
```

For a previous release, check out its manifest commit and hydrate that manifest. Hydration stages and verifies the complete snapshot before installing files. It refuses to overwrite local financial data whose checksum differs. Restore into a clean checkout if local changes must be preserved.

The legacy format remains supported: if `reports/operations/published_storage.json` points to a pre-migration GitHub Release, the workflow can hydrate and audit it without R2. New publication is blocked until R2 credentials are configured.

## Cost and provider references

Cloudflare R2 provides an S3-compatible API and currently lists 10 GB-month of Standard storage and free Internet egress in its free tier. Storage above the allowance is billed by usage, so monitor actual bucket growth and the provider's current pricing. Do not enable a public development URL for production. The project uses the private S3 API and only exposes credentials to the workflow and the read-only dashboard key.

- [R2 S3 API setup and credentials](https://developers.cloudflare.com/r2/get-started/s3/)
- [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [R2 public bucket guidance](https://developers.cloudflare.com/r2/buckets/public-buckets/)
