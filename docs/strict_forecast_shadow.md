# Next official 95-octane decision

The shadow experiment estimates the change in the next official announced price, in LBP per 20 L. It stores the resulting price and time in Asia/Beirut. Next-decision order uses publication. The prevailing-price anchor uses publication and effectiveness. A projected announcement date remains a date estimate.

## Source status on 16 November 2026

The Ministry's public price search returned four records for 1 October through 16 November. All four were already in the local ledger. The newest was 10 November, 2,445,000 LBP/20 L. The search returned no links to original decisions and supplied no publication or effective clocks. [Preserved archive capture and hash](../research/evidence/ministry_probe_20261116/manifest.json).

IPT lists 2,391,000 LBP/20 L on 13 November. That price remains supplier-only in the local ledger. The original 13 November Ministry schedule or a government-hosted copy with the price and usable timing evidence is still needed. Agreement among supplier and news reports cannot establish an official decision sequence. [IPT price page](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices) · [Ministry price archive](https://energyandwater.gov.lb/ar/prices).

See the [audit](forecast_readiness_audit_2026-11-16.md) and [dated assumptions](../research/verified_assumptions.md) for the 2021 subsidy explanation, the 2023 and 2025 cost annexes, and gaps in current pricing FX, duties, freight, margins and rounding. The four-close structural proxy remains exploratory. No licensed Mediterranean series or current upstream formula was verified in this phase.

## Capture and settle

Use the ordinary collectors and the [document import workflow](data_updates.md) to add an original document and reviewed transcription. Review the issuer, grade, units, decision identifier, source date, publication, effectiveness and any amendments. Capture on an ongoing schedule. Use the document import time or a supported older capture record for availability. Keep the original evidence and the exact revision ID.

Create a settlement manifest with these fields, using only reviewed values:

| Field | Content |
| --- | --- |
| `reviewer`, `clock_evidence_url` | Named reviewer and evidence link. |
| `outcomes[]` | Each entry has `source_observation_id`, `official_decision_key`, `price_lbp_20l`, `available_at`, and `source_revision_id` for a linked shadow anchor. |
| Publication/effectiveness | `publication_timestamp` and `effective_timestamp` for documented exact clocks. `publication_date` and `effective_date` support documented date-only timing and require the linked raw document. A documented date in the original observation can supply the corresponding date. |
| `coverage` | `certified: true`, `evidence_url`, `from` and `through`, with explicit offsets and a reviewed complete sequence in that interval. When gaps are unresolved, leave coverage unapproved. |
| `forecast_ids` | Optional IDs to match now. The configured operations cycle can also check the saved candidates when new reviews arrive. |

```bash
cd "/Users/andrew/MyApp_macOS/fuel forecast"
.venv/bin/python -m lebanon_fuel.validation.cli settle --manifest "/absolute/path/to/reviewed-decisions.json"
```

The matcher checks the whole possible Beirut day for date-only timing. A date that could straddle the actual forecast creation or compete with another decision leaves the case pending. A timing correction outside the possible target window leaves unrelated scores eligible. Shadow settlement checks the recorded anchor against the reviewed prevailing price at issue time. The ledger appends outcomes, scores and review attempts.

## Freeze, issue, replay and report

Use one writable manifest path per experiment. The existing 2026 model artifacts are frozen research candidates, trained on conditional archival targets. The freeze also fits the historical median and simple Brent references using matured development rows before the fixed cutoff. The new evidence comes from forecasts genuinely issued after the freeze and settled against reviewed targets.

```bash
cd "/Users/andrew/MyApp_macOS/fuel forecast"
.venv/bin/python -m lebanon_fuel.validation.cli freeze-shadow --manifest "data/manual/next_decision_shadow.json"
.venv/bin/python -m lebanon_fuel.validation.cli issue-shadow --manifest "data/manual/next_decision_shadow.json"
.venv/bin/python -m lebanon_fuel.validation.cli report-shadow --manifest "data/manual/next_decision_shadow.json"
```

The freeze requires the local development CSV, which the GitHub repository excludes for size. Reuse the existing freeze manifest on the exact reviewed code and dependency versions. To inspect a previous saved origin, run `replay-shadow --manifest <path> --origin <saved timezone-aware origin>`. Replay reconstructs captured domestic revisions and market vintages before that origin using the same feature path as issuance. The replay returns evidence separately from prospectively recorded scores.

Optional scheduling uses the existing local or GitHub refresh workflow. Set `[shadow].frozen_manifest` in `config/automation.toml` to the reviewed path and `[settlement].reviewed_manifest` to the approved coverage manifest. Configure a cloud run only after checking that its runtime, signed-off artifacts and reviewed evidence are available there. Operations then logs each candidate independently without changing the dashboard’s existing tiers. Maintain an external or private archive for any licensed or nonpublic data.

## Release decision

Production approval is withheld. Keep the existing 20-decision floor and aim for at least 50 scored decisions before substantive review. Agree on issuance-rate and paired-error limits before examining the final prospective results. Count one case per actual decision and compare candidates on the same recorded origins. Report misses as well as model availability. The report separates fresh and lagged-market cases and keeps candidate calibration in shadow until the exact model and data release passes independent review.

| Horizon | Current status |
| --- | --- |
| Next official decision | 4 conditional 2026 selection origins. Strict shadow issue, replay and scoring implemented. Zero settled shadow cases. |
| Next two official decisions | 2 conditional selection origins. Strict validation pending. |
| Next four official decisions | 0 conditional selection origins. Strict validation pending. |
| Day 1 | 13 conditional selection origins, some sharing a decision. Strict effective-price validation pending. |
| Day 3 | 9 conditional selection origins. Strict effective-price validation pending. |
| Day 7 | 1 conditional selection origin. Strict effective-price validation pending. |
| Day 14 | 0 conditional selection origins. Strict effective-price validation pending. |
| Day 30 | 0 conditional selection origins. Conditional scenarios until separate strict validation supports a forecast. |

The official structural candidate remains unavailable pending verified pricing inputs. The first release compares persistence, last change, historical median, Brent, the refined-product proxy and the existing hybrid. None is approved by the shadow tooling.

## First real run

On 16 November at 16:24 Beirut, the local experiment `a965c880296590a856c52fa5887de38b409009eacee24fd2742f029ddda8b44c` froze the reference models using 145 matured conditional development rows from 145 base decisions. Its first batch appended seven candidate abstentions, forecast IDs 45188–45194. The November 13 supplier-only record blocked the base price. The strict replay reproduced all seven outputs, the read-only ledger hash-chain check passed, and there are zero scored shadow outcomes. The test suite passed 235 tests with 7 existing pandas deprecation warnings.

## Provisional forecasts from two price sources

When the latest valid IPT record agrees with TotalEnergies or Taqtek on the gasoline 95 price and source date, and there is no conflicting valid record for that date, reconciliation records a provisional price with the matching source links. TotalEnergies' public price board is linked from its fuel-price page; the collector reads the settled SP95 value and preserves both raw pages. TheFuelPrice reports a dated 20-liter equivalent price but often updates later, so its current row is stored as supplementary evidence and never alone authorizes a provisional forecast. This does not establish an official decision or effective date.

The public forecast pipeline can use that price for an explicitly labeled research point estimate, subject to the normal freshness and market gates. If quantitative inputs fail, persistence can use the same provisional anchor. Prediction intervals and probabilities are withheld on this route because its calibration has not been established. Strict shadow scoring and production eligibility still require reviewed official evidence. If the source code changes, freeze a new shadow manifest before issuing under it.
