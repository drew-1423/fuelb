# Part 2 validation record

Executed on 10 November 2026, native Apple Silicon macOS, CPython 3.13.12. The resolved data/test dependencies are in `requirements-data-lock.txt`.

- Real collection: IPT public XLSX export, 1,312 parsed rows; ministry public search, 940 rows across 47 exposed pages; Taqtek embedded LBP series, 914 observations. Original responses are captured in SQLite with content hashes and files.
- Offline replay: all 3,166 source rows from the successful captures re-parsed through the implemented adapters. Added zero semantic observations and zero unchanged ledger revisions.
- Three original official PDF documents were downloaded and visually reviewed before importing their explicit transcriptions. Their source URLs, review locators and evidence hashes are retained.
- Automated tests: **28 passed**. See `tests.txt` and `tests.xml`. Coverage includes validation/units, timezone handling, date alignment, duplicate imports, revisions, conflict resolution, stale resolutions after new evidence, transactions, source parsers, raw-file tampering, access denial, robots rules, stale data and exports.
- SQLite integrity and foreign-key checks passed. All captured raw files matched their stored SHA-256 hashes. Required deliverables, local document links and exported date uniqueness passed.

Two initial discovery runs stopped when the IPT URL was supplied by script and the ministry exposed pagination. Those failed runs remain in the audit history. Corrected collectors then completed successfully; no access-control bypass was used.

This validation establishes operation of the data pipeline, not completeness of historical official decisions, source correctness, a current pricing formula or forecasting accuracy. See `data_quality.md` for the remaining limitations.
