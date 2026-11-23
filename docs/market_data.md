# Market data: operation and contracts

## Install and update

Use the project environment on Apple Silicon; no service/database server is required. `requirements-market-lock.txt` pins the environment actually used for Part 3. Modeling libraries are not installed by this file.

```bash
.venv/bin/python -m pip install -r requirements-market-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/fuel-market collect --source all
.venv/bin/fuel-market report
.venv/bin/python -m pytest Tests/fuel -q
```

Sources can be updated separately with `--source eia`, `ec`, or `fed`. Each command downloads the full linked history as a backfill/revision check, captures the exact response and parses it atomically per series. A successful earlier series remains committed if a later source fails. Collection exits nonzero for any failed source; inspect `collection_runs` and freshness before use. A partial or failed run is not proof of current data.

Cboe OVX (`OVXCLS`) is collected from FRED's public CSV and stored under the existing `cboe_ovx` series identity:

```bash
.venv/bin/python -m lebanon_fuel.market.cli collect --source fred
```

An authorized local Cboe or FRED CSV can be imported with `collect --source cboe --input /absolute/path/file.csv`. The importer validates the file before capture, records the local path and content hash, and accepts the Cboe `Date,...,Close` or FRED `observation_date/DATE,OVXCLS` layouts. Historical `as_of_close` availability uses 23:59:59 UTC on each observation date; strict availability remains the actual capture time. OVX is a crude-oil ETF options volatility proxy, not a Lebanese gasoline volatility measure.

`scripts/update_market_data.py` runs collection once. `config/market_updates.toml` documents command, timezone and failure behavior for a local scheduler. No job has been registered. Use one process at a time, an external overlap lock, the project's working directory and full executable path. Poll daily at most for these histories; a market session does not imply a new published row. Recheck source policies and schedules when adapters change.

## SQLite extension

The existing `data/lebanon_fuel.sqlite` contains both datasets; Lebanese price observations and decision versions retain their Part 2 contracts. Market schema is in `src/lebanon_fuel/market/schema.sql`.

| Table | Purpose |
| --- | --- |
| `market_series` | Immutable identity, product role, original/normalized units, conversion factor, source timezone, observation frequency and explicitly assumed research lag |
| `market_observations` | Immutable dated source values, original row JSON, original/normalized units, explicit missing/invalid flags, publication and vintage timestamps when evidenced |
| `market_sightings` | Every capture/row occurrence, observation reference, available-at time and evidence basis; supports revisions and reversals |
| Existing `captures`, `collection_runs`, `sources` | Shared content-addressed raw files, URLs, HTTP metadata, UTC retrieval times, request outcomes and source lineage |

Dates identify the quoted session or reference period; weekly stock dates are week endings. Publication, retrieval and vintage times are separate. Store aware instants in UTC and use IANA `Europe/London`, `America/New_York`, `Europe/Brussels`, `Asia/Beirut` for their respective contexts. The shared capture display-timezone field is the project's Asia/Beirut setting, not the market's session timezone. HTTP Date/Last-Modified, package Prepared and page “updated” labels are not historical observation publication timestamps.

Semantic duplicate detection excludes changing row locations and package metadata; their originals remain in raw captures and sightings. Later captures preserve changed values. Strict queries select the latest edition eligible at origin; an invalid latest value does not revive a superseded value. Two differing values for the same date in one capture remain ambiguous and are excluded. Series metadata changes require a versioned identity instead of changing conversion factors underneath stored values.

Normalizations: 42 US gallons = one petroleum barrel; USD/US gallon × 42 → USD/barrel. Stocks in thousand barrels × 0.001 → million barrels. EUR/1000 L × 0.001 → EUR/L. Percent utilization stays percent and can historically exceed 100; values above 100 are flagged for review. No general metric-ton conversion exists without a specified density/version. No currency conversion is silently applied.

## Information available at a forecast origin

```bash
.venv/bin/fuel-market snapshot --origin '2026-11-10T23:00:00+02:00' --mode strict --output data/exports/market_snapshot.json
```

The origin must have an explicit UTC offset. Strict mode uses capture time for today's retrospective histories. A historical publication timestamp alone cannot backdate the current revised value. A documented original vintage requires publication timestamp, vintage timestamp and original edition evidence URL; the importer rejects impossible temporal ordering. These fields are assertions requiring source review, not an automatic authenticity certificate.

Features enforce available-at ≤ origin for every included observation. They record original IDs, maximum knowledge time, observation age, units and availability basis. A stored market snapshot does not certify the Lebanese target's announcement timestamp, economic correctness, completeness, or trading availability. `backtest_eligible=true` means the strict **market availability rule** was used; the target and vintage evidence still need audit.

Unknown historical release times are not replaced with invented market-close times. For future collected data, actual capture time is conservative. For historical comparisons, `--mode research` uses today's latest vintage with **assumed calendar lags**: EIA 14 days, H.10 10 days, Commission 7 days, reviewed payment FX 1 day. These are sensitivity assumptions, not verified delays or sufficient protection against revisions. Every research output is marked `NOT_BACKTEST`; never feed it into claimed real-time performance metrics.

Historical comparison origins are assumed 00:00 Asia/Beirut before the source-labelled Lebanese date. They are explicitly not known announcement times. Weekends/holidays are left absent; there is no manufactured daily price, linear interpolation or holiday calendar claim. Weekday-grid absence is reported as an **unclassified candidate**, not a missing official market session. Captured knowledge times govern strict alignment across holidays/DST, so market and Lebanese calendars cannot expose unpublished values. Actual historical market/government calendars and announcement times remain a prerequisite for event-time backtesting.

## Features and economic meaning

`src/lebanon_fuel/features/market.py` calculates one-observation returns, seven-calendar-day returns using the closest earlier available reference, 30-day momentum, trailing 5/20-observation averages, one-observation lags, and annualized 20-return log volatility. It uses 252 daily / 52 weekly observations as stated scaling conventions. It does not fill weekends. Excessive gaps disable returns/windows; old levels expire at the series staleness limit. In research mode the assumed publication lag is added to that age limit and remains labelled.

Trend compares with the trailing mean; the high-volatility flag compares current volatility with preceding trailing volatility only. No whole-sample percentile, scaler or fitted transform is used. Irregular official FX expires after seven days and cannot generate a continuous exchange-rate history. The synchronized NYH-minus-Brent feature uses equal observation dates and retains both original IDs; it is a cross-region gross spread, not refinery profit. Genuine Med refining/crack margins remain absent until licensed compatible legs and conventions are available.

Later modeling must fit any imputation, scaling, feature selection and regime estimation within chronological training folds. Provisional Lebanese policy buckets are descriptive labels inherited from Part 2, not certified regime break dates.

## Manual authorized data and original vintages

The template is `config/market_import_template.csv`. Missing values remain empty; never enter zero or create rows for dates without observations.

```bash
.venv/bin/fuel-market import-csv /absolute/path/authorized_history.csv --series brent_spot --source-url 'https://publisher.example/original-file' --license-note 'Describe the actual authorization and dataset identity'
```

The example URL is a placeholder, not a claimed endpoint. Only import into a series if product, units, source and methodology truly match its catalogue identity. Paid Med/futures/freight files first require a separate reviewed series definition and parser, exact symbols/contracts, source licence, original timestamps and tests; they cannot be relabelled as Brent. Keep licensed raw files private if required by the agreement.

The reviewed payment FX CSV additionally requires reviewer, original evidence locator and hash matching a previously captured official PDF. Its observation is not historically available in strict mode until capture/review; the old decision date alone is insufficient.

## Outputs and checks

- `data/exports/market_history.csv`: latest eligible valid normalized observations, original units, IDs and provenance. Missing/invalid originals remain in SQLite/raw files.
- `data/exports/market_features_current_strict.json`: current trailing features with evidence lineage.
- `data/exports/market_lebanon_alignment_RESEARCH_ONLY.csv`: regime-labelled historical comparisons, assumed origins and fixed-lag returns. Not a training/backtest dataset.
- `reports/market_coverage.md/json`: actual coverage, units, staleness, timing limitations and missing licensed data.
- `reports/market_gap_candidates.csv`, `market_calendar_candidates.csv`, `market_revisions.csv`, `market_conflicts.csv`: separate review queues; do not overwrite disputes or impute absences.
- `reports/market_reported_missing.csv`: explicit unavailable/invalid source rows, separate from calendar absence candidates.
- `reports/market_suspicious_changes.csv`, `market_date_alignment.csv`: large moves and unusual reference weekdays for review; real shocks and holiday labels are retained.
- `reports/charts/`: PNG and SVG comparison, coverage and exploratory lag-correlation figures. All use actual observed values and latest downloaded vintages.
- `reports/tests_part3.txt/xml`, `reports/market_validation.md`: executed test and integrity evidence.

HTTP failures and parser schema drift stop that source; no access workaround, alternate unofficial quote, estimated observation count or synthetic quotation is substituted. Replay preserved captures with `fuel-market replay --capture-id ID --series SERIES` to reproduce parser output without network access.
