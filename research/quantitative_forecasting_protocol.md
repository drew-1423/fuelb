# Part 5 research protocol and limitations

Research run: 11 November 2026. Verification status terminology follows `verified_assumptions.md`.

## Inputs reviewed

Parts 1–4 research, SQLite ledger/market observations, original annex transcriptions, policy strata, structural engine, freeze manifests and evaluation outputs were inspected before this implementation. Primary evidence remains linked in `verified_assumptions.md`, `international_market_sources.md` and `structural_pricing_equation.md`; no formula parameter changed because a regression fitted well.

| Statement | Status / evidence |
| --- | --- |
| Exact current official formula, benchmark window and component policy history are incomplete | Unresolved; original-document evidence register and Part 4 parameter table |
| Original historical release instants/vintages are absent for the collected market histories | Observed database limitation; Part 3 strict snapshot results |
| Source-date price records exist, but complete official decision sequence and effective instants are unproven | Observed limitation; Part 2 quality report and ledger statuses |
| Three annex calculations reconcile closely | Calculated arithmetic only; Part 4 report. Not a substitute for forecast accuracy. |
| Sample sizes and scores in Part 5 | Calculated from actual data exports and frozen model runs; `reports/forecasting/` |
| Twenty-quote product window, positive transmission, flat future market and constant policy for proxy B | Research assumptions; not official rules |
| Historical label availability at the next local midnight | Explicit research assumption; no source publication timestamp is overwritten |
| Data support live/current calibrated numerical predictions | **Not established**; current gates abstain |

## Prespecified design

`config/forecasting_research.json` and `research/evidence/forecasting_protocol_freeze.json` establish development boundaries, horizons, candidate families, fold dates, regularization grid, tree capacity and sample thresholds before fitting. `forecasting_implementation_freeze.json` records algorithm details before the first fits. Small algorithmic choices are documented in the model guide. CPU training uses seed 20261111 and two threads for tree libraries.

All eight horizons are direct targets. Event horizons do not assume daily decisions; calendar horizons model a conditional prevailing price. Candidate records must have eligible government/corroborated/document status and all intervening records must remain valid. A 14-day maximum gap is a conservative archive-quality rule, not proof of completeness within 14 days. Calendar witnesses delay label availability; this is intentionally stricter than using the endpoint alone.

Nominal pre-crisis and recent pre-fiscal data are fitted separately. No pooling across the subsidy/FX crisis, 2025 fiscal shift or current 2026 policy. Announcement intervals, market observation units and timing assumptions remain explicit. Holidays are handled by available observations and gap guards, not by inventing quotes or announcements.

## Leakage limits

Chronological feature transforms, hyperparameter selection, fit labels, ensemble weights, directional calibration and prediction-interval residuals respect their assumed historical knowledge times. Maturity purging also covers overlapping multi-decision labels. Market histories are latest captured editions, however, and domestic archive revisions are not originally timestamped. Therefore the exercises remain retrospective latest-vintage development studies despite their chronological design. A long assumed delay does not cure revision leakage or establish an original vintage.

The raw target periods reserved from Part 5 were already examined in Part 4. No fresh untouched-test claim is permitted. Part 6 should document this history and use prospective captures or new held-out evidence for stronger confirmation. Testing several models/horizons/regimes creates selection multiplicity; an apparent best score is not proof of superior expected performance.

Calendar labels overlap, and several originate from the same base decision. Inverse-count training weights and unique-base sample gates reduce replication effects; they do not make errors independent. Nonoverlap interval thinning can change the calendar-phase mix. Observed older one-/three-day ensemble coverage is poor, and recent one-day intervals degenerate to zero width. Those failed results are retained, not repaired by tuning on their own outcomes. Calendar-phase-aware/block calibration is an unresolved methodological need for independent review.

## What improvement can mean here

Compare each candidate and baseline on identical eligible origins, within the same nominal regime and horizon. Report the full coverage denominator. For comparisons across multiple families use the exported common-origin intersection. Do not infer causation from predictive relationships, interpret β as an official FX rate, interpret a cross-region gasoline/crude spread as actual refining profit, or claim exact formula reconstruction.

The available B proxy is a new transparent transmission scenario anchored in Part 4 economic structure. The full Part 4 accounting engine is reused through a separate adapter and cannot be forecast-scored without complete dated inputs. Part 4's published proxy numbers use different origins and test periods, so they are not directly comparable to the Part 5 error table. A claim that advanced ML improves the actual official structural formula remains unsupported.

## Stage boundary

Part 5 demonstrates working model families on genuine historical observations, saved/reloaded artifacts, conditional historical outputs and explicit abstentions. It does not certify probabilities, choose a production winner, activate a scheduler or perform the independent Part 6 validation. The report lists promising candidates and failures to guide that next stage.
