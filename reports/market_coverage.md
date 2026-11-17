# International market coverage and quality

Generated for 2026-11-17T06:55:35.979663+00:00. Counts below are actual stored observations, not estimates.

| Series | Unique valid dates | Earliest | Latest | Latest normalized value | Stale |
| --- | ---: | --- | --- | --- | --- |
| brent_spot | 9128 | 1987-05-20 | 2026-11-11 | 92.14 USD/bbl | False |
| nyh_gasoline | 9177 | 1986-06-02 | 2026-11-11 | 101.43 USD/bbl | False |
| us_gasoline_stocks | 1923 | 1990-01-05 | 2026-11-06 | 210.757 million_bbl | False |
| us_crude_stocks | 2302 | 1982-08-20 | 2026-11-06 | 414.417 million_bbl | False |
| us_refinery_utilization | 1880 | 1990-11-02 | 2026-11-06 | 95.2 percent | False |
| eurusd | 6984 | 1999-01-04 | 2026-11-06 | 1.1154 USD/EUR | False |
| italy_gasoline_ex_tax | 1091 | 2005-01-03 | 2026-11-09 | 0.962698 EUR/L | False |
| greece_gasoline_ex_tax | 1091 | 2005-01-03 | 2026-11-09 | 0.931434 EUR/L | False |
| lbp_payment_fx | 2 | 2023-05-12 | 2025-05-29 | 89700 LBP/USD | True |
| brent_futures | 0 | None | None | unknown USD/bbl | True |
| rbob_futures | 0 | None | None | unknown USD/bbl | True |
| gasoil_futures | 0 | None | None | unknown USD/bbl | True |
| cboe_ovx | 4912 | 2007-05-10 | 2026-11-12 | 51.72 percent_annualized | False |

## Latest collection outcomes

| Source | Result | Completed UTC | Detail |
| --- | --- | --- | --- |
| market_cboe | success | 2026-11-13T16:28:03.126952+00:00 | 4912 reviewed/imported rows |
| market_ec | failed | 2026-11-16T07:33:55.576046+00:00 | [Errno 54] Connection reset by peer |
| market_eia | success | 2026-11-16T07:28:44.768844+00:00 | 24,410 rows parsed; 0 new observations |
| market_fed | success | 2026-11-16T07:34:10.741565+00:00 | 7,265 rows parsed; 0 new observations |
| market_official_review | success | 2026-11-14T20:06:38.456497+00:00 | 1 reviewed/imported rows |
| market_yahoo | partial | 2026-11-12T11:01:09.971477+00:00 | rows parsed: unavailable; 0 new observations; brent_futures: unavailable — AccessStopped: Request denied by robots policy; Stored fallback: brent_spot (latest 2026-11-03); not newly collected futures; rbob_futures: unavailable — AccessStopped: Request denied by robots policy; Stored fallback: nyh_gasoline (latest 2026-11-03); not newly collected futures; gasoil_futures: unavailable — AccessStopped: Request denied by robots policy |

## Availability and validation

38,773 immutable observations; 283 invalid/missing rows retained. 0 dates with captured value revisions; 0 same-capture contradictions quarantined. Raw hash failures: 0.
39 long interval candidates; 2832 unclassified weekday/weekly calendar candidates. These include holidays and cannot be called missing market sessions without an authoritative calendar. No filling or interpolation was applied.
40 large-move review candidates; 0 unusual reference-weekday candidates. Review flags do not prove source errors or erase real market shocks.
Known per-observation publication timestamps: 0. Documented original historical vintages: 0. Dates in today's workbook are not release timestamps.
At 1371 historical source-date origins, 1 have any market value proven available by this project's capture/vintage evidence. Origins are assumed 00:00 Asia/Beirut; Lebanese announcement times are still unknown.

## Historical relationships

732 comparisons pair adjacent corroborated/document-verified Lebanese rows separated by at most 14 days. Conflict rows and unverified neighbors are excluded. These remain source-date comparisons, not certified consecutive official decisions.
The CSV reports fixed 0, 3, 7 and 14 calendar-day additional lags, seven-day market returns and Lebanese decision-to-decision changes by provisional regime. Latest revised market histories and assumed release lags are used. Correlations are descriptive, dependent and confounded by FX/tax regimes; no causation, optimal transmission lag or forecast accuracy is established.
For the provisional November 2022–May 2025 bucket, the fixed zero-additional-lag correlations are:

| Market return | Pairs | Correlation |
| --- | ---: | ---: |
| brent_spot | 160 | 0.098 |
| nyh_gasoline | 160 | 0.189 |
| italy_gasoline_ex_tax | 160 | 0.015 |
| greece_gasoline_ex_tax | 160 | 0.172 |
| eurusd | 160 | 0.041 |

Zero additional lag still includes the assumed publication lag (14 EIA / 7 Commission / 10 H.10 calendar days). Results change with lag and regime; this analysis does not establish a reliable leading variable or a statutory transmission window.

## Missing datasets

- **platts_AAWZA00**: Genuine FOB Med 95 RON assessment; licensed history and release vintages absent; exact current Lebanese retail symbol unverified.
- **platts_AAWZB00**: Genuine CIF Med assessment includes freight; licensed history absent; do not add freight twice.
- **eurobob_wholesale**: ARA barge gasoline is a different regional/product basis; licensed history absent.
- **ice_brent_contracts**: Actual futures contracts and settlements absent; need licensed contract history, expiration calendar and explicit roll policy.
- **med_clean_freight**: No authorized Med clean-product freight/war-risk premium history obtained; Baltic data need a licence.
- **med_refinery_outages**: No verified dated structured regional outage/capacity history obtained.
- **pricing_formula_fx**: Only one reviewed customer-payment FX observation; full formula FX series and regime transitions remain unresolved.
- **opec_monthly**: Public monthly reports available as context; structured vintage-preserving extraction deferred, no invented observations.

## Readiness

Collectors, normalized storage, trailing features and audit checks are ready for research. Institutional historical backtesting is blocked by original release vintages, unknown Lebanese announcement times, incomplete formula/FX evidence and missing licensed Mediterranean assessments. No forecasting model was trained.

See `research/international_market_sources.md`, `docs/market_data.md`, the JSON report and companion quality CSVs for definitions and procedures.
