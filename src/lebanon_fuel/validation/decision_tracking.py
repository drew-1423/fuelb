"""Append-only next-update scoring and prospective Hybrid interval validation."""
from bisect import bisect_right
from contextlib import closing
from datetime import date
import json
from math import ceil
from collections import Counter
import math
from pathlib import Path
import sqlite3
from statistics import mean

from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE, VERIFIED
from .decision_events import event_clocks, stamp
from .ledger import ForecastLedger, canonical, hashed, now
from .provisional import select_target
from lebanon_fuel.storage.database import sqlite_connection

FAMILY = "G_hybrid"
MAX_GAP_DAYS = 7
MIN_CALIBRATION = 30
MIN_COVERAGE_TEST = 20
INTERVAL_COVERAGE = .90
RECENT_RESIDUALS = 60
ATTEMPT_CHANNEL = "supplier_next_update"
SUPPLIER_STATUS = "supplier_match"
PUBLICATION_STATUS = {
    "supplier_match": "IPT and another dated source agree. Official review pending.",
    "no_new_record": "Waiting for a newer dated price.",
    "record_may_precede_forecast": "The first new record could have been published before issuance.",
    "anchor_revised": "The starting price was revised or disputed.",
    "gap": "More than seven days separate the starting price and next record.",
    "conflict": "The next recorded price is disputed.",
    "unconfirmed": "The next record is waiting for matching dated price sources.",
    "not_matured": "The calendar endpoint has not matured yet.",
    "missing_calendar_witness": "A later corroborated record is required to confirm the endpoint observation.",
    "missing_endpoint_observation": "No corroborated observation exists on the calendar endpoint date.",
    "endpoint_not_observed_in_time": "Endpoint quotes were not both captured before the forecast cutoff.",
}

# Legacy complete runs still contribute genuine Hybrid observations. Missing rows
# never qualify as a complete run, even if the row for the next decision exists.
BATCH = """
WITH live AS (
    SELECT * FROM forecasts
    WHERE mode IN ('prospective', 'prospective_research') AND created_at >= :start AND origin >= :start
), complete AS (
    SELECT run_id, origin FROM live GROUP BY run_id, origin
    HAVING COUNT(*) = 8 AND COUNT(DISTINCT horizon) = 8
       AND SUM(horizon IN ('decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30')) = 8
       AND (SUM(status = 'issued' AND predicted_price IS NOT NULL) = 8
         OR SUM(status = 'abstained') = 8
         OR SUM(json_extract(target_json, '$.pinned_family') = 'G_hybrid') = 8)
)
"""
FORECASTS = """
    SELECT f.*, json_extract(m.metadata_json, '$.family') AS family
    FROM live f JOIN complete c USING (run_id, origin)
    JOIN models m ON f.model_version=m.id
    WHERE f.horizon='decision_1'
"""
ATTEMPT = """
    SELECT * FROM match_attempts
    WHERE forecast_id=:id AND json_extract(details_json, '$.channel')='supplier_next_update'
      AND (:cutoff IS NULL OR created_at < :cutoff)
    ORDER BY id DESC LIMIT 1
"""
VERSION_QUERY = BATCH + """
    SELECT f.id AS forecast_id, f.horizon, f.origin, f.created_at AS issued_at, f.target_json, f.base_price,
           f.predicted_price, f.predicted_change, o.*, e.created_at AS scored_at, e.kind,
           a.status AS supplier_status, a.details_json AS supplier_details, a.created_at AS supplier_reviewed_at
    FROM live f JOIN complete c USING (run_id, origin)
    JOIN models m ON f.model_version=m.id
    JOIN evaluations e ON e.forecast_id=f.id AND e.kind IN ('official_match','provisional_match')
    JOIN outcomes o ON o.id=e.outcome_id
    LEFT JOIN match_attempts a ON a.id=(
        SELECT MAX(id) FROM match_attempts WHERE forecast_id=f.id
        AND json_extract(details_json, '$.channel')='supplier_next_update' AND created_at < :cutoff
    )
    WHERE f.status='issued'
      AND json_extract(m.metadata_json,'$.family')='G_hybrid'
      AND e.created_at < :cutoff
      AND e.id=(SELECT MAX(id) FROM evaluations WHERE forecast_id=f.id AND kind=e.kind AND created_at < :cutoff)
    ORDER BY f.created_at, f.id
"""


def protocol_start(root):
    protocol = json.loads((Path(root) / "config/prospective_holdout.json").read_text())
    return max(stamp(protocol["prospective_start"]), stamp(protocol["sealed_at"])).isoformat()


def first_new_record(forecast, records, days):
    target = json.loads(forecast["target_json"])
    base_day = target.get("base_source_date")
    if not base_day or base_day not in records:
        return "anchor_revised", None
    base = records[base_day]
    if base.get("price_lbp_20l") != forecast["base_price"] or base["verification_status"] == "conflict":
        return "anchor_revised", None
    index = bisect_right(days, base_day)
    if index == len(days):
        return "no_new_record", None
    day = days[index]
    row = records[day]
    if row["verification_status"] == "conflict":
        return "conflict", row
    issued_day = max(stamp(forecast["origin"]), stamp(forecast["created_at"])).astimezone(BEIRUT).date()
    candidate_date = date.fromisoformat(day)
    if candidate_date <= issued_day:
        return "record_may_precede_forecast", row
    if (candidate_date - date.fromisoformat(base_day)).days > MAX_GAP_DAYS:
        return "gap", row
    return "candidate", row


def supplier_proof(source, record):
    if record["verification_status"] not in VERIFIED | {PROVISIONAL_PRICE}:
        return None
    rows = source.db.execute("""
        SELECT id, source_id, price_lbp_20l, source_url, first_retrieved_at
        FROM observations WHERE source_date=? AND is_valid=1 AND source_id IN ('ipt','totalenergies','taqtek')
        ORDER BY first_retrieved_at, id
    """, (record["source_date"],)).fetchall()
    selected = {}
    for row in rows:
        if row["price_lbp_20l"] != record["price_lbp_20l"]:
            return None
        selected.setdefault(row["source_id"], dict(row))
    partner = "totalenergies" if "totalenergies" in selected else "taqtek"
    return [selected["ipt"], selected[partner]] if "ipt" in selected and partner in selected else None


def settle_supplier_updates(root, cfg, source):
    records = {record["source_date"]: record for record in source.ledger()}
    days = sorted(records)
    counts = {}
    checked = {}
    with closing(ForecastLedger(root / cfg["validation"]["forecast_ledger"])) as ledger:
        forecasts = ledger.db.execute(BATCH + FORECASTS.replace("WHERE f.horizon='decision_1'", "WHERE 1=1") + " AND f.status='issued'",
                                      {"start": protocol_start(root)}).fetchall()
        for forecast in forecasts:
            if forecast["family"] != FAMILY:
                continue
            status, record, payload = select_target(forecast, records, days, source)
            details = {"channel": ATTEMPT_CHANNEL, "horizon": forecast['horizon']}
            if record:
                details.update(source_date=record['source_date'], source_revision_id=record['revision_id'])
            if status == 'candidate':
                sources = [s for item in payload['path'] + ([payload['witness']] if payload['witness'] else []) for s in item['sources']]
                available = max(stamp(s['first_retrieved_at']) for s in sources)
                if available <= stamp(now()):
                    payload.update(details)
                    oid = ledger.outcome('supplier:'+record['source_date'], available.isoformat(), record['price_lbp_20l'],
                        payload['sources'][0]['source_url'], 'supplier_agreement', hashed(payload), payload,
                        source_revision_id=record['revision_id'])
                    ledger._score(forecast['id'], oid, 'provisional_match')
                    details['outcome_id'] = oid
                    status = SUPPLIER_STATUS
                else:
                    status = 'not_matured'
            previous = ledger.db.execute(ATTEMPT, {"id": forecast["id"], "cutoff": None}).fetchone()
            payload = canonical(details)
            if previous is None or (previous["status"], previous["details_json"]) != (status, payload):
                with ledger.db:
                    ledger.db.execute("INSERT INTO match_attempts(created_at,forecast_id,status,details_json) VALUES (?,?,?,?)",
                                      (now(), forecast["id"], status, payload))
            counts[status] = counts.get(status, 0) + 1
    return counts


def _matched(db, start, at, *, selected_ids=None):
    cases = {}
    cutoff = stamp(at)
    for row in db.execute(VERSION_QUERY, {"start": start, "cutoff": cutoff.isoformat()}):
        spec = json.loads(row["target_json"])
        if selected_ids is not None:
            if row["forecast_id"] not in selected_ids:
                continue
        elif spec.get("score_protocol"):
            continue  # The historical track retains its original selection rule.
        cohort = "provisional" if spec.get("anchor_verification") == PROVISIONAL_PRICE else "government_backed"
        if spec.get("anchor_verification") not in VERIFIED | {PROVISIONAL_PRICE}:
            continue
        known = max(stamp(row["scored_at"]), stamp(row["available_at"]))
        origin = max(stamp(row["origin"]), stamp(row["issued_at"]))
        if known >= cutoff or origin >= cutoff:
            continue
        if row["kind"] == "provisional_match":
            state = json.loads(row["supplier_details"] or "{}")
            if row["supplier_status"] != SUPPLIER_STATUS or state.get("outcome_id") != row["id"]:
                continue
            known = max(known, stamp(row["supplier_reviewed_at"]))
            if known >= cutoff:
                continue
            day = json.loads(row["payload_json"])["source_date"]
            if date.fromisoformat(day) <= origin.astimezone(BEIRUT).date():
                continue
        else:
            publication, effective = event_clocks(row)
            if row["verification_status"] != "document_verified" or not publication or not effective:
                continue
            if row['horizon'].startswith('decision_'):
                if not publication.after(origin):
                    continue
                day = publication.lower.astimezone(BEIRUT).date().isoformat()
            else:
                endpoint = stamp(spec['endpoint'])
                if not publication.by(endpoint) or not effective.by(endpoint) or endpoint >= cutoff:
                    continue
                day = endpoint.astimezone(BEIRUT).date().isoformat()
        key = (row["kind"], cohort, spec.get("artifact_sha256"), row["horizon"], day)
        if selected_ids is not None:
            key = (row["kind"], row["forecast_id"])
        cases[key] = dict(kind=row["kind"], cohort=cohort, artifact=spec.get("artifact_sha256"),
                          horizon=row["horizon"], label_end=known,
                          day=day, known=known, origin=origin, forecast_id=row["forecast_id"],
                          forecast=row["predicted_price"], actual=row["price"], base=row["base_price"],
                          predicted_change=row["predicted_change"], source_url=row["source_url"],
                          outcome_id=row["id"])
    return sorted(cases.values(), key=lambda row: (row["origin"], row["forecast_id"]))


def _radius(sample, coverage=INTERVAL_COVERAGE):
    errors = sorted(abs(row['actual'] - row['forecast']) for row in sample)
    rank = ceil((len(errors)+1)*coverage)
    if not errors or rank > len(errors):
        return None
    return max(5000.0, errors[rank-1])


def _clock(value):
    return stamp(value.isoformat() if hasattr(value, 'isoformat') else value)


def _independent(cases):
    """Non-overlapping forecast-to-label-information intervals, not first-day sampling."""
    result = []
    end = None
    for row in sorted(cases, key=lambda r: _clock(r['origin'])):
        origin = _clock(row['origin'])
        if end is not None and origin <= end:
            continue
        result.append(row)
        end = max(_clock(row.get('label_end',row['known'])), _clock(row['known']))
    return result


def calibration(cases, cohort, artifact, horizon='decision_1', at=None):
    cutoff = _clock(at or now())
    strata = {}
    for kind in ('official_match','provisional_match'):
        # Repeated runs for a target date contribute once, using the latest
        # eligible forecast without rewriting the earlier immutable forecasts.
        unique = {}
        for row in cases:
            if (row['kind'] == kind and row['cohort'] == cohort and row['artifact'] == artifact
                    and row.get('horizon','decision_1') == horizon
                    and _clock(row['known']) < cutoff and _clock(row['origin']) < cutoff
                    and math.isfinite(row['actual']) and math.isfinite(row['forecast'])):
                key = row.get('day',str(row['origin']))
                if key not in unique or _clock(row['origin']) > _clock(unique[key]['origin']):
                    unique[key] = row
        eligible = _independent(list(unique.values()))
        sample = eligible[-RECENT_RESIDUALS:]
        levels = {}
        for coverage in (.8,.9):
            checks = []
            for case in eligible:
                earlier = [r for r in eligible if _clock(r['origin']) < _clock(case['origin'])
                           and _clock(r['known']) < _clock(case['origin'])]
                if len(earlier) >= MIN_CALIBRATION:
                    radius = _radius(earlier[-RECENT_RESIDUALS:],coverage)
                    checks.append((abs(case['actual']-case['forecast']) <= radius, 2*radius))
            checks = checks[-RECENT_RESIDUALS:]
            measured = mean(c[0] for c in checks) if checks else None
            lower, upper = (.70,.90) if coverage == .8 else (.80,.98)
            ready = len(sample) >= MIN_CALIBRATION and len(checks) >= MIN_COVERAGE_TEST and lower <= measured <= upper
            reasons = []
            if len(sample) < MIN_CALIBRATION: reasons.append('insufficient_nonoverlapping_matured_calibration_cases')
            if len(checks) < MIN_COVERAGE_TEST: reasons.append('insufficient_chronological_coverage_tests')
            if measured is not None and not lower <= measured <= upper: reasons.append('empirical_coverage_outside_release_tolerance')
            levels[str(int(coverage*100))] = dict(nominal=coverage, calibration_n=len(sample), evaluation_n=len(checks),
                empirical_coverage=measured, mean_evaluated_width_lbp=mean(c[1] for c in checks) if checks else None,
                radius=_radius(sample,coverage) if ready else None, status='released' if ready else 'withheld', reasons=reasons)
        strata[kind] = dict(levels=levels, eligible_n=len(eligible), raw_distinct_targets=len(unique))
    # Outcome evidence quality is independent of starting-price evidence. Never
    # pool official effective targets with conditional supplier targets.
    chosen = 'official_match'
    if strata['official_match']['levels']['90']['radius'] is None:
        if (strata['provisional_match']['levels']['90']['radius'] is not None
                or strata['provisional_match']['eligible_n'] > strata['official_match']['eligible_n']):
            chosen = 'provisional_match'
    selected = strata[chosen]; outer=selected['levels']['90']; inner=selected['levels']['80']
    return dict(cohort=cohort,horizon=horizon,artifact=artifact,evidence_category=chosen,
        calibration_n=outer['calibration_n'],evaluation_n=outer['evaluation_n'],empirical_coverage=outer['empirical_coverage'],
        minimum_calibration_n=MIN_CALIBRATION,minimum_evaluation_n=MIN_COVERAGE_TEST,
        nominal=.9,radius=outer['radius'],radius_80=inner['radius'],levels=selected['levels'],evidence_strata=strata,
        policy='Separate outcome-evidence strata; exact horizon/artifact/anchor cohort; nonoverlapping intervals; strictly earlier matured labels; trailing 60 residuals',
        target_limitation='Supplier evaluation is conditional on recorded corroborated quotes and does not certify official publication/effective times' if chosen=='provisional_match' else 'Reviewed complete official outcome sequence')


def _read(path):
    db = sqlite_connection(path, readonly=True)
    db.row_factory = sqlite3.Row
    return closing(db)


def apply_live_calibration(root, ledger_path, forecasts, at):
    from .live_score import protocol, selections

    policy = protocol(root)
    with _read(ledger_path) as db:
        if policy and _clock(at) >= stamp(policy["starts_at"]):
            selected, _ = selections(db, policy, at)
            cases = _matched(db, stamp(policy["starts_at"]).isoformat(), at,
                             selected_ids={row["id"] for row, _ in selected.values()})
        else:
            cases = _matched(db, protocol_start(root), at)
    for forecast in forecasts:
        if forecast.get("pinned_family") != FAMILY or forecast["status"] != "issued":
            continue
        for field in ("interval_nominal", "interval_80", "interval_80_nominal"):
            forecast.pop(field, None)
        forecast.update(interval=None, probabilities=None,
                        uncertainty="Waiting for a validated prediction range from live outcomes.")
        cohort = 'provisional' if forecast['anchor_verification'] == PROVISIONAL_PRICE else 'government_backed'
        measured = calibration(cases,cohort,forecast['artifact_sha256'],forecast['horizon'],at=at)
        forecast['public_calibration'] = measured
        change,base = forecast['predicted_change'],forecast['base_price']
        if measured['radius'] is not None:
            radius = measured['radius']
            forecast.update(interval=[max(1-base,change-radius),change+radius],interval_nominal=.9,
                uncertainty=f"90% pointwise prediction range conditional on {measured['evidence_category']} evidence; empirical coverage {measured['empirical_coverage']:.0%} on {measured['evaluation_n']} nonoverlapping tests.")
        if measured['radius_80'] is not None:
            radius = measured['radius_80']
            forecast.update(interval_80=[max(1-base,change-radius),change+radius],interval_80_nominal=.8)


def dashboard_evidence(root, path):
    start = protocol_start(root)
    with _read(path) as db:
        cases = [r for r in _matched(db, start, now()) if r.get("horizon", "decision_1") == "decision_1"]
        forecasts = db.execute(BATCH + FORECASTS + " ORDER BY f.id DESC", {"start": start}).fetchall()
        issued = [f for f in forecasts if f["status"] == "issued" and f["family"] == FAMILY]
        checks = []
        official = {r["forecast_id"] for r in cases if r["kind"] == "official_match"}
        for f in issued[:12]:
            attempt = db.execute(ATTEMPT, {"id": f["id"], "cutoff": None}).fetchone()
            detail = json.loads(attempt["details_json"]) if attempt else {}
            checks.append(dict(issued=f["created_at"], start_date=json.loads(f["target_json"]).get("base_source_date"),
                               target_date=detail.get("source_date"), status="Official outcome scored" if f["id"] in official
                               else PUBLICATION_STATUS.get(attempt["status"], "Waiting for the next refresh") if attempt
                               else "Waiting for the next refresh"))
    checks = [dict(item, issued=stamp(item["issued"]).astimezone(BEIRUT).strftime("%d %b %Y %H:%M")) for item in checks]
    return dict(complete=len(forecasts), issued=len(issued), checks=checks,
                cases=[{k: v for k, v in case.items() if k not in ("origin", "known")} for case in cases])
