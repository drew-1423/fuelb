from contextlib import closing
from io import BytesIO
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from lebanon_fuel.automation import publication as publish
from lebanon_fuel.automation.state import now
from lebanon_fuel.validation.ledger import ForecastLedger


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.uploads = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        data = Path(filename).read_bytes()
        self.objects[(bucket, key)] = (data, (ExtraArgs or {}).get("Metadata", {}))
        self.uploads.append(key)

    def head_object(self, Bucket, Key):
        try:
            data, metadata = self.objects[(Bucket, Key)]
        except KeyError as exc:
            missing = RuntimeError("missing")
            missing.response = {"ResponseMetadata": {"HTTPStatusCode": 404}}
            raise missing from exc
        return {"ContentLength": len(data), "Metadata": metadata}

    def get_object(self, Bucket, Key):
        data, _ = self.objects[(Bucket, Key)]
        return {"Body": BytesIO(data)}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        rows = [{"Key": key, "Size": len(data)} for (bucket, key), (data, _) in self.objects.items()
                if bucket == Bucket and key.startswith(Prefix)]
        return {"Contents": rows, "IsTruncated": False}


class FailingS3(FakeS3):
    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        raise OSError("object storage unavailable")


STORAGE = dict(endpoint_url="https://account.r2.cloudflarestorage.com", bucket="fuelb-data",
               prefix="fuelb", region="auto")


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
    duplicate_capture = root / "data/raw/total/source.html"
    duplicate_capture.parent.mkdir(parents=True)
    duplicate_capture.write_bytes(capture.read_bytes())
    widget = root / publish.WIDGET
    widget.parent.mkdir(parents=True)
    widget.write_text("[2291000,2260066,1795271400]")
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "add", publish.DATABASES[0]], cwd=root, check=True)
    with pytest.raises(ValueError, match="Operational data must not be staged"):
        publish.check_staged_sizes(root)

    monkeypatch.setattr(publish, "PART_BYTES", 64 * 1024)
    output = tmp_path / "assets"
    manifest = publish.assemble(root, output, "drew-1423/fuelb", "fuel-storage-1-1", storage=STORAGE)
    assert manifest["databases"]["lebanon_fuel.sqlite"]["bytes"] > 100 * 1024**2
    assert len(manifest["assets"]["databases"]) > 1
    assert manifest["version"] == 2
    assert len({row["key"] for row in manifest["assets"]["captures"]}) == 1
    pointer = root / publish.POINTER
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"published":"previous"}')
    previous_pointer = pointer.read_bytes()
    with pytest.raises(OSError, match="object storage unavailable"):
        publish.upload_snapshot(root, output, client=FailingS3())
    assert pointer.read_bytes() == previous_pointer

    remote = FakeS3()
    uploaded = publish.upload_snapshot(root, output, client=remote,
                                       credentials={"access_key_id": "writer", "secret_access_key": "secret"})
    assert uploaded["status"] == "verified"
    assert uploaded["unique_capture_objects"] == 1
    assert uploaded["object_count"] == len(manifest["assets"]["databases"]) + 1
    assert len(remote.uploads) == len(manifest["assets"]["databases"]) + 1
    upload_count = len(remote.uploads)
    publish.upload_snapshot(root, output, client=remote,
                            credentials={"access_key_id": "writer", "secret_access_key": "secret"})
    assert len(remote.uploads) == upload_count
    corrupt_remote = FakeS3()
    corrupt_remote.objects = dict(remote.objects)
    first_database_part = manifest["assets"]["databases"][0]
    corrupt_remote.objects[(STORAGE["bucket"], first_database_part["key"])] = (b"wrong", {"sha256": first_database_part["sha256"]})
    with pytest.raises(ValueError, match="Immutable object conflicts"):
        publish.upload_snapshot(root, output, client=corrupt_remote,
                                credentials={"access_key_id": "writer", "secret_access_key": "secret"})
    pointer = root / publish.POINTER
    pointer.write_text(json.dumps(manifest))
    original_hydrate = publish.hydrate
    credentials = {"access_key_id": "reader", "secret_access_key": "secret",
                   "endpoint_url": STORAGE["endpoint_url"], "bucket": STORAGE["bucket"]}
    with monkeypatch.context() as patcher:
        patcher.setattr(publish, "hydrate", lambda item, destination, **kwargs:
                        original_hydrate(item, destination, client=remote, **kwargs))
        cached = publish.reader_root(root, credentials=credentials)
        assert all(publish.digest(cached / name) == manifest["databases"][name.name]["sha256"]
                   for name in publish.DATABASES)
        assert not (cached / capture.relative_to(root)).exists()
        assert publish.reader_root(root, credentials=credentials) == cached
    restore = tmp_path / "restored"
    publish.hydrate(manifest, restore, client=remote)
    assert (restore / capture.relative_to(root)).read_bytes() == capture.read_bytes()
    assert (restore / duplicate_capture.relative_to(root)).read_bytes() == capture.read_bytes()
    for name in publish.DATABASES:
        assert publish.digest(restore / name) == manifest["databases"][name.name]["sha256"]
    with closing(sqlite3.connect(restore / publish.DATABASES[0])) as db:
        assert db.execute("SELECT id, length(record) FROM history").fetchone() == (1, 105 * 1024**2)
    previous = publish.digest(restore / publish.DATABASES[0])
    bad_part = manifest["assets"]["captures"][0]
    remote.objects[(STORAGE["bucket"], bad_part["key"])] = (b"interrupted", {"sha256": "bad"})
    with pytest.raises(ValueError, match="checksum mismatch"):
        publish.hydrate(manifest, restore, client=remote)
    assert publish.digest(restore / publish.DATABASES[0]) == previous


def test_publication_gate_requires_both_collection_and_audit():
    assert publish.publication_allowed("success", "success")
    assert not publish.publication_allowed("failure", "success")
    assert not publish.publication_allowed("success", "failure")
    assert not publish.publication_allowed("skipped", "success")


def test_object_store_credentials_cannot_be_sent_to_manifest_endpoint():
    with pytest.raises(ValueError, match="does not match trusted configuration"):
        publish.s3_client(STORAGE, {"access_key_id": "reader", "secret_access_key": "secret",
                                    "endpoint_url": "https://untrusted.example", "bucket": STORAGE["bucket"]})


def test_missing_object_store_configuration_fails_closed():
    with pytest.raises(RuntimeError, match="FUEL_STORAGE_ENDPOINT_URL"):
        publish.s3_settings({})


def test_retried_forecast_batch_is_idempotent_without_changing_hash_chain(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecast-ledger.sqlite")
    origin = now().isoformat()
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
    conflict = dict(item, prediction=20_000)
    with pytest.raises(ValueError, match="conflicts with immutable issuance"):
        ledger.issue_batch([conflict])
    assert ledger.db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1
    ledger.close()


def test_workflow_uses_gate_and_does_not_upload_databases_to_github_releases():
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/refresh.yml").read_text()
    assert "Gate publication on collection and integrity success" in workflow
    assert workflow.count("if: steps.publication_gate.outcome == 'success'") == 4
    assert "gh release create" not in workflow
    assert "publication upload" in workflow


def test_staged_guard_rejects_raw_capture_files(tmp_path):
    root = tmp_path
    raw = root / "data/raw/ipt/source.html"
    raw.parent.mkdir(parents=True)
    raw.write_text("evidence")
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "add", "data/raw/ipt/source.html"], cwd=root, check=True)
    with pytest.raises(ValueError, match="Operational data must not be staged"):
        publish.check_staged_sizes(root)


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
