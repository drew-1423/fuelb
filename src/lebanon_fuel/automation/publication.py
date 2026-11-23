"""Durable refresh snapshots, published through one Git manifest."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
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
OBJECT_STORE_WARNING_BYTES = 8 * 1024**3
GROUPS = ("databases", "captures")
S3_ENV = {
    "endpoint_url": "FUEL_STORAGE_ENDPOINT_URL",
    "bucket": "FUEL_STORAGE_BUCKET",
    "access_key_id": "FUEL_STORAGE_ACCESS_KEY_ID",
    "secret_access_key": "FUEL_STORAGE_SECRET_ACCESS_KEY",
}


def s3_settings(environ=None):
    """Read writer settings without logging credentials or supplying defaults."""
    environ = os.environ if environ is None else environ
    values = {key: environ.get(variable, "").strip() for key, variable in S3_ENV.items()}
    missing = [variable for key, variable in S3_ENV.items() if not values[key]]
    if missing:
        raise RuntimeError("Durable object storage is not configured: " + ", ".join(missing))
    values["prefix"] = environ.get("FUEL_STORAGE_PREFIX", "fuelb").strip("/")
    values["region"] = environ.get("FUEL_STORAGE_REGION", "auto").strip()
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]*", values["prefix"])
            or ".." in values["prefix"].split("/") or not values["region"]):
        raise ValueError("Object storage prefix contains invalid path characters or region is empty")
    return values


def s3_client(storage, credentials=None):
    credentials = s3_settings() if credentials is None else credentials
    access_key = credentials.get("access_key_id")
    secret_key = credentials.get("secret_access_key")
    if not access_key or not secret_key:
        raise RuntimeError("Read/write credentials for the configured object store are required")
    endpoint_url = credentials.get("endpoint_url")
    bucket = credentials.get("bucket")
    if not endpoint_url or not bucket:
        raise RuntimeError("Trusted object storage endpoint and bucket configuration are required")
    if endpoint_url != storage["endpoint_url"] or bucket != storage["bucket"]:
        raise ValueError("Snapshot object-store location does not match trusted configuration")
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("Install the project requirements to use durable object storage") from exc
    return boto3.client("s3", endpoint_url=storage["endpoint_url"],
                        region_name=storage.get("region", "auto"),
                        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                        config=Config(signature_version="s3v4", retries={"max_attempts": 4}))


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


def assemble(root, output, repository, tag, storage=None):
    """Back up each SQLite connection, leaving the live databases untouched."""
    storage = s3_settings() if storage is None else dict(storage)
    for required in ("endpoint_url", "bucket", "prefix", "region"):
        if not storage.get(required):
            raise ValueError(f"Object storage setting is required: {required}")
    if not storage["endpoint_url"].startswith("https://"):
        raise ValueError("Object storage endpoint must use HTTPS")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", storage["bucket"], re.ASCII):
        raise ValueError("Invalid object storage bucket name")
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
    capture_refs = [dict(path=path.as_posix(), bytes=(root / path).stat().st_size,
                         sha256=digest(root / path),
                         key=f"{storage['prefix']}/captures/sha256/{digest(root / path)}")
                    for path in captures]
    snapshot_prefix = f"{storage['prefix']}/snapshots/{tag}"
    for part in databases:
        part["key"] = f"{snapshot_prefix}/databases/{part['name']}"
    manifest = dict(version=2, repository=repository, tag=tag,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    storage={key: storage[key] for key in ("endpoint_url", "bucket", "prefix", "region")},
                    assets=dict(databases=databases, captures=capture_refs),
                    databases=report, capture_count=len(captures),
                    widget_sha256=digest(root / WIDGET))
    validate_manifest(manifest)
    write_json(output / "manifest.json", manifest)
    return manifest


def validate_manifest(manifest):
    version = manifest["version"]
    if (version not in (1, 2)
            or not re.fullmatch(r"[\w.-]+/[\w.-]+", manifest["repository"], re.ASCII)
            or not re.fullmatch(r"fuel-storage-[0-9]+-[0-9]+", manifest["tag"])
            or set(manifest["assets"]) != set(GROUPS)
            or set(manifest["databases"]) != {path.name for path in DATABASES}):
        raise ValueError("Unsupported refresh storage manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["widget_sha256"]):
        raise ValueError("Invalid widget checksum")
    if version == 2:
        storage = manifest["storage"]
        if (not storage["endpoint_url"].startswith("https://")
                or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", storage["bucket"], re.ASCII)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_-]*", storage["prefix"])
                or ".." in storage["prefix"].split("/") or not storage["region"]):
            raise ValueError("Invalid object storage configuration in snapshot manifest")
    for group in GROUPS:
        parts = manifest["assets"][group]
        if group == "captures" and version == 2:
            if len(parts) != manifest["capture_count"]:
                raise ValueError("Snapshot capture count mismatch")
            paths = set()
            for part in parts:
                path = PurePosixPath(part["path"])
                if (path.is_absolute() or ".." in path.parts or path.parts[:2] != ("data", "raw")
                        or part["path"] in paths or part["bytes"] < 0
                        or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                        or part["key"] != f"{storage['prefix']}/captures/sha256/{part['sha256']}"):
                    raise ValueError("Invalid content-addressed capture reference")
                paths.add(part["path"])
            continue
        if not parts:
            raise ValueError("Empty refresh snapshot")
        for index, part in enumerate(parts):
            expected_name = f"{group}-{index:04d}.part" if version == 1 else f"databases-{index:04d}.part"
            if (part["name"] != expected_name or not 0 < part["bytes"] <= PART_BYTES
                    or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                    or (version == 2 and part["key"] != f"{storage['prefix']}/snapshots/{manifest['tag']}/databases/{part['name']}")):
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


def _s3_read(client, bucket, key, destination, expected_bytes=None, expected_sha=None):
    response = client.get_object(Bucket=bucket, Key=key)
    checksum, size = sha256(), 0
    with destination.open("xb") as out:
        body = response["Body"]
        try:
            while block := body.read(1024 * 1024):
                size += len(block)
                checksum.update(block)
                out.write(block)
        finally:
            body.close()
    if (expected_bytes is not None and size != expected_bytes) or (expected_sha and checksum.hexdigest() != expected_sha):
        destination.unlink(missing_ok=True)
        raise ValueError(f"Object storage checksum mismatch: {key}")


def _hydrate_s3(manifest, destination, *, database_only=False, credentials=None, client=None):
    storage = manifest["storage"]
    client = client or s3_client(storage, credentials)
    bucket = storage["bucket"]
    with tempfile.TemporaryDirectory(dir=destination) as directory:
        stage = Path(directory)
        archive_path = stage / "databases.tar.gz"
        with archive_path.open("wb") as out:
            for part in manifest["assets"]["databases"]:
                path = stage / part["name"]
                _s3_read(client, bucket, part["key"], path, part["bytes"], part["sha256"])
                with path.open("rb") as source:
                    shutil.copyfileobj(source, out)
                path.unlink()
        members = _extract(archive_path, stage, "databases")
        archive_path.unlink()
        if members != set(DATABASES):
            raise ValueError("Snapshot is missing a database")
        for name in DATABASES:
            path = stage / name
            if digest(path) != manifest["databases"][name.name]["sha256"]:
                raise ValueError(f"Database checksum mismatch: {name.name}")
            check_database(path)
        if not database_only:
            for capture in manifest["assets"]["captures"]:
                path = stage / capture["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                _s3_read(client, bucket, capture["key"], path,
                         capture["bytes"], capture["sha256"])
        # Verify all staged data before touching any existing destination file.
        for source in stage.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and digest(target) != digest(source):
                    raise ValueError(f"Refusing to replace conflicting local evidence: {target}")
        for source in stage.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(stage)
                if not target.exists():
                    source.replace(target)


def hydrate(manifest, destination, *, database_only=False, credentials=None, client=None):
    """Verify each remote part before installing any of the reconstructed files."""
    validate_manifest(manifest)
    destination.mkdir(parents=True, exist_ok=True)
    if manifest["version"] == 2:
        return _hydrate_s3(manifest, destination, database_only=database_only,
                           credentials=credentials, client=client)
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


def reader_root(root, credentials=None):
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
                hydrate(manifest, stage, database_only=True, credentials=credentials)
                stage.replace(target)
            cutoff = time.time() - 48 * 3600
            for generation in cache.iterdir():
                if (generation != target and re.fullmatch(r"[0-9a-f]{64}", generation.name)
                        and generation.is_dir() and generation.stat().st_mtime < cutoff):
                    shutil.rmtree(generation, ignore_errors=True)
    return target


def upload_snapshot(root, output, manifest_path=None, *, client=None, credentials=None):
    """Write immutable database snapshots and content-addressed raw captures, then verify them."""
    manifest = json.loads((manifest_path or output / "manifest.json").read_text())
    validate_manifest(manifest)
    if manifest["version"] != 2:
        raise ValueError("New snapshots must use durable object storage")
    storage = manifest["storage"]
    client = client or s3_client(storage, credentials)
    checked = set()
    uploads = []
    for part in manifest["assets"]["databases"]:
        uploads.append((output / part["name"], part["key"], part["bytes"], part["sha256"], False))
    for capture in manifest["assets"]["captures"]:
        key = capture["key"]
        if key not in checked:
            uploads.append((root / capture["path"], key, capture["bytes"], capture["sha256"], True))
            checked.add(key)
    for path, key, size, checksum, content_addressed in uploads:
        try:
            existing = client.head_object(Bucket=storage["bucket"], Key=key)
        except Exception as exc:
            if getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
        else:
            metadata = existing.get("Metadata", {})
            if existing.get("ContentLength") != size or metadata.get("sha256") != checksum:
                raise ValueError(f"Immutable object conflicts with its expected checksum: {key}")
            if not content_addressed:
                with tempfile.TemporaryDirectory() as directory:
                    check = Path(directory) / "remote-object"
                    _s3_read(client, storage["bucket"], key, check, size, checksum)
            continue
        client.upload_file(str(path), storage["bucket"], key,
                           ExtraArgs={"Metadata": {"sha256": checksum}})
        remote = client.head_object(Bucket=storage["bucket"], Key=key)
        if remote.get("ContentLength") != size or remote.get("Metadata", {}).get("sha256") != checksum:
            raise ValueError(f"Uploaded object failed metadata verification: {key}")
        # Full read-back verifies the bytes, not merely the provider's ETag.
        with tempfile.TemporaryDirectory() as directory:
            check = Path(directory) / "remote-object"
            _s3_read(client, storage["bucket"], key, check, size, checksum)
    storage_bytes, object_count = 0, 0
    token = None
    while True:
        kwargs = {"Bucket": storage["bucket"], "Prefix": f"{storage['prefix']}/"}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            storage_bytes += item["Size"]
            object_count += 1
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            raise ValueError("Object store returned an incomplete usage listing")
    if storage_bytes >= OBJECT_STORE_WARNING_BYTES:
        print(f"::warning::Fuel storage prefix uses {storage_bytes} bytes across {object_count} objects; review storage costs and recovery policy.")
    return dict(status="verified", database_parts=len(manifest["assets"]["databases"]),
                unique_capture_objects=len(checked), object_count=object_count,
                storage_bytes=storage_bytes)


def publication_allowed(collection_outcome, audit_outcome):
    """Publish only after both collection and integrity audit completed successfully."""
    return collection_outcome == "success" and audit_outcome == "success"


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
        if name.startswith("data/raw/") or (name.startswith("data/") and PurePosixPath(name).suffix in {".sqlite", ".db"}):
            raise ValueError(f"Operational data must not be staged in Git: {name}")
        size = int(subprocess.check_output(["git", "cat-file", "-s", ":" + name], cwd=root))
        if size >= GIT_MAX_BYTES:
            raise ValueError(f"Staged Git blob {name} is {size} bytes. Publish operational data only through configured durable storage.")
        if size >= 50 * 1024**2:
            print(f"::warning::Large staged Git blob: {name} ({size} bytes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check-config", "pack", "hydrate", "upload", "verify-remote", "check-staged", "verify-widget", "gate"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    parser.add_argument("--collect-outcome")
    parser.add_argument("--audit-outcome")
    args = parser.parse_args()
    if args.command == "check-config":
        settings = s3_settings()
        print(json.dumps({"endpoint_url": settings["endpoint_url"], "bucket": settings["bucket"],
                          "prefix": settings["prefix"], "credentials": "configured"}))
    elif args.command == "pack":
        check_refresh_output(args.root)
        manifest = assemble(args.root, args.output, args.repository, args.tag)
        print(json.dumps({k: manifest[k] for k in ("tag", "databases", "capture_count")}, indent=2))
    elif args.command == "hydrate":
        path = args.manifest or args.root / POINTER
        if path.is_file():
            hydrate(json.loads(path.read_text()), args.root)
        else:
            print("Using the Git bootstrap snapshot")
    elif args.command == "upload":
        print(json.dumps(upload_snapshot(args.root, args.output), indent=2))
    elif args.command == "verify-remote":
        manifest = json.loads(args.manifest.read_text())
        with tempfile.TemporaryDirectory() as directory:
            hydrate(manifest, Path(directory))
    elif args.command == "gate":
        collect = args.collect_outcome or os.environ.get("COLLECT_OUTCOME", "")
        audit = args.audit_outcome or os.environ.get("AUDIT_OUTCOME", "")
        if not publication_allowed(collect, audit):
            raise SystemExit("Publication blocked: collection and strict integrity audit must both succeed")
        print("Collection and integrity audit passed; durable publication may proceed.")
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
