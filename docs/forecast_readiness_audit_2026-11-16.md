# Lebanon gasoline 95 forecast readiness audit

**Audit date:** 16 November 2026, Asia/Beirut.  
**Scope:** Local forecasting code at `a1ec1a2`, current local SQLite databases, saved predictions, production selection, and live forecast check. GitHub `main` at `60290a2` differs from the audited source commit only in dashboard presentation and README files. This audit recalculates metrics from saved rows and checks selected provenance and integrity fields.

## Release decision

**Research only.** The latest batch abstained on all eight horizons. The model has no measured prospective accuracy, the historical evaluation has zero certified effective-price targets, and the current validation command cannot produce strict performance evidence. The immediate priority is a complete, timestamped domestic decision sequence and dependable settlement.

## Current anchor and coverage

The forecast check at 12:17 Beirut on 16 November recorded eight abstentions (forecast IDs 45180–45187). The latest ledger revision was 13 November, 2,391,000 LBP/20 L, supplier-only (revision 3473). IPT independently displays the same dated quote. The last corroborated archive revision was 10 November, 2,445,000 LBP/20 L (revision 3447). Neither revision has a recorded official effective date. The audit did not establish a corresponding original ministry decision for the 13 November quote.

The Brent and NY Harbor gasoline closes in the saved run were dated 11 November, within the configured seven-day fresh-market gate. The domestic anchor failed before the live model attempted those checks. All eight registered quantitative bundle checksums match. There were 59 issued prospective research forecasts across eight runs and zero prospective evaluations in the current ledger. Both price and forecast SQLite files returned `ok` from read-only `PRAGMA quick_check`.

The current 2026 price ledger has 88 source-date rows: 78 supplier-only, eight corroborated archive, one government archive only, and one conflict. None has an official effective date. From June 1 onward the ledger holds 47 rows, including seven archive-corroborated and 39 supplier-only. These denominators measure captured rows rather than full official decision coverage.

Sources: [IPT fuel prices](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices), dated 13 November 2026, checked 16 November 2026. [Ministry price portal](https://energyandwater.gov.lb/ar/prices), checked 16 November 2026. Local evidence: `reports/operations/current_forecast_check.json`, `data/lebanon_fuel.sqlite`, and `data/forecast_ledger.sqlite`.

## Independent recalculation

From `reports/model_validation/research_walk_forward_predictions.csv`, I grouped by horizon, family and origin. Error is saved predicted change minus the recorded target change. Coverage is the fraction of outcomes inside both saved change bounds, inclusive. The now-used June–November selection period contains 288 model rows over 29 origin/horizon pairs, all uncertified archive targets. Only four are next-decision origins. The latest recorded training label matured at 00:00 Beirut on 23 December 2025. No saved training label cutoff reached the fit cutoff and no saved calibration label cutoff reached its forecast origin. Those checks establish stored cutoff consistency.

| Next-decision method | Sample | n | MAE, LBP/20 L | RMSE, LBP/20 L | Nominal 90% interval hits |
| --- | --- | ---: | ---: | ---: | ---: |
| Hybrid | Shared with last-change baseline | 2 | 366.17 | 369.34 | 2/2 |
| No change | Same two origins | 2 | 26,500.00 | 33,503.73 | 1/2 |
| Last change | Same two origins | 2 | 15,500.00 | 21,224.99 | 1/2 |
| Hybrid | All available next-decision origins | 4 | 18,951.18 | 33,849.68 | 3/4 |
| No change | Same four origins | 4 | 34,250.00 | 45,340.38 | 2/4 |

The hybrid got the sign right on all four cases, which were all decreases. On the 6 November target it predicted −9,757 LBP/20 L against a recorded −77,000, a miss of approximately 67,243 LBP/20 L. The mean nominal 90% interval width across those four was 70,115 LBP/20 L. This sample cannot establish directional skill or interval reliability.

Usable origin counts before restrictions for model comparisons were four for the next decision, two for the next two decisions, zero for the next four decisions, 13 for day 1, nine for day 3, one for day 7, zero for day 14, and zero for day 30. Repeated calendar origins can share the same underlying decision.

## Findings and required corrections

| Severity | Finding | Required correction |
| --- | --- | --- |
| Critical | Newer supplier-only quotes block all live issuance, and strict settlement needs documented publication, effective timing and complete coverage. `forecasting/live.py:55`, `validation/settlement.py:25`, `validation/ledger.py:249`. | Build a reviewed ministry-document import and cycle coverage registry. Preserve source, publication, effective, first-seen and revision clocks. Reconcile the latest observation and adjacent decisions. If an exact time is missing, use an explicit date/interval precision method only after proving ordering and use eligibility; otherwise abstain. |
| Critical | Research labels are always uncertified. The active runner loads only the conditional design and writes `strict_n=0`. Research dates assume domestic knowledge at next-day midnight and market knowledge at an assumed close using the latest edition. `forecasting/data.py:25,65,236`, `market/store.py:111`, `validation/runner.py:128,171,224`. | Build an actual vintage-backed validation path from verified decision events and captured source versions. Reconstruct the exact information set available at each origin. Keep research scores outside approval. |
| High | Two shared cases gave the hybrid its headline score. The 2026 period was used to select models. There are zero settled prospective forecasts. `config/validation_protocol.json:12`, `validation/runner.py:97,159`. | Freeze a new evaluation protocol and compare against persistence, last change and the strongest simple alternatives on identical targets. Report the full eligible denominator, issuance rate and paired comparison intersection. Reserve a new final or prospective sample. |
| High | The structural delta uses a four-close proxy window, constant 89,700 FX, 1.01 bank and 1.11 VAT factors. The 150,000 LBP flag represents a large past move. `forecasting/data.py:160–196,229–232`. | Verify dated pricing annexes and effective regimes. Separate goods/customs/customer payment FX and define freight treatment, VAT base and rounding. Use dated parameters as policy facts and estimated windows/coefficients as model inputs. |
| High | Tier 2 accepts 8–14-day spot data using the same quantitative prediction path and model/OVX calibration lookup. The evaluation does not certify this freshness subgroup. `forecasting/live.py:124,310–348`. | Replay each latency tier with captured publication vintages, report eligibility and error by input age, and label or withhold intervals and probabilities for unsupported age regimes. |
| High | Gap in reproducibility: eight bundle hashes and the design hash match the saved registry/manifest, but `validation/ledger.py`, `validation/reporting.py`, `validation/runner.py` and `forecasting/live.py` differ from the source hashes captured for the evaluation. | Preserve the original hashes. Add immutable candidate release manifests binding the evaluation, issuance, settlement and configuration revisions. Run strict prospective validation against the release candidate. |
| Medium | Settlement's timing-conflict query is global. An unrelated amended decision can block matching outside the affected period. `validation/ledger.py:258–273`. | Scope timing review to decision events that could change the target. Test corrections, multiple same-day observations, overlapping windows and idempotent settlement. |

## What to source first

1. A consecutive set of signed 95-octane decisions in the current policy regime, starting with the most recent entries. Capture original evidence and all exceptions. Keep collecting in real time even while an archive backfill is underway.
2. Timely, authorized refined-product inputs. EIA NY Harbor conventional regular gasoline is a US product proxy and EIA Brent is a crude input. A licensed Platts Mediterranean gasoline history with true release versions can improve economic alignment if the relevant symbol/window is established and paired validation confirms value. A CIF series already embeds its freight component.
3. Documented regime parameters from current and dated ministry pricing schedules. The code's 89,700 price sensitivity and the dashboard's 89,500 display conversion serve different purposes. Banque du Liban's 89,500 statistical exchange-rate series does not establish a Ministry goods conversion rate.

Primary references, checked 16 November 2026: [EIA spot series definitions](https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm), [S&P Global refined-product methodology, July 2026](https://www.spglobal.com/content/dam/spglobal/ci/en/documents/platts/en/our-methodology/methodology-specifications/refined-products/refined-products-europe-africa-specifications.pdf), [Banque du Liban USD/LBP series](https://www.bdl.gov.lb/keyfiguressub.php?code=3&docId=161&filecode=323), [Ministry annex, 29 May 2025](https://energyandwater.gov.lb/mediafiles/prices/1-2025-05-29.pdf).
