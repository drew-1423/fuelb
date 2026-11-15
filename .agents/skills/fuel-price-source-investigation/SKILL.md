---
name: fuel-price-source-investigation
description: Find and assess public historical Lebanese gasoline prices and export options on IPT or official sources, including browser-visible records.
---

# Fuel Price Source Investigation

Use this skill when the task is to locate, inspect, or extract historical Lebanese fuel-price records, especially from IPT's public website or government publications.

- Start with the site's public navigation, search, downloadable files, and visible export controls. Use authorized browser automation only within accessible public pages and controls. Do not bypass authentication, access controls, rate limits, or other technical restrictions; stop and report the limit if access is blocked.
- Record where each observation came from and how it was obtained: page/document URL, visible label or table context, retrieval timestamp, stated publication date, stated effective date, product, unit, and any export parameters. Preserve source files or raw page observations unchanged when project storage permits.
- Inspect export coverage, date range, granularity, timezone, units, product naming, duplicate rows, revisions, and gaps. Compare a sample of exported values with the visible source before relying on the export.
- Keep literal source values separate from parsed/normalized values. Document parsing and unit conversions; retain ambiguous labels and conflicting records for follow-up rather than guessing.
- Report gaps and inaccessible periods plainly. Do not interpolate, carry prices forward, infer an effective date from a crawl date, or label an estimate as an observation.

Activate for source discovery and browser-based investigation. Once collection requirements are established, use `financial-data-engineering` for a repeatable ingestion and storage pipeline.
