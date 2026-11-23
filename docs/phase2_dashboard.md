# Driver Pulse and forecast accountability

Driver Pulse leads with the latest eligible recorded price, one Hybrid estimate and its exact starting price. Older prices remain in Source evidence and older comparisons. Full horizons, attribution and research overlays are in Price & Forecast Trajectory. All earlier markets, analyst, options, scenario, ledger, performance and quality tools remain available.

## Routes

Use `?view=driver`, `calculator`, `alerts`, `trajectory`, `markets`, `briefing`, `performance`, `timeline`, `volatility` or `quality`. A shared view selects its corresponding perspective. Tank size, alert threshold and submitted scenario assumptions are retained across navigation within the session.

An immutable forecast URL is `https://fuelb95.streamlit.app/?forecast=<64-character-record-hash>`. It reads that exact prospective Hybrid ledger row and its original snapshot; it does not fetch current feeds or replace the prediction. It shows original anchor, inputs, issuance, target, artifact identity, originally published intervals and subsequent eligible matched outcome. Expiry does not remove the historical record. A missing/synchronizing record gets an explicit empty state. Candidate historical intervals are identified as originally saved candidates, not retroactively released calibration.

## Uncertainty and charts

Outer 90% and inner 80% bounds come from the saved issuance. Each level requires its own Phase 1 released status, minimum calibration/coverage sample, exact horizon and exact artifact. A baseline receives no bands. Bounds must be finite, positive, ordered and contain the point estimate; an inner interval cannot extend beyond an available outer interval.

Ribbons join contiguous supported horizons only when origin, run, snapshot, model version, artifact, family, anchor price and target type agree. A missing intermediate horizon or unsupported endpoint breaks continuity. Decision and calendar targets are separate. Single endpoints have error bars; they never create a shaded polygon back to an observed anchor. Interpolated boundaries are pointwise ranges, not joint coverage or a forecast of the path between dates. Existing normal dots, faint historical step underfill, wheel/pinch zoom, pan and reset remain.

## In-app alerts

Open Alert center and set a change threshold in LBP per 20 L. Events cover corroborated price changes, eligible forecast threshold conditions, stale/unavailable forecasts, current conflicts and failed scheduled runs. IDs derive from the underlying evidence, target and configured threshold; refreshing the same event does not create another alert. Acknowledge hides it for the current browser session. No acknowledgement is represented as durable across devices or restarts.

External delivery is disabled and no destination is configured. No email, SMS, WhatsApp transport, account or subscription is created. Copying a briefing is a separate user action. A future delivery adapter requires explicit destination configuration and opt-in before any messages can be sent.

## Sharing and clipboard recovery

The briefing contains dated source evidence, the exact starting and predicted prices, estimated target, issuance, freshness expiry, reliability limitation and immutable link. It never promises savings or invents a morning publication time. Copy uses the browser clipboard permission. If blocked, a visible status directs the user to the preview's copy/select control or the text download.

## Health and performance

Data freshness, forecast status, range readiness and system integrity are separate indicators. An available research estimate cannot hide missing captures or a failed refresh. Refresh request/queue times and successful capture times are separate; acceptance of a workflow dispatch is not a completed collection. Current blockers, optional missing feeds and dated historical evidence gaps are separated in governance. Raw observation/capture denominators are never described as unique pricing decisions.

Performance separates previously examined retrospective research from prospective scored outcomes, uses error in LBP/20 L and direction counts out of measured cases, and labels coverage widths and denominators. Availability uses complete issuance attempts, not uptime. Reference comparisons remain in release evaluation; there is no consumer model selector.

## Operations

Launch from the repository root with `PYTHONPATH=src .venv/bin/python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501`.

Owner refresh continues using the Phase 1 durable writer and requires server-side `LEBANON_FUEL_ACTIONS_TOKEN` plus owner authorization. This phase provisions no credentials. Scheduled refreshes remain independent of browser sessions. Strict checks still fail until the original missing evidence is recovered; this release does not change model approval or fit any weights.
