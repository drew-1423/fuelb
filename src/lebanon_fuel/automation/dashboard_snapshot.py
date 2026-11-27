"""Read-only dashboard publication discovery and atomic snapshot caching."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import Request, urlopen

from . import publication

REPOSITORY = "drew-1423/fuelb"
PUBLIC_SUMMARY = "https://drew-1423.github.io/fuelb/"
REPORTS = (
    publication.WIDGET,
    Path("reports/operations/current_forecast_check.json"),
    Path("reports/operations/latest_run.json"),
    Path("reports/operations/monitoring.json"),
    Path("reports/data_quality.json"),
)
META = "dashboard-snapshot.json"
LIMIT = 2 * 1024 * 1024


def _get(url, limit=LIMIT):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "fuelb-dashboard"})
    with urlopen(request, timeout=3) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Dashboard publication response exceeds size limit")
    return data


def publication_record(content, revision=None):
    manifest = json.loads(content)
    publication.validate_manifest(manifest)
    if manifest["repository"] != REPOSITORY or datetime.fromisoformat(manifest["created_at"]).utcoffset() is None:
        raise ValueError("Unexpected dashboard publication identity")
    return dict(tag=manifest["tag"], created_at=manifest["created_at"], identity=sha256(content).hexdigest(),
                revision=revision, manifest=manifest)


def pinned_url(revision, path):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Dashboard publication requires an immutable Git commit")
    return f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{path.as_posix()}"


def canonical_publication():
    ref = json.loads(_get(f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main", 16384))
    revision = ref["object"]["sha"]
    return publication_record(_get(pinned_url(revision, publication.POINTER), 100000), revision)


def repository_publication(root):
    return publication_record((root / publication.POINTER).read_bytes())


def cache_dir(root):
    return root / "data/cache/dashboard-snapshots"


def verified_widget(path, record):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != record["manifest"]["widget_sha256"]:
        raise ValueError("Dashboard summary checksum mismatch")
    price, forecast, issued = json.loads(raw)
    if (any(value is not None and (type(value) is not int or value <= 0) for value in (price, forecast))
            or type(issued) is not int or issued < 0):
        raise ValueError("Dashboard summary values are invalid")
    return price, forecast, issued


def restore(root, record):
    """Install databases and matching Git reports together, each on the same release."""
    cache = cache_dir(root)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / record["identity"]
    if ready(target):
        return target
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        stage = Path(directory) / "verified"
        for name in REPORTS:
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if record["revision"]:
                dest.write_bytes(_get(pinned_url(record["revision"], name)))
            else:
                shutil.copyfile(root / name, dest)
            json.loads(dest.read_bytes())
        verified_widget(stage / publication.WIDGET, record)
        publication.hydrate(record["manifest"], stage, database_only=True)
        (stage / META).write_text(json.dumps(record))
        try:
            stage.rename(target)
        except OSError:
            if not ready(target):
                raise
    return target


def ready(path):
    return (path / META).is_file() and all((path / name).is_file() for name in (*publication.DATABASES, *REPORTS))


def previous_snapshot(root, *, before):
    candidates = []
    for path in cache_dir(root).glob("*"):
        if not re.fullmatch(r"[0-9a-f]{64}", path.name) or not ready(path):
            continue
        try:
            record = json.loads((path / META).read_text())
            created = datetime.fromisoformat(record["created_at"])
            if path.name == record["identity"] and created <= datetime.fromisoformat(before):
                candidates.append((created, path, record))
        except (ValueError, OSError, KeyError, TypeError):
            continue
    if candidates:
        _, path, record = max(candidates)
        return path, record
    return None
