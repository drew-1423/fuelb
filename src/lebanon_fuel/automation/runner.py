"""One complete, bounded refresh cycle. No model fitting or automatic approval."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
import subprocess
import sys
import time
import tomllib
from uuid import uuid4

import pandas as pd

from lebanon_fuel.dashboard import analyst
from lebanon_fuel.dashboard.data import anchors, ledger_rows, live_forecasts
from lebanon_fuel.domain import BEIRUT
from lebanon_fuel.storage.database import Store
from lebanon_fuel.validation.ledger import ForecastLedger
from lebanon_fuel.validation.quality import export_data, report
from lebanon_fuel.storage.baseline import BASELINE_CONFIG
from lebanon_fuel.validation.decision_tracking import protocol_start, settle_supplier_updates
from lebanon_fuel.validation.settlement import settle
from . import forecast, maintenance, monitoring
from .schedule import DOMESTIC_SOURCES, SOURCES, due, settings
from .state import Journal, atomic_write, now, refresh_lock, write_json


def execute(root, source, cfg):
    module = "lebanon_fuel.cli" if source in DOMESTIC_SOURCES else "lebanon_fuel.market.cli"
    command = [sys.executable, "-m", module, "--root", str(root), "collect", "--source", source]
    if source == "ministry":
        command.extend(["--start", (now().astimezone(BEIRUT).date() - timedelta(days=cfg["collection"]["ministry_lookback_days"])).isoformat()])
    env = dict(os.environ, PYTHONUNBUFFERED="1", MPLCONFIGDIR=str(root / "data/cache/matplotlib"),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                                timeout=cfg["collection"]["timeout_seconds"])
        return dict(status="success" if result.returncode == 0 else "failed", returncode=result.returncode,
                    stdout=result.stdout[-24000:], stderr=result.stderr[-12000:], seconds=time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        return dict(status="failed", returncode=None, stdout="", stderr=f"Collector exceeded {exc.timeout}s and was stopped.", seconds=time.monotonic() - started)
    except OSError as exc:
        return dict(status="failed", returncode=None, stdout="", stderr=str(exc), seconds=time.monotonic() - started)


def cooldown(source, journal, cfg, at):
    last = journal.latest("source_attempt", source)
    if last:
        earliest = datetime.fromisoformat(last["recorded_at"]) + timedelta(minutes=cfg["collection"]["minimum_interval_minutes"][source])
        if at < earliest:
            return "source_minimum_interval_until_" + earliest.isoformat()
    result = journal.latest("source_result", source)
    if result and result["payload"].get("retry_not_before") and at < datetime.fromisoformat(result["payload"]["retry_not_before"]):
        return "access_cooldown_until_" + result["payload"]["retry_not_before"]
    return None


def access_cooldown(store, source, started, cfg):
    source_id = source if source in DOMESTIC_SOURCES else "market_" + source
    rows = store.db.execute("SELECT http_status,retrieved_at,metadata_json FROM captures WHERE source_id=? AND retrieved_at>=? AND http_status IN (401,403,406,429)",
                            (source_id, started)).fetchall()
    deadlines = []
    for status, captured, metadata in rows:
        at = datetime.fromisoformat(captured)
        deadline = at + timedelta(hours=cfg["collection"]["access_failure_pause_hours"])
        retry = json.loads(metadata).get("headers", {}).get("retry-after")
        if retry:
            try:
                requested = at + timedelta(seconds=int(retry)) if retry.isdigit() else parsedate_to_datetime(retry)
                if requested.utcoffset() is not None:
                    deadline = max(deadline, requested)
            except (ValueError, TypeError, OverflowError):
                pass
        deadlines.append(deadline)
    return max(deadlines).isoformat() if deadlines else None


def settle_available(root, cfg, ops):
    path = ops["settlement"]["reviewed_manifest"]
    if not path:
        return {"status": "pending_reviewed_official_clocks_and_complete_coverage", "newly_matched": 0}
    manifest = root / path
    payload = json.loads(manifest.read_text())
    imported = settle(root, manifest)
    matches = {}
    with closing(ForecastLedger(root / cfg["validation"]["forecast_ledger"])) as ledger:
        # Revisit previously scored forecasts too: corrected actuals append evaluations.
        cutoff = protocol_start(root) if (root / BASELINE_CONFIG).is_file() else ""
        ids = [r[0] for r in ledger.db.execute("""SELECT id FROM forecasts
            WHERE mode IN ('prospective','prospective_research','prospective_shadow') AND status='issued'
            AND origin >= ? AND created_at >= ?""", (cutoff, cutoff))]
        for fid in ids:
            matches[str(fid)] = ledger.match(fid, payload.get("coverage", {}))
    return dict(status="reviewed_manifest_processed", import_result=imported, match_status=matches)


def analyst_report(root, monitor, cfg):
    with closing(Store(root, cfg["storage"]["database"], readonly=True)) as source:
        records = source.ledger()
        latest, previous = anchors(records)
    best = pd.read_csv(root / "reports/model_validation/descriptive_best_models.csv")
    decision = json.loads((root / cfg["validation"]["decision_file"]).read_text())
    rows = pd.concat([ledger_rows(root / cfg['validation']['forecast_ledger'], 'decision_1', mode)
                      for mode in ('prospective', 'prospective_research')], ignore_index=True)
    current = live_forecasts(rows, cfg, decision, 'decision_1', records[-1] if records else None)
    sections = analyst.brief(latest, previous, monitor["market"], best, decision, current.iloc[0] if not current.empty else None)
    return "# Lebanon gasoline 95 analyst report\n\nGenerated " + monitor["generated_at"] + "\n\n" + "\n\n".join(
        f"## {heading}\n\n{body}" for heading, body in sections.items()) + "\n\n## Operating alerts\n\n" + "\n".join(
        "- " + item["message"] for item in monitor["alerts"]) + "\n"


def run(root, *, scheduled=False, sources=None, offline=False, collector=execute):
    root = root.resolve()
    ops = settings(root)
    cfg = tomllib.loads((root / "config/project.toml").read_text())
    requested = list(SOURCES) if sources is None else list(sources)
    if not set(requested) <= set(SOURCES):
        raise ValueError("Unknown collector")
    with refresh_lock(root), closing(Journal(root)) as journal:
        at = now()
        last = journal.latest("cycle_started", "schedule")
        ready, reason = due(at, last["recorded_at"] if last else None, ops["schedule"])
        request = root / "data/operations/refresh.request"
        if scheduled and not ready and not request.exists():
            return dict(status="not_due", checked_at=at.isoformat())
        request.unlink(missing_ok=True)
        run_id = "ops-" + at.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        folder = root / "reports/operations/runs" / run_id
        journal.append(run_id, "cycle_started", "schedule", dict(reason=reason if scheduled else "manual", offline=offline))
        result = dict(run_id=run_id, started_at=at.isoformat(), offline=offline, steps=[], source_results={})
        unfinished = journal.db.execute("""SELECT s.run_id FROM events s WHERE s.kind='cycle_started'
            AND s.run_id!=? AND NOT EXISTS(SELECT 1 FROM events e WHERE e.kind='cycle_finished' AND e.run_id=s.run_id)""", (run_id,)).fetchall()
        result["previous_interrupted_cycles"] = [row[0] for row in unfinished]

        def step(name, action):
            started = time.monotonic()
            try:
                value = action()
                entry = dict(name=name, status="success", result=value)
            except Exception as exc:
                entry = dict(name=name, status="failed", error=f"{type(exc).__name__}: {exc}")
            entry["seconds"] = time.monotonic() - started
            result["steps"].append(entry)
            journal.append(run_id, "step", name, entry)
            write_json(folder / "progress.json", result)
            return entry

        # Fail before collecting or issuing if either existing database is corrupt.
        initial = step("database_integrity_before_refresh", lambda: [maintenance.check_database(root / p)
                       for p in (cfg["storage"]["database"], cfg["validation"]["forecast_ledger"])])
        if initial["status"] == "success":
            if not offline:
                for source in requested:
                    pause = cooldown(source, journal, ops, now())
                    if pause:
                        result["source_results"][source] = dict(status="skipped", reason=pause)
                        continue
                    started = now().isoformat()
                    journal.append(run_id, "source_attempt", source, {})
                    try:
                        outcome = collector(root, source, ops)
                    except Exception as exc:
                        outcome = dict(status="failed", stderr=f"{type(exc).__name__}: {exc}")
                    with closing(Store(root, cfg["storage"]["database"])) as source_store:
                        outcome["retry_not_before"] = access_cooldown(source_store, source, started, ops)
                        source_id = source if source in DOMESTIC_SOURCES else "market_" + source
                        # A terminated collector can leave an unclosed run. Preserve its failure.
                        interrupted = source_store.db.execute("SELECT id FROM collection_runs WHERE source_id=? AND status='running'", (source_id,)).fetchall()
                        for row in interrupted:
                            source_store.finish_run(row[0], "failed", {"error": "Collector interrupted or timed out", "operations_run": run_id})
                    result["source_results"][source] = outcome
                    journal.append(run_id, "source_result", source, outcome)
                    write_json(folder / "progress.json", result)

            def reconcile():
                with closing(Store(root, cfg["storage"]["database"])) as source:
                    revisions = source.reconcile()
                    export_data(source, root / cfg["storage"]["export_dir"])
                    quality = report(source, root / cfg["storage"]["report_dir"], now().astimezone(BEIRUT).date().isoformat(), cfg["collection"]["stale_after_days"])
                return dict(new_decision_versions=revisions, report=quality)

            reconciliation = step("reconcile_and_export", reconcile)
            def market_quality():
                os.environ.setdefault("MPLCONFIGDIR", str(root / "data/cache/matplotlib"))
                from lebanon_fuel.market.store import MarketStore
                from lebanon_fuel.market.reports import report as market_report
                with closing(MarketStore(root, cfg["storage"]["database"], readonly=True)) as source:
                    return market_report(source, now().isoformat())
            step("market_quality_and_coverage", market_quality)
            step("settle_verified_outcomes", lambda: settle_available(root, cfg, ops))
            if reconciliation["status"] == "success":
                def supplier_matches():
                    with closing(Store(root, cfg["storage"]["database"], readonly=True)) as store:
                        return settle_supplier_updates(root, cfg, store)
                if (root / "config/prospective_holdout.json").is_file():
                    step("score_supplier_agreements", supplier_matches)
                check = step("refresh_forecast_decision", lambda: forecast.refresh(root, cfg, run_id))
                if check["status"] == "success":
                    write_json(root / "reports/operations/current_forecast_check.json", check["result"])
                shadow_path = ops.get("shadow", {}).get("frozen_manifest")
                if shadow_path:
                    from lebanon_fuel.validation import shadow
                    def issue_shadow():
                        output = shadow.issue(root, root / shadow_path, run_id=run_id + "-shadow")
                        write_json(root / "reports/operations/shadow_evidence.json", shadow.report(root, root / shadow_path))
                        return output
                    step("issue_shadow_experiment", issue_shadow)
            previous_path = root / "reports/operations/monitoring.json"
            try:
                previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
            except ValueError:
                previous = None
            checked = step("monitor", lambda: monitoring.build(root, cfg, ops, previous))
            if checked["status"] == "success":
                write_json(previous_path, checked["result"])
                write_json(folder / "monitoring.json", checked["result"])
                brief = step("analyst_report", lambda: analyst_report(root, checked["result"], cfg))
                if brief["status"] == "success":
                    atomic_write(folder / "analyst_report.md", brief["result"])
                    atomic_write(root / "reports/latest_analyst_report.md", brief["result"])
            step("integrity_and_financial_arithmetic", lambda: maintenance.audit(root, cfg))
            saved = journal.latest("backup", "complete")
            if saved is None or (now() - datetime.fromisoformat(saved["recorded_at"])).total_seconds() >= ops["maintenance"]["backup_every_hours"] * 3600:
                copied = step("backup", lambda: maintenance.backup(root, cfg))
                if copied["status"] == "success":
                    journal.append(run_id, "backup", "complete", copied["result"])
        failed = any(s["status"] == "failed" for s in result["steps"]) or any(s["status"] == "failed" for s in result["source_results"].values())
        result.update(finished_at=now().isoformat(), status="degraded" if failed else "completed",
                      production_forecast_status="withheld_pending_validation")
        issued = next((s['result'] for s in result['steps'] if s['name']=='refresh_forecast_decision' and s['status']=='success'), {})
        result['forecast_status'] = issued.get('status', 'failed')
        result['forecast_tiers'] = {r['horizon']:r['tier'] for r in issued.get('forecasts', [])}
        if 1 in result['forecast_tiers'].values():
            result['production_forecast_status'] = 'approved_for_selected_horizons'
        write_json(folder / "result.json", result)
        write_json(root / "reports/operations/latest_run.json", result)
        journal.append(run_id, "cycle_finished", "schedule", dict(status=result["status"], path=str(folder / "result.json")))
        return result
