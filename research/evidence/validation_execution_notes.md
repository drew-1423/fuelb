# Part 6 execution notes

11 November 2026. Protocol frozen before constructing/scoring the Part 6 challenge. Prior Part 4 exposure and Part 5 development results were already known and disclosed. No challenge-driven hyperparameter or model change was made.

The first research execution finished all prediction, evaluation, comparison and metric output, then failed its final ledger integrity report. The cause was serialization of negative floating-point zero: SQLite stores `-0.0` as `0.0`, whereas the first hashing implementation distinguished their JSON encodings. Sixty-two affected rows were verified against the exact original signed-zero encoding. A normalization fix prevents new occurrences; the immutable original rows and hashes remain intact. A regression test covers this case.

The completion/approval reports were resumed from the preserved prediction tables; no model refit or new scoring period was performed to address this engineering defect. Additional changes add prospective research mode, matching/date checks, tests, reports and documentation. They do not alter Part 5 models or Part 6 numerical predictions. Fresh-holdout and strict historical sample sizes remain zero.

No separate external reviewer or sub-agent was used. The review uses distinct equations, evidence tables, frozen source/model checks and explicit findings, while disclosing the same-agent limitation.
