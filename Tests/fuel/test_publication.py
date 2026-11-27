from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from lebanon_fuel.automation import publication as publish


def test_oversized_refresh_roundtrip_and_git_guard(tmp_path, monkeypatch):
    monkeypatch.delenv("LEBANON_FUEL_LOCAL_STORAGE", raising=False)
    root = tmp_path / "source"
    for name in publish.DATABASES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, record BLOB)")
            db.execute("INSERT INTO history VALUES (1, zeroblob(?))",
                       (105 * 1024**2 if name == publish.DATABASES[0] else 4,))
            db.commit()
    capture = root / "data/raw/ipt/source.html"
    capture.parent.mkdir(parents=True)
    capture.write_bytes(b"unchanged source receipt")
    widget = root / publish.WIDGET
    widget.parent.mkdir(parents=True)
    widget.write_text("[2291000,2260066,1795271400]")
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "add", publish.DATABASES[0]], cwd=root, check=True)
    with pytest.raises(ValueError, match="Operational data must not be staged"):
        publish.check_staged_sizes(root)

    monkeypatch.setattr(publish, "PART_BYTES", 64 * 1024)
    output = tmp_path / "assets"
    manifest = publish.assemble(root, output, "drew-1423/fuelb", "fuel-storage-1-1")
    assert manifest["databases"]["lebanon_fuel.sqlite"]["bytes"] > 100 * 1024**2
    assert len(manifest["assets"]["databases"]) > 1

    requests = []

    def fetch(url, destination):
        requests.append(url)
        shutil.copyfile(output / url.rsplit("/", 1)[-1], destination)

    monkeypatch.setattr(publish, "download", fetch)
    pointer = root / publish.POINTER
    pointer.write_text(json.dumps(manifest))
    cached = publish.reader_root(root)
    assert not (cached / capture.relative_to(root)).exists()
    assert all("/databases-" in req for req in requests)
    assert publish.reader_root(root) == cached
    restore = tmp_path / "restored"
    publish.hydrate(manifest, restore)
    assert (restore / capture.relative_to(root)).read_bytes() == capture.read_bytes()
    for name in publish.DATABASES:
        assert publish.digest(restore / name) == manifest["databases"][name.name]["sha256"]
    with closing(sqlite3.connect(restore / publish.DATABASES[0])) as db:
        assert db.execute("SELECT id, length(record) FROM history").fetchone() == (1, 105 * 1024**2)
    previous = publish.digest(restore / publish.DATABASES[0])
    bad_part = output / manifest["assets"]["captures"][0]["name"]
    bad_part.write_bytes(b"interrupted")
    with pytest.raises(ValueError, match="Storage checksum mismatch"):
        publish.hydrate(manifest, restore)
    assert publish.digest(restore / publish.DATABASES[0]) == previous


def test_publication_requires_widget_from_same_successful_run(tmp_path):
    operations = tmp_path / "reports/operations"
    operations.mkdir(parents=True)
    check = {"anchor": {"price_lbp_20l": 2291000}, "origin": "2026-11-23T12:00:00Z"}
    (operations / "current_forecast_check.json").write_text(json.dumps(check))
    (operations / "latest_run.json").write_text(json.dumps({"steps": [
        {"name": "refresh_forecast_decision", "status": "success", "result": check},
    ]}))
    (tmp_path / publish.WIDGET).write_text(json.dumps(publish.widget_snapshot(check)))
    publish.check_refresh_output(tmp_path)
    (tmp_path / publish.WIDGET).write_text("[1,null,0]")
    with pytest.raises(ValueError, match="do not match"):
        publish.check_refresh_output(tmp_path)



def test_publication_gate_requires_successful_collection_and_audit():
    assert publish.publication_allowed("success", "success")
    assert not publish.publication_allowed("failure", "success")
    assert not publish.publication_allowed("success", "failure")
    assert not publish.publication_allowed("skipped", "success")


def test_workflow_gates_release_and_pointer_on_both_checks():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/refresh.yml").read_text()
    assert "publication gate" in workflow.lower()
    assert "gh release create" in workflow
    assert "gh release upload" in workflow
    assert workflow.count("if: steps.publication_gate.outcome == 'success'") == 5
    assert "Deploy verified snapshot to the public app branch" in workflow
    assert 'git push origin "$deployment_commit:refs/heads/codex/cloud-clean"' in workflow
    assert "FUEL_STORAGE_" not in workflow
    assert "Check cumulative release storage" in workflow


def test_staged_guard_rejects_raw_captures_and_sqlite_databases(tmp_path):
    root = tmp_path
    subprocess.run(["git", "init", "-q", root], check=True)
    raw = root / "data/raw/ipt/source.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("evidence")
    subprocess.run(["git", "add", "data/raw/ipt/source.html"], cwd=root, check=True)
    with pytest.raises(ValueError, match="Operational data must not be staged"):
        publish.check_staged_sizes(root)
    subprocess.run(["git", "reset", "-q"], cwd=root, check=True)
    database = root / "data/forecast_ledger.sqlite"
    database.write_bytes(b"sqlite data")
    subprocess.run(["git", "add", "data/forecast_ledger.sqlite"], cwd=root, check=True)
    with pytest.raises(ValueError, match="Operational data must not be staged"):
        publish.check_staged_sizes(root)


def test_retried_forecast_batch_is_idempotent_and_keeps_hash_chain(tmp_path):
    from datetime import datetime, timezone
    from lebanon_fuel.validation.ledger import ForecastLedger

    ledger = ForecastLedger(tmp_path / "forecast-ledger.sqlite")
    origin = datetime.now(timezone.utc).isoformat()
    item = dict(run_id="refresh-retry", origin=origin, mode="prospective_research",
                model_version="research-v1", model_metadata={"research_only": True},
                snapshot_payload={"anchor": 1_000_000}, horizon="decision_1",
                target={"kind": "decision", "steps": 1}, base_price=1_000_000,
                prediction=10_000, interval=None, probabilities=None, reasons=[])
    first = ledger.issue_batch([item])
    second = ledger.issue_batch([item])
    assert second == first
    assert ledger.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1
    assert ledger.integrity()["hash_chain_valid"]
    with pytest.raises(ValueError, match="conflicts with immutable issuance"):
        ledger.issue_batch([dict(item, prediction=20_000)])
    assert ledger.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1
    ledger.close()
