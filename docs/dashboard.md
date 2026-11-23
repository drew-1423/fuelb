# Levant Energy Terminal

Part 8 connects manual refresh to the shared operations pipeline and adds its latest cycle, current gate and monitoring alerts to Data quality. Native scheduling runs independently of this dashboard. See [operations and maintenance](operations.md).

The dashboard runs locally on macOS. It reads the existing price and market database, immutable forecast ledger and Part 6 validation results. The unit throughout the domestic price views is **LBP per 20 liters**.

## Launch

From the project root, activate the existing project virtual environment or create one with Python 3.11 or newer.

```sh
.venv/bin/python -m pip install -e '.[dashboard,market,dev]'
.venv/bin/python -m streamlit run src/lebanon_fuel/dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

Open [Levant Energy Terminal](http://127.0.0.1:8501). Press Control-C in the server terminal to stop it. For the exact environment used in verification, install `requirements-dashboard-lock.txt` and install the project in editable mode. The full lock includes the existing forecasting environment and its macOS OpenMP prerequisite. Forecast values and model versions come from the ledger.

## Use the terminal

- **Overview** shows the latest corroborated or document-reviewed record, the previous record in that tier, the change between the two, and the latest source capture. Supplier-only quotes and the latest reviewed original decision have their own labels. Consecutive official decision timing is unresolved.
- **Price & forecasts** plots government source records and can overlay saved retrospective ledger forecasts. Choose the next update, 7, 14 or 30 days. The chart uses the source date for observed records, and a stored endpoint or matched target date for forecasts. Shaded spans represent individual candidate intervals. Their horizontal widths are graphical markers. Calendar endpoints use Beirut local time.
- **Global markets** shows observation dates, retrieval and publication timestamps, source links, freshness, and movements from the existing feature pipeline. The cross-region gasoline/Brent spread is a gross price spread. Verified refinery margins and licensed Mediterranean benchmarks are unavailable. The historical customer payment conversion has its own identity and freshness label.
- **Analyst report** builds and exports a deterministic Markdown brief from the displayed evidence and saved validation results.
- **Model performance** reads the Part 6 metrics, matched recorded prices, baseline comparisons and reliability bins. Select a horizon, evaluation period and model. The plotted ledger run is linked to the validation manifest. Model hashes and input snapshot IDs are available in the detail panel.
- **Scenario simulator** calls the Part 4 structural engine in scenario mode. Enter a refined product quote directly or supply Brent and an assumed product spread. The Brent relationship is a user assumption. Adjust freight, USD/LBP, VAT and the assumed government charge. The domestic cost scaffold dates to May 2025. All outputs are hypothetical deterministic estimates.
- **Data quality** shows source collection runs, stale or missing observations, conflicts, unusual moves and saved prospective forecast checks. Gap reports carry their audit date.

## Refresh and production status

**Refresh selected source** runs the existing domestic or market collector for that source. Collection requires a working internet connection and upstream access. Database reads are cached briefly and invalidated on writes. A successful refresh can return the same observation dates. An error or timeout is shown explicitly with collector output. Existing observations retain their dates and source evidence.

Part 6 rejected production approval. The dashboard connects to the production decision and prospective forecast ledger. Current predicted prices, dates, probabilities and intervals are unavailable. Historical research predictions remain available through the overlay and performance views.

## Verification

```sh
.venv/bin/python -m pytest Tests/fuel -q
```

The dashboard was launched on loopback and opened in Chrome on macOS on 11 November 2026. The overview, model performance view, structural scenario and IPT refresh were exercised against project data. The IPT collector parsed 1,312 source rows and added zero new semantic observations. All 126 fuel tests passed. Dashboard checks cover all seven views, all requested chart horizons, the direct and Brent-linked scenario inputs, forecast gating and collection failure handling.

[Streamlit Plotly chart API](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart) · [Streamlit AppTest API](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest)
