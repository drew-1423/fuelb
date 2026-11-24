# Lebanese gasoline 95 data quality report

As of 2026-11-24, Asia/Beirut. Generated 2026-11-24T00:42:49.505793+00:00. Counts are database queries over actual captures.

| Completion measure | Observed result |
| --- | --- |
| Earliest archive-corroborated or document-verified date | 2010-10-27 |
| Latest archive-corroborated or document-verified date | 2026-11-17 |
| Original-document verified dates | 4; 2010-10-27 to 2025-05-29 |
| Unique observed official archive IDs (year + number) | 668; incomplete archive, not the total historical decision count |
| Archive dates without ID | 274 |
| Candidate ledger dates | 1374 |
| Conflict dates, quarantined | 42 |

Verification: `document_verified` requires an original government PDF and recorded review. `archive_corroborated` means government HTML and IPT agree on a dated price; it does not authenticate an original decision or its publication time. Taqtek shares ministry lineage and cannot independently establish official truth. No source-labelled date is invented as an effective date.

## Source coverage

| Source | Observations | Unique valid dates | Earliest | Latest | Age days | Stale |
| --- | ---: | ---: | --- | --- | ---: | --- |
| ipt | 1314 | 1310 | 2008-01-02 | 2026-11-20 | 4 | False |
| taqtek | 917 | 917 | 2010-10-27 | 2026-11-20 | 4 | False |
| ministry | 946 | 914 | 2010-10-27 | 2026-11-17 | 7 | False |
| official_document | 4 | 4 | 2010-10-27 | 2025-05-29 | 544 | True |
| manual | 21 | 17 | 2026-01-16 | 2026-11-13 | 11 | True |
| thefuelprice | 2 | 2 | 2026-11-17 | 2026-11-22 | 2 | False |
| totalenergies | 1 | 1 | 2026-11-20 | 2026-11-20 | 4 | False |

Latest successful IPT import parsed 1315 original rows. Semantic observations and unique dates differ because all raw row occurrences, including duplicates and same-day alternatives, are retained in `sightings`.

## Retrieved examples

| Source-labelled date | Price LBP/20 L | Verification | Official effective date |
| --- | ---: | --- | --- |
| 2008-01-02 | 24100 | supplier_observed | unknown |
| 2010-10-27 | 33300 | document_verified | 2010-10-27 |
| 2025-05-29 | 1489000 | document_verified | 2025-05-29 |
| 2026-11-17 | 2343000 | archive_corroborated | unknown |
| 2026-11-20 | 2291000 | provisional_corroborated | unknown |

## Gaps and frequency

169 unusually long observed intervals are listed in [gap_candidates.csv](gap_candidates.csv). The threshold is greater than max(5 days, 1.5 × that source/year median interval). These are investigation candidates, not fabricated missing decision dates. Cross-source absent dates are listed in [cross_source_missing_dates.csv](cross_source_missing_dates.csv). A source gap is not proof of a nonpublication.

Observed frequency by year is in [frequency_by_year.csv](frequency_by_year.csv); the ledger is a decision-event series, not a generated daily panel. No forward fill or interpolation is applied. Regime labels are provisional research buckets, not verified tax/FX boundaries.

## Conflicts and limitations

Status counts: `{"archive_corroborated": 810, "conflict": 42, "document_verified": 4, "government_archive": 58, "provisional_corroborated": 3, "supplementary_observed": 1, "supplier_observed": 456}`. All contradictory valid source values remain in the immutable observation table; disputed dates have null canonical prices. [conflicting_observations.csv](conflicting_observations.csv) links them to observation IDs.

Unknown publication timestamps: 3205 observations. Unknown official effective dates: 3201. Original Excel/HTML dates have no invented midnight release timestamp. Retrieval is stored in UTC and rendered with Asia/Beirut rules.

Changes in the export are relative to the previous eligible verified record, with its date and an explicit basis. They are not asserted to be changes from the immediately preceding official decision. Sparse verified history cannot establish that predecessor.

Source/revision priority: original decision 1, ministry HTML 2, IPT 3, Taqtek 4, unverified manual 5. Priority never silently settles a contradiction. A reviewed resolution appends an audit event and a ledger version. Same-day multiple official decisions remain ambiguous without decision IDs/times; they are not guessed or collapsed into a verified event sequence.

## Model readiness

Adequate for source reconciliation and exploratory target analysis. Not ready for an institutional as-of forecasting backtest: effective/release times, unresolved conflicts, coverage and regimes need review.

See [source assessment](../research/data_source_assessment.md), [assumptions](../research/verified_assumptions.md) and [update instructions](../docs/data_updates.md).

Raw integrity: 0 missing or hash-mismatched captured files. `date_alignment_review` records are excluded from verified exports pending review of inconsistent source weekday/date labels.

## Longest IPT intervals to investigate

| Previous observation | Next observation | Elapsed days |
| --- | --- | ---: |
| 2021-05-19 | 2021-06-09 | 21 |
| 2020-05-13 | 2020-05-28 | 15 |
| 2021-08-11 | 2021-08-24 | 13 |
| 2025-04-03 | 2025-04-15 | 12 |
| 2024-11-29 | 2024-12-10 | 11 |
