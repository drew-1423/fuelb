# Live Hybrid forecasting and publication

## Prospective scorecard protocol

Protocol `2026-live-score-v3` starts at 00:00 Beirut time on 28 November 2026. Earlier results retain their original research protocol. Every normal issuance is preserved in the append-only ledger. A complete run has one row for each of the eight horizons, including any explicit abstentions.

Each eligible issued Hybrid row stores the selection key, exclusive entry cutoff and available baseline values in the hashed target record. The scorecard takes the first eligible complete issuance by immutable ledger ID. Outcome data never enters that selection. The row's primary key, issue timestamp, model, input snapshot and base price identify the choice. Any subsequent match, revision or dispute leaves that choice intact.

- For decision horizons, the key is the starting source date and forecast horizon. Entry closes at the end of the following Beirut date. A forecast recorded after the cutoff is ineligible. A later official review or an anchor revision cannot override the selection for the same date.
- For calendar horizons, the key is the Beirut endpoint date and horizon. The batch must issue before 12:00 Beirut time on the origin date. Its endpoint retains the exact saved local horizon clock, so all methods are compared at the same lead time. Late and incomplete batches cannot replace an eligible issuance.
- A missed cutoff is counted for a target key seen in the complete ledger batches. A calendar day with no complete batch is visible in operations availability and does not produce an invented scoring row.
- Match only against eligible later events. Supplier targets require dated independent agreement and conservative ordering. An off-date quote cannot certify a calendar endpoint, or prove that a price persisted over an unobserved day. Gaps and conflicts remain visible. Subsequent confirmation on the same target date counts as one aggregate outcome.
- Persistence uses the original recorded starting price. Last change repeats the adjacent eligible price move when it was actually known and the gap is at most seven days. Each baseline is compared with Hybrid only on rows where that baseline exists.
- The shadow sensitivity sets only `x_domestic_change_lag1` to zero using the same frozen model and same input vintage. Other lag variables remain in place. This measures one feature perturbation. The operator can run `PYTHONPATH=src python scripts/audit_hybrid_lag.py` against a restored snapshot. It prints local research results and excludes any row whose frozen model and issued price cannot be reproduced.

Calibration uses only the selected live forecasts for this protocol, strictly earlier matured labels, nonoverlapping eligible cases, and the original horizon, artifact, starting evidence and outcome evidence strata. Release rules still require at least 30 qualifying cases and 20 chronological coverage tests with acceptable coverage. The chart treats decision dates as projections and independent calendar results as point estimates.

## Forecast Review

Market & Intelligence → Forecast Review reads the selected forecasts and supported outcomes in the published ledger. Each matched row carries the issue time, outcome evidence, forecast and price, signed error, available paired baselines, and the saved market inputs and model attribution. An earlier match is available for reference without entering the current checkpoint.

The 30-outcome checkpoint counts distinct matches for the latest selected model version and the chosen horizon. It is a cue to review the evidence, independent of calibration and model approval. The journal records forecast timing separately from pricing errors. It flags hypotheses such as domestic momentum overshoot or delayed market inputs for point-in-time tests on shared origins. Outcomes with missing or disputed evidence stay out of pricing metrics.

The downloadable JSON research packet includes the matching and market cutoffs, forecast IDs and hashes, paired errors, test ideas and any personal notes added in the session. Save the packet to retain personal notes. The journal has no training or model-selection write path.

## Evidence check for 27 November 2026

The restored release `fuel-storage-46051273585-1` had 1,312 dated IPT records (2008-01-02 through 2026-11-27) and three dated TotalEnergies observations (2026-11-20 through 2026-11-27). All three TotalEnergies dates had an agreeing IPT price. The TotalEnergies page exposed one current price date at inspection. [IPT fuel price archive](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices) · [TotalEnergies fuel prices](https://pricing.totalenergies.com.lb/fuelprice/)

IPT and TotalEnergies showed 2,158,000 LBP per 20 L on 27 November. The prior eligible price was 2,242,000 on 24 November, a decline of 84,000. The prior government-backed archive price was 2,343,000 on 17 November, a decline of 185,000 across multiple recorded updates. The 22 November supplementary quote repeated the 20 November price. Original rows remain in storage.

The Ministry's 2 January 2026 source row explicitly showed 1,359,000 in the 95 column and 1,320,000 in the 98 column. Taqtek showed 1,320,000 for 95. The Ministry's 15 December 2025 row actually contained 143,300, whereas Taqtek showed 1,433,000. The archived bytes explain both normalized disagreements. These are source conflicts and cannot be resolved by rewriting a parser or multiplying the price by ten without decisive additional evidence. [Ministry price archive](https://energyandwater.gov.lb/ar/prices) · [Taqtek fuel archive](https://taqteklb.com/en/fuel/)

The next-update research estimate was 2,106,904.51 LBP, down 51,095.49. The earlier matched 27 November forecast was 2,207,694.67 against 2,158,000 actual. Hybrid and persistence errors were 49,694.67 and 84,000 respectively, for one distinct outcome under the earlier protocol. In the published estimate, domestic momentum contributed about −43,516 LBP. This is model attribution. The latest release had one calibration outcome and zero coverage tests for the next update under the prior protocol.

New strict feature reads use `captured` mode. They require actual capture availability and resolve the vintage at each origin. Historical `strict` market reads that explicitly support documented editions remain available for reproducibility. The frozen historical research design still uses assumed close and latest-vintage values.

NY Harbor gasoline and Brent last observed on 24 November were first captured on 26 November, a two-calendar-day lag. Across the latest 30 dates for each, the median first-capture lag was eight calendar days. The latter includes collection and backfill delays and cannot be interpreted as a supplier release schedule. There were zero valid RBOB futures rows in this release. The public exchange product page identifies the contract, but supplies no verified point-in-time history for this project. The weekly Italy/Greece retail series last observed 23 November and were neither timelier on this snapshot nor equivalent to CIF Mediterranean 95. Keep market proxies labeled. [EIA petroleum data](https://www.eia.gov/petroleum/) · [CME RBOB contract](https://www.cmegroup.com/markets/energy/refined-products/rbob-gasoline.html)

## Cloud deployment and operations

The app compares the local release with the canonical `main` publication. It pins the manifest and companion JSON files to a single Git commit, checks the public summary checksum and the individual database hashes, and installs them as one generation. A process-wide worker avoids concurrent per-session downloads. While loading, visitors can see a verified bundled price summary and its original timestamp. A failed download leaves a prior verified generation usable. The active manifest tag, manifest hash and timestamps are visible or machine readable in the rendered page.

GitHub Actions remains the only scheduled deployment sync writer. After syncing a changed tree, it reads the rendered release identity from the public app, with explicit outcomes for hosting sleep, startup, hydration, stale data or missing evidence. A green branch sync by itself does not prove the loaded Streamlit snapshot. The app can poll the canonical manifest on subsequent user reruns without waiting for a source checkout change. The first deployment of this code still needs Streamlit to pull the source revision. The static summary remains available at https://drew-1423.github.io/fuelb/.
