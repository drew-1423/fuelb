"""Private audit of one lag variable on paired live outcomes. Prints local results."""
from datetime import datetime, timezone
import json
from math import isclose, sqrt
from pathlib import Path
from statistics import mean
import tomllib

from lebanon_fuel.forecasting.live import current_context, generate
from lebanon_fuel.validation import decision_tracking, live_score


def main():
    root = Path.cwd()
    settings = tomllib.loads((root / "config/project.toml").read_text())
    config = json.loads((root / "config/live_forecasting.json").read_text())
    decision = json.loads((root / settings["validation"]["decision_file"]).read_text())
    now = datetime.now(timezone.utc).isoformat()
    policy = live_score.protocol(root)
    cases = []
    excluded = []
    with decision_tracking._read(root / settings["validation"]["forecast_ledger"]) as db:
        tracks = {}
        if policy:
            score = live_score.report(db, policy, now)
            tracks[policy["version"]] = [entry for entry in score["entries"] if entry["status"] == "matched"]
        earlier = decision_tracking._matched(db, decision_tracking.protocol_start(root), now)
        prior = {}
        for item in earlier:
            if item["horizon"] == "decision_1":
                retained = prior.setdefault(item["day"], item)
                if item["forecast_id"] == retained["forecast_id"] and item["kind"] == "official_match":
                    prior[item["day"]] = item
        tracks["earlier_protocol_research"] = list(prior.values())
        for track, entries in tracks.items():
            for entry in entries:
                fid = entry["forecast_id"]
                saved = db.execute("SELECT * FROM forecasts WHERE id=?", (fid,)).fetchone()
                spec = json.loads(saved["target_json"])
                at = datetime.fromisoformat(saved["origin"])
                records, histories = current_context(root, settings, at)
                candidates = generate(root, settings, config, decision, records, histories, at, research_sensitivity=True)
                issued = candidates["forecasts"][0]
                price = issued.get("predicted_price")
                alternative = issued.get("shadow_zero_domestic_lag1_price")
                if (price is None or alternative is None or issued.get("artifact_sha256") != spec.get("artifact_sha256")
                        or issued.get("base_revision_id") != spec.get("base_revision_id")
                        or not isclose(price, saved["predicted_price"], abs_tol=.01, rel_tol=0)):
                    excluded.append(fid)
                    continue
                previous = live_score.previous_update(records, candidates["anchor"])
                recent_move = abs(saved["base_price"] - previous["price_lbp_20l"]) if previous else None
                cases.append(dict(track=track, forecast_id=fid, observed=entry["actual"],
                                  hybrid=price, zero_domestic_lag1=alternative, starting_move=recent_move))
    metrics = []
    for track in tracks:
        for group in ("all", "starting move ≥ 50,000 LBP"):
            sample = [row for row in cases if row["track"] == track and
                      (group == "all" or (row["starting_move"] or 0) >= 50000)]
            for model in ("hybrid", "zero_domestic_lag1"):
                errors = [row[model] - row["observed"] for row in sample]
                if errors:
                    metrics.append(dict(track=track, group=group, model=model, n=len(errors),
                                        mae=mean(map(abs, errors)), rmse=sqrt(mean(e*e for e in errors)),
                                        bias=mean(errors)))
    print(json.dumps(dict(cases=cases, metrics=metrics, excluded_forecast_ids=excluded), indent=2))


if __name__ == "__main__":
    main()
