"""Local, authorized AAWZB00 trial against the exact saved Hybrid forecasts."""
import argparse
from contextlib import closing
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from lebanon_fuel.domain import BEIRUT, utc_timestamp
from lebanon_fuel.validation.decision_tracking import _matched, _read, protocol_start
from lebanon_fuel.validation.decision_events import stamp

MIN_FIT = 30

def quotes_from_csv(csv_bytes):
    from io import BytesIO
    table = pd.read_csv(BytesIO(csv_bytes), dtype=str)
    required = {"symbol", "observation_date", "mid", "unit", "published_at"}
    if not required.issubset(table) or table.empty:
        raise ValueError("CSV requires symbol,observation_date,mid,unit,published_at and original assessments")
    if not table["symbol"].eq("AAWZB00").all() or not table["unit"].eq("USD/mt").all():
        raise ValueError("Expected only AAWZB00 prices in USD/mt")
    if table["observation_date"].duplicated().any():
        raise ValueError("Supply one original assessment per date. Keep corrected vintages outside this trial file.")
    quotes = []
    for row in table.to_dict("records"):
        day = date.fromisoformat(row["observation_date"])
        published = stamp(utc_timestamp(row["published_at"]))
        value = float(row["mid"])
        if published.date() < day or not np.isfinite(value) or value <= 0:
            raise ValueError("Invalid assessment clock or midpoint")
        quotes.append((day, published, value))
    return sorted(quotes)


def quote_feature(quotes, origin):
    window = [item for item in quotes if item[1] < origin][-8:]
    if len(window) < 8 or (origin.astimezone(BEIRUT).date() - window[-1][0]).days > 7:
        return None
    if (window[-1][0] - window[0][0]).days > 16:
        return None
    return float(np.mean([q[2] for q in window[4:]]) - np.mean([q[2] for q in window[:4]]))


def evaluate(quotes, cases):
    comparable = []
    for row in cases:
        value = quote_feature(quotes, row["origin"])
        if value is not None:
            comparable.append(dict(row, feature=value))
    output = {}
    for cohort, kind in (("government_backed", "official_match"), ("provisional", "provisional_match")):
        sample = [r for r in comparable if r["cohort"] == cohort and r["kind"] == kind]
        baseline, revised = [], []
        for row in sample:
            past = [r for r in sample if r["origin"] < row["origin"] and r["known"] < row["origin"]
                    and r["artifact"] == row["artifact"]]
            if len(past) < MIN_FIT:
                continue
            model = make_pipeline(StandardScaler(), Ridge(alpha=12.0))
            model.fit([[r["feature"]] for r in past], [r["actual"] - r["forecast"] for r in past])
            error = row["actual"] - row["forecast"]
            baseline.append(abs(error))
            revised.append(abs(error - model.predict([[row["feature"]]])[0]))
        output[cohort] = dict(assessment_overlap=len(sample), compared=len(baseline),
                              hybrid_mae_lbp=float(np.mean(baseline)) if baseline else None,
                              incremental_med_mae_lbp=float(np.mean(revised)) if revised else None)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--authorization", required=True, help="Reference to your authorized evaluation terms")
    args = parser.parse_args()
    if not args.authorization.strip():
        parser.error("An authorization reference is required")
    raw = args.input.read_bytes()
    quotes = quotes_from_csv(raw)
    root = args.root.resolve()
    from lebanon_fuel.dashboard.data import config, database_paths
    _, ledger = database_paths(root, config(root))
    with _read(ledger) as db:
        cases = _matched(db, protocol_start(root), pd.Timestamp.now(tz="UTC").isoformat())
    print(json.dumps(dict(symbol="AAWZB00", input_sha256=sha256(raw).hexdigest(), assessments=len(quotes),
                          minimum_fit_cases=MIN_FIT, results=evaluate(quotes, cases)), indent=2))

if __name__ == "__main__":
    main()
