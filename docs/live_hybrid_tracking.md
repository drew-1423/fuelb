# Live Hybrid decision tracking

The live issuer pins the existing `G_hybrid` artifact for each configured horizon. An ineligible horizon records an abstention in the same atomic refresh and adds its reason. Public views display Hybrid results only. Historical model tests and the original forecast ledger stay available for internal audit.

The scheduled or manual refresh reviews the first recorded date after the forecast base. A provisional score requires exact IPT and Taqtek agreement on that date, a date after the forecast's Beirut issuance day, and no observed conflict, intervening unverified record or gap exceeding seven days. These checks cannot establish that all decisions were captured. Same-day outcomes require stronger timing evidence. Source changes append review events and may withdraw a provisional score. The original forecast and earlier scores remain immutable. Official scoring uses the existing reviewed-manifest process, with publication and effective timing and complete sequence evidence. Provisional and official scores are presented separately.

The next-update range uses prospectively settled errors from the exact Hybrid artifact. Official outcomes calibrate government-backed starting prices. Supplier agreements calibrate provisional starting prices. Both require at least 30 distinct outcomes for fitting and at least 20 chronological coverage checks. Recent rolling empirical coverage must fall between 80% and 98% for the nominal 90% interval. The minimum half-width is 5,000 LBP per 20 L. Calendar and later-decision ranges need their own mature evidence. Existing retrospective bands and probabilities are withheld by the pinned issuer.

## AAWZB00 licensed trial

[S&P Global lists refined-product market data, a demo and full-history access](https://www.spglobal.com/energy/en/products-solutions/fuels-refined-products/fuels-refining-market-data). Its public material does not supply the continuous licensed series with original release timestamps needed for a point-in-time trial. Obtain authorized AAWZB00 evaluation data and confirm whether the licence allows derived outputs to be published. Do not commit the raw data or credentials to this repository.

Normalize the trial file to `symbol,observation_date,mid,unit,published_at`, with one original AAWZB00 assessment per date, USD/mt and an explicit offset on publication timestamps. Run privately from the project root.

```sh
PYTHONPATH=src .venv/bin/python scripts/evaluate_med_benchmark.py \
  --input /absolute/path/to/authorized-aaWZB00.csv \
  --authorization 'S&P evaluation agreement reference'
```

The comparison asks whether pre-issuance movements in the Mediterranean assessment improve the saved Hybrid's errors on identical settled outcomes. It uses only matured prior errors and reports the two starting-price groups separately. Treat a small or missing overlap as insufficient evidence to purchase or change the forecast.
