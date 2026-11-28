"""Rebuild research notes from selected saved forecasts and matched price evidence."""
from collections import Counter
from datetime import date
import json
import math
from statistics import mean

from lebanon_fuel.domain import BEIRUT
from .decision_events import stamp
from .decision_tracking import _matched, _read, protocol_start
from .live_score import protocol, report

REVIEW_CHECKPOINT = 30
TESTS = {
    "Domestic momentum": "Compare the frozen Hybrid with versions that reduce or remove the last domestic move.",
    "Lagged market inputs": "Compare a timelier gasoline proxy at identical issuance cutoffs.",
    "Projected date": "Test the announcement schedule separately from the forecast price.",
    "Move size": "Test whether the model systematically undershoots or overshoots same-direction moves.",
    "Directional miss": "Test whether the model improves on no change and last change under the same direction rule.",
    "Last change benchmark": "Compare against last change on the same dates, including larger price moves.",
}
MARKET_SERIES = ("nyh_gasoline", "brent_spot", "rbob_futures", "brent_futures")
ATTRIBUTIONS = ("commodity_pass_through", "lagged_domestic_momentum", "fiscal_shock",
                "other_features", "baseline_intercept")


def _direction(change, deadband):
    return int(change > deadband) - int(change < -deadband)


def _record_context(db, forecast_id, snapshots):
    row = db.execute("""SELECT record_hash, model_version, snapshot_id, origin, target_json
                        FROM forecasts WHERE id=?""", (forecast_id,)).fetchone()
    if row is None:
        raise ValueError("A journal forecast is missing from the saved ledger")
    target = json.loads(row["target_json"])
    snapshot_id = row["snapshot_id"]
    if snapshot_id not in snapshots:
        snapshot = db.execute("SELECT payload_json FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        payload = json.loads(snapshot["payload_json"]) if snapshot else {}
        snapshots[snapshot_id] = payload.get("available_market_inputs") or {}
    origin = stamp(row["origin"])
    market = []
    for name in MARKET_SERIES:
        observation = snapshots[snapshot_id].get(name)
        if not observation or not observation.get("available_at") or not observation.get("observation_date"):
            continue
        if stamp(observation["available_at"]) > origin:
            continue
        market.append(dict(series=name, date=observation["observation_date"],
                           known_at=observation["available_at"], value=observation.get("value"),
                           unit=observation.get("unit"), url=observation.get("source_url")))
    attribution = target.get("driver_contributions") or {}
    return dict(record_hash=row["record_hash"], model_version=row["model_version"], snapshot_id=snapshot_id,
                artifact_sha256=target.get("artifact_sha256"), starting_date=target.get("base_source_date"),
                starting_evidence=target.get("anchor_verification"), market=market,
                lagged_market_inputs=target.get("lagged_market_inputs") or [],
                attribution={key: attribution[key] for key in ATTRIBUTIONS if key in attribution})


def _review(entry, context, deadband, *, decision):
    estimate, actual, base = (entry[key] for key in ("forecast", "actual", "base_price"))
    error = estimate - actual
    change, actual_change = estimate - base, actual - base
    direction_hit = _direction(change, deadband) == _direction(actual_change, deadband)
    timing = (date.fromisoformat(entry["recorded_date"]) - date.fromisoformat(entry["expected_date"])).days if (
        decision and entry["recorded_date"] and entry["expected_date"]) else None
    baselines = {name: dict(price=price, absolute_error=abs(price - actual))
                 for name, price in entry["baseline_prices"].items()}
    momentum = context["attribution"].get("lagged_domestic_momentum")
    topics = []
    if (abs(error) > deadband and momentum is not None and change
            and abs(momentum) >= .5 * abs(change) and momentum * error > 0):
        topics.append("Domestic momentum")
    if abs(error) > deadband and context["lagged_market_inputs"]:
        topics.append("Lagged market inputs")
    if timing:
        topics.append("Projected date")
    if not direction_hit:
        topics.append("Directional miss")
    elif abs(error) > deadband and abs(actual_change) > deadband:
        topics.append("Move size")
    if "Last change" in baselines and baselines["Last change"]["absolute_error"] < abs(error):
        topics.append("Last change benchmark")
    return dict(entry, **{key: value for key, value in context.items() if key not in entry},
                signed_error=error, absolute_error=abs(error), forecast_change=change, actual_change=actual_change,
                direction_hit=direction_hit, days_from_projection=timing, baselines=baselines,
                test_topics=topics)


def load(root, ledger, horizon, at):
    """Keep legacy references out of prospective counts and use one scored outcome per date."""
    policy = protocol(root)
    if policy is None:
        raise ValueError("The live score protocol is missing")
    with _read(ledger) as db:
        score = report(db, policy, at, horizon=horizon)
        entries = score["entries"]
        snapshots = {}
        cases = [_review(entry, _record_context(db, entry["forecast_id"], snapshots),
                         policy["direction_deadband_lbp"], decision=horizon.startswith("decision_"))
                 for entry in entries if entry["status"] == "matched"]
        older = {}
        cutoff = min(stamp(at), stamp(policy["starts_at"])).isoformat()
        for row in _matched(db, protocol_start(root), cutoff):
            if row["horizon"] != horizon:
                continue
            current = older.get(row["day"])
            if current is None or (current["kind"] != "official_match" and row["kind"] == "official_match"):
                older[row["day"]] = row
        archive = []
        for row in older.values():
            entry = dict(forecast_id=row["forecast_id"], issued_at=row["origin"].isoformat(),
                         expected_date=None, recorded_date=row["day"], base_price=row["base"],
                         forecast=row["forecast"], actual=row["actual"], evidence=row["kind"],
                         evidence_url=row["source_url"], outcome_id=row["outcome_id"],
                         outcome_known_at=row["known"].isoformat(), baseline_prices={"No change": row["base"]})
            archive.append(_review(entry, _record_context(db, row["forecast_id"], snapshots),
                                   policy["direction_deadband_lbp"], decision=False))

    newest = max(entries, key=lambda row: row["forecast_id"], default=None)
    current_version = newest["model_version"] if newest else None
    current_cases = [case for case in cases if case["model_version"] == current_version]
    n = len(current_cases)
    errors = [case["signed_error"] for case in current_cases]
    topics = Counter(topic for case in current_cases for topic in case["test_topics"])
    return dict(as_of=stamp(at).isoformat(), horizon=horizon, unit="LBP per 20 L", protocol=score["version"],
                starts_at=score["starts_at"], deadband_lbp=policy["direction_deadband_lbp"],
                counts=score["counts"], selections=entries, cases=cases, earlier_cases=archive,
                model_version=current_version, current_matches=n, review_checkpoint=REVIEW_CHECKPOINT,
                mae=mean(map(abs, errors)) if errors else None,
                rmse=math.sqrt(mean(e * e for e in errors)) if errors else None,
                mean_error=mean(errors) if errors else None,
                direction_hits=sum(case["direction_hit"] for case in current_cases),
                comparisons=score["comparisons"],
                hypotheses=[dict(topic=topic, cases=topics[topic], sample=n, test=suggestion)
                            for topic, suggestion in TESTS.items() if topics[topic]])
