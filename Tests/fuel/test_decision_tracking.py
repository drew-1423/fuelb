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
