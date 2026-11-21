"""Measured prospective performance and operating alerts, without model promotion."""
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
import sqlite3

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from lebanon_fuel.dashboard.data import anchors, market_and_prices
from lebanon_fuel.market.catalog import SERIES
from lebanon_fuel.storage.baseline import BASELINE_CONFIG
from lebanon_fuel.validation.decision_tracking import protocol_start
from .state import now


def alert(code, message, severity="warning"):
    return {"code": code, "severity": severity, "message": message}


def metric_group(rows):
    """Latest actual revisions only. All errors are forecast minus actual in LBP/20L."""
    actual = rows.actual_change.to_numpy(float)
    predicted = rows.predicted_change.to_numpy(float)
    errors = predicted - actual
    intervals = rows.interval_low.notna() & rows.interval_high.notna()
    bounded = rows[intervals]
    distributions = [(json.loads(row.probabilities_json), int(np.sign(row.actual_change)) + 1)
                     for row in rows.itertuples() if row.probabilities_json]
    q = np.array([r[0] for r in distributions])
    y = np.array([r[1] for r in distributions], dtype=int)
    reliability = []
    if len(q):
        for k, label in enumerate(("decrease", "no_change", "increase")):
            for b in range(5):
                use = np.minimum((q[:, k] * 5).astype(int), 4) == b
                if use.any():
                    reliability.append(dict(event=label, bin=b, n=int(use.sum()),
                        predicted=float(q[use, k].mean()), observed=float((y[use] == k).mean())))
    ece = max((sum(r["n"] * abs(r["predicted"] - r["observed"]) for r in reliability
                   if r["event"] == label) / len(q) for label in ("decrease", "no_change", "increase")), default=None) if len(q) else None
    nominal = {json.loads(t).get("interval_nominal") for t in bounded.target_json}
    return dict(n=len(rows), distinct_official_decisions=rows.decision_key.nunique(),
        first_origin=rows.origin.min(), last_origin=rows.origin.max(),
        mae_lbp=float(np.abs(errors).mean()), rmse_lbp=float(np.sqrt((errors**2).mean())),
        bias_lbp=float(errors.mean()), directional_accuracy=float((np.sign(actual) == np.sign(predicted)).mean()),
        no_change_accuracy=float(((actual == 0) == (predicted == 0)).mean()),
        no_change_baseline_mae_lbp=float(np.abs(actual).mean()),
        interval_n=len(bounded), interval_nominal=next(iter(nominal)) if len(nominal) == 1 else None,
        interval_coverage=float(((bounded.interval_low <= bounded.actual_change) &
                               (bounded.actual_change <= bounded.interval_high)).mean()) if len(bounded) else None,
        interval_width_lbp=float((bounded.interval_high - bounded.interval_low).mean()) if len(bounded) else None,
        probability_n=len(q), brier_multiclass=float(((q - np.eye(3)[y])**2).sum(axis=1).mean()) if len(q) else None,
        maximum_class_ece=ece, probability_reliability=reliability)


def prospective_performance(path, thresholds, *, start=""):
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        rows = pd.read_sql_query("""
            SELECT f.*, e.actual_change, e.prediction_error, o.decision_key
            FROM forecasts f JOIN evaluations e ON e.forecast_id=f.id
            JOIN outcomes o ON o.id=e.outcome_id
            WHERE f.mode IN ('prospective','prospective_research') AND e.kind='official_match'
            AND f.origin >= ? AND f.created_at >= ?
            AND e.id=(SELECT MAX(id) FROM evaluations WHERE forecast_id=f.id AND kind='official_match')
            ORDER BY f.origin,f.id
        """, db, params=(start, start))
    groups, alerts = [], []
    for (mode, model, horizon), group in rows.groupby(["mode", "model_version", "horizon"]):
        # Monitoring decision uses one latest issuance per observed official decision,
        # not an inflated count from hourly reissues or multiple calendar endpoints.
        recent = group.drop_duplicates("decision_key", keep="last").tail(thresholds["window_outcomes"])
        metrics = metric_group(recent)
        groups.append(dict(mode=mode, model_version=model, horizon=horizon,
                           all_issuances=metric_group(group), monitoring_window=metrics))
        if metrics["distinct_official_decisions"] < thresholds["minimum_outcomes"]:
            alerts.append(alert("insufficient_outcomes", f"{model}/{horizon} has too few distinct official outcomes for monitoring conclusions."))
            continue
        reasons = []
        if metrics["mae_lbp"] > thresholds["mae_review_lbp"]:
            reasons.append("absolute error exceeds operating limit")
        if metrics["mae_lbp"] > metrics["no_change_baseline_mae_lbp"] * 1.10:
            reasons.append("MAE exceeds the no-change baseline by more than 10%")
        if abs(metrics["bias_lbp"]) > thresholds["absolute_bias_review_lbp"]:
            reasons.append("persistent signed bias exceeds operating limit")
        if metrics["directional_accuracy"] < thresholds["direction_review_below"]:
            reasons.append("directional accuracy below review threshold")
        if metrics["interval_n"] >= thresholds["minimum_outcomes"]:
            nominal = metrics["interval_nominal"]
            if nominal is None or abs(metrics["interval_coverage"] - nominal) > thresholds["coverage_tolerance"]:
                reasons.append("interval calibration needs review")
        if metrics["probability_n"] >= thresholds["minimum_outcomes"] and metrics["maximum_class_ece"] > thresholds["probability_ece_review_above"]:
            reasons.append("direction probabilities need recalibration review")
        if reasons:
            alerts.append(alert("model_review_required", f"{model}/{horizon}: " + "; ".join(reasons)))
    return dict(evaluated_forecasts=len(rows), groups=groups, alerts=alerts,
                automatic_retraining=False, automatic_model_replacement=False)


def policy_headlines(root, db_path):
    """Inspect captured official landing-page headlines. Never infer enacted law."""
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        row = db.execute("""SELECT raw_path,retrieved_at FROM captures WHERE source_id='ministry'
            AND url='https://energyandwater.gov.lb/ar/prices' AND http_status=200 ORDER BY id DESC LIMIT 1""").fetchone()
    if not row:
        return {"status": "unavailable", "items": []}
    soup = BeautifulSoup((root / row[0]).read_bytes(), "html.parser", from_encoding="utf-8")
    words = ("محروقات", "بنزين", "رسوم", "رسم", "ضريب", "نفط", "fuel", "tax", "gasoline")
    items = sorted({(a.get("href", ""), a.get_text(" ", strip=True)) for a in soup.select("a[href]")
                    if "/details/" in a["href"] and any(w in a.get_text(" ", strip=True).lower() for w in words)})
    return dict(status="captured_headlines_only", retrieved_at=row[1],
                items=[dict(url=u, title=t, publication_timestamp=None) for u, t in items],
                note="Changes require original-document review. This is not complete policy surveillance.")


def build(root, settings, operations, previous=None):
    cfg = settings
    db_path = root / cfg["storage"]["database"]
    snap = market_and_prices(root, db_path)
    at = now()
    limits = operations["monitoring"]
    prices = snap["prices"]
    latest, _ = anchors(prices)
    alerts = []
    conflicts = sum(r["verification_status"] == "conflict" for r in prices)
    quality = dict(conflict_dates=conflicts, missing_publication_clocks=snap["missing_clocks"][0],
                   missing_effective_dates=snap["missing_clocks"][1], candidate_dates=len(prices),
                   suspicious_dates=sum(any("suspicious" in i for i in r["issues"]) for r in prices))
    if conflicts:
        alerts.append(alert("conflicting_prices", f"{conflicts} source dates remain quarantined for conflicting prices."))
    if previous:
        if conflicts > previous.get("data_quality", {}).get("conflict_dates", 0):
            alerts.append(alert("quality_deterioration", "The number of unresolved source conflicts increased."))
    if not latest or (at.date() - datetime.fromisoformat(latest["source_date"]).date()).days > limits["verified_anchor_maximum_age_days"]:
        alerts.append(alert("stale_verified_anchor", "The latest verified-tier record is too old for a current-price assumption."))
    for row in snap["runs"].itertuples():
        if row.status != "success":
            alerts.append(alert("source_failure", f"{row.source_id}: last collection is {row.status}."))
    for sid, row in snap["market"]["series"].items():
        if row["status"] != "available":
            alerts.append(alert("market_unavailable", f"{SERIES[sid].title}: {row['status']}."))
        if abs(row.get("return_7_calendar_days") or 0) >= limits["weekly_market_move_review"]:
            alerts.append(alert("unusual_market_move", f"{sid}: absolute seven-day move exceeds the configured review threshold."))
    policy_path = root / "config/policy_review.json"
    policy = json.loads(policy_path.read_text())
    policy_hash = sha256(policy_path.read_bytes()).hexdigest()
    reviewed = datetime.fromisoformat(policy["reviewed_at"]) if policy.get("reviewed_at") else None
    valid_review = (reviewed is not None and reviewed.utcoffset() is not None and reviewed <= at and
                    (at - reviewed).days <= limits["policy_review_maximum_age_days"] and
                    policy.get("status") == "reviewed" and policy.get("reviewer") and policy.get("evidence_urls"))
    if not valid_review:
        alerts.append(alert("policy_review_required", "Current pricing policy needs a dated, evidence-backed human review."))
    if previous and previous.get("policy_review_sha256") != policy_hash:
        alerts.append(alert("policy_parameters_changed", "The policy review file changed. Revalidation is required before issuance."))
    headlines = policy_headlines(root, db_path)
    previous_urls = {item["url"] for item in (previous or {}).get("policy_headlines", {}).get("items", [])}
    if previous and any(item["url"] not in previous_urls for item in headlines["items"]):
        alerts.append(alert("new_policy_headline", "New fuel/tax headlines appeared on the captured ministry page. Review the original instruments."))
    start = protocol_start(root) if (root / BASELINE_CONFIG).is_file() else ""
    performance = prospective_performance(root / cfg["validation"]["forecast_ledger"], limits, start=start)
    alerts.extend(performance["alerts"])
    if performance["evaluated_forecasts"] == 0:
        alerts.append(alert("no_prospective_accuracy", "No numerical prospective forecasts have verified settled outcomes. Live accuracy is unavailable."))
    decision = json.loads((root / cfg["validation"]["decision_file"]).read_text())
    if not decision.get("production_approved"):
        alerts.append(alert("production_withheld", "Part 6 rejects production approval for all selected horizons."))
    return dict(generated_at=at.isoformat(), data_quality=quality, alerts=alerts,
                latest_verified_record=latest, market=snap["market"], performance=performance,
                policy_review_sha256=policy_hash, policy_review=policy, policy_headlines=headlines,
                production_approved=decision.get("production_approved", False),
                thresholds=limits, threshold_status="operating_review_rules_not_statistical_certification")
