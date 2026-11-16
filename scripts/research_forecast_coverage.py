"""Build a separate decision-date research cohort and compare low-dimensional models."""
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from hashlib import file_digest
from io import BytesIO
import json
from pathlib import Path
import sqlite3

from bs4 import BeautifulSoup
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE, VERIFIED
from lebanon_fuel.forecasting.data import MarketFeatures, features_at
from lebanon_fuel.forecasting.live import model_prediction
from lebanon_fuel.forecasting.models import fit_model
from lebanon_fuel.forecasting.pipeline import load_bundle
from lebanon_fuel.forecasting.uncertainty import direction_class
from lebanon_fuel.market.catalog import BARREL_LITERS
from lebanon_fuel.market.store import MarketStore

START = "2023-05-12"
FIT_END = "2026-05-31"
EVAL_END = "2026-11-10"
VALIDATION_START = "2024-06-01"
RBOB_END = "2024-04-05"
MIN_TRAIN = 24
MAX_GAP = 14
ARCHIVE = VERIFIED | {"government_archive"}
RESEARCH_MATCH = ARCHIVE | {PROVISIONAL_PRICE, "ipt_lebvote_match"}
MARKETS = ("nyh_gasoline", "brent_spot", "italy_gasoline_ex_tax", "greece_gasoline_ex_tax")
MODELS = {
    "EIA Brent": ["brent"],
    "EIA gasoline": ["gasoline"],
    "EIA gasoline + Brent": ["gasoline", "brent"],
    "EIA + last domestic change": ["gasoline", "brent", "last_change"],
    "EIA + European retail": ["gasoline", "brent", "italy", "greece"],
}


def digest(path):
    with path.open("rb") as file:
        return file_digest(file, "sha256").hexdigest()


def lebvote_rows(raw):
    """Read published chart date/value pairs. The two coordinates are display only."""
    chart = BeautifulSoup(raw, "html.parser").select_one("[data-chart]")
    if chart is None:
        raise ValueError("No public chart in LebVote capture")
    payload = json.loads(chart["data-chart"])
    if payload.get("unit") != "ل.ل. للصفيحة (20 ليتر)":
        raise ValueError("LebVote unit was not LBP per 20 liters")
    rows = {}
    for _, _, label, price in payload["pts"]:
        date.fromisoformat(label)
        if type(price) is not int or price <= 0 or label in rows:
            raise ValueError(f"Invalid or duplicated LebVote observation for {label}")
        rows[label] = price
    if not rows:
        raise ValueError("Empty LebVote chart")
    return rows


def rbob_rows(raw):
    table = pd.read_excel(BytesIO(raw), sheet_name="Data 1", header=None)
    if table.iat[1, 1] != "EER_EPMRR_PE1_Y35NY_DPG":
        raise ValueError("Unexpected EIA workbook series")
    rows = []
    for when, value in table.iloc[3:, :2].itertuples(index=False, name=None):
        if pd.isna(value):
            continue
        day = pd.Timestamp(when).date().isoformat()
        if not np.isfinite(value) or value <= 0 or day > RBOB_END:
            raise ValueError(f"Unexpected EIA RBOB observation for {day}")
        rows.append({"observation_date": day, "value": value * 42, "available_at": day + "T23:59:59+00:00"})
    if not rows or list(row["observation_date"] for row in rows) != sorted(
            {row["observation_date"] for row in rows}):
        raise ValueError("Empty, unordered or duplicate EIA RBOB observations")
    return rows


def reconcile_research(ledger, ipt, alternative):
    """Add exact matches only. Unresolved dates remain in the sequence as barriers."""
    counts = Counter()
    findings = []
    active = {r["source_date"]: r for r in ledger if START <= r["source_date"] <= EVAL_END}
    for day, observed in sorted(alternative.items()):
        if not START <= day <= EVAL_END:
            continue
        values = ipt.get(day, set())
        original = active.get(day, {})
        status = original.get("verification_status")
        candidate_prices = set(original.get("candidate_values", []))
        if not values:
            result = "no_ipt_match"
            active.setdefault(day, {"source_date": day, "verification_status": "unmatched_alternative", "price_lbp_20l": None, "revision_id": None})
        elif values != {observed} or status == "conflict" or candidate_prices - {observed}:
            result = "conflict"
            active[day] = dict(original, source_date=day, verification_status="research_conflict")
        elif status not in ARCHIVE and status != PROVISIONAL_PRICE:
            result = "new_research_corroboration"
            active[day] = dict(original, source_date=day, verification_status="ipt_lebvote_match", price_lbp_20l=observed)
        else:
            result = "already_corroborated"
        counts[(day[:4], result)] += 1
        findings.append(dict(source_date=day, lebvote_lbp_20l=observed, ipt_lbp_20l="|".join(map(str, sorted(values))),
                             previous_status=status, research_disposition=result))
    return sorted(active.values(), key=lambda r: r["source_date"]), counts, findings


def local_clock(day, *, following=False):
    day = date.fromisoformat(day) + timedelta(days=int(following))
    return datetime.combine(day, time(3), BEIRUT).astimezone(timezone.utc).isoformat()


class SeriesWindow:
    def __init__(self, rows, sessions, lag=0, max_age=8):
        self.sessions, self.max_age = sessions, max_age
        self.rows = []
        for row in rows:
            day = row["observation_date"]
            lag_day = date.fromisoformat(day) + timedelta(days=lag)
            assumed = max(f"{lag_day.isoformat()}T23:59:59+00:00", row["available_at"])
            self.rows.append((assumed, day, row["value"]))
        self.rows.sort()
        self.times = [row[0] for row in self.rows]

    def at(self, origin):
        end = bisect_left(self.times, origin)
        if end < self.sessions:
            return np.nan
        window = self.rows[end - self.sessions:end]
        # Release order and observation chronology can diverge for revised source rows.
        days = sorted(date.fromisoformat(row[1]) for row in window)
        origin_day = datetime.fromisoformat(origin).astimezone(BEIRUT).date()
        if (origin_day - days[-1]).days > self.max_age or (days[-1] - days[0]).days > 10:
            return np.nan
        return np.mean([row[2] for row in window])

    def move(self, origin, previous_origin):
        return self.at(origin) - self.at(previous_origin)


def build_cases(rows, market, statuses):
    cases = []
    for previous, base, target in zip(rows, rows[1:], rows[2:]):
        if {row["verification_status"] for row in (previous, base, target)} - statuses:
            continue
        days = [row["source_date"] for row in (previous, base, target)]
        if max((date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(days, days[1:])) > MAX_GAP:
            continue
        origin, last_origin = local_clock(days[1], following=True), local_clock(days[0], following=True)
        if origin >= local_clock(days[2], following=True):
            continue
        last, current, actual = (row["price_lbp_20l"] for row in (previous, base, target))
        case = dict(origin=origin, origin_date=origin_date(origin), base_source_date=days[1],
                    target_date=days[2], label_end=local_clock(days[2], following=True),
                    base_price=current, actual_price=actual, actual_change=actual-current, last_change=current-last,
                    source_cohort="government_archive_path" if all(r["verification_status"] in ARCHIVE
                                for r in (previous, base, target)) else "multiple_source_research_path")
        case.update({key: window.move(origin, last_origin) for key, window in market.items()})
        cases.append(case)
    return pd.DataFrame(cases)


def origin_date(origin):
    return datetime.fromisoformat(origin).astimezone(BEIRUT).date().isoformat()


def predict(train, test, columns):
    model = make_pipeline(StandardScaler(), Ridge(alpha=12.0))
    usable = train.dropna(subset=columns)
    if len(usable) < MIN_TRAIN:
        return pd.Series(index=test.index, dtype=float)
    model.fit(usable[columns], usable["actual_change"])
    forecast = test.dropna(subset=columns)
    return pd.Series(model.predict(forecast[columns]), index=forecast.index).reindex(test.index) if len(forecast) else pd.Series(index=test.index, dtype=float)


def walk_forward(cases, eligible, models):
    result = pd.DataFrame(index=eligible.index, columns=models, dtype=float)
    for origin in eligible["origin"].unique():
        block = eligible.loc[eligible["origin"].eq(origin)]
        past = cases.loc[cases["label_end"].lt(origin)]
        for name, columns in models.items():
            result.loc[block.index, name] = predict(past, block, columns)
    return result


def scores(cases, prediction):
    actual = cases.loc[prediction.index, "actual_change"]
    records = []
    for name in prediction:
        error = prediction[name] - actual
        records.append(dict(method=name, n=len(error), mae_lbp=float(error.abs().mean()),
                            rmse_lbp=float((error.pow(2).mean()) ** 0.5),
                            direction_hits=int((direction_class(prediction[name]) == direction_class(actual)).sum())))
    return records


def evaluate(archive, expanded):
    development = expanded.loc[expanded["target_date"].le(FIT_END)]
    validation = development.loc[development["origin_date"].ge(VALIDATION_START)]
    cv = walk_forward(development, validation, MODELS).dropna()
    if cv.empty:
        raise ValueError("No common pre-evaluation dates for feature selection")
    selection = scores(validation, cv)
    pick = min(selection, key=lambda row: row["mae_lbp"])["method"]
    cutoff = local_clock(FIT_END, following=True)
    development = development.loc[development["label_end"].lt(cutoff)]
    archive_training = archive.loc[archive["label_end"].lt(cutoff)]
    test = expanded.loc[expanded["origin_date"].gt(FIT_END)]
    evaluation = pd.DataFrame({name: predict(development, test, columns) for name, columns in MODELS.items()})
    evaluation["No price change"] = 0.0
    evaluation["Repeat last change"] = test["last_change"]
    evaluation["Selected model with original cohort"] = predict(archive_training, test, MODELS[pick])
    delayed = [f"{col}_delayed" if col in {"gasoline", "brent"} else col for col in MODELS[pick]]
    evaluation["Selected model with three-day spot lag"] = predict(development, test, delayed)

    common = evaluation.dropna()
    if common.empty:
        raise ValueError("No common evaluation dates")
    prediction_rows = test.loc[common.index, ["origin", "base_source_date", "target_date", "actual_price",
                                                "base_price", "actual_change", "source_cohort"]].join(common)
    early = expanded.loc[expanded["origin_date"].ge("2024-01-01") & expanded["target_date"].le(RBOB_END)]
    rbob_models = {"EIA spot on paired history": ["gasoline", "brent"], "RBOB on paired history": ["rbob", "brent"]}
    overlap = expanded.dropna(subset=["gasoline", "brent", "rbob"])
    paired_pilot = walk_forward(overlap, early, rbob_models).dropna()
    return dict(selected_pre_evaluation=pick, development_qualified=len(development), archive_training_qualified=len(archive_training),
                evaluation_candidates=len(test), evaluation_shared=len(common),
                validation_scores=selection, evaluation_scores=scores(test, common),
                shared_path_counts=prediction_rows["source_cohort"].value_counts().to_dict(),
                futures_pilot_scores=scores(early, paired_pilot) if not paired_pilot.empty else []), prediction_rows



def compare_hybrid(root, rows, training_cases, predictions, selected):
    """Use the exact deployed bundle, frozen before each candidate target origin."""
    policy = json.loads((root / "config/live_forecasting.json").read_text())
    candidate = next((item for item in policy["quantitative_candidates"]
                      if item["horizon"] == "decision_1" and item["family"] == "G_hybrid"), None)
    if not candidate:
        return {"status": "current_hybrid_not_configured"}
    folder = root / candidate["path"]
    if not (folder / "bundle.joblib").is_file():
        return {"status": "current_hybrid_bundle_missing"}
    artifact_sha = digest(folder / "bundle.joblib")
    if artifact_sha != candidate["artifact_sha256"]:
        raise ValueError("Live Hybrid bundle hash mismatch")
    bundle = load_bundle(folder)
    config = json.loads((root / "config/forecasting_research.json").read_text())
    config["target_statuses"] = sorted(RESEARCH_MATCH)
    # Preserve the existing model's feature definition and historical dataset
    # convention. This comparison has no strict historical capture clocks.
    positions = {row["source_date"]: i for i, row in enumerate(rows)}
    values, forecast_features, training_features = {}, {}, []
    with closing(MarketStore(root, readonly=True)) as store:
        market = MarketFeatures(store, config)
        def make_features(case):
            at = datetime.fromisoformat(case["origin"]).astimezone(BEIRUT)
            position = positions[case["base_source_date"]]
            values_at_origin = features_at(rows[:position + 1], position, at, market, config)
            if values_at_origin is None or not np.isfinite(values_at_origin["x_structural_delta_lbp_20l"]):
                return None
            return values_at_origin

        cutoff = local_clock(FIT_END, following=True)
        for _, case in training_cases.loc[training_cases["label_end"].lt(cutoff)].iterrows():
            features = make_features(case)
            if features is not None:
                training_features.append(dict(features, origin=case["origin"], label_end=case["label_end"],
                                              horizon="decision_1", partition="development",
                                              target_change_lbp_20l=case["actual_change"]))
        retrained = fit_model("G_hybrid", pd.DataFrame(training_features), config)

        for index, case in predictions.iterrows():
            if pd.Timestamp(bundle["fit_cutoff"]) >= pd.Timestamp(case["origin"]):
                continue
            features = make_features(case)
            if features is None:
                continue
            value = model_prediction(bundle, "G_hybrid", pd.DataFrame([features]))
            if np.isfinite(value) and case["base_price"] + value > 0:
                values[index] = value
                forecast_features[index] = features
    predictions["Current frozen Hybrid"] = pd.Series(values, dtype=float)
    forecasts = pd.DataFrame.from_dict(forecast_features, orient="index")
    predictions["Hybrid retrained on expanded data"] = pd.Series(
        retrained.predict(forecasts), index=forecasts.index, dtype=float) if len(forecasts) else np.nan
    names = ["Current frozen Hybrid", "Hybrid retrained on expanded data", selected,
             "Repeat last change", "No price change"]
    paired = predictions[names].dropna()
    return dict(status="completed", artifact_sha256=artifact_sha,
                expanded_hybrid_training_cases=len(training_features),
                current_hybrid_training_cases=bundle["models"]["G_hybrid"].extra.get("train_rows"),
                retrained_hybrid_residual_model=retrained.extra["residual_model"],
                paired_scores=scores(predictions, paired) if not paired.empty else [])




def availability(path, start):
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute("""
            SELECT f.status, f.reason_json, f.target_json
            FROM forecasts f
            JOIN (SELECT run_id, origin FROM forecasts WHERE mode IN ('prospective', 'prospective_research')
                  GROUP BY run_id, origin HAVING COUNT(*) = 8 AND COUNT(DISTINCT horizon) = 8
                  AND (SUM(status = 'issued') = 8 OR SUM(status = 'abstained') = 8)) b
            USING (run_id, origin)
            WHERE horizon = 'decision_1' AND created_at >= ?
        """, (start,)).fetchall()
        certified = db.execute("""
            SELECT COUNT(DISTINCT o.decision_key) FROM evaluations e JOIN outcomes o ON o.id = e.outcome_id
            JOIN forecasts f ON f.id = e.forecast_id
            WHERE e.kind = 'official_match' AND f.horizon = 'decision_1'
              AND f.mode IN ('prospective', 'prospective_research') AND f.created_at >= ?
        """, (start,)).fetchone()[0]
    stops, tiers, tier_two_failures = Counter(), Counter(), Counter()
    for status, reasons, target_json in rows:
        target = json.loads(target_json)
        if status == "abstained":
            stops.update(json.loads(reasons))
        else:
            tiers[str(target["tier"])] += 1
        for attempt in target.get("attempts", []):
            if attempt["tier"] == 2:
                tier_two_failures.update(set(attempt["reasons"]))
    return dict(complete_runs=len(rows), abstention_reasons=stops, issued_tiers=tiers,
                tier_two_failures=tier_two_failures, officially_matched_decisions=certified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--lebvote", type=Path, required=True)
    parser.add_argument("--rbob", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, files = args.root, (args.lebvote, args.rbob)
    alternative = lebvote_rows(args.lebvote.read_bytes())
    futures = rbob_rows(args.rbob.read_bytes())
    db_path = root / "data/lebanon_fuel.sqlite"
    with closing(MarketStore(root, readonly=True)) as store:
        ledger = store.ledger()
        prices = defaultdict(set)
        for day, price in store.db.execute("SELECT source_date, price_lbp_20l FROM observations "
                                           "WHERE source_id='ipt' AND source_date BETWEEN ? AND ?", (START, EVAL_END)):
            prices[day].add(price)
        market = {sid: store.history(sid, EVAL_END + "T23:59:59+00:00", mode="as_of_close") for sid in MARKETS}
    original = [r for r in ledger if START <= r["source_date"] <= EVAL_END]
    expanded, coverage, findings = reconcile_research(original, prices, alternative)
    windows = dict(gasoline=SeriesWindow(market["nyh_gasoline"], 4),
                   brent=SeriesWindow(market["brent_spot"], 4),
                   gasoline_delayed=SeriesWindow(market["nyh_gasoline"], 4, lag=3),
                   brent_delayed=SeriesWindow(market["brent_spot"], 4, lag=3),
                   italy=SeriesWindow(market["italy_gasoline_ex_tax"], 1, max_age=21),
                   greece=SeriesWindow(market["greece_gasoline_ex_tax"], 1, max_age=21),
                   rbob=SeriesWindow(futures, 4))
    archive_cases = build_cases(original, windows, ARCHIVE)
    cases = build_cases(expanded, windows, RESEARCH_MATCH)
    metrics, predictions = evaluate(archive_cases, cases)
    live_protocol = json.loads((root / "config/prospective_holdout.json").read_text())
    metrics.update(
        assumptions="Retrospective latest-vintage archive research with assumed market availability. No production approval.",
        input_sha256={path.name: digest(path) for path in (*files, db_path, root/"data/forecast_ledger.sqlite")},
        source_rows=dict(lebvote=len(alternative), rbob=len(futures),
                         rbob_in_project_era=sum(row["observation_date"] >= START for row in futures)),
        source_comparison=[dict(year=year, status=status, dates=n) for (year, status), n in sorted(coverage.items())],
        live=availability(root/"data/forecast_ledger.sqlite", max(live_protocol["sealed_at"], live_protocol["prospective_start"])),
        evaluation_dates=[predictions["target_date"].min(), predictions["target_date"].max()],
        current_hybrid_comparison=compare_hybrid(root, expanded, cases, predictions, metrics["selected_pre_evaluation"]),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(findings).to_csv(args.output / "source_reconciliation.csv", index=False)
    cases.to_csv(args.output / "research_decision_cases.csv", index=False)
    predictions.to_csv(args.output / "paired_evaluation_predictions.csv", index=False)
    public_methods = {
        "Current frozen Hybrid": "G_hybrid",
        "Hybrid retrained on expanded data": "G_hybrid_expanded",
        "Repeat last change": "Z_last_change",
        "No price change": "A_no_change",
    }
    paired = predictions.dropna(subset=list(public_methods))
    public = pd.concat([
        paired.assign(horizon="decision_1", regime="expanded_2026_research", family=family,
                      endpoint=paired["target_date"], target_source_date=paired["target_date"],
                      endpoint_price_lbp_20l=paired["actual_price"],
                      predicted_endpoint_price_lbp_20l=paired["base_price"] + paired[method])
        for method, family in public_methods.items()
    ])
    public[["origin", "horizon", "regime", "family", "endpoint", "target_source_date",
            "endpoint_price_lbp_20l", "predicted_endpoint_price_lbp_20l", "source_cohort"]].to_csv(
        args.output / "dashboard_predictions.csv", index=False)
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
    print(json.dumps(metrics, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
