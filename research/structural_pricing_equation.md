# Structural pricing equation — Part 4

Research cutoff: 10 November 2026. Target: gasoline 95, LBP per 20 liters. This is a **dated downstream reconstruction and a conditional costing engine**. The exact current official upstream formula is unresolved. Numerical component observations are bound to original PDF hashes in `data/manual/structural_annexes.json`.

## Evidenced structure

For a dated annex, all domestic components below are LBP/kiloliter:

\[
P^{raw}_{20L}=\frac{G+D+T+R+B+O+\tau Z}{50},\qquad
P^{published}_{20L}=\mathcal R_d(P^{raw}_{20L}).
\]

`G`: goods/import subtotal; `D`: aggregate duties; `T`: domestic transport; `R`: station commission; `B`: bank commission; `O`: any other explicitly specified cost; `Z`: sum of components included in the VAT base. `1/50` converts kiloliters to 20 liters. The three reviewed annexes support `Z = G+D+T+R+B` for those dates. The engine requires an explicit taxable flag for every component. **Rounding operator R is not authenticated.** Raw totals are the headline reconciliation; optional nearest-increment, half-up rounding is a labelled hypothesis.

The Ministry's [23 February 2021 explanation](https://energyandwater.gov.lb/ar/details/100628/المديرية-العامة-للنفط-توضح-ال-لي-ـة-المعتمدة-أسبوعيا-لتحديد-أسعار-مبيع-المحروقات) describes weekly Platts product averages plus marine transport, insurance, banking/profit costs and domestic charges. It is verified historical evidence; its contemporaneous subsidy treatment cannot be applied to later years. Publication clock absent; rechecked 10 November 2026.

## Unknown upstream subtotal

A dimensional scenario equation is:

\[
G_d = X_d [c_u(\bar q_d)+F_d+I_d],\quad
\bar q_d=\sum_{j\in W_d}w_{dj}q_j,\quad \sum w_{dj}=1.
\]

`X` is the applicable goods FX, `F` marine freight in USD/kl, `I` separately specified import costs in USD/kl. These inputs may already contain embedded profit or banking charges: never add them twice. For USD/metric ton, `c_u(q)=q×density_kg/L`; for USD/bbl, `c_u(q)=q×1000/158.987294928`; for USD/L, multiply by 1000. FOB allows separately specified freight; CIF already includes freight, which the engine rejects if added again. A per-component FX arrangement must be converted explicitly before entering domestic costs; the engine does not invent a blended subsidy rate.

[S&P's May 2026 specification](https://www.spglobal.com/content/dam/spglobal/ci/en/documents/platts/en/our-methodology/methodology-specifications/refined-products/refined-products-europe-africa-specifications.pdf) defines candidate AAWZA00 FOB Med 95 RON/10 ppm and AAWZB00 CIF Med. Its 0.755 kg/L reference density is **not established as the ministry's formula parameter**. Neither the licensed quotation history nor an authenticated current Lebanese symbol/window is present. A four-week industry description in September 2015 and a weekly ministry description in February 2021 concern different historical contexts; procurement bill-of-lading windows are not retail pricing windows. See the bounded primary-source register in `verified_assumptions.md`, S01–S04.

## Original annex observations

All values except USD goods and FX are LBP/kl; final prices are LBP/20 L. Original document dates shown; individual web publication timestamps unknown. Verified by image review on 10 November 2026. The 2023 source was newly captured in Part 4; the other originals were retained in Part 2.

| Component | 17 Sep 2021, decision 180 | 12 May 2023, decision 245 | 29 May 2025, decision 166 |
|---|---:|---:|---:|
| Goods G | 7,186,500 | 65,591,500 | 58,956,500 |
| Aggregate duties D | 253,000 | 1,022,000 | 1,022,000 |
| Domestic transport T | 112,000 | 1,654,000 | 1,570,000 |
| Station R | 300,000 | 4,725,000 | 4,933,500 |
| Separate station-bank B | Not separately listed | 656,000 | 590,000 |
| Pretax subtotal | 7,851,500 | 73,648,500 | 67,072,000 |
| VAT rate | 11% | 11% | 11% |
| VAT amount | 863,665 | 8,101,335 | 7,377,920 |
| Printed pump price | 174,300 | 1,635,000 | 1,489,000 |
| Printed parallel-market FX | Not listed | 94,500 | 89,700 |
| Printed goods USD/kl | Not listed | 693.88 | 656.84 |

Sources: [17 September 2021, page 2](https://energyandwater.gov.lb/mediafiles/prices/1-2021-09-17.pdf#page=2), [12 May 2023, page 2](https://energyandwater.gov.lb/mediafiles/prices/1-2023-05-12.pdf#page=2), [29 May 2025, page 2](https://energyandwater.gov.lb/mediafiles/prices/1-2025-05-29.pdf#page=2). Dates and original hashes are preserved with each machine-readable transcription. Entries are valid on the evidenced date only. No separate distributor-bank gasoline charge is printed in the later annexes; this does not establish absence of distribution/import margin inside G.

**Calculated discrepancy:** printed USD goods × printed FX is below printed LBP goods by 19,840 LBP/kl in 2023 and 37,952 LBP/kl in 2025. Preserve both; unexplained hidden precision, column error or other adjustment must not be silently inferred. The later station-bank rows carry a 1% label; the printed fixed amounts are used, without inventing the exact base/intermediate rounding.

## Parameters and status

| Input | Evidence status | Implementation |
|---|---|---|
| Dated LBP goods, duties, transport, station, bank amounts and VAT | Verified document transcription, date-specific | Explicit parameter records with URL, capture knowledge time and same-day validity |
| Current goods FX, tax base/rate and all current margins | Unresolved | No carried-forward official defaults |
| Current assessment, averaging weights/cutoff and import uplift | Unresolved | Caller-supplied, evidenced or explicitly scenario inputs |
| Empirical slopes, averaging windows and lags | Estimated research relationships | Train/validation only; never ministerial parameters |
| Rounding | Unresolved | Unrounded reconciliation; any rounding option is hypothetical |
| Scenario cost bounds | Assumptions | Conditional input ranges, no probability claim |

`research/structural_parameters.csv` provides the full dated parameter metadata. `reports/structural_validation.md` distinguishes arithmetic agreement from prediction accuracy.

## Next-decision sensitivities

At the **29 May 2025 cost structure**, holding domestic charges fixed and taking goods to be taxable, each additional USD/kl of goods costs adds `89,700×1.11/50 = 1,991.34` LBP/20 L. With the *illustrative* 0.755 density, +10 USD/ton adds 15,034.62 LBP/20 L. A 1% increase in goods LBP cost adds 13,088.34 LBP/20 L. A one-percentage-point VAT increase adds 13,414.40 LBP/20 L. These are partial derivatives of this historical equation, not estimates of current policy or market movement.

The benchmark, applicable FX, import freight/risk premium and government charges can therefore materially affect the next price. Their actual ranking today cannot be established without current components and shock sizes. A hypothetical 300,000 LBP/20 L increment contributes 300,000 if applied after VAT, or 333,000 if added to an 11% taxable base; the legal placement must be verified. No current tax scenario is presented as enacted law.

## Uncertainty and operational gate

The engine provides a conditional range if explicit bounds are supplied. It carries no inferred confidence level, excludes unbounded policy/basis risks, and refuses missing, stale-validity or future-known parameters in forecasting/scenario mode. Historical reconciliation deliberately permits a later retrieval time and exposes that mode.

A next-decision production estimate still needs: the current authenticated annex and legal changes; applicable product, window and cutoff; authorized refined quotation vintages through that cutoff; goods/customs/payment FX distinctions; current freight/insurance/import uplift; verified tax/margin bases; and the announcement schedule. Public proxies can inform scenarios but cannot fill these fields as known facts.
