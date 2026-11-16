"""Read-only next-decision scorecard for the forecasts actually issued live."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import mean

from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE, VERIFIED
from .decision_events import event_clocks, stamp

HORIZONS = ("decision_1", "decision_2", "decision_4", "day_1",
            "day_3", "day_7", "day_14", "day_30")
COHORTS = ("Government-backed price", "Provisional source agreement", "Other or undocumented price")
METHODS = {"forecast": "Issued forecast", "no_change": "No change", "last_change": "Repeat last observed change"}

QUERY = """
WITH live AS (
    SELECT * FROM forecasts
    WHERE mode IN ('prospective', 'prospective_research')
      AND origin >= :start AND created_at >= :start
), batches AS (
    SELECT run_id, origin,
           COUNT(*) = :count AND COUNT(DISTINCT horizon) = :count
             AND SUM(horizon IN ({horizons})) = :count
             AND (SUM(status = 'issued' AND predicted_price IS NOT NULL) = :count
                  OR SUM(status = 'abstained') = :count) AS complete
    FROM live GROUP BY run_id, origin
)
SELECT f.id, f.origin, f.created_at, f.status, f.base_price, f.predicted_price, f.model_version,
       b.complete, json_extract(f.target_json, '$.anchor_verification') AS anchor_status,
       json_extract(m.metadata_json, '$.family') AS family,
       json_extract(s.payload_json, '$.inputs.anchor') AS saved_anchor,
       o.decision_key, o.price AS actual, o.publication_timestamp, o.effective_timestamp,
       o.payload_json, o.verification_status, o.source_url
FROM live f
JOIN batches b USING (run_id, origin)
JOIN models m ON m.id = f.model_version
JOIN snapshots s ON s.id = f.snapshot_id
LEFT JOIN evaluations e ON e.id = (
    SELECT MAX(id) FROM evaluations WHERE forecast_id = f.id AND kind = 'official_match'
)
LEFT JOIN outcomes o ON o.id = e.outcome_id
WHERE f.horizon = 'decision_1'
ORDER BY f.created_at, f.origin, f.id
"""


def _case(row):
    if row["verification_status"] != "document_verified":
        return None
    publication, effective = event_clocks(row)
    if not publication or not effective or not publication.after(max(stamp(row["origin"]), stamp(row["created_at"]))):
        return None
    anchor = json.loads(row["saved_anchor"] or "{}") or {}
    status = row["anchor_status"] or anchor.get("verification_status")
    if status == PROVISIONAL_PRICE:
        cohort = COHORTS[1]
    elif status in VERIFIED:
        cohort = COHORTS[0]
    else:
        cohort = COHORTS[2]
    base = row["base_price"]
    previous = anchor.get("previous_verified_price") if anchor.get("price_lbp_20l") == base else None
    last_change = 2 * base - previous if isinstance(previous, (int, float)) and 0 < previous < 2 * base else None
    return dict(cohort=cohort, decision_key=row["decision_key"],
                decision_date=publication.lower.astimezone(BEIRUT).date().isoformat(),
                issued_at=row["created_at"], forecast_id=row["id"], family=row["family"] or row["model_version"],
                anchor=base, forecast=row["predicted_price"], actual=row["actual"], no_change=base,
                last_change=last_change, source_url=row["source_url"])


def _direction(change):
    return (change > 3000) - (change < -3000)


def _metrics(cases, method):
    count = len(cases)
    return dict(method=METHODS[method], n=count,
                mae=mean(abs(r[method] - r["actual"]) for r in cases) if count else None,
                direction=mean(_direction(r[method] - r["anchor"]) == _direction(r["actual"] - r["anchor"])
                               for r in cases) if count else None)


def load_scorecard(ledger_path, protocol_path):
    protocol = json.loads(Path(protocol_path).read_text())
    start = max(stamp(protocol["prospective_start"]), stamp(protocol["sealed_at"])).isoformat()
    horizons = {f"h{i}": horizon for i, horizon in enumerate(HORIZONS)}
    query = QUERY.format(horizons=", ".join(f":{key}" for key in horizons))
    uri = Path(ledger_path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(query, dict(start=start, count=len(horizons), **horizons)).fetchall()

    complete = [row for row in rows if row["complete"]]
    issued = [row for row in complete if row["status"] == "issued"]
    matched = [case for row in issued if (case := _case(row)) is not None]
    # Re-issues can share an outcome. Select by actual issuance time and a stable
    # tie-breaker, before examining any errors. Each cohort has its own sample.
    selected = {(case["cohort"], case["decision_key"]): case for case in matched}
    groups = {}
    for cohort in COHORTS:
        cases = sorted(
            (case for case in selected.values() if case["cohort"] == cohort),
            key=lambda case: (case["decision_date"], case["issued_at"], case["forecast_id"]),
            reverse=True,
        )
        paired = [case for case in cases if case["last_change"] is not None]
        groups[cohort] = dict(
            cases=cases, primary=[_metrics(cases, method) for method in ("forecast", "no_change")],
            three_way=[_metrics(paired, method) for method in METHODS],
        )
    return dict(start=start, issued=len(issued), abstained=len(complete) - len(issued),
                incomplete=len(rows) - len(complete), matched_issues=len(matched),
                settled_decisions=len({case["decision_key"] for case in matched}), groups=groups)
