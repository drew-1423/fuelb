import json

from lebanon_fuel.domain import PROVISIONAL_PRICE
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.validation.scorecard import COHORTS, HORIZONS, load_scorecard


def test_scorecard_uses_distinct_prospective_decisions_and_paired_baselines(tmp_path):
    path = tmp_path / "ledger.sqlite"
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({
        "prospective_start": "2026-02-01T00:00:00+00:00",
        "sealed_at": "2026-02-01T10:00:00+00:00",
    }))
    ledger = ForecastLedger(path)
    # Insert fixtures for historical issuance timestamps and for legacy ledger
    # rows that newer write guards would already refuse.
    db = ledger.db
    db.execute("INSERT INTO models VALUES ('model', '', 0, '{}')")

    def issue(run, hour, price, *, previous=100_000, status="document_verified",
              actual_key=None, publication_hour=20, horizons=HORIZONS, mode="prospective_research"):
        at = f"2026-02-01T{hour:02d}:00:00+00:00"
        base = 120_000 if price is not None else None
        anchor = {"price_lbp_20l": base, "previous_verified_price": previous}
        db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                   (run, at, at, mode, json.dumps({"inputs": {"anchor": anchor}})))
        for horizon in horizons:
            inserted = db.execute("""
                INSERT INTO forecasts (run_id, created_at, origin, mode, model_version, snapshot_id, horizon,
                       target_json, status, base_price, predicted_price, reason_json, record_hash)
                VALUES (?, ?, ?, ?, 'model', ?, ?, ?, ?, ?, ?, '[]', ?)
            """, (run, at, at, mode, run, horizon, json.dumps({"anchor_verification": status}),
                  "issued" if price is not None else "abstained", base, price, f"{run}:{horizon}"))
            if horizon == "decision_1" and actual_key:
                actual = 145_000
                published = f"2026-02-01T{publication_hour:02d}:00:00+00:00"
                outcome = ledger.outcome(actual_key, "2026-02-02T00:00:00+00:00", actual,
                                         "https://example.org/reviewed", "document_verified", actual_key,
                                         {}, published, published)
                db.execute("""
                    INSERT INTO evaluations (created_at, forecast_id, outcome_id, kind,
                        prediction_error, actual_change, direction_hit)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (at, inserted.lastrowid, outcome, "official_match", price - actual, actual - base))

    issue("unsealed", 9, 145_000, actual_key="pre-seal")
    issue("older", 10, 145_000, actual_key="decision-a")
    issue("newer", 11, 133_000, actual_key="decision-a")
    issue("provisional", 12, 122_000, previous=None, status=PROVISIONAL_PRICE, actual_key="decision-a")
    issue("abstained", 13, None)
    issue("late", 19, 145_000, actual_key="decision-b", publication_hour=18)
    issue("partial", 15, 145_000, actual_key="decision-c", horizons=("decision_1",))
    issue("research", 16, 145_000, actual_key="decision-d", mode="retrospective_research")
    db.commit()
    ledger.close()

    result = load_scorecard(path, protocol)
    assert (result["issued"], result["abstained"], result["incomplete"]) == (4, 1, 1)
    assert (result["matched_issues"], result["settled_decisions"]) == (3, 1)
    government = result["groups"][COHORTS[0]]
    assert len(government["cases"]) == 1
    assert government["cases"][0]["forecast"] == 133_000
    assert [row["mae"] for row in government["three_way"]] == [12_000, 25_000, 5_000]
    assert [row["direction"] for row in government["three_way"]] == [1, 0, 1]
    provisional = result["groups"][COHORTS[1]]
    assert provisional["primary"][0]["direction"] == 0
    assert provisional["three_way"][0]["n"] == 0
