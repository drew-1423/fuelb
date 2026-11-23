"""User LaunchAgent lifecycle. No root daemon or dependency on Codex."""
from pathlib import Path
import os
import plistlib
import subprocess
import sys

from .schedule import settings

LABEL = "com.andrew.lebanon-fuel.refresh"


def manifest(root, python=None):
    root = root.resolve()
    cfg = settings(root)
    return dict(Label=LABEL,
        ProgramArguments=[str(python or root / ".venv/bin/python"), "-m", "lebanon_fuel.automation.cli", "--root", str(root), "tick"],
        WorkingDirectory=str(root), RunAtLoad=True, StartInterval=cfg["schedule"]["poll_seconds"],
        ProcessType="Background", LowPriorityIO=True, Nice=5, ThrottleInterval=60,
        StandardOutPath=str(root / "data/logs/launchd.out.log"),
        StandardErrorPath=str(root / "data/logs/launchd.err.log"),
        EnvironmentVariables=dict(PATH="/usr/bin:/bin:/usr/sbin:/sbin", PYTHONPATH=str(root / "src"),
                                  PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1",
                                  OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1",
                                  MPLCONFIGDIR=str(root / "data/cache/matplotlib")))


def prepare(root):
    path = root / "data/launchd" / (LABEL + ".plist")
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / "data/logs").mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(manifest(root)))
    subprocess.run(["/usr/bin/plutil", "-lint", str(path)], check=True, capture_output=True)
    return path


def domain():
    return f"gui/{os.getuid()}"


def call(*args, check=True):
    result = subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result


def install(root):
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent installation requires macOS")
    prepared = prepare(root)
    target = Path.home() / "Library/LaunchAgents" / prepared.name
    target.parent.mkdir(parents=True, exist_ok=True)
    current = call("print", domain() + "/" + LABEL, check=False)
    if current.returncode == 0:
        # Do not interrupt an active data refresh just to change its schedule.
        if "state = running" in current.stdout:
            raise RuntimeError("Refresh is running. Retry installation after it finishes.")
        call("bootout", domain() + "/" + LABEL)
    target.write_bytes(prepared.read_bytes())
    target.chmod(0o644)
    call("enable", domain() + "/" + LABEL)
    call("bootstrap", domain(), str(target))
    return dict(installed=str(target), status=call("print", domain() + "/" + LABEL).stdout)


def uninstall():
    current = call("print", domain() + "/" + LABEL, check=False)
    if current.returncode == 0:
        if "state = running" in current.stdout:
            raise RuntimeError("Wait for the active refresh to finish before uninstalling")
        call("bootout", domain() + "/" + LABEL)
    path = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    path.unlink(missing_ok=True)
    return dict(status="removed", path=str(path))
