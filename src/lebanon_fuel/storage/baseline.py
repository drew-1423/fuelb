"""Locate and verify the sealed source database for historical research audits."""
from contextlib import contextmanager, closing
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory

BASELINE_CONFIG = Path("config/audited_baseline.json")


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_legacy_archive(root):
    path = root / BASELINE_CONFIG
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    archive = root / manifest["legacy_archive"]
    if file_digest(archive) != manifest["legacy_archive_sha256"]:
        raise ValueError("Legacy database archive checksum mismatch")
    return manifest


@contextmanager
def historical_database(root):
    """Use the original revision IDs and data when reproducing pre-cutover artifacts."""
    manifest = check_legacy_archive(root)
    with TemporaryDirectory(prefix="fuel-legacy-audit-") as scratch:
        database = root / "data/lebanon_fuel.sqlite"
        if manifest:
            database = Path(scratch) / "legacy.sqlite"
            with gzip.open(root / manifest["legacy_archive"], "rb") as source, database.open("xb") as dest:
                shutil.copyfileobj(source, dest)
            if file_digest(database) != manifest["legacy_database_sha256"]:
                raise ValueError("Legacy database checksum mismatch")
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            yield connection
