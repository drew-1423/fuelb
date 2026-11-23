# Lebanon gasoline pricing mechanism

As of 10 November 2026. Target: official 95-octane consumer price, LBP per 20 L. The evidence supports a regulated cost build-up, but does **not** yet establish a reproducible current formula. Source dates and verification bounds below refer to the [evidence register](verified_assumptions.md).

## Authority and inputs

**Verified historical:** MOEW/DGO issues price decisions; delegated authority and immediate effect appear in the dated [26 March 2024 decision (S06)](https://en.dgo.gov.lb/upload/2821website%E2%80%8E%E2%81%A8%D8%A3%D8%B3%D8%B9%D8%A7%D8%B1%20%D8%A7%D9%84%D9%85%D8%AD%D8%B1%D9%88%D9%82%D8%A7%D8%AA%20Online%2026-3-2024%E2%81%A9.pdf). DGO's [institutional description (S16, undated)](https://www.dgo.gov.lb/category/1) assigns price/cost and fiscal studies to its economic/financial unit. Ministerial decisions, their annexes and effective dates outrank a supplier display.

**Verified historical:** the [23 February 2021 clarification (S01)](https://energyandwater.gov.lb/ar/details/100628/المديرية-العامة-للنفط-توضح-ال-لي-ـة-المعتمدة-أسبوعيا-لتحديد-أسعار-مبيع-المحروقات) identifies Platts product averages, marine transport, insurance, banking/profit costs, taxes and domestic commissions. The [12 May 2023 table (S05)](https://energyandwater.gov.lb/mediafiles/prices/1-2023-05-12.pdf) exposes intermediate distributor/station totals. Component values and bases must be extracted per dated annex, not assumed constant. Part 4 visually verified its gasoline-95 LBP components and reconciled the downstream arithmetic; a printed USD/FX conversion discrepancy remains. See [the structural equation](structural_pricing_equation.md).

## Refined benchmark, observation window and delay

**Verified procurement evidence, not current retail law:** the [2023 gasoline tender (S03)](https://pe.ppa.gov.lb/storage/annual-plans/files/combi-diesel-gasoline95-tor_20231114-193725_jhx23jdjyjrvv2s7.pdf) names Prem Unl 10ppm FOB Med (Italy). Its bill-of-lading-centered averaging includes future quotations relative to shipment date and cannot be used as an information-available retail forecasting feature. Its inconsistent quotation counts need resolution.

**Verified benchmark definition:** [S&P's May 2026 guide (S04)](https://www.spglobal.com/content/dam/spglobal/ci/en/documents/platts/en/our-methodology/methodology-specifications/refined-products/refined-products-europe-africa-specifications.pdf) distinguishes FOB and freight-inclusive CIF Med assessments. Avoid adding freight twice. USD/ton to USD/kiloliter needs documented density: `USD/kl = USD/ton × density_kg_per_liter`; reference specification density is not automatically the ministry's conversion parameter.

**Historical evidence differs:** [APIC September 2015 (S02)](https://data.infopro.com.lb/file/Snapshot%20of%20the%20Refined%20Petroleum%20Market%20in%20LEBANON_APIC.pdf) describes four weeks, while S01 describes a weekly average. **Unresolved:** today's observation cutoff, holiday handling, weights and administrative delay. Estimate candidate distributed lags within training folds only; empirical lag is a predictive relationship, not proof of an official rule. Crude is a potential proxy with basis risk, not a substitute refined-product quotation.

## FX, taxes and regimes

**Verified historical:** S01's 90/10 subsidized FX mix applies to its dated explanation. [BDL's 2022 overview (S07)](https://www.bdl.gov.lb/CB%20Com/Publications/Publications/Monetary%20Overview_22_Ar%C2%A78193_1.pdf) dates complete fuel-subsidy lifting to October 2022. Exact intermediate arrangements need documents. S05 labels parallel FX; S06 distinguishes the USD payment rate. Keep goods conversion, cost conversion, customs conversion and customer USD payment rates separate.

**Verified policy event:** [MOEW, 5 June 2025 (S08)](https://energyandwater.gov.lb/ar/details/100997/بيان-صادر-عن-الوزير-الصدي-حول-قرار-تعديل-الرسوم-الجمركية-على-المحروقات) confirms a May Cabinet customs change. **Reported:** [21 July 2025 suspension account (S09)](https://www.lbcgroup.tv/news/lebanon-news/868579/lbci-lebanon-articles/en) requires the underlying legal instruments. **Reported:** [AP, 17 February 2026 (S10)](https://apnews.com/article/lebanon-taxes-fuel-salaries-protests-5971edfb501c3aee4f508709ee702d15) describes the additional gasoline charge. **Verified proposal, not repeal:** [MOEW, 29 September 2026 (S11)](https://energyandwater.gov.lb/ar/details/101203/الصدي-سأطلب-من-الحكومة-إلغا-رسم-الـ300-ألف-على-المحروقات-أو-تعليقه). Current enacted VAT/charges remain to be checked against current annexes and legal text.

## Publication process and forecast implications

**Observed:** recent IPT dates include Tuesdays/Fridays; earlier records are largely weekly and crisis-era updates more frequent. This is an empirical schedule, not a binding calendar. Ministry rows also include other weekdays. Missing archive rows cannot establish that no decision occurred. Publication date, effective date, announcement time and retrieval time are separate fields.

**Design:** model the decision sequence first. A conceptual structural function is `P_d = round_to_rule(0.02 × total_LBP_per_kl_d)`, where the total is the evidenced taxable and exempt components converted using their own rates. This identity is dimensional bookkeeping, not an authenticated government formula. Actual component bases, adjustments and rounding remain unknown. Use historical regime labels, structural-break sensitivity and recent-window comparisons; do not pool subsidy-era LBP levels with later levels without controls.
