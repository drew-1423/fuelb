"""Build a clean database and preserve the pre-cutover database byte for byte."""
from argparse import ArgumentParser
from contextlib import closing
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
import sqlite3

from lebanon_fuel.automation.maintenance import check_database
from lebanon_fuel.storage.baseline import file_digest
from lebanon_fuel.storage.database import Store


# Preserve primary keys. Keep the original first sighting so the raw row and its
# availability clock have the same evidence. Historical decision revisions are
# recomputed at cutover and get new IDs.
COPY_FILTERS = {
    "schema_version": "",
    "sources": "",
    "collection_runs": "",
    "captures": "WHERE id IN (SELECT id FROM retained_captures)",
    "observations": """WHERE EXISTS (
        SELECT 1 FROM legacy.sightings s JOIN captures c ON c.id=s.capture_id
        WHERE s.observation_id=o.id AND c.retrieved_at=o.first_retrieved_at
        AND (o.document_verified=0 OR EXISTS (
            SELECT 1 FROM captures p WHERE p.id=json_extract(c.metadata_json,'$.evidence_capture_id')
            AND p.sha256=json_extract(o.raw_json,'$.evidence_sha256')
        ))
    )""",
    "sightings": """WHERE capture_id IN (SELECT id FROM captures)
        AND observation_id IN (SELECT id FROM observations)""",
    "resolutions": """WHERE chosen_observation_id IN (SELECT id FROM observations)
        AND NOT EXISTS (SELECT 1 FROM json_each(o.basis_observation_ids)
                        WHERE value NOT IN (SELECT id FROM observations))""",
    "decision_versions": "WHERE 0",
    "market_series": "",
    "market_observations": """WHERE EXISTS (
        SELECT 1 FROM legacy.market_sightings s JOIN captures c ON c.id=s.capture_id
        WHERE s.observation_id=o.id AND c.retrieved_at=o.first_seen_at
    )""",
    "market_sightings": """WHERE capture_id IN (SELECT id FROM captures)
        AND observation_id IN (SELECT id FROM market_observations)""",
    "news_items": "WHERE capture_id IN (SELECT id FROM captures)",
    "news_sightings": """WHERE capture_id IN (SELECT id FROM captures)
        AND item_id IN (SELECT id FROM news_items)""",
}


def build(root, output, source_commit):
    source_path = root / "data/lebanon_fuel.sqlite"
    check_database(source_path)
    source_hash = file_digest(source_path)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "lebanon_fuel_prebaseline.sqlite.gz"
    with source_path.open("rb") as source, archive.open("xb") as packed:
        with gzip.GzipFile(filename="", fileobj=packed, mode="wb", mtime=0) as destination:
            shutil.copyfileobj(source, destination)
    database = output / "lebanon_fuel.sqlite"
    with closing(sqlite3.connect(database.as_uri(), uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("ATTACH DATABASE ? AS legacy", (source_path.as_uri() + "?mode=ro",))
        schema = db.execute("SELECT type,name,sql FROM legacy.sqlite_schema WHERE sql IS NOT NULL").fetchall()
        tables = {row["name"]: row["sql"] for row in schema if row["type"] == "table"}
        if tables.keys() != COPY_FILTERS.keys():
            raise ValueError("Unexpected source schema. Review evidence dependencies before building.")
        captures = [dict(row) for row in db.execute("""SELECT id,source_id,url,retrieved_at,
            sha256,raw_path,metadata_json FROM legacy.captures ORDER BY id""")]
        checked = {}
        excluded = {}
        retained = {}
        for capture in captures:
            path = capture["raw_path"]
            target = (root / path).resolve()
            if not target.is_relative_to((root / "data/raw").resolve()):
                raise ValueError(f"Raw capture outside data/raw: {path}")
            if path not in checked:
                checked[path] = file_digest(target) if target.is_file() else None
            if checked[path] != capture["sha256"]:
                excluded[capture["id"]] = dict(capture, reason="missing" if checked[path] is None else "checksum_mismatch")
            else:
                retained[capture["id"]] = capture
        # A saved transcription may depend on a separate PDF capture.
        while True:
            disconnected = [i for i, c in retained.items()
                            if (parent := json.loads(c["metadata_json"]).get("evidence_capture_id"))
                            and parent not in retained]
            if not disconnected:
                break
            for i in disconnected:
                excluded[i] = dict(retained.pop(i), reason="missing_linked_original")
        db.execute("CREATE TEMP TABLE retained_captures(id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO retained_captures VALUES (?)", [(i,) for i in retained])
        counts = {}
        with db:
            for table, condition in COPY_FILTERS.items():
                db.execute(tables[table])
                original = db.execute(f"SELECT COUNT(*) FROM legacy.{table}").fetchone()[0]
                db.execute(f"INSERT INTO main.{table} SELECT o.* FROM legacy.{table} o {condition}")
                count = db.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
                counts[table] = {"legacy": original, "retained": count}
                # IDs belong to immutable provenance. Prevent future inserts from reusing
                # an excluded ID when a table's last row did not survive the copy.
                if "id INTEGER PRIMARY KEY" in tables[table] and table != "decision_versions":
                    before, after = (db.execute(f"SELECT MAX(id) FROM {schema_name}.{table}").fetchone()[0]
                                     for schema_name in ("legacy", "main"))
                    if before != after:
                        raise ValueError(f"{table} requires an ID reservation strategy before cutover")
            for item in schema:
                if item["type"] != "table":
                    db.execute(item["sql"])
            revision_floor = db.execute("SELECT COALESCE(MAX(id),0) FROM legacy.decision_versions").fetchone()[0]
    with closing(Store(root, database)) as store:
        revised = store.reconcile(first_revision_id=revision_floor + 1)
    check_database(database)
    if file_digest(source_path) != source_hash:
        raise ValueError("Source database changed during baseline build")
    clock = datetime.now(timezone.utc).isoformat()
    manifest = dict(
        version="audited-baseline-v1", created_at=clock, legacy_commit=source_commit,
        legacy_archive="data/legacy/" + archive.name, legacy_archive_sha256=file_digest(archive),
        legacy_database_sha256=source_hash, initial_active_database_sha256=file_digest(database),
        excluded_capture_rows=len(excluded), excluded_paths=len({item["raw_path"] for item in excluded.values()}),
        legacy_max_revision_id=revision_floor, rebuilt_revisions=revised, row_counts=counts,
    )
    (output / "audited_baseline.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for capture in excluded.values():
        capture.pop("metadata_json")
    (output / "baseline_excluded_captures.json").write_text(json.dumps(list(excluded.values()), indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.output.resolve(), args.source_commit), indent=2))
