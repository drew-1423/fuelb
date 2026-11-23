# Evidence register and verified assumptions

Research cutoff: 10 November 2026, Asia/Beirut. Verification means inspection of the linked publication or public UI, not a guarantee that every number on that site is correct. Publication times without a stated timezone remain unknown. Retrieval timestamps for collected files are recorded in their manifests/database.

## Status vocabulary

- **Verified historical**: primary evidence for the dated period only.
- **Observed**: directly read source/UI/file; official truth not independently established.
- **Corroborated**: agreeing independent source observations; still distinct from an authenticated decision.
- **Reported**: secondary account; original legal instrument still required.
- **Hypothesis/design**: proposed relationship or system choice, not an official fact.
- **Unresolved**: evidence insufficient, contradictory, or inaccessible.

## Sources and bounded claims

| ID | Publication date / scope | Verification | Source and supported claim |
| --- | --- | --- | --- |
| S01 | 2021-02-23; clock time absent | Verified historical | [MOEW/DGO clarification](https://energyandwater.gov.lb/ar/details/100628/المديرية-العامة-للنفط-توضح-ال-لي-ـة-المعتمدة-أسبوعيا-لتحديد-أسعار-مبيع-المحروقات): weekly Platts product averages, import-related costs, domestic charges and a 90% official / 10% parallel FX subsidy arrangement **then**. |
| S02 | September 2015 presentation | Verified historical industry account | [APIC presentation, final slide](https://data.infopro.com.lb/file/Snapshot%20of%20the%20Refined%20Petroleum%20Market%20in%20LEBANON_APIC.pdf): four-week Platts Mediterranean average described in 2015. Not current law. |
| S03 | 2023 tender; URL upload 2023-11-14, exact publication time unverified | Verified procurement specification | [MOEW/DGO tender, price clause](https://pe.ppa.gov.lb/storage/annual-plans/files/combi-diesel-gasoline95-tor_20231114-193725_jhx23jdjyjrvv2s7.pdf): gasoline Prem Unl 10ppm FOB Med (Italy), 11 quotations around bill of lading. This procurement window is not proof of the retail table window; the document also contains inconsistent references to 21 quotations. |
| S04 | May 2026 methodology edition | Verified benchmark definition | [S&P refined-products guide](https://www.spglobal.com/content/dam/spglobal/ci/en/documents/platts/en/our-methodology/methodology-specifications/refined-products/refined-products-europe-africa-specifications.pdf): AAWZA00 FOB Mediterranean 95 RON, USD/metric ton, reference density 0.755 kg/L; AAWZB00 CIF Med includes a freight netforward. Does not establish Lebanon's current chosen symbol. |
| S05 | 2023-05-12; decision date, clock time absent | Verified historical document, numeric extraction provisional | [MOEW retail price table](https://energyandwater.gov.lb/mediafiles/prices/1-2023-05-12.pdf): parallel FX label, import cost, duties, transport, station/bank commissions, 11% VAT and consumer price. Reconcile image and arithmetic before admitting numeric fields. |
| S06 | 2024-03-26; clock time absent | Verified historical document, OCR unreliable | [DGO decision bundle](https://en.dgo.gov.lb/upload/2821website%E2%80%8E%E2%81%A8%D8%A3%D8%B3%D8%B9%D8%A7%D8%B1%20%D8%A7%D9%84%D9%85%D8%AD%D8%B1%D9%88%D9%82%D8%A7%D8%AA%20Online%2026-3-2024%E2%81%A9.pdf): ministerial delegated decision, consumer maximum, immediate effect and stated USD payment exchange rate. Automated text contains conflicting digits/columns. Direct download returned HTTP 406; no bypass attempted. |
| S07 | 2022 overview; exact release timestamp absent | Verified central-bank historical account | [BDL monetary overview](https://www.bdl.gov.lb/CB%20Com/Publications/Publications/Monetary%20Overview_22_Ar%C2%A78193_1.pdf): dates complete fuel-subsidy removal to October 2022 and official FX change to 15,000 from February 2023. Intermediate product-specific changes still need dated instruments. |
| S08 | 2025-06-05 | Verified historical policy announcement | [MOEW statement](https://energyandwater.gov.lb/ar/details/100997/بيان-صادر-عن-الوزير-الصدي-حول-قرار-تعديل-الرسوم-الجمركية-على-المحروقات): Cabinet decision of 2025-05-29 altered customs charges. |
| S09 | 2025-07-21; clock/timezone to recheck | Reported legal implementation | [LBCI account of Finance Ministry statement](https://www.lbcgroup.tv/news/lebanon-news/868579/lbci-lebanon-articles/en): suspension of additional excise under customs decision 49/2025 following Shura decision 219/2024-2025. Obtain original decision before coding dates/rates. |
| S10 | 2026-02-17 | Reported policy | [AP report](https://apnews.com/article/lebanon-taxes-fuel-salaries-protests-5971edfb501c3aee4f508709ee702d15): Cabinet approved LBP 300,000 per 20 L gasoline; VAT proposal required parliamentary approval. A proposal is not an enacted VAT rate. |
| S11 | 2026-09-29 | Verified proposal only | [MOEW announcement](https://energyandwater.gov.lb/ar/details/101203/الصدي-سأطلب-من-الحكومة-إلغا-رسم-الـ300-ألف-على-المحروقات-أو-تعليقه): minister sought removal/suspension of the 300,000 charge; does not verify repeal. |
| S12 | 2026-07-07 13:32; timezone unspecified | Reported ministerial explanation | [Lebanon24 press-conference report](https://www.lebanon24.com/news/articles/1547084/lebanon24): refined products, customs, freight, insurance and war-risk costs discussed. No complete current retail formula or averaging window established. |
| S13 | Live page/export observed 2026-11-10 | Observed supplier source | [IPT fuel prices](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices): date controls, chart and working XLSX export. Snapshot preserved under `research/evidence/`; it is not itself an official decision archive. |
| S14 | Dynamic page observed 2026-11-10 | Observed government archive, rows require checks | [MOEW prices](https://energyandwater.gov.lb/ar/prices): Arabic date search with product columns, decision IDs and some PDF links; sparse results and suspicious cells observed. |
| S15 | Live page observed 2026-11-10; crawler copy was 2026-11-06 | Observed supplementary archive | [Taqtek](https://taqteklb.com/en/fuel/): explicitly independent; admits gaps; exposes year archives. Uses 89,500 for displayed USD conversion, not proof of pricing FX. |
| S16 | Undated institutional page, inspected 2026-11-10 | Verified institutional description | [DGO responsibilities](https://www.dgo.gov.lb/category/1): economic/financial unit studies petroleum prices, costs and fiscal matters under the listed decrees. |
| S17 | 2021-09-17 | Verified historical official table | [MOEW decision 180 table](https://energyandwater.gov.lb/mediafiles/prices/1-2021-09-17.pdf): 95-octane consumer price 174,300 LBP/20 L and dated historical margins. |
| S18 | Document issue date 2025-05-29; web publication time unknown | Verified historical, original images reviewed | [MOEW decision 166 and annex](https://energyandwater.gov.lb/mediafiles/prices/1-2025-05-29.pdf): 95 price 1,489,000 LBP/20 L; immediate-effect clause. Original bytes and reviewed transcription are preserved in Part 2. |
| S19 | Document dateline 2010-10-27; web publication time unknown | Verified historical government announcement, image reviewed | [MOEW press release](https://energyandwater.gov.lb/mediafiles/prices/f2010-10-27.pdf): 95 consumer price 33,300 LBP per tin, effective that day. Unit mapped to the official archive's 20 L heading; individual decision numbers are absent. |

## Assumptions that must not become defaults

The current complete retail formula, Platts symbol, averaging window, density treatment, component-specific FX, tax bases, margins and rounding remain **unresolved**. A weekly window in S01, four weeks in S02 and the shipment-centered procurement clause in S03 describe different dates/contexts. None justifies a universal fixed delay. The 2021 subsidy weights are historical, and the current FX rate cannot be inferred from a secondary site's USD display. We have not established the complete set of policy change dates.

All formula parameters must carry `valid_from`, `valid_to`, `known_at`, evidence URL and status. Unknown is null, never a guessed zero. Research hypotheses and regime annotations are excluded from verified observations.

## Part 3 evidence additions

See [international market sources](international_market_sources.md) for primary URLs, publication-date limits, access outcomes and economic roles. Actual normalized observations and capture times are in the shared SQLite database; counts and gaps are generated in `reports/market_coverage.md`.

- **Verified historical document**: S18 page 1 states 89,700 LBP/USD for customer USD payments on 29 May 2025. The reviewed transcription is a single observation, not a continuous official formula FX history.
- **Observed primary data**: EIA XLS histories, the Commission's tax-excluded Italy/Greece Euro-super 95 history and the Federal Reserve's original H.10 XML were actually downloaded and parsed. Individual historical release instants and original vintages are not established by their date columns.
- **Verified source distinction**: Brent is crude; NYH regular gasoline is a U.S. product proxy; Commission prices are consumer/retail proxies. None is a collected Mediterranean wholesale assessment. S04 still defines relevant genuine Med candidates whose licensed histories are absent.
- **Observed access limitation**: the Commission's repeat refresh returned HTTP 429; collection stopped. Its earlier successful capture was retained. FRED payloads were removed after its current use restrictions were reviewed; FX comes directly from the Federal Reserve.
- **Research only**: fixed lag assumptions, provisional regimes and exploratory correlations are not verified statutory windows, causation or forecast accuracy. Strict historical market snapshots remain empty for the existing source-date origins without original vintage evidence.

## Part 4 evidence additions

- **Verified historical, image reviewed:** S17/S18 and newly captured S05 have now been transcribed at gasoline-95 component level. Their dated LBP pretax and 11% VAT totals reconcile; see `structural_pricing_equation.md` and hash-bound `data/manual/structural_annexes.json`. This does not establish current validity.
- **Observed discrepancy:** S05/S18 printed USD goods × printed parallel FX differs from printed LBP goods. Retain all original figures; exact upstream conversion/adjustments remain unresolved.
- **Calculated, not forecast accuracy:** three nonconsecutive annexes reconstruct to within 3.30 LBP/20 L before rounding. Same-document components cannot establish predictive performance.
- **Estimated, research only:** chronological proxy results are in `../reports/structural_validation.md`. No per-observation original release vintages or target publication times were recovered; strict historical evaluation remains empty. Empirical windows/slopes never become official parameters.

## Part 5 evidence additions — 11 November 2026

- **Calculated development results:** 16 horizon/regime bundles were fitted and reloaded on actual source-linked historical inputs. Numerical B is explicitly a positive transmission proxy; the full Part 4 accounting adapter has incomplete dated inputs and abstains. See `../reports/forecasting_development.md` and `quantitative_forecasting_protocol.md`.
- **Research assumptions:** next-midnight domestic availability, Part 3 market release delays, archive completeness conditional on eligible paths, positive product-gap transmission and calendar coverage witnesses. None is a newly verified official pricing rule.
- **Observed model limitation:** older one-/three-day ensemble intervals severely under-cover outcomes; recent one-day intervals have zero width and under-cover. Their nominal 90% setting is not a verified confidence level. Long-horizon calibration often lacks enough nonoverlapping samples.
- **Observed primary news data:** 35 EIA feed items were actually captured on 2026-11-11; 34 preserve usable original publication timestamps. Exact source URLs, raw clocks and capture versions are stored. See `news_intelligence.md` for primary URLs, publication-date limits and reuse findings. Their historical incremental predictive value is **unresolved**, with zero eligible development ablation cases.
- **Stage limitation:** no current official forecast, production winner or independent Part 6 validation is established. Earlier Part 4 exposure of 2018–2019/2025 periods is disclosed; those periods cannot become globally untouched tests by renaming them.

## Part 6 evidence additions — 11 November 2026

- **Recalculated:** Part 5's 158 reported metric groups reproduce under separate equations. This validates arithmetic, not historical availability or forecast validity.
- **Observed source-timing limit:** actual domestic reconciliation/capture and market sighting times are later than the evaluated historical origins. The strict evaluator admits zero forecasts; no strict error figure is available.
- **Calculated, non-strict research only:** expanded temporal challenge results and strong-baseline comparisons are in `../reports/model_validation_report.md`. Previously examined periods remain explicitly exposed; there is no fresh final holdout score.
- **Confirmed model-risk finding:** deterministic calibration thinning overselects unchanged labels and produces severe undercoverage in some calendar horizons. No coverage guarantee is established by the nominal interval setting.
- **Governance decision:** all requested production selections are null/rejected. Current prospective ledger entries are abstentions. No current official price prediction or claimed external independent certification was created.
