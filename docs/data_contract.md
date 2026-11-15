# Data contract and verification policy

Schema: [schema.sql](../src/lebanon_fuel/storage/schema.sql). Source priority is a provenance rule, not permission to erase disagreement.

## Tables

`sources` fixes source identity, lineage and priority. `collection_runs` records success/failure and actual parsed counts. `captures` records original response bytes by SHA-256, retrieval instant in UTC, public URL, source, status/MIME, safe headers and form parameters. A response or local import is captured even when parsing fails. HTTP Last-Modified is retained as a header; it is never promoted to a price-publication timestamp.

`observations` stores literal row JSON, parsed 95-octane LBP/20 L price, source-labelled date, date role, official effective date if evidenced, publication date/time if evidenced, first retrieval timestamp, units, decision number, validation issues and document-review status. Rows are append-only. Semantic identity excludes retrieval time and source row position so re-imports do not duplicate observations. `sightings` preserves every row occurrence within every capture, including exact duplicate export rows. Different values on one date remain distinct observations.

`resolutions` appends reviewer, explanation, chosen observation, evidence and the observation set reviewed. New evidence makes a previous resolution stale. `decision_versions` appends reconciled payloads with prior version ID and creation timestamp. `current_decisions` selects the latest version per source-labelled date; `price_history` exposes the required fields for querying. Historical versions remain queryable. No daily values or missing decision IDs are manufactured.

## Price and date semantics

- Positive integer nominal LBP per 20 L; source raw value and unit retained. No automatic conversion from USD/gallons/liters is accepted.
- A date-only label is an ISO calendar date in `source_timezone=Asia/Beirut`. It is never an invented midnight timestamp. Unknown publication/effective fields remain SQL NULL.
- A known publication instant must have an explicit UTC offset; the stored value is UTC and converts to Beirut through IANA zone rules, including historical DST.
- `source_date` identifies a source-labelled decision candidate. An explicitly different official effective date is retained and flagged. Such records need timeline reconciliation before being used as an effective-price panel.
- `previous_verified_price/date` means the preceding stored eligible verified record. `absolute_price_change` and `percentage_price_change` compare against that reference. They do not certify the immediate previous official decision; the export repeats `change_basis` to prevent misinterpretation.
- Regime columns are explicit provisional research buckets, not a verified legal timeline. Nominal levels remain unscaled. Downstream work must choose comparable regimes and account for currency/subsidy changes.

## Status definitions

| Status | Meaning / eligibility |
| --- | --- |
| `document_verified` | Original government PDF reviewed with price/product/unit/date locator and evidence hash; uncontested or explicitly resolved. Eligible verified record, but web release time may remain unknown. |
| `archive_corroborated` | Ministry HTML and IPT agree; no contrary valid observation. Eligible archive verification, explicitly weaker than original-document review. |
| `government_archive` | Government HTML only. Not independently verified. |
| `date_alignment_review` | Government weekday/date labels disagree. Excluded from verified export until resolved. |
| `supplier_observed` / `supplementary_observed` | Direct source observation. Not official verification. |
| `reviewed_resolution` | Human/agent review chose an existing non-document observation with rationale. Not automatically upgraded to document verification. |
| `conflict` | Different valid prices or unresolved evidence; canonical price NULL. Could include same-day successive official decisions, not necessarily source error. |
| `invalid` | Rejected normalization, price/unit/date or verification claim; original bytes/row retained. |

Taqtek derives much history from the ministry, so its agreement is not a third independent official verification. Exactly matching rows and duplicate decision numbers are flagged separately from contradictory values. The dataset cannot certify the total number of historical official decisions: incomplete archive coverage, absent IDs and multiple decisions per date prevent that claim.

## Quality outputs

Reports expose cross-source missing dates, unusually long observed intervals, annual cadence/weekday distributions, within-source duplicates/conflicts, invalid price/unit/date entries, source freshness and missing timing evidence. A cadence-based gap is a research lead rather than an assertion of an unobserved official decision. A 25% observed price step is flagged for review and never automatically corrected. Contested records remain quarantined until supported resolution.

Raw captures and SQLite audit rows are part of the dataset and should travel together. Historical source availability is not reconstructed by the current retrieval timestamp. A real-time backtest must use documented availability assumptions or a historical archive of releases and vintages; current snapshots alone are insufficient.
