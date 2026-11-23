# Part 3 execution and validation

Completed 10 November 2026 on native Apple Silicon, CPython 3.13.12. Exact local package versions are in `requirements-market-lock.txt`.

## Actual retrieval and update evidence

- Public EIA history pages and their linked XLS files downloaded successfully; all five final EIA collectors completed an update with zero new semantic observations. This confirms duplicate prevention on the captured histories, not a guarantee against future source format changes.
- The European Commission history XLSX downloaded successfully and yielded 1,091 original rows for each selected country, including one blank value each. A repeat collector request returned HTTP 429 and stopped. The previous successful artifact and its retrieval time remain available; the failed refresh is recorded in the coverage report.
- The Federal Reserve's original complete H.10 XML ZIP downloaded successfully. Its daily USD-per-EUR series has 7,265 source rows: 6,984 values and 281 ND sentinel rows. ND is preserved as unavailable, not normalized into a negative exchange rate. A later collector update added zero semantic observations.
- The original MOEW decision 166 was visually rechecked; one customer-payment exchange-rate observation, 89,700 LBP/USD on 29 May 2025, was imported with original PDF hash and review locator. It is stale for current forecasting and does not become a continuous pricing-FX series.
- FRED was investigated and withdrawn after current use restrictions were reviewed. Exploratory payloads were removed; a metadata-only record remains in `market_source_withdrawal.json`. The active FX data comes from the original Federal Reserve publisher.

## Data and audit checks

Actual database counts: **33,843 market observations**, comprising **33,560 valid observations** and **283 unavailable values**. Eight original automatic-source captures were replayed: **33,842 source rows parsed, zero new observations**. The remaining observation is the reviewed official FX record. Evidence: `market_replay_validation.json`.

`PRAGMA integrity_check` returned `ok`; `foreign_key_check` returned no errors. Raw market capture hashes matched their saved files. Original Lebanese tables retain **3,168 observations, 3,443 decision versions and 3,169 sightings**, matching their counts before Part 3. Evidence: `market_integrity.json` and `market_coverage.json`.

The initial market fingerprint was improved to exclude changing spreadsheet row positions and XML package metadata. A recorded initialization migration changed identifiers only; no market values were changed and no duplicate observations required merging. SQL mutation guards were restored. A join index was added after testing the full dataset to keep quality queries efficient. Records are append-only in normal operation; the documented withdrawal of newly captured FRED payloads is a source-policy exception.

## Automated tests

Executed command:

```bash
.venv/bin/python -m pytest Tests/fuel -q --junitxml=reports/tests_part3.xml
```

**58 passed.** The suite includes the Part 2 tests and checks:

- Immutable observations/sightings, semantic duplicates, changed raw row locations, correction and A→B→A reversal histories.
- Simultaneous contradictions, invalid latest revisions, source units, positivity, nonfinite values, missing values and future dates.
- Explicit UTC offsets, DST/weekend capture alignment, original vintage evidence and impossible timestamp ordering.
- A future observation or later correction cannot change a prior strict feature snapshot.
- Trailing returns/averages, staleness/gap handling, matching spread dates and unit normalization.
- EC product/unit schema checks, original EIA workbook/header checks, Federal Reserve XML identities, rate direction and ND sentinel handling.
- Atomic rollback on parser failure, manual authorization/evidence requirements and zero-duplicate replay of an actual EIA download.
- Research comparison equivalence to trailing feature returns, honest assumed-origin labels and the market join index.

No live network requests are made by tests. Synthetic test fixtures are not exported or reported as observations. Text and JUnit evidence: `tests_part3.txt`, `tests_part3.xml`.

## Deliverables and remaining limits

Collectors, schema, normalized SQLite data, raw captures, source documentation, feature code, CSV exports, quality queues and three PNG/SVG charts exist. The charts were visually inspected for labels, units and explanatory notes. The production command `fuel-market report` runs against the real database.

Historical comparisons include 728 eligible adjacent verified-tier Lebanese record pairs and fixed lag/regime summaries. They use latest market vintages and assumed release lags, so they are exploratory. **None of the 1,370 historical source-date origins has a market observation proven available then by this project's original-vintage/capture evidence.** This is disclosed rather than hidden through backdated release assumptions.

No licensed Mediterranean gasoline assessments, contract-level ICE futures, Med clean freight history or complete pricing-formula FX series was obtained. Actual source release vintages, original Lebanese announcement times, current formula components and unresolved target conflicts remain necessary before institutional backtesting. No complex forecast model, forecast accuracy claim or live scheduler was created. Part 3 stops here.
