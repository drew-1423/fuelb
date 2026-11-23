from contextlib import closing
import json
import shutil
import sqlite3
import subprocess

import pytest

from lebanon_fuel.automation import publication as publish


def test_oversized_refresh_roundtrip_and_git_guard(tmp_path, monkeypatch):
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
    with pytest.raises(ValueError, match="Staged Git blob data/lebanon_fuel.sqlite"):
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
