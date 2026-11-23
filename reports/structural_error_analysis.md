# Part 4 error analysis

The accounting residuals are 3.30, -3.30 and -1.60 LBP/20 L for the three dated annexes. The independently printed pretax and VAT lines reconcile exactly; tiny final differences are compatible with rounding but do not prove a legal rounding rule. Larger upstream USD-to-LBP discrepancies remain unresolved. No adjustment was fitted to force those currencies to agree.

The following largest errors belong to the validation-selected champions in their untouched chronological test periods. Historical records and units are real; release-delay/vintage assumptions prevent treating these as deployable forecast results. A large residual does not identify its cause. Missing FX changes, tax/margin events, regional product spreads, source-date misalignment and administrative windows are candidate explanations requiring additional evidence.

| Date | Segment | Champion | Actual | Estimate | Signed error | Target evidence |
|---|---|---|---|---|---|---|
| 2025-04-25 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,339,000.00 | 1,367,969.73 | 28,969.73 | archive_corroborated |
| 2025-03-07 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,439,000.00 | 1,467,609.21 | 28,609.21 | archive_corroborated |
| 2025-04-22 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,365,000.00 | 1,392,127.11 | 27,127.11 | archive_corroborated |
| 2025-04-08 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,431,000.00 | 1,410,937.46 | -20,062.54 | government_archive |
| 2025-05-20 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,370,000.00 | 1,350,333.68 | -19,666.32 | archive_corroborated |
| 2025-03-11 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,419,000.00 | 1,438,261.09 | 19,261.09 | archive_corroborated |
| 2025-04-03 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,412,000.00 | 1,393,147.56 | -18,852.44 | archive_corroborated |
| 2025-03-28 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,396,000.00 | 1,378,914.92 | -17,085.08 | government_archive |
| 2025-03-14 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,397,000.00 | 1,413,508.54 | 16,508.54 | archive_corroborated |
| 2025-04-11 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,412,000.00 | 1,427,978.15 | 15,978.15 | government_archive |
| 2025-05-02 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,348,000.00 | 1,333,936.00 | -14,064.00 | archive_corroborated |
| 2025-04-15 | recent_pre_fiscal | asymmetric:brent_spot:w20:lag14 | 1,398,000.00 | 1,411,651.26 | 13,651.26 | archive_corroborated |

Quality-stratified champion metrics are saved in `structural/champion_metrics_by_target_quality.csv`. All family test metrics, including failed challengers, remain in `structural/test_metrics.csv`. No outlier was deleted based on its fitted error. Conflicts were excluded by the frozen input-quality rule before fitting.

## Limitations

- Only three nonconsecutive annexes have component-level review; they cannot quantify genuine next-decision structural accuracy.
- No licensed Med quotation history or documented current wholesale-to-goods uplift exists in the database.
- No full official pricing FX series exists; regime splitting cannot remove within-segment FX confounding.
- Historical targets are mostly archive corroboration, not original document verification. Missing timestamps prevent strict label availability checks.
- Sparse recent official history makes the final recent test particularly small. Do not present its percentages without n.
- The final period is now consumed for this experiment. New model selection must use new validation data or a separately declared protocol, not repeatedly optimize this holdout.
- Crisis and later fiscal regimes are deliberately unevaluated; performance cannot be extrapolated to them.

No current official price, government formula, benchmark quotation or probability was fabricated.
