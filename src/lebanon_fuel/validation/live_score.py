"""Prospective score selection from immutable issuance rows, independent of outcomes."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from statistics import mean

from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE, VERIFIED, supplier_agreement
from .decision_events import stamp


def protocol(root):
    path = root / "config/live_score_v3.json"
    return json.loads(path.read_text()) if path.is_file() else None


def record_supported(record):
    status = record.get("verification_status")
    return status in VERIFIED or (status == PROVISIONAL_PRICE and supplier_agreement(
        source["id"] for source in record.get("corroborating_sources", ())))


def update_records(records):
    """Drop only repeated supplementary quotes after an eligible price."""
    result = []
    for row in records:
        previous = result[-1] if result else None
        if (row.get("verification_status") == "supplementary_observed" and previous
                and record_supported(previous) and (previous.get("price_lbp_20l") or 0) > 0
                and previous["price_lbp_20l"] == row.get("price_lbp_20l")):
            continue
        result.append(row)
    return result


def previous_update(records, anchor):
    """Use the adjacent eligible update. An unsupported record remains a barrier."""
    last = update_records(records)
    if len(last) < 2 or last[-1]["revision_id"] != anchor["revision_id"]:
        return None
    previous = last[-2]
    gap = (date.fromisoformat(anchor["source_date"]) - date.fromisoformat(previous["source_date"])).days
    if not (record_supported(previous) and 0 < gap <= 7 and previous.get("price_lbp_20l")):
        return None
    return previous


def issuance_protocol(policy, records, anchor, forecast, at):
    if not policy or at < stamp(policy["starts_at"]) or forecast.get("pinned_family") != "G_hybrid":
        return None
    day = at.astimezone(BEIRUT).date()
    horizon = forecast["horizon"]
    if horizon.startswith("decision_"):
        if not anchor:
            return None
        target = date.fromisoformat(anchor["source_date"])
        # Exclusive midnight after the allowed decision entry days.
        deadline = datetime.combine(target + timedelta(days=policy["decision_entry_days_after_anchor"] + 1),
                                    time(), BEIRUT)
    else:
        target = stamp(forecast["endpoint"]).astimezone(BEIRUT).date()
        deadline = datetime.combine(day, time(policy["calendar_cutoff_hour"]), BEIRUT)
    metadata = dict(version=policy["version"], key=f"{horizon}:{target}", target_key_date=target.isoformat(),
                    entry_cutoff=deadline.astimezone(timezone.utc).isoformat(), baselines={})
    if anchor and forecast["status"] == "issued":
        price = anchor["price_lbp_20l"]
        metadata["baselines"]["No change"] = price
        previous = previous_update(records, anchor)
        if previous and (last_price := 2 * price - previous["price_lbp_20l"]) > 0:
            metadata["baselines"]["Last change"] = last_price
    return metadata


def selections(db, policy, at):
    """Earliest eligible ledger insertion per key wins forever, even if it never matches."""
    from .decision_tracking import BATCH

    rows = db.execute(BATCH + """
        SELECT f.* FROM live f JOIN complete c USING (run_id, origin)
        WHERE json_extract(f.target_json, '$.score_protocol.version') = :version
          AND f.created_at < :cutoff ORDER BY f.id
    """, dict(start=stamp(policy["starts_at"]).isoformat(), cutoff=stamp(at.isoformat() if isinstance(at, datetime) else at).isoformat(),
              version=policy["version"]))
    chosen, seen = {}, {}
    for row in rows:
        spec = json.loads(row["target_json"])
        marker = spec["score_protocol"]
        key = marker["key"]
        seen.setdefault(key, (row, spec))
        if key in chosen:
            continue
        if (row["status"] == "issued" and spec.get("family") == "G_hybrid"
                and stamp(row["created_at"]) < stamp(marker["entry_cutoff"])
                and marker["baselines"].get("No change") == row["base_price"]):
            chosen[key] = (row, spec)
    return chosen, seen


def _metrics(cases, model, deadband):
    signed = [case["prices"][model] - case["actual"] for case in cases]
    direction = lambda change: (change > deadband) - (change < -deadband)
    hits = sum(direction(case["prices"][model] - case["base"]) == direction(case["actual"] - case["base"])
               for case in cases)
    return dict(model=model, n=len(cases), mae=mean(map(abs, signed)), rmse=math.sqrt(mean(e*e for e in signed)),
                bias=mean(signed), direction_hits=hits)


def report(db, policy, at, *, horizon="decision_1", include_research=False):
    from .decision_tracking import ATTEMPT, _matched

    at = at.isoformat() if isinstance(at, datetime) else at
    chosen, seen = selections(db, policy, at)
    primary = {row["id"]: (row, spec) for row, spec in chosen.values() if row["horizon"] == horizon}
    by_id = {}
    for case in _matched(db, stamp(policy["starts_at"]).isoformat(), at, selected_ids=primary):
        previous = by_id.get(case["forecast_id"])
        if previous is None or case["kind"] == "official_match":
            by_id[case["forecast_id"]] = case
    counts = Counter(selected=len(primary))
    for key, (row, spec) in seen.items():
        if row["horizon"] == horizon and key not in chosen:
            status = "missed_entry" if stamp(at) >= stamp(spec["score_protocol"]["entry_cutoff"]) else "awaiting_eligible"
            counts[status] += 1
    cases_by_day = {}
    entries = []
    for fid, (row, spec) in primary.items():
        attempt = db.execute(ATTEMPT, (fid,)).fetchone()
        outcome = by_id.get(fid)
        target = spec.get("endpoint") or spec.get("scheduled_effective") or spec["score_protocol"]["target_key_date"]
        target_day = (stamp(target).astimezone(BEIRUT).date() if "T" in target else date.fromisoformat(target))
        expired = stamp(at).astimezone(BEIRUT).date() > target_day + timedelta(days=policy["outcome_grace_days"])
        reason = attempt["status"] if attempt else "no_match_attempt"
        if outcome:
            prices = {"Hybrid": outcome["forecast"], **spec["score_protocol"]["baselines"]}
            if include_research and spec.get("shadow_zero_domestic_lag1_price") is not None:
                prices["Zero latest domestic change"] = spec["shadow_zero_domestic_lag1_price"]
            candidate = dict(outcome, prices=prices)
            prior = cases_by_day.get(outcome["day"])
            # Distinct outcomes across evidence levels. For competing origins,
            # use the earliest precommitted ledger ID, independent of error.
            if prior is None:
                cases_by_day[outcome["day"]] = candidate
            status = "matched" if prior is None else "duplicate_target"
        elif reason in {"conflict", "anchor_revised"}:
            status = "disputed"
        elif reason in {"gap", "record_may_precede_forecast", "endpoint_not_observed_in_time"} or (
                expired and reason in {"missing_endpoint_observation", "missing_calendar_witness", "unconfirmed"}):
            status = "coverage_gap"
        else:
            status = "expired" if expired else "pending"
        counts[status] += 1
        entries.append(dict(forecast_id=fid, issued_at=row["created_at"], expected_date=target_day.isoformat(),
                            recorded_date=outcome["day"] if outcome else None, status=status, reason=reason,
                            model_version=row["model_version"], snapshot_id=row["snapshot_id"],
                            base_price=row["base_price"], forecast=row["predicted_price"],
                            actual=outcome["actual"] if outcome else None,
                            evidence=outcome["kind"] if outcome else None))
    cases = list(cases_by_day.values())
    comparisons = []
    models = ["No change", "Last change"]
    if include_research:
        models.append("Zero latest domestic change")
    for name in models:
        sample = [case for case in cases if name in case["prices"]]
        if sample:
            comparisons.extend(dict(_metrics(sample, model, policy["direction_deadband_lbp"]), comparison=name)
                               for model in ("Hybrid", name))
    return dict(version=policy["version"], starts_at=policy["starts_at"], counts=dict(counts),
                comparisons=comparisons, entries=entries)
