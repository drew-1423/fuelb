"""Local operations commands. Scheduled jobs do not invoke an AI service."""
from contextlib import closing
from pathlib import Path
import argparse
import json
import subprocess
import sys
import tomllib

from . import launchd, maintenance
from .runner import run
from .schedule import SOURCES
from .state import AlreadyRunning, Journal, now, refresh_lock, atomic_write


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "tick"):
        command = commands.add_parser(name)
        command.add_argument("--source", choices=SOURCES)
        command.add_argument("--offline", action="store_true", help="Evaluate stored data without network collection")
    for name in ("prepare", "install", "uninstall", "status", "kick", "audit", "backup"):
        commands.add_parser(name)
    command = commands.add_parser("verify-backup")
    command.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command in ("run", "tick"):
            result = run(root, scheduled=args.command == "tick", sources=[args.source] if args.source else None, offline=args.offline)
            if result["status"] != "not_due":
                summary = {k: result[k] for k in ("run_id", "status", "production_forecast_status")}
                summary["sources"] = result["source_results"]
                summary["failed_steps"] = [s for s in result["steps"] if s["status"] == "failed"]
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            return int(result["status"] == "degraded")
        if args.command == "prepare":
            result = dict(plist=str(launchd.prepare(root)))
        elif args.command == "install":
            result = launchd.install(root)
        elif args.command == "uninstall":
            result = launchd.uninstall()
        elif args.command == "status":
            state = launchd.call("print", launchd.domain() + "/" + launchd.LABEL, check=False)
            print(state.stdout or state.stderr)
            latest = root / "reports/operations/latest_run.json"
            if latest.exists():
                report = json.loads(latest.read_text())
                print(json.dumps({k: report[k] for k in ("run_id", "started_at", "finished_at", "status")}, indent=2))
            return int(state.returncode != 0)
        elif args.command == "kick":
            # No -k: never kill a running refresh. Preserve a request until consumed.
            atomic_write(root / "data/operations/refresh.request", now().isoformat())
            try:
                result = dict(status="requested", output=launchd.call("kickstart", launchd.domain() + "/" + launchd.LABEL).stdout)
            except subprocess.TimeoutExpired:
                result = dict(status="queued", note="launchd is throttling startup. The persistent request will be consumed on the next scheduler wake.")
        elif args.command == "verify-backup":
            result = maintenance.verify_backup(args.path)
        else:
            cfg = tomllib.loads((root / "config/project.toml").read_text())
            with refresh_lock(root):
                result = getattr(maintenance, args.command)(root, cfg)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AlreadyRunning as exc:
        print(str(exc))
        return 0 if args.command == "tick" else 2
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(message, file=sys.stderr)
        try:
            with closing(Journal(root)) as journal:
                journal.append("fatal-" + now().isoformat(), "fatal_error", args.command, dict(error=message))
        except Exception:
            pass  # Filesystem failures must still reach launchd's stderr log.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
