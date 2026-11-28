from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from random import Random
from types import SimpleNamespace

from lebanon_fuel.domain import PROVISIONAL_PRICE
from lebanon_fuel.validation import decision_tracking as tracking
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.validation.scorecard import HORIZONS


def test_supplier_match_is_idempotent_and_revoked_by_a_conflict(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/prospective_holdout.json").write_text(json.dumps({
        "prospective_start": "2025-02-01T00:00:00+00:00", "sealed_at": "2025-02-01T00:00:00+00:00"}))
    ledger_path = tmp_path / "forecasts.sqlite"
    origin = "2025-02-02T01:00:00+00:00"
    source_db = sqlite3.connect(":memory:")
    source_db.row_factory = sqlite3.Row
    source_db.execute("""CREATE TABLE observations(id INT, source_id TEXT, price_lbp_20l REAL, source_url TEXT,
                      first_retrieved_at TEXT, source_date TEXT, is_valid INT)""")
    base = {"source_date": "2025-02-01", "price_lbp_20l": 1000000, "verification_status": PROVISIONAL_PRICE,
            "revision_id": 1}
    target = {"source_date": "2025-02-03", "price_lbp_20l": 1030000, "verification_status": PROVISIONAL_PRICE,
              "revision_id": 2}
    for i, name in enumerate(("ipt", "taqtek")):
        source_db.execute("INSERT INTO observations VALUES (?, ?, 1030000, ?, ?, '2025-02-03', 1)",
                          (i, name, f"https://example.org/{name}", "2025-02-03T08:00:00+00:00"))
    store = SimpleNamespace(db=source_db, ledger=lambda: [base, target])
    cfg = {"validation": {"forecast_ledger": "forecasts.sqlite"}}
    with closing(ForecastLedger(ledger_path)) as ledger:
        db = ledger.db
        db.execute("INSERT INTO models VALUES ('model', '', 0, ?)", (json.dumps({"family":tracking.FAMILY}),))
        db.execute("INSERT INTO snapshots VALUES ('snap', ?, ?, 'prospective_research', '{}')", (origin, origin))
        spec = json.dumps({"pinned_family":tracking.FAMILY, "base_source_date":base["source_date"],
                           "anchor_verification":PROVISIONAL_PRICE, "artifact_sha256":"test"})
        for i, horizon in enumerate(HORIZONS):
            db.execute("""INSERT INTO forecasts (run_id, created_at, origin, mode, model_version, snapshot_id,
                       horizon, target_json, status, base_price, predicted_price, predicted_change, reason_json, record_hash)
                       VALUES ('run', ?, ?, 'prospective_research', 'model', 'snap', ?, ?, ?, 1000000, ?, ?, '[]', ?)""",
                       (origin, origin, horizon, spec, "issued" if i == 0 else "abstained",
                        1020000 if i == 0 else None, 20000 if i == 0 else None, horizon))
        db.commit()
    assert tracking.settle_supplier_updates(tmp_path, cfg, store) == {"supplier_match": 1}
    assert tracking.settle_supplier_updates(tmp_path, cfg, store) == {"supplier_match": 1}
    view = tracking.dashboard_evidence(tmp_path, ledger_path)
    assert len(view["cases"]) == 1
    assert view["cases"][0]["actual"] == 1030000
    assert view["cases"][0]["forecast"] == 1020000
    with sqlite3.connect(ledger_path) as db:
        assert db.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM match_attempts").fetchone()[0] == 1
    target.update(verification_status="conflict", revision_id=3)
    assert tracking.settle_supplier_updates(tmp_path, cfg, store) == {"conflict": 1}
    assert tracking.dashboard_evidence(tmp_path, ledger_path)["cases"] == []
    with sqlite3.connect(ledger_path) as db:
        assert db.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 1
    source_db.close()


def test_intervals_require_matured_cases_and_measured_coverage_in_the_same_group():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    cases = []
    rng = Random(17)
    for i in range(60):
        origin = start + timedelta(days=3*i)
        cases.append(dict(kind="provisional_match", cohort="provisional", artifact="one", origin=origin,
                          known=origin+timedelta(days=1), forecast=100000,
                          actual=100000 + rng.randrange(20000)))
    assert tracking.calibration(cases[:49], "provisional", "one")["radius"] is None
    result = tracking.calibration(cases, "provisional", "one")
    assert result["evaluation_n"] == 30
    assert .80 <= result["empirical_coverage"] <= .98
    assert result["radius"] is not None
    assert tracking.calibration(cases, "government_backed", "one")["radius"] is None
    assert tracking.calibration(cases, "provisional", "another")["radius"] is None
    future = [dict(r, known=start+timedelta(days=365)) for r in cases]
    assert tracking.calibration(future, "provisional", "one")["radius"] is None


def test_fixed_protocol_selects_before_matching_and_does_not_replace_first_issuance(tmp_path):
    from lebanon_fuel.validation import review_journal
    from lebanon_fuel.validation.live_score import issuance_protocol, report, selections

    now = datetime(2026, 2, 4, tzinfo=timezone.utc)
    policy = dict(version="test-fixed", starts_at="2026-02-01T00:00:00+00:00",
                  calendar_cutoff_hour=12, decision_entry_days_after_anchor=1,
                  outcome_grace_days=7, direction_deadband_lbp=3000)
    config = tmp_path / "config"
    config.mkdir()
    (config / "live_score_v3.json").write_text(json.dumps(policy))
    (config / "prospective_holdout.json").write_text(json.dumps(
        dict(prospective_start=policy["starts_at"], sealed_at=policy["starts_at"])))
    anchor = dict(source_date="2026-02-02", revision_id=2, price_lbp_20l=1000000,
                  verification_status="archive_corroborated")
    history = [dict(anchor, source_date="2026-01-30", revision_id=1, price_lbp_20l=990000), anchor]
    with closing(ForecastLedger(tmp_path / "ledger.sqlite")) as ledger:
        db = ledger.db
        db.execute("INSERT INTO models VALUES ('model', '', 0, ?)", (json.dumps({"family":tracking.FAMILY}),))
        market = {"nyh_gasoline": dict(available_at="2026-02-02T12:00:00+00:00", observation_date="2026-02-01"),
                  "brent_spot": dict(available_at="2026-02-03T12:00:00+00:00", observation_date="2026-02-02")}
        db.execute("INSERT INTO snapshots VALUES ('snap', '', '', 'prospective_research', ?)",
                   (json.dumps({"available_market_inputs": market}),))
        starts = ["2026-02-02T10:00:00+00:00", "2026-02-02T14:00:00+00:00", "2026-02-03T13:00:00+00:00"]
        for i, start in enumerate(starts):
            issued = datetime.fromisoformat(start)
            for j, horizon in enumerate((*HORIZONS,)):
                if i == 0 and horizon == "day_30":
                    continue  # The partial first batch cannot win.
                is_decision = horizon.startswith("decision_")
                endpoint = None if is_decision else (issued + timedelta(days=int(horizon[4:]))).isoformat()
                forecast = dict(family=tracking.FAMILY, pinned_family=tracking.FAMILY, horizon=horizon,
                                status="issued", endpoint=endpoint)
                marker = issuance_protocol(policy, history, anchor, forecast, issued)
                spec = dict(forecast, score_protocol=marker, base_source_date=anchor["source_date"],
                            anchor_verification=PROVISIONAL_PRICE, artifact_sha256="test",
                            scheduled_effective="2026-02-05" if is_decision else None,
                            lagged_market_inputs=[{"series": "nyh_gasoline"}])
                db.execute("""INSERT INTO forecasts (run_id, created_at, origin, mode, model_version, snapshot_id,
                           horizon, target_json, status, base_price, predicted_price, predicted_change, reason_json, record_hash)
                           VALUES (?, ?, ?, 'prospective_research', 'model', 'snap', ?, ?, 'issued',
                                   1000000, 1020000, 20000, '[]', ?)""",
                           (str(i), start, start, horizon, json.dumps(spec), f"{i}:{j}"))
        db.commit()
        chosen, _ = selections(db, policy, now)
        row, spec = chosen["decision_1:2026-02-02"]
        assert row["run_id"] == "1"
        assert spec["score_protocol"]["baselines"] == {"No change": 1000000, "Last change": 1010000}
        assert all(not key.startswith("day_") for key in chosen)  # Both complete calendar batches missed noon.
        score = report(db, policy, now)
        assert score["counts"] == {"selected": 1, "pending": 1}
        payload = dict(source_date="2026-02-04")
        db.execute("""INSERT INTO outcomes(id,created_at,decision_key,available_at,price,source_url,
                   verification_status,source_hash,payload_json)
                   VALUES (1,'2026-02-04T08:00:00+00:00','supplier:2026-02-04',
                   '2026-02-04T08:00:00+00:00',1030000,'https://example.org/ipt','supplier_agreement','hash',?)""",
                   (json.dumps(payload),))
        # A later issuance has a match first. The selected result remains pending.
        later = db.execute("SELECT id FROM forecasts WHERE run_id='2' AND horizon='decision_1'").fetchone()[0]
        for fid in (later, row["id"]):
            db.execute("""INSERT INTO evaluations(created_at,forecast_id,outcome_id,kind,prediction_error,
                       actual_change,direction_hit) VALUES ('2026-02-04T09:00:00+00:00',?,1,'provisional_match',-10000,30000,1)""", (fid,))
            db.execute("""INSERT INTO match_attempts(created_at,forecast_id,status,details_json)
                       VALUES ('2026-02-04T09:00:00+00:00',?,'supplier_match',?)""",
                       (fid, json.dumps({"channel": tracking.ATTEMPT_CHANNEL, "outcome_id": 1})))
            score = report(db, policy, now + timedelta(hours=12))
            assert score["entries"][0]["forecast_id"] == row["id"]
            if fid == later:
                assert score["counts"]["pending"] == 1
        assert score["counts"]["matched"] == 1
        assert score["comparisons"][0]["mae"] == 10000
        assert score["comparisons"][1]["mae"] == 30000
        db.commit()
        assert report(db, policy, now)["entries"][0]["reason"] == "no_match_attempt"
    ledger_path = tmp_path / "ledger.sqlite"
    pending = review_journal.load(tmp_path, ledger_path, "decision_1", now.isoformat())
    assert pending["current_matches"] == 0 and pending["mae"] is None
    assert pending["hypotheses"] == []
    journal = review_journal.load(tmp_path, ledger_path, "decision_1", (now + timedelta(hours=12)).isoformat())
    assert journal["current_matches"] == 1
    assert journal["earlier_cases"] == []
    assert journal["mae"] == journal["rmse"] == 10000
    assert journal["mean_error"] == -10000 and journal["direction_hits"] == 1
    case, = journal["cases"]
    assert case["forecast_id"] == row["id"] and case["outcome_id"] == 1
    assert case["outcome_known_at"] == "2026-02-04T09:00:00+00:00"
    assert case["days_from_projection"] == -1
    assert case["baselines"]["Last change"]["absolute_error"] == 20000
    assert [item["series"] for item in case["market"]] == ["nyh_gasoline"]
    assert {idea["topic"] for idea in journal["hypotheses"]} == {"Lagged market inputs", "Projected date", "Move size"}
