"""Consistent SQLite backups and reproducible local integrity checks."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import json
import math
import sqlite3
import tarfile

from lebanon_fuel.market.catalog import SERIES
from lebanon_fuel.validation.ledger import ForecastLedger, hashed
from .state import now, write_json


def digest(path):
    checksum = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def check_database(path):
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign = list(db.execute("PRAGMA foreign_key_check"))
    if integrity != ["ok"] or foreign:
        raise ValueError(f"SQLite integrity failed for {path.name}: {integrity}, foreign keys {foreign}")
    return dict(database=path.name, integrity="ok", foreign_key_errors=0)


def audit(root, cfg):
    source_path = root / cfg["storage"]["database"]
    ledger_path = root / cfg["validation"]["forecast_ledger"]
    databases = [check_database(path) for path in (source_path, ledger_path, root / "data/operations.sqlite") if path.exists()]
    with closing(sqlite3.connect(f"{source_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        raw = db.execute("SELECT DISTINCT raw_path,sha256 FROM captures").fetchall()
        for path, checksum in raw:
            if digest(root / path) != checksum:
                raise ValueError(f"Raw capture checksum mismatch: {path}")
        units = db.execute("SELECT COUNT(*) FROM observations WHERE is_valid=1 AND (unit!='LBP/20L' OR price_lbp_20l<=0)").fetchone()[0]
        if units:
            raise ValueError("Invalid domestic unit or price in eligible observations")
        checked = 0
        for sid, value, raw_value, unit in db.execute("SELECT series_id,value,raw_value,unit FROM market_observations WHERE valid=1"):
            spec = SERIES[sid]
            if unit != spec.normalized_unit or not math.isclose(value, float(raw_value) * spec.factor, rel_tol=1e-12):
                raise ValueError(f"Incorrect market normalization: {sid}")
            checked += 1
    model_files = {}
    for path in (root / "data/models/part5").glob("*/*/manifest.json"):
        for filename, checksum in json.loads(path.read_text())["files"].items():
            artifact = (path.parent / filename).resolve()
            if not artifact.is_relative_to((root / "data/models").resolve()):
                raise ValueError("Model manifest path escapes the local model directory")
            model_files[artifact] = checksum
    folds = root / "reports/model_validation/folds.json"
    if folds.exists():
        for fold in json.loads(folds.read_text()):
            if fold.get("model_path") and fold.get("model_sha256"):
                model_files[root / fold["model_path"] / "bundle.joblib"] = fold["model_sha256"]
    for path, checksum in model_files.items():
        if digest(path) != checksum:
            raise ValueError(f"Saved model checksum mismatch: {path}")
    with closing(ForecastLedger(ledger_path)) as ledger:
        integrity = ledger.integrity()
        snapshots = 0
        for identity, payload in ledger.db.execute("SELECT id,payload_json FROM snapshots"):
            if hashed(json.loads(payload)) != identity:
                raise ValueError("Input snapshot hash mismatch")
            snapshots += 1
        # Re-evaluate every stored signed error, including superseded versions.
        errors = ledger.db.execute("""SELECT COUNT(*) FROM evaluations e
            JOIN forecasts f ON f.id=e.forecast_id JOIN outcomes o ON o.id=e.outcome_id
            WHERE ABS(e.prediction_error-(f.predicted_price-o.price))>0.000001
               OR ABS(e.actual_change-(o.price-f.base_price))>0.000001""").fetchone()[0]
        if errors:
            raise ValueError("Forecast evaluation arithmetic mismatch")
    return dict(checked_at=now().isoformat(), databases=databases, raw_files_checked=len(raw),
                normalized_market_rows_checked=checked, snapshots_checked=snapshots,
                model_files_checked=len(model_files),
                evaluation_arithmetic_errors=errors, **integrity)


def backup(root, cfg):
    stamp = now().strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / "data/backups" / stamp
    destination.mkdir(parents=True, exist_ok=False)
    databases = [root / cfg["storage"]["database"], root / cfg["validation"]["forecast_ledger"], root / "data/operations.sqlite"]
    files = {}
    for path in databases:
        if not path.exists():
            continue
        target = destination / path.name
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(target)) as copy:
            source.backup(copy)
        check_database(target)
        files[target.name] = digest(target)
    archive = destination / "artifacts.tar.gz"
    members = ["src/lebanon_fuel", "config", "research", "docs", "scripts", "Tests/fuel", ".streamlit",
               ".agents/skills", "data/raw", "data/manual", "data/models", "data/exports", "reports",
               "pyproject.toml", "README.md"] + [p.name for p in root.glob("requirements*lock.txt")]
    with tarfile.open(archive, "w:gz") as output:
        for member in members:
            path = root / member
            if path.exists():
                output.add(path, arcname=member, filter=lambda info: None if "__pycache__" in info.name else info)
    files[archive.name] = digest(archive)
    result = dict(created_at=now().isoformat(), directory=str(destination), files=files,
                  note="SQLite online backups under the shared refresh lock. Retain this entire directory and copy off-device.")
    write_json(destination / "manifest.json", result)
    return result


def verify_backup(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        if digest(path / name) != checksum:
            raise ValueError("Backup checksum mismatch: " + name)
        if name.endswith(".sqlite"):
            check_database(path / name)
    with tarfile.open(path / "artifacts.tar.gz") as archive:
        count = len(archive.getmembers())
        for member in archive.getmembers():
            if member.isfile():
                with archive.extractfile(member) as stream:
                    while stream.read(1024 * 1024):
                        pass  # Verify compressed payload readability without extracting paths.
    return dict(status="verified", files=len(manifest["files"]), archive_members=count)
