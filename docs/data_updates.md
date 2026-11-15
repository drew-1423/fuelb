# Collecting and reviewing Lebanese gasoline 95 data

Run commands from the workspace root. All stored prices are nominal LBP per 20 L. The existing Swift app is a separate workspace component.

## Environment

Use native 64-bit CPython on Apple Silicon. The initial data pipeline has been run in the project's `.venv`; exact resolved data/test dependency versions are in `requirements-data-lock.txt`. Research/ML/dashboard optional groups are not installed or locked by that file.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-data-lock.txt
.venv/bin/python -m pip install --no-deps -e .
```

Alternatively install initial declared ranges with `.venv/bin/python -m pip install -e '.[dev]'`. Future model stages must resolve and validate their own native dependencies.

## Updating from public sources

```bash
.venv/bin/fuel-data collect --source all --start 2008-01-01 --end 2026-11-10
.venv/bin/fuel-data report --as-of 2026-11-10
```

Omit `--end` / `--as-of` to use today's Asia/Beirut date. Collection date bounds apply to the ministry archive; IPT/Taqtek collect their complete exposed history. Report `--as-of` controls freshness checks, not reconstruction of a historical data vintage. For an explicit current update and report: `.venv/bin/python scripts/update_fuel_data.py`. No scheduling is enabled. `collect` returns a nonzero exit code if any source fails and retains the failed run and captures; other sources still run. The report can always be regenerated offline. Run `.venv/bin/python -m pytest Tests/fuel -q` for deterministic tests; they make no real network requests.

IPT uses the inspected public ASP.NET `all` and `EXPORT` postbacks with the current state tokens, follows the generated spreadsheet link, and parses `Fuel Prices` / `Octane95`. This uses ordinary HTTP; Playwright is unnecessary for this verified path. The single-date filter was observed in the UI but is not used for bulk collection. If markup/control names change, the adapter fails rather than guessing.

The ministry adapter reads its public `pricesCtrl.js`, derives the actual JSON search action, and follows only pagination numbers in returned HTML. Its default 200-page guard stops unexpectedly expanded runs. Taqtek's gasoline_95 LBP series is parsed from structured data embedded in the served HTML, not the USD display and not an assumed API. Original HTML is retained. Collection observes robots, waits at least three seconds per host, respects a longer declared crawl delay, uses TLS verification and stops on 401/403/406/429 or challenge pages. It never evades restrictions. Public export access does not grant a redistribution licence.

## Manual fallback and original decisions

Download through the public IPT page: choose `all`, then `EXPORT`. Preserve the file unchanged and record when the actual download occurred (offset required). Then:

```bash
.venv/bin/fuel-data import-ipt /absolute/path/download.xlsx --source-url https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices --retrieved-at 2026-11-10T20:35:00+02:00
.venv/bin/fuel-data report
```

The timestamp above illustrates syntax only; supply the actual retrieval time. Without `--retrieved-at`, the capture explicitly records local import time, not a historical web publication time. Original state/cookies or account credentials are not required.

For a manually transcribed observation, copy `config/manual_import_template.csv`, retaining its header. Required fields: ISO `source_date`, integer `price_lbp_20l`, exact `unit=LBP/20L`, HTTPS `source_url`. Optional fields remain empty when unknown. `official_effective_date` is populated only from explicit evidence. `publication_date` is the source publication date if established; a document issue date alone is not a known web release time. `publication_timestamp` must include a UTC offset. Keep document issue dates and the literal statement in `note` / `evidence_locator`.

```bash
.venv/bin/fuel-data import-csv /absolute/path/observations.csv --source manual
```

To verify an official price, first preserve an actual publicly linked government PDF:

```bash
.venv/bin/fuel-data download-official --url https://energyandwater.gov.lb/mediafiles/prices/f2010-10-27.pdf
```

Inspect the original document image, product, 20 L units, date and amendment/effective clauses. Numeric OCR alone is insufficient. An official-document CSV row needs `verification_status=document_verified`, `reviewer`, a precise `evidence_locator`, and the government source URL. Import with `--source official_document --evidence /absolute/path/original.pdf`. The importer stores the original PDF hash and the literal reviewed row. User-supplied verification is an auditable assertion, not an automated authenticity guarantee. No automatic PDF price admission is implemented.

## Reconciling conflicts and corrections

```bash
.venv/bin/fuel-data observations --date 2025-12-15
.venv/bin/fuel-data resolve --date YYYY-MM-DD --observation-id ID --reason 'Evidence-based explanation' --evidence-url https://official-source.example/evidence --reviewer 'Reviewer name'
.venv/bin/fuel-data report
```

Use actual values in the resolution command; no example resolves a real dispute. Select an already stored observation for that date. A correction first enters as a new observation; it never modifies or deletes the original. The resolution appends a review event and a new decision version. Newly arriving observations invalidate the old resolution basis and require review again. An unresolved contradiction leaves the canonical price null even if one source has higher priority. Repeated identical captures add sightings without duplicating semantic observations or unchanged ledger revisions.

## Outputs and interpretation

- `data/lebanon_fuel.sqlite`: schema at `src/lebanon_fuel/storage/schema.sql`; `price_history` view exposes required prices, dates, changes and status.
- `data/raw/<source>/<sha256>.*`: original bytes; `captures` records URL, retrieval UTC timestamp, MIME/status, request parameters and selected response headers. `sightings` relates each original row to an observation.
- `data/exports/gasoline_95_history.csv`: one candidate per source-labelled date. **Not** a complete certified official event ledger. Multiple decisions on a single date need more evidence.
- `data/exports/gasoline_95_verified.csv`: uncontested document-verified or ministry/IPT-matched archive records; inspect status before use.
- `data/exports/source_observations.csv`: immutable values including raw row JSON and all conflict alternatives.
- `reports/data_quality.md` / `.json`, `gap_candidates.csv`, `cross_source_missing_dates.csv`, `frequency_by_year.csv`, `conflicting_observations.csv`: actual counts, uncertainty and quality findings.

Retrieval instants are timezone-aware UTC strings; original date-only labels carry `source_timezone=Asia/Beirut` with no invented clock time. `official_effective_date` stays null where unknown. Distinct publication/effective dates and anomalies are retained. Regime labels are provisional research periods; all prices remain nominal LBP without back-conversion. Changes are relative to the previous verified **record**, with explicit reference date, not an asserted immediately previous official decision. Publication/effective gaps and unknown chronology currently limit backtesting.

Configuration is `config/project.toml`. Keep target units fixed. The three-second minimum cannot be disabled through configuration. SQLite is local and single-writer; stop updates before taking a portable database backup and copy the raw directory with it. Never replace the database to apply a correction.
