"""Operational behavior and independent arithmetic checks. Fixtures are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import plistlib
import shutil
import sqlite3

import pandas as pd
import pytest

from lebanon_fuel.automation import forecast, launchd, maintenance, monitoring, runner
from lebanon_fuel.automation.schedule import due, settings
from lebanon_fuel.automation.state import AlreadyRunning, Journal, now, refresh_lock
from lebanon_fuel.dashboard.data import approved_forecasts
from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.domain import Observation
from lebanon_fuel.validation.ledger import ForecastLedger

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    # The fixture creates its own database and has no production cutover archive.
    shutil.copytree(ROOT / "config", tmp_path / "config",
                    ignore=shutil.ignore_patterns("audited_baseline.json"))
    folder = tmp_path / "reports/model_validation"
    folder.mkdir(parents=True)
    for name in ("production_selection.json", "descriptive_best_models.csv"):
        shutil.copy(ROOT / "reports/model_validation" / name, folder / name)
    with closing(MarketStore(tmp_path)) as store:
        cap = store.capture("ipt", "https://example.test/prices", b"test fixture", "text/plain")
        store.ingest(cap, [Observation("ipt", now().date().isoformat(), 1000000,
                     "https://example.test/prices", {"fixture": True}, "1")])
        store.reconcile()
    with closing(ForecastLedger(tmp_path / "data/forecast_ledger.sqlite")):
        pass
    return tmp_path


def test_scheduler_beirut_watch_window_and_clock_awareness():
    schedule = settings(ROOT)["schedule"]
    # Wednesday 09:30 Beirut = 07:30 UTC after fall DST transition.
    at = datetime(2026, 11, 11, 7, 30, tzinfo=timezone.utc)
    ready, reason = due(at, (at - timedelta(minutes=61)).isoformat(), schedule)
    assert ready and reason == "announcement_watch_window"
    assert not due(at, (at - timedelta(minutes=59)).isoformat(), schedule)[0]
    saturday = at + timedelta(days=3)
    assert not due(saturday, (saturday - timedelta(hours=2)).isoformat(), schedule)[0]
    assert due(saturday, (saturday - timedelta(hours=6)).isoformat(), schedule)[0]
    with pytest.raises(ValueError):
        due(at.replace(tzinfo=None), None, schedule)


def test_scheduler_uses_utc_elapsed_time_across_dst():
    schedule = dict(settings(ROOT)["schedule"], announcement_windows=[])
    at = datetime(2026, 10, 25, 7, tzinfo=timezone.utc)
    assert due(at, (at - timedelta(hours=6)).isoformat(), schedule)[0]
    assert not due(at, (at - timedelta(hours=5, minutes=59)).isoformat(), schedule)[0]


def test_plist_is_native_and_uses_absolute_project_interpreter():
    manifest = plistlib.loads(plistlib.dumps(launchd.manifest(ROOT)))
    assert manifest["ProgramArguments"][0] == str(ROOT / ".venv/bin/python")
    assert manifest["RunAtLoad"] and manifest["StartInterval"] == 300
    assert "codex" not in " ".join(manifest["ProgramArguments"]).lower()
    assert manifest["WorkingDirectory"] == str(ROOT)


def test_refresh_lock_releases_after_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with refresh_lock(tmp_path):
            with pytest.raises(AlreadyRunning):
                with refresh_lock(tmp_path):
                    pass
            raise RuntimeError("interrupted")
    with refresh_lock(tmp_path):
        pass


def test_access_denial_respects_long_retry_after(project):
    with closing(MarketStore(project)) as store:
        started = now().isoformat()
        store.capture("market_ec", "https://example.test", b"limited", "text/plain", http_status=429,
                      metadata={"headers": {"retry-after": "172800"}})
        deadline = runner.access_cooldown(store, "ec", started, settings(project))
    assert datetime.fromisoformat(deadline) >= datetime.fromisoformat(started) + timedelta(days=2)
    with closing(Journal(project)) as journal:
        journal.append("test", "source_result", "ec", {"retry_not_before": deadline})
        assert runner.cooldown("ec", journal, settings(project), now()).startswith("access_cooldown")
        with pytest.raises(sqlite3.IntegrityError):
            journal.db.execute("DELETE FROM events")


def test_failed_source_does_not_stop_other_collectors_or_create_forecast(project):
    seen = []
    def collect(root, source, cfg):
        seen.append(source)
        if source == "ipt":
            raise OSError("network unavailable")
        return dict(status="success", stdout="fixture collector", stderr="")
    result = runner.run(project, sources=["ipt", "eia"], collector=collect)
    assert seen == ["ipt", "eia"]
    assert result["status"] == "degraded"
    assert all(s["status"] == "success" for s in result["steps"])
    with closing(ForecastLedger(project / "data/forecast_ledger.sqlite")) as ledger:
        assert ledger.db.execute("SELECT COUNT(*) FROM forecasts WHERE status='abstained'").fetchone()[0] == 8
        assert ledger.db.execute("SELECT COUNT(*) FROM forecasts WHERE predicted_price IS NOT NULL").fetchone()[0] == 0
        assert ledger.integrity()["hash_chain_valid"]
    monitoring_result = json.loads((project / "reports/operations/monitoring.json").read_text())
    assert monitoring_result["performance"]["evaluated_forecasts"] == 0
    assert (project / "reports/latest_analyst_report.md").exists()
    assert runner.run(project, scheduled=True, collector=collect)["status"] == "not_due"


def test_native_manual_request_runs_even_before_regular_interval(project):
    runner.run(project, offline=True)
    request = project / "data/operations/refresh.request"
    request.write_text("manual")
    result = runner.run(project, scheduled=True, offline=True)
    assert result["status"] == "completed" and not request.exists()


def test_backup_restores_readable_databases_and_detects_damage(project):
    import tomllib
    config = tomllib.loads((project / "config/project.toml").read_text())
    result = maintenance.backup(project, config)
    folder = Path(result["directory"])
    assert maintenance.verify_backup(folder)["status"] == "verified"
    with closing(sqlite3.connect(folder / "lebanon_fuel.sqlite")) as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    with (folder / "lebanon_fuel.sqlite").open("ab") as output:
        output.write(b"damage")
    with pytest.raises(ValueError, match="checksum"):
        maintenance.verify_backup(folder)


def test_review_config_cannot_promote_rejected_models(project):
    import tomllib
    config = tomllib.loads((project / "config/project.toml").read_text())
    config["forecasting"]["enabled"] = True
    config["validation"]["production_approved"] = True
    result = forecast.refresh(project, config, "forged-boolean")
    assert result["status"] == "abstain"
    assert 'independent corroboration' in result['reasons'][0]
    assert all(row['tier'] is None for row in result['forecasts'])


def test_metrics_sign_baseline_intervals_and_probabilities():
    rows = pd.DataFrame([
        dict(actual_change=10., predicted_change=12., interval_low=0, interval_high=20, probabilities_json="[0,0,1]", origin="a", decision_key="A", target_json='{"interval_nominal":0.9}'),
        dict(actual_change=-10., predicted_change=4., interval_low=0, interval_high=20, probabilities_json="[0,1,0]", origin="b", decision_key="B", target_json='{"interval_nominal":0.9}'),
    ])
    result = monitoring.metric_group(rows)
    assert result["mae_lbp"] == 8 and result["bias_lbp"] == 8
    assert result["no_change_baseline_mae_lbp"] == 10
    assert result["directional_accuracy"] == .5
    assert result["interval_coverage"] == .5 and result["interval_width_lbp"] == 20
    assert result["brier_multiclass"] == 1
    assert result["n"] == result["distinct_official_decisions"] == 2


def test_ledger_concurrent_issuers_form_one_hash_chain(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with closing(ForecastLedger(path)) as ledger:
        ledger.model("fixture", {})
    def issue(index):
        with closing(ForecastLedger(path)) as ledger:
            origin = now().isoformat()
            snapshot = ledger.snapshot(origin, "prospective_research", {"fixture": index})
            ledger.issue(str(index), origin, "prospective_research", "fixture", snapshot,
                         "decision_1", {"kind": "decision", "steps": 1}, 100, prediction=1)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(issue, range(24)))
    with closing(ForecastLedger(path)) as ledger:
        assert ledger.integrity()["forecasts"] == 24


def test_ledger_abstention_cannot_carry_probabilities(tmp_path):
    with closing(ForecastLedger(tmp_path / "l.sqlite")) as ledger:
        ledger.model("fixture", {})
        origin = now().isoformat()
        snapshot = ledger.snapshot(origin, "prospective", {})
        with pytest.raises(ValueError, match="abstention"):
            ledger.issue("r", origin, "prospective", "fixture", snapshot, "decision_1", {}, 100, probabilities=[0, 1, 0])


def test_dashboard_expires_old_forecast_and_respects_later_guard():
    at = now()
    config = {"forecasting": {"enabled": True}, "validation": {"production_approved": True}}
    decision = {"production_approved": True, "selection": {"decision_1": {"production_model": "fixture"}}}
    row = dict(id=1, mode="prospective", model_version="fixture", approved=1, status="issued", predicted_price=100, actual_price=None,
               origin=(at - timedelta(days=2)).isoformat(), created_at=(at - timedelta(days=2)).isoformat())
    assert approved_forecasts(pd.DataFrame([row]), config, decision, "decision_1", at=at).empty
    row["origin"] = row["created_at"] = at.isoformat()
    assert len(approved_forecasts(pd.DataFrame([row]), config, decision, "decision_1", at=at)) == 1
    later = dict(row, id=2, model_version="guard", status="abstained", predicted_price=None)
    assert approved_forecasts(pd.DataFrame([row, later]), config, decision, "decision_1", at=at).empty


def test_future_actual_knowledge_and_coverage_are_rejected(tmp_path):
    with closing(ForecastLedger(tmp_path / "ledger.sqlite")) as ledger:
        at = now()
        with pytest.raises(ValueError, match="future"):
            ledger.outcome("fixture", (at + timedelta(days=1)).isoformat(), 100,
                           "https://example.test/fixture", "document_verified", "hash", {})
        ledger.model("fixture", {})
        snapshot = ledger.snapshot(at.isoformat(), "prospective_research", {})
        fid = ledger.issue("fixture", at.isoformat(), "prospective_research", "fixture", snapshot,
                           "decision_1", {"kind": "decision", "steps": 1}, 100, prediction=10)
        with pytest.raises(ValueError, match="future"):
            ledger.match(fid, dict(certified=True, evidence_url="https://example.test/fixture",
                                   **{"from": at.isoformat(), "through": (at + timedelta(days=1)).isoformat()}))


def test_revised_outcomes_update_metrics_without_rewriting_predictions(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with closing(ForecastLedger(path)) as ledger:
        at = now()
        ledger.model("fixture", {})
        snapshot = ledger.snapshot(at.isoformat(), "prospective_research", {})
        fid = ledger.issue("fixture", at.isoformat(), "prospective_research", "fixture", snapshot,
                           "decision_1", {"kind": "decision", "steps": 1}, 100, prediction=10)
        publication = now().isoformat()
        for price in (115, 120):
            ledger.outcome("fixture-A", now().isoformat(), price, "https://example.test/fixture",
                           "document_verified", str(price), {"fixture": True}, publication, publication)
            assert ledger.match(fid, dict(certified=True, evidence_url="https://example.test/fixture",
                                          **{"from": at.isoformat(), "through": now().isoformat()})) == "matched_verified_outcome"
        assert ledger.db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 2
        assert ledger.db.execute("SELECT predicted_price FROM forecasts").fetchone()[0] == 110
        assert ledger.integrity()["hash_chain_valid"]
    result = monitoring.prospective_performance(path, settings(ROOT)["monitoring"])
    assert result["evaluated_forecasts"] == 1
    assert result["groups"][0]["monitoring_window"]["mae_lbp"] == 10
    assert result["groups"][0]["monitoring_window"]["bias_lbp"] == -10


def test_widget_snapshot_compact_and_consistent():
    check = dict(origin="2026-11-22T12:38:23+00:00",
                 anchor=dict(price_lbp_20l=2291000),
                 forecasts=[
                     dict(horizon="decision_2", status="issued", base_price=2291000, predicted_price=1),
                     dict(horizon="decision_1", status="issued", base_price=2291000, predicted_price=2260065.5899658627),
                 ])
    payload = runner.widget_snapshot(check)
    assert payload == dict(v=1, at=check["origin"], c=2291000, p=2260066)
    assert len(json.dumps(payload, separators=(",", ":"))) < 128

    check["forecasts"][1]["base_price"] = 2343000
    assert runner.widget_snapshot(check)["p"] is None
    check["anchor"]["price_lbp_20l"] = None
    assert runner.widget_snapshot(check)["c"] is None
    check["anchor"]["price_lbp_20l"] = float("nan")
    assert runner.widget_snapshot(check)["c"] is None
