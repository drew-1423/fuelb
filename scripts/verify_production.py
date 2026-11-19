"""Re-run the fuel project's test suite and artifact audits; never train or collect."""
from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    "current_release_integrity": [sys.executable, "-m", "lebanon_fuel.automation.release", "verify"],
    "pytest": [sys.executable, "-m", "pytest", "Tests/fuel", "-q"],
    "structural_artifact_audit": [sys.executable, "scripts/audit_structural_artifacts.py"],
    "forecasting_artifact_audit": [sys.executable, "scripts/audit_forecasting_artifacts.py"],
    "validation_artifact_audit": [sys.executable, "scripts/audit_validation_artifacts.py"],
    "operations_integrity": [sys.executable, "-m", "lebanon_fuel.automation.cli", "audit"],
    "dependency_compatibility": [sys.executable, "-m", "pip", "check"],
}


def main():
    results = {}
    for name, command in COMMANDS.items():
        started = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
        results[name] = dict(command=command, returncode=completed.returncode,
                             seconds=time.monotonic() - started, stdout=completed.stdout, stderr=completed.stderr)
        print(f"{name}: {'passed' if completed.returncode == 0 else 'FAILED'}", flush=True)
    payload = dict(checked_at=datetime.now(timezone.utc).isoformat(), scope="Lebanon fuel Python project; unrelated Swift application excluded",
                   all_passed=all(r["returncode"] == 0 for r in results.values()), results=results)
    destination = ROOT / "reports/operations/final_verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2))
    print(str(destination))
    return int(not payload["all_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
