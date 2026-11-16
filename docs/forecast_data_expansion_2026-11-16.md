# Expanded Lebanese gasoline backtest

## Data and forecast coverage

The research target is the change from one recorded Lebanese 95-octane price to the next, in LBP per 20 liters. The original source status and all live price decisions remain in the original database.

- [LebVote's all-history gasoline chart](https://leb-vote.com/stats/gasoline_95?range=all), captured at 19:01:07 UTC on November 16, 2026, exposed 293 dated LBP/20 L observations. LebVote identifies the Ministry via the National News Agency as its underlying source. The study added 106 exact IPT matches to the research cohort for May 12, 2023 through November 10, 2026, including 49 in 2026. Another 105 chart dates were already corroborated in the local ledger. Four disputed dates and 19 dates without IPT agreement were excluded as new evidence. Source dates alone cannot establish complete coverage, original publication time or official effective time. [IPT fuel prices](https://www.iptgroup.com.lb/ipt/en/our-stations/fuel-prices)
- The local prospective ledger had 12 complete refreshes since the sealed cutoff at the time of the study. Ten abstained at the domestic anchor gate. The other two issued Tier 2 estimates. No Tier 2 market failures were logged in that small set of completed local refreshes. Zero distinct official next-decision outcomes had settled. The public ledger can contain a different set of runs.
- The audited [Ministry price archive](https://energyandwater.gov.lb/ar/prices) and public [Taqtek price tables](https://taqteklb.com/en/prices/) have observable gaps. Taqtek shares Ministry lineage, so matching copies of a Ministry record do not establish additional independent publication evidence.

## Experiment and results

The research build requires three successive eligible observed dates for the previous-change comparison, with gaps of at most 14 calendar days. Conflicting or uncorroborated intervening records break the sequence. Forecasts are reconstructed from 03:00 Beirut on the day after the base source date. Targets mature at 03:00 Beirut on the day after their source date. These are research clocks. Model and feature selection use a chronological development walk-forward with labels that matured before each origin. Final fits exclude June–November evaluation labels. Market data are latest-vintage, use explicit assumed availability, and cannot reproduce historical releases with certainty.

The refitted Hybrid used **174 cases**. The deployed frozen Hybrid used **145**. The original validation report has four next-update observations. The expanded comparison has **20** paired cases with target dates from July 31 to November 10, 2026. Eighteen paths use at least one research-cohort price and two use only government-backed archive records. The period had already been examined in the project, so this is an exploratory comparison.

| Forecast | MAE · LBP/20 L | RMSE · LBP/20 L | Direction correct |
|---|---:|---:|---:|
| Current frozen Hybrid | 16,885 | 24,295 | 15 of 20 |
| Hybrid refit on expanded data | 16,996 | 24,255 | 17 of 20 |
| Compact ridge with EIA spot and the last domestic change | 19,846 | 25,448 | 16 of 20 |
| Repeat last change | 18,050 | 23,396 | 15 of 20 |
| No price change | 28,250 | 35,425 | 2 of 20 |

Direction treats a change within ±3,000 LBP as flat. The refit improved direction by two cases and slightly reduced RMSE. It increased MAE by 111 LBP. The current live artifact stays in place. The comparisons do not establish a reliable directional or price-error gain.

## Market input tests

- [EIA's RBOB Contract 1 history](https://www.eia.gov/dnav/pet/hist/EER_EPMRR_PE1_Y35NY_DPGD.htm) and its [public workbook](https://www.eia.gov/dnav/pet/hist_xls/EER_EPMRR_PE1_Y35NY_DPGd.xls), captured at 19:01:34 UTC on November 16, 2026, contain 4,609 settlements, including 226 within the project era. RBOB MAE was 11,172 LBP vs. 11,154 for the EIA gasoline spot variant on 18 paired early-2024 cases. The EIA futures series ends on April 5, 2024. This pilot used an assumed same-day UTC close. It cannot establish live 2026 access or coverage.
- In the enlarged 2026 sample, a three-calendar-day spot delay assumption increased compact-model MAE from 19,846 to 20,779 LBP. This is a sensitivity test, with no claim about EIA's per-observation publication delay. Adding the [European Commission's Italy and Greece weekly tax-exclusive retail prices](https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en) to the spot-only model increased MAE from 26,183 to 27,820 LBP on the same dates. These are retail proxies with a conservative seven-day observation lag in the experiment.
- [S&P Global's July 2026 specifications](https://www.spglobal.com/content/dam/spglobal/ci/en/documents/platts/en/our-methodology/methodology-specifications/refined-products/refined-products-europe-africa-specifications.pdf) list AAWZB00, premium unleaded 10 ppm CIF Mediterranean cargo in USD/metric ton. Its link to Lebanon's current pricing formula is unverified. No licensed historical data or price quote was obtained. Before purchase, obtain permitted evaluation history with original timestamps and a cost and redistribution quote. Test it against the current Hybrid and repeat-last-change on identical later outcomes. Similarly, [CME DataMine](https://datamine.new.cmegroup.com/catalog/dataset/33c2b6a2a39649a0b69c76163f49f4c1) documents a continuous RBOB series. Neither purchase is supported by the current pilot.

## Reproduce

From the project root, use the saved public captures and the database snapshot identified by the SHA-256 values in the run's `metrics.json`.

```sh
PYTHONPATH=src .venv/bin/python scripts/research_forecast_coverage.py \
  --lebvote research/evidence/forecast_data_expansion/lebvote_gasoline_95.html \
  --rbob research/evidence/forecast_data_expansion/eia_rbob_contract_1.xls \
  --output reports/research/expanded_coverage
```

The run writes the source reconciliation, research design, paired predictions, and metrics. The public dashboard reads the reduced chart export. Raw captures are retained locally.
