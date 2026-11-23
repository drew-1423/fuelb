"""Durable refresh snapshots, published through one Git manifest."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .maintenance import check_database, digest
from .runner import widget_snapshot
from .state import write_json

POINTER = Path("reports/operations/published_storage.json")
DATABASES = tuple(Path("data") / name for name in (
    "lebanon_fuel.sqlite", "forecast_ledger.sqlite", "operations.sqlite",
))
WIDGET = Path("reports/operations/widget_snapshot.json")
PART_BYTES = 64 * 1024**2
GIT_MAX_BYTES = 95 * 1024**2
GROUPS = ("databases", "captures")


def _archive(root, paths, output, group):
    parts = []
    with tempfile.TemporaryDirectory(dir=output) as directory:
        bundle = Path(directory) / f"{group}.tar.gz"
        with tarfile.open(bundle, "w:gz", compresslevel=3) as archive:
            for name in paths:
                archive.add(root / name, arcname=name.as_posix(), recursive=False)
        with bundle.open("rb") as stream:
            while block := stream.read(PART_BYTES):
                name = f"{group}-{len(parts):04d}.part"
                path = output / name
                path.write_bytes(block)
                parts.append(dict(name=name, bytes=len(block), sha256=digest(path)))
    return parts


def assemble(root, output, repository, tag):
    """Back up each SQLite connection, leaving the live databases untouched."""
    output.mkdir(parents=True, exist_ok=False)
    report = {}
    with tempfile.TemporaryDirectory(dir=output) as directory:
        backup = Path(directory)
        for name in DATABASES:
            source = root / name
            target = backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db, \
                    closing(sqlite3.connect(target)) as copy:
                db.backup(copy)
                size = db.execute("PRAGMA page_size").fetchone()[0]
                pages = db.execute("PRAGMA page_count").fetchone()[0]
                free = db.execute("PRAGMA freelist_count").fetchone()[0]
            check_database(target)
            report[name.name] = dict(bytes=pages * size, reclaimable_bytes=free * size,
                                     sha256=digest(target))
        databases = _archive(backup, DATABASES, output, "databases")
    captures = sorted(path.relative_to(root) for path in (root / "data/raw").rglob("*")
                      if path.is_file())
    manifest = dict(version=1, repository=repository, tag=tag,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    assets=dict(databases=databases, captures=_archive(root, captures, output, "captures")),
                    databases=report, capture_count=len(captures),
                    widget_sha256=digest(root / WIDGET))
    validate_manifest(manifest)
    write_json(output / "manifest.json", manifest)
    return manifest


def validate_manifest(manifest):
    if (manifest["version"] != 1
            or not re.fullmatch(r"[\w.-]+/[\w.-]+", manifest["repository"], re.ASCII)
            or not re.fullmatch(r"fuel-storage-[0-9]+-[0-9]+", manifest["tag"])
            or set(manifest["assets"]) != set(GROUPS)
            or set(manifest["databases"]) != {path.name for path in DATABASES}):
        raise ValueError("Unsupported refresh storage manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["widget_sha256"]):
        raise ValueError("Invalid widget checksum")
    for group in GROUPS:
        parts = manifest["assets"][group]
        if not parts:
            raise ValueError("Empty refresh snapshot")
        for index, part in enumerate(parts):
            if (part["name"] != f"{group}-{index:04d}.part" or not 0 < part["bytes"] <= PART_BYTES
                    or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])):
                raise ValueError("Invalid refresh snapshot part")


def download(url, destination, *, attempts=4):
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=45) as response, destination.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024**2)
            return
        except (URLError, TimeoutError, ConnectionError) as exc:
            if (isinstance(exc, HTTPError) and exc.code not in {404, 408, 429, 500, 502, 503, 504}
                    or attempt + 1 >= attempts):
                raise
            time.sleep(2**attempt)


def _extract(archive_path, destination, group):
    seen = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        for entry in archive:
            name = PurePosixPath(entry.name)
            if (not entry.isfile() or name.is_absolute() or ".." in name.parts or name in seen
                    or (name not in DATABASES if group == "databases" else name.parts[:2] != ("data", "raw"))):
                raise ValueError(f"Invalid snapshot member: {entry.name}")
            seen.add(name)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, target.open("xb") as out:
                shutil.copyfileobj(source, out)
    return seen


def hydrate(manifest, destination, *, database_only=False):
    """Verify each remote part before installing any of the reconstructed files."""
    validate_manifest(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    base = f"https://github.com/{manifest['repository']}/releases/download/{manifest['tag']}"
    with tempfile.TemporaryDirectory(dir=destination) as directory:
        stage = Path(directory)
        for group in GROUPS[:1] if database_only else GROUPS:
            archive = stage / "bundle.tar.gz"
            with archive.open("wb") as out:
                for part in manifest["assets"][group]:
                    path = stage / part["name"]
                    download(f"{base}/{part['name']}", path)
                    if path.stat().st_size != part["bytes"] or digest(path) != part["sha256"]:
                        raise ValueError(f"Storage checksum mismatch: {part['name']}")
                    with path.open("rb") as stream:
                        shutil.copyfileobj(stream, out)
                    path.unlink()
            members = _extract(archive, stage, group)
            if group == "databases":
                if members != set(DATABASES):
                    raise ValueError("Snapshot is missing a database")
                for name in DATABASES:
                    path = stage / name
                    if digest(path) != manifest["databases"][name.name]["sha256"]:
                        raise ValueError(f"Database checksum mismatch: {name.name}")
                    check_database(path)
            elif len(members) != manifest["capture_count"]:
                raise ValueError("Snapshot capture count mismatch")
            archive.unlink()
        for source in stage.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)


def reader_root(root):
    """Isolate cloud readers by generation, even while a new bundle downloads."""
    manifest_path = root / POINTER
    if not manifest_path.is_file() or os.environ.get("LEBANON_FUEL_LOCAL_STORAGE") == "1":
        return root
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)
    cache = root / "data/cache/published-storage"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / digest(manifest_path)
    with (cache / "download.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not all((target / name).is_file() for name in DATABASES):
            with tempfile.TemporaryDirectory(dir=cache) as directory:
                stage = Path(directory) / "snapshot"
                hydrate(manifest, stage, database_only=True)
                stage.replace(target)
            cutoff = time.time() - 48 * 3600
            for generation in cache.iterdir():
                if (generation != target and re.fullmatch(r"[0-9a-f]{64}", generation.name)
                        and generation.is_dir() and generation.stat().st_mtime < cutoff):
                    shutil.rmtree(generation, ignore_errors=True)
    return target


def check_refresh_output(root):
    operations = root / "reports/operations"
    cycle = json.loads((operations / "latest_run.json").read_text())
    steps = {item["name"]: item for item in cycle["steps"]}
    check = json.loads((operations / "current_forecast_check.json").read_text())
    if (any(item["status"] != "success" for item in steps.values())
            or steps.get("refresh_forecast_decision", {}).get("result") != check
            or json.loads((root / WIDGET).read_text()) != widget_snapshot(check)):
        raise ValueError("Refresh outputs do not match a completed forecast cycle")


def check_staged_sizes(root):
    names = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], cwd=root,
    ).split(b"\0")
    for path in filter(None, names):
        name = os.fsdecode(path)
        size = int(subprocess.check_output(["git", "cat-file", "-s", ":" + name], cwd=root))
        if size >= GIT_MAX_BYTES:
            raise ValueError(f"Staged Git blob {name} is {size} bytes. Publish large files as release assets.")
        if size >= 50 * 1024**2:
            print(f"::warning::Large staged Git blob: {name} ({size} bytes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pack", "hydrate", "verify-remote", "check-staged", "verify-widget"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    args = parser.parse_args()
    if args.command == "pack":
        check_refresh_output(args.root)
        manifest = assemble(args.root, args.output, args.repository, args.tag)
        print(json.dumps({k: manifest[k] for k in ("tag", "databases", "capture_count")}, indent=2))
    elif args.command == "hydrate":
        path = args.manifest or args.root / POINTER
        if path.is_file():
            hydrate(json.loads(path.read_text()), args.root)
        else:
            print("Using the Git bootstrap snapshot")
    elif args.command == "verify-remote":
        manifest = json.loads(args.manifest.read_text())
        with tempfile.TemporaryDirectory() as directory:
            hydrate(manifest, Path(directory))
    elif args.command == "check-staged":
        check_staged_sizes(args.root)
    else:
        manifest = json.loads((args.root / POINTER).read_text())
        validate_manifest(manifest)
        base = f"https://raw.githubusercontent.com/{manifest['repository']}/{args.commit}"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            download(f"{base}/{WIDGET}", folder / "widget.json")
            download(f"{base}/{POINTER}", folder / "pointer.json")
            if (digest(folder / "widget.json") != manifest["widget_sha256"]
                    or json.loads((folder / "pointer.json").read_text()) != manifest):
                raise ValueError("Published widget or manifest failed verification")
            print("Public widget and storage manifest verified.")


if __name__ == "__main__":
    main()
