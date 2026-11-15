# Lebanese fuel-price source assessment

Inspection date: 10 November 2026, Asia/Beirut. Status vocabulary and publication metadata are in [verified_assumptions.md](verified_assumptions.md). Public access is not an open-data redistribution licence.

| Source | Observed access / format | Coverage and limitations | Intended role |
| --- | --- | --- | --- |
| [IPT](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices) (S13; live) | Public ASP.NET page, current dated prices, single-date filter, chart range controls and EXPORT. Clicking `all` then EXPORT generated an XLSX and a visible `ExportFuelPrices.aspx?path=…xlsx` link. | Actual download: 1,312 data rows, 2008-01-02 through 2026-11-10; six columns `Date, Octane98, Octane95, Diesel, GasOil, Gas`. Prices are formatted strings; Excel dates have no timezone. Five extra rows share existing dates; gaps and revisions need reconciliation. | Primary historical supplier observations. Date is source-labelled, not independently established publication/effective time. |
| [MOEW](https://energyandwater.gov.lb/ar/prices) (S14; live) | Date search produces HTML table; some rows link official PDFs. Default page text misses dynamic results. | 2010 search returned two records, starting 2010-10-27; 2025-11-10 to 2026-11-10 returned 20 rows, latest 2026-10-02. Some download cells empty; anomalous numbers appear. This describes the retrieved archive, not all actual decisions. | Government archive corroboration; authenticated original decisions are highest-priority evidence. |
| [Taqtek](https://taqteklb.com/en/fuel/) (S15; live) | HTML, yearly archive, LBP/USD toggle, date slider. Temporary automatic browser check cleared normally; no challenge bypass. | States coverage since 2010 with gaps. Live UI showed 2026-11-10 while web extraction showed 2026-11-06. No CSV/API/export verified. | Supplementary cross-check; shares ministry lineage, so agreement need not be independent. |

The IPT live display and downloaded row agree for 2026-11-10: 95 = 2,445,000 LBP. Taqtek's live UI also agrees. These are **observed/corroborated supplier values**, not a verified copy of the current official decision. Taqtek's USD conversion is not ministry FX evidence.

The ministry UI showed 143,300 for 95 on 2025-12-15 and 1,359,000 for 95 versus 1,320,000 for 98 on 2026-01-02. Flag these as suspicious; do not repair by inference. DGO PDF extraction also produced column/digit conflicts. Secondary agreement cannot silently fix a government archive entry.

## Permitted collection and controls

Prefer the actual XLSX download over chart scraping. Reuse only links/actions observed on the public page; no endpoint guessing. HTTP collection must preserve state tokens for ASP.NET form actions and honor robots, responses and rate limits. Browser export or a manual file import remains a supported fallback. Record HTTP status and content type, save original bytes with a hash, and reject HTML challenge pages masquerading as workbooks.

[IPT robots](https://www.iptgroup.com.lb/robots.txt) (observed; undated) disallows `/bin/`; its [privacy policy](https://www.iptgroup.com.lb/ipt/en/footer-menu/privacy-policy) is dated 2025-07-07. Neither constitutes a blanket data licence. Keep requests sequential and modest, stop on denial or challenge, and retain attribution. Paid benchmark history/licensing remains unresolved; it is outside Part 2.

No canonical public IPT JSON API has been verified. The export route is verified through the UI only; its generated filename is transient. Completeness requires comparing source dates with official decisions and documenting missing/contradictory records. Do not synthesize a daily price history.

## Part 2 follow-up: real HTTP collection

The subsequent implementation verified ordinary HTTP postbacks for IPT's public export; its returned script supplies the actual download URL. No Playwright scraper was needed. The complete 1,312-row download contains 1,311 unique semantic observations on 1,307 dates: one exact duplicate row plus four additional conflicting same-date observations. All occurrences are retained in capture sightings.

The ministry's served [pricesCtrl.js](https://energyandwater.gov.lb/js/pricesCtrl.js) (undated; fetched 2026-11-10) identifies its public `RenderPrices` POST action. Following its exposed navigation yielded **940 actual rows across 47 pages** for 2008-01-01 to 2026-11-10; the UI's first 20 rows were only a page. Raw JSON is captured unchanged even where the server declares an HTML MIME type. Its last retrieved record remains 2026-10-02; archive coverage is incomplete.

Taqtek's public HTML embeds an inspected `gasoline_95` LBP series; **914 observations** were collected without inventing an API endpoint or converting its rounded USD display. These results supersede Part 1's unverified programmatic-export/API status. Detailed current counts, conflicts, gap intervals and verification bounds are in [the generated report](../reports/data_quality.md). Source lineage remains a limitation.
