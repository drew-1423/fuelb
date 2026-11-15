# Lebanon gasoline forecasting platform

Part 8 adds persistent macOS collection, forecast accountability, monitoring, analyst reports and backups. **No production forecasting model is approved.** The local system operates as a research and monitoring terminal and records current forecast abstentions. See the [final project report](reports/final_project_report.md), [financial and technical audit](reports/production_audit.md), and [operations guide](docs/operations.md).

```sh
cd /Users/andrew/MyApp_macOS/fuel forecast
.venv/bin/python -m lebanon_fuel.automation.cli run
.venv/bin/python -m lebanon_fuel.automation.cli status
```

## Local dashboard

Part 7 adds Levant Energy Terminal for price history, market data, saved forecasts, validation results, scenario analysis and source alerts. The production decision remains withheld. [Launch and use the dashboard](docs/dashboard.md).

```sh
.venv/bin/python -m streamlit run src/lebanon_fuel/dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

The Python project studies Lebanon's official gasoline 95 consumer price in **LBP per 20 liters**. Parts 1–6 implement research, Lebanese price collection, international market histories, availability-aware features, a dated structural cost engine, eight-horizon model development, and model risk validation. **Part 6 rejects production approval**: strict historical/fresh holdout evidence is absent, calibration fails in several horizons, and advanced models do not consistently beat strong baselines. Live forecasting remains disabled.

- [Pricing mechanism research](research/lebanon_pricing_mechanism.md), [source assessment](research/data_source_assessment.md), [forecast design](research/forecasting_methodology.md), [verified assumptions](research/verified_assumptions.md), [unresolved questions](research/unresolved_questions.md).
- [System architecture](docs/architecture.md), [data contract](docs/data_contract.md), [installation/update/review instructions](docs/data_updates.md).
- [Actual data quality report](reports/data_quality.md), [historical CSV](data/exports/gasoline_95_history.csv), [verified-tier CSV](data/exports/gasoline_95_verified.csv), [SQLite database](data/lebanon_fuel.sqlite).
- [Market source research](research/international_market_sources.md), [market update and alignment guide](docs/market_data.md), [market coverage report](reports/market_coverage.md), [comparison chart](reports/charts/market_price_comparison.png).
- [Structural equation](research/structural_pricing_equation.md), [regulatory regimes](research/regulatory_regimes.md), [pricing engine guide](docs/structural_model.md), [Part 4 validation](reports/structural_validation.md), [error analysis](reports/structural_error_analysis.md).
- [Part 5 development results](reports/forecasting_development.md), [training and saved-model guide](docs/quantitative_forecasting.md), [frozen research protocol](research/quantitative_forecasting_protocol.md), [optional news pipeline](research/news_intelligence.md).
- [Part 6 validation decision](reports/model_validation_report.md), [model comparisons](reports/model_comparison_report.md), [probability calibration](reports/probability_calibration_analysis.md), [stress tests](reports/stress_testing_report.md), [validation and permanent ledger guide](docs/model_validation.md).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-data-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/fuel-data collect --source all
.venv/bin/fuel-data report
.venv/bin/python -m pytest Tests/fuel -q
```

The current target dataset contains supplier observations, ministry archive records, original-document reviews and quarantined disagreements. Consult each row's verification status. Source-labelled dates do not prove publication instants or effective dates, and the complete current official pricing formula remains unresolved. Data supports reconciliation and exploratory analysis; a defensible institutional backtest still needs original vintages, announcement times and licensed Mediterranean assessments. Part 4 fits simple statistical relationships for explicitly retrospective research, without certifying real-time forecast accuracy.

For Part 3, install `requirements-market-lock.txt`, then run `.venv/bin/fuel-market collect --source all` and `.venv/bin/fuel-market report`. Free market proxies are labelled by product/region. Strict snapshots use captured knowledge times; historical comparisons marked `RESEARCH_ONLY` use explicitly assumed lags and latest vintages, and cannot support real-time accuracy claims.

For Part 4, install `requirements-structural-lock.txt`, then run `.venv/bin/fuel-structure reconcile`, `.venv/bin/fuel-structure research`, and `.venv/bin/fuel-structure report`. Three official annex arithmetic checks are separate from historical proxy predictions; neither certifies the complete current formula.

For Part 5, install `requirements-forecasting-lock.txt` and the macOS OpenMP runtime (`brew install libomp`), then reinstall the project entry points. Run `.venv/bin/fuel-forecast train`, `.venv/bin/fuel-forecast report`, and `.venv/bin/fuel-forecast preview --regime recent_pre_fiscal --horizon decision_1`. The preview explicitly reproduces a **historical** origin, not today's prediction. Sixteen horizon/regime bundles are saved; unsupported family/horizon combinations abstain. The full official structural adapter remains blocked by incomplete inputs. Short-calendar ensemble interval calibration failures are disclosed; no production winner is selected before Part 6.

The pipelines and CPU models were run on Apple Silicon with CPython 3.13.12. Stage-specific lockfiles preserve executed dependency sets. The local dashboard supports on-demand collection.

For Part 6, the same forecasting environment supports `fuel-validate run`, `fuel-validate stress`, `fuel-validate report` and `fuel-validate ledger-check`. The strict evaluator correctly produces zero eligible historical predictions. Separately labeled retrospective challenges preserve their original-date limitations. The append-only `data/forecast_ledger.sqlite` distinguishes replayed forecasts from actual prospective issuance and keeps later outcome corrections separate. No model is approved for the next-decision, seven-day or thirty-day production target.
