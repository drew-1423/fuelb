# Unresolved research questions and data limitations

As of Part 1, 10 November 2026. Track resolutions with the original source, decision date, effective date, known-at timestamp and reviewer explanation.

| Priority | Question / limitation | Evidence needed / implication |
| --- | --- | --- |
| Critical | Current exact retail benchmark, window, cutoff and weights | Current MOEW/DGO methodology and dated annex; no hard-coded Platts window until verified |
| Critical | Current component FX, taxes, margins and rounding | Original decisions and amendments; distinguish announced proposals from law |
| Critical | Authoritative historical target and amendments | Signed/official decision PDFs reconciled to supplier records; archive UI may contain errors |
| Critical | Publication time versus effective date | Decision text and archived announcement timestamp; date-only exports do not prove availability |
| High | Incomplete government archive and duplicates within IPT | Preserve conflicts, identify authentic amendments, compare date coverage; absent rows are not proof of no decisions |
| High | Exact subsidy transitions / FX regime boundaries | Dated product-specific legal records; provisional labels cannot be economic truth |
| High | Historic Platts data licence and availability | Authorized provider history, exact symbol/specifications and revision policy; crude proxies incur basis risk |
| High | DGO PDF digit and column extraction errors | Inspect document images and reconcile totals; deny automatic verification on OCR alone |
| Medium | Publication cadence, holidays and exceptional updates | Observed decision ledger with known gaps; model event timing separately |
| Medium | Site access, export stability and redistribution terms | Retain source policy snapshots; manual import fallback if blocked; public availability alone is not a licence |

Part 1 gate: research and architecture exist; data ingestion can proceed. This is not approval of model accuracy or a claim that the current official formula is known. Part 2 results belong in `reports/data_quality.md` and `docs/data_updates.md`.

## Part 3 additions

- No licensed AAWZA00/AAWZB00, Eurobob, ICE contract history or Mediterranean clean-product freight history has been obtained. Provider pricing and historical delivery latency require actual quotes/agreements.
- The free series are genuine crude, U.S. product/supply data or European consumer-price proxies; none establishes Lebanon's current refined benchmark formula.
- Current public workbooks are revised histories without original per-observation release clocks. Strict historical snapshots remain sparse/empty until original vintage evidence is supplied. Historical lag comparisons are descriptive and explicitly not backtests.
- H.10 customizable DDP retirement is announced in November 2026; the complete XML release remains accessible during this run. Preserve a manual import path and monitor adapter failures when explicitly scheduled.
- FRED/ALFRED are excluded because current use restrictions affect this software project; the original Federal Reserve supplies FX instead. No API key or publisher permission was fabricated.
- Calendar absence candidates include holidays. Actual historical market sessions, Lebanese holidays/exceptional decisions and announcement times require primary evidence before event-time forecasting validation.

## Part 4 additions

1. Explain the printed USD/FX/LBP goods discrepancies in the 12 May 2023 and 29 May 2025 annexes; obtain exact upstream component precision and intermediate rounding.
2. Obtain the station-bank fee base/rounding and separately identifiable import/distribution margin; printed aggregate goods cost cannot identify them statistically without genuine benchmark/FX histories.
3. Confirm the current legal status, effective dates and VAT treatment of the 2025/2026 fiscal changes, including any actual repeal after the September 2026 proposal.
4. Obtain enough consecutive original annexes and original information-time records to measure structural forecast accuracy. The three accounting checks are insufficient.
5. Investigate training-only instability in the recent transmission segment; the CUSUM diagnostic is suggestive, not a dated policy finding. No reliable increase/decrease asymmetry was established by the fixed training specification.
6. The recent validation winner barely improves on persistence in 19 held-out observations and its 90% interval covers 84.2%. More current, prospectively captured data are required before deployment or confident lag claims.

## Part 5 additions

1. Independently assess model improvements on identical origins with dependence-aware uncertainty and multiple-comparison controls. Recent next-decision tree comparisons have only 11 cases; headline older-regime gains do not establish current transportability.
2. Resolve short-calendar interval undercoverage, phase selection from deterministic thinning and zero-width residual bands. Keep the failed development evidence; do not tune on the same scored outcomes and call it independent calibration.
3. Obtain contiguous recent sequences sufficient for SARIMAX, and more distinct recent 30-day base decisions before fitting tree models at the frozen threshold.
4. Collect prospective news text vintages and verify source completeness. EIA-only coverage is partial, Lebanese regulatory clocks are missing, and OPEC database-use restrictions limit bulk ingestion. Historical news improvement cannot yet be measured.
5. Establish current announcement timing and official effective-price anchors before a live calendar target or next-decision detector is certified. The historical witness rule is retrospective quality selection, not a live schedule model.
6. Part 6 must disclose Part 4's prior exposure to its nominal reserved periods. Stronger confirmation needs prospective evidence or a genuinely new holdout, not a production winner selected from Part 5 development tables.

## Part 6 dispositions

- Production approval is rejected for next decision, seven days and thirty days. Strict historical forecasts and fresh final holdout outcomes both number zero. Original availability/official timing and current-policy work remain blocking.
- The added last-change baseline leads the primary target on common origins in both exposed challenge regimes; complexity has not earned promotion. Recent horizon samples are particularly small and dependent.
- Confirmed calibration selection bias: recent three-day zero-change fraction rises from 18.25% in eligible prior errors to 90% in the retained calibration sample. Repair requires a new development protocol and fresh assessment, not retrospective replacement of scored intervals.
- The local forecast ledger now preserves predictions, source snapshots and separate corrected actuals/evaluations. Current entries abstain; complete decision coverage and exact clocks are needed before automated official matching.
- Additional external/organizationally independent review remains necessary; the current agent performed the separate code/equation review. See `../reports/model_validation_report.md` for evidence, severity and disposition.
