# Structural model operations — Part 4

## Install and reproduce

Native Apple Silicon environment: CPython 3.13.12. The executed environment is pinned in `requirements-structural-lock.txt`; no GPU, paid-data credentials or forecasting service is required.

```bash
.venv/bin/python -m pip install -r requirements-structural-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/fuel-structure reconcile
.venv/bin/fuel-structure research
.venv/bin/fuel-structure report
.venv/bin/python -m pytest Tests/fuel -q
```

`reconcile` verifies original PDF hashes, calculates three dated annexes, and regenerates the parameter table and component exports. It does not alter the Lebanese ledger. `research` runs the declared chronological protocol on existing SQLite data, saves model selection before evaluating final dates, and produces research-only estimates. `report` writes Markdown analysis and PNG/SVG charts. All three commands operate offline. Source refresh remains in the Part 2/3 collectors.

`config/structural_research.json` is hash-bound to `research/evidence/structural_protocol_freeze.json`. The final holdout has now been evaluated. Reproduction retains the original selection artifact and rejects changed selections. Do not edit this protocol to optimize the consumed test results; declare a separate research experiment and a new evaluation period when adding models/data.

## Cost engine

```bash
.venv/bin/fuel-structure price config/structural_scenario_before_vat.json \
  --output data/exports/structural/scenario_before_vat.json
.venv/bin/fuel-structure price config/structural_scenario_after_vat.json \
  --output data/exports/structural/scenario_after_vat.json
```

These files are **illustrative sensitivity exercises**, using the actual last collected U.S. NYH quote carried forward, hypothetical import-cost bounds, and a May 2025 domestic-cost scaffold. Their dated origins are explicit. They do not estimate the next official decision or establish today's FX, tax or margins. The two examples expose the difference between a hypothetical charge inside/outside the VAT base. No probability is assigned. The current project setting `forecasting.enabled = false` remains appropriate.

Python API: `from lebanon_fuel.structural.engine import price`; pass a JSON-compatible dict, receive decimal-string amounts and evidence metadata. Fields:

- `mode`: `reconciliation`, `scenario` or `as_of`; `origin` must include a timezone; `effective_date` is the Asia/Beirut calendar date.
- Either `goods_lbp_kl` (recorded subtotal), **or** `benchmark`, `fx`, `freight_usd_kl`, `other_import_usd_kl`; never both routes. The benchmark identifies product, averaging/window description and FOB/CIF basis. USD/mt requires explicit density in kg/L. USD/bbl, USD/kl and USD/L are also supported.
- `costs`: uniquely named LBP/kl charges with explicit `taxable` booleans; `goods_taxable`; `vat` as a fraction. This engine adds supplied costs; the caller must disclose incomplete coverage in `coverage_note`. It cannot infer omitted import/distribution margins or legal tax bases.
- Every numeric parameter has `value`, `unit`, `status`, `valid_from`, `valid_to`, `known_at`, `evidence`, and `note`. Status is `verified_document`, `estimated` or `scenario`. Unknown is missing/null and fails; zero requires an explicit explanation. Evidence status describes the supplied provenance, not automatic legal authentication by the software.
- `rounding: null` returns unrounded arithmetic. The only implemented rounding option is an explicitly hypothetical positive increment with half-up handling; no legal rule is built in.
- Optional per-parameter `low`/`high` gives a monotone input-bound range, holding unbounded inputs fixed. It is neither a calibrated interval nor a promise to cover policy or basis shocks.

The engine validates nonnegative finite numbers, units, dates, parameter availability and CIF freight double counting. Forecast/scenario mode refuses stale validity and parameters known only after the origin. `as_of` rejects scenario values. Reconciliation permits later evidence retrieval and labels that mode. Negative credits, multiple tax layers, percentage charges on dynamically nested bases and weighted subsidy FX are not silently approximated: first supply an evidenced, correctly normalized subtotal or extend the accounting engine with separately reviewed rules.

## Files and lineage

| Artifact | Purpose |
|---|---|
| `data/manual/structural_annexes.json` | Original-document component transcription, URL/hash/capture and date scope |
| `research/structural_pricing_equation.md` | Equation, units, evidence boundaries, drivers and sensitivities |
| `research/structural_parameters.csv` | Dated verified parameter values and metadata; not a current schedule |
| `research/estimated_transmission_parameters.csv` | Last saved fit coefficients for each family and regime; explicitly estimated |
| `research/structural_transmission.md` | Statistical equations, selected windows, lag interpretation and diagnostic findings |
| `research/regulatory_regimes.md` | Verified events, reported events, provisional boundaries and exclusions |
| `data/exports/structural/annex_reconstructions.csv` | Three arithmetic checks; not historical forecasts |
| `data/exports/structural/research_design_matrix.csv` | 433 real input/target pairs with observation/capture/revision IDs |
| `data/exports/structural/historical_proxy_predictions_RESEARCH_ONLY.csv` | All selected-family final-test predictions, intervals and fitted coefficients |
| `reports/structural/validation_grid.csv` | Every validation candidate, including poor results |
| `reports/structural/selection_frozen_before_test.json` | Validation-only choices saved before test calculation |
| `reports/structural/run_manifest.json` | Counts, protocol/data hash, timing limits, results and available proxy inputs |
| `reports/structural_validation.md` | Chronological metrics and calibration results |
| `reports/structural_error_analysis.md` | Largest errors, evidence limitations and unresolved explanations |
| `reports/structural/historical_reconstruction.png` | Exportable historical comparison and error chart |
| `reports/structural_audit.md` | Executed checks, material findings and completion status |

The original data collectors and observations are preserved. The newly reviewed 2023 annex is not automatically promoted in the Part 2 target ledger; its component review has its own artifact. Training uses the pre-existing ledger evidence statuses consistently.

## Readiness

Completed: dated accounting engine, explicit parameter provenance, scenario ranges, independent recomputation checks, chronological proxy comparisons and documented limitations. The review was performed by the implementing agent using the auditor skill's criteria; it is not an independent external audit.

Still required for operational pricing: a current complete official schedule; verified retail assessment/window/cutoff; licensed refined assessments and freight where needed; official goods FX history; target publication/effective timestamps; original market vintages; and a genuinely new prospective validation sample. No live forecast or next-stage implementation is enabled.
