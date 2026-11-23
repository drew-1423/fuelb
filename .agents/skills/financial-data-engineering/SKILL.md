---
name: financial-data-engineering
description: Build or maintain reliable pipelines for Lebanese fuel-price observations and related commodity and financial-market data.
---

# Financial Data Engineering

Use this skill to collect, normalize, validate, and store historical fuel-price and market data for this project.

- Keep source records and normalized observations traceable to a source URL/document, retrieval timestamp, source publication/effective date, product or series, and any transformation. Retain original values and units; never silently overwrite source observations or revisions.
- Normalize dates, timezone, frequency, product grade, currency, quotation unit, and price semantics (for example pump price versus wholesale benchmark) in explicit fields. Preserve source precision and record any conversion formula and inputs.
- Treat IPT and official Lebanese price decisions as separate sources until matched. Reconcile overlaps and disagreement without silently selecting one; distinguish a weekly listed price from its effective date when evidence permits.
- Make ingestion repeatable and idempotent. Validate types, units, date ordering, duplicates, plausible changes, gaps, and source freshness. Keep raw capture separate from cleaned/derived data so transformations can be rerun.
- Mark missing, revised, estimated, or imputed values explicitly with method and provenance. Do not invent historical values or forward-fill a price series merely to make it continuous.
- For market data, capture instrument/benchmark definition, venue or publisher, currency, units, timestamp convention, and licensing/access constraints. Align frequencies only through documented transformations.

Activate for source ingestion, data schemas, ETL, storage, reconciliation, and data-quality work supporting this forecast. For discovering IPT site exports or browser-only archives, use `fuel-price-source-investigation`.
