"""Restore a trusted project backup into a fresh temporary directory and audit it."""
from pathlib import Path
from contextlib import closing
import argparse
import json
import shutil
import sqlite3
import tarfile
import tempfile
import tomllib

from lebanon_fuel.automation.maintenance import audit, verify_backup
from lebanon_fuel.automation.state import now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--report", type=Path, default=Path("reports/operations/backup_restore_check.json"))
    args = parser.parse_args()
    backup = args.backup.resolve()
    verification = verify_backup(backup)
    root = Path(tempfile.mkdtemp(prefix="lebanon-fuel-recovery-"))
    with tarfile.open(backup / "artifacts.tar.gz") as archive:
        archive.extractall(root, filter="data")
    (root / "data").mkdir(exist_ok=True)
    for path in backup.glob("*.sqlite"):
        shutil.copy2(path, root / "data" / path.name)
    config = tomllib.loads((root / "config/project.toml").read_text())
    integrity = audit(root, config)
    with closing(sqlite3.connect(root / config["storage"]["database"])) as db:
        observations = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    result = dict(checked_at=now().isoformat(), status="passed", backup=str(backup),
                  recovery_directory=str(root), source_observations=observations,
                  backup_verification=verification, integrity=integrity,
                  note="Restored to a new directory. Working project and native scheduler were not replaced.")
    write_json(args.report, result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
