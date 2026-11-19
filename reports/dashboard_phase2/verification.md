# Phase 2 dashboard verification

## Implemented

Driver Pulse leads with one current eligible recorded price and one Hybrid next-update estimate, tied visibly to its exact anchor. LBP/USD and per-liter equivalents, source date/age, estimated target, issuance and expiry are adjacent. The fill-up calculator is conditional; older source comparisons are secondary. Full horizons, source records, attribution, markets, analyst reporting, scenarios, options, backtests and governance remain accessible.

Three perspectives support direct view routes and preserve useful session inputs. Browser testing identified and fixed a scenario-state overwrite during successive switches. A regression test submits a freight change and switches through all three perspectives before checking that it remains. A calendar forecast permalink also displays its saved endpoint rather than treating it as an unknown decision date.

Forecast hashes resolve to exact immutable prospective Hybrid records and original snapshots, including original input dates, artifact/model identities, original intervals and subsequent matched outcomes. No current feed is required to open a saved record, and missing IDs never substitute a newer forecast. Example: https://fuelb95.streamlit.app/?forecast=2faea79d5a6c0c9bb58fa872ac0280c77ee9bf80ff37483f49835e28ebf4f2f5

Four health indicators separate required data freshness, forecast status, range readiness and integrity. The original 69 missing capture files still prevent strict operations approval. Governance distinguishes current blockers, optional unavailable feeds and historical evidence gaps with capture/raw-observation denominators and source-date ranges.

In-app alerts cover recorded corroborated price changes, research-estimate thresholds, stale/unavailable forecasts, source conflicts and failed scheduled refreshes. Stable evidence-derived event IDs prevent refresh duplicates. Acknowledgements and thresholds are session-scoped. No external transport, destination, account or opt-in is configured, and no messages were sent.

## Financial and chart contracts

- Existing pricing engines and ledger values are reused. No model weights, training data, historical manifests or database schemas changed.
- Each 80%/90% band requires that exact saved level's release status, horizon, artifact and minimum evidence counts. Saved bounds must be finite, positive, ordered and nested when both levels exist.
- Different snapshots, runs, families, versions, anchors, target types and missing intermediate horizons break ribbons. Isolated targets retain whiskers. No fan is drawn to an invented zero-width anchor.
- The current real data has insufficient released live range evidence; its forecasts remain markers with explicit readiness counts. Synthetic, clearly identified unit fixtures verify the released-ribbon branches.
- Normal observation dots and faint historical step underfill remain. Visible hover identifies the estimate and says “Not released” when no range exists. Wheel zoom, pan and reset remain configured. A date-only decision target is labelled as an estimated date, not a midnight announcement.

## Actual local verification

The complete fuel suite passed with **349 tests and zero pytest warnings** after the final changes. `scripts/verify_production.py` runs the suite together with release, financial artifact, ledger replay and dependency checks. Source/model release identity, structural artifact audit, forecasting artifact audit, validation replay/hash-chain audit and dependency compatibility passed. Strict operations integrity failed on the missing original captures, so the overall verifier correctly returned **exit code 1**. Exact outputs are retained in `reports/operations/final_verification.json`.

An existing feed-age fixture was corrected to subtract eight days from the Beirut calendar date, matching the unchanged production gate. Before that fix it failed during the period when Beirut had crossed midnight and UTC had not. No forecasting gate or audit assertion was weakened.

## Browser evidence

- 375 × 900: stacked prices and readable amounts; measured document width 375 with viewport 375, no page overflow. `mobile-375.jpg`.
- 768 × 1024: two-column price comparison and responsive health grid; measured document width 768 with viewport 768. `tablet-768.jpg`.
- 1440 × 1000: current price, anchored estimate and nearby tank comparison; separate health indicators. `desktop-1440.jpg`.
- Chart zoom changed the visible date ticks, pan changed the date window, and reset restored it. Clicking an estimate produced a hover with actual saved price, issuance and “90% range: Not released”. A trackpad-style wheel event changed the visible date range. Tab focus reached Zoom in with a solid 2 px focus outline. `trajectory.jpg`.
- Browser scenario checks: FX preset 100,000 produced approximately 2,505,003 LBP/20 L; Status Quo reset to exactly 2,343,000; manual freight 35 USD/kL produced approximately 2,352,934. These are hypothetical engine outputs, not market forecasts.
- A local-only QA surface selected stored historical records to exercise missing, stale and conflict recovery without writing or inventing market data. No current price was substituted for missing/conflicting evidence.
- The exact saved forecast route showed original prediction 2,307,569 LBP, original anchor 2,343,000, saved issuance/target, no published live interval and no yet-matched outcome.
- Browser clipboard write returned success and displayed the Copied status. A local QA iframe using the production component with a browser permission policy denying clipboard writes displayed the expected preview/download fallback. The automation tool's isolated clipboard proxy was empty, so an operating-system paste round-trip was **not verified**. A physical trackpad pinch gesture was **not directly generated**; wheel zoom and the shared Plotly scrollZoom configuration were verified.

Caption text was measured at rgb(197, 210, 236), 14 px and full opacity on the dark surface. All status indicators include text, not color alone. This is a targeted keyboard/contrast/reflow review, not a complete assistive-technology certification.

## Publishing and remaining limits

The established pull-request workflow runs the strict verifier and uploads an exact-commit attestation. Its operations failure must remain visible until the original evidence is recovered. Public deployment is smoke-tested separately; passing tests does not establish forecasting skill.

The 69 missing original captures, twelve unrecovered older source versions and insufficient independent live outcome evidence remain Phase 1 blockers. Owner-triggered durable refresh still requires the existing server-side token configuration. External alerts remain disabled. Alert acknowledgements are not cross-device durable. Native clipboard paste and physical pinch remain manual follow-up checks.
