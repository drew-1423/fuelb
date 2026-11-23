"""Read-only dashboard queries. Collection goes through the existing CLI."""
from contextlib import closing
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
import sqlite3
import subprocess
import sys
import tomllib

import pandas as pd

from lebanon_fuel.domain import BEIRUT, VERIFIED, PROVISIONAL_PRICE, utc_timestamp
from lebanon_fuel.features.market import from_histories
from lebanon_fuel.market.catalog import SERIES
from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.storage.database import sqlite_connection

HORIZONS = {"Next official update": "decision_1", "7 days": "day_7",
            "14 days": "day_14", "30 days": "day_30"}
EXPECTED_HORIZONS = ("decision_1", "decision_2", "decision_4", "day_1",
                     "day_3", "day_7", "day_14", "day_30")
LIVE_MODES = ("prospective", "prospective_research")
MINIMUM_PROBABILITY_HOLDOUT = 10
DISPLAY_FX = 89500.0
STATUS = {"document_verified": "🏛️ Official Ministry Decree",
          "archive_corroborated": "📜 Government Archive",
          "government_archive": "📜 Government Archive · uncorroborated",
          PROVISIONAL_PRICE: "🤝 Matching dated price sources",
          "supplier_observed": "🔍 Single Station Quote",
          "conflict": "Conflicting sources"}


def currency_values(price, change=None):
    """Display conversion only; never a pricing-formula or observed FX input."""
    price = float(price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("A finite positive price is required")
    result = dict(lbp_20l=price, usd_20l=price / DISPLAY_FX,
                  lbp_liter=price / 20, usd_liter=price / 20 / DISPLAY_FX)
    if change is not None:
        if not math.isfinite(float(change)):
            raise ValueError("A finite change is required")
        result.update(change_lbp=float(change), change_usd=float(change) / DISPLAY_FX)
    return result


def refresh_poll_seconds(running):
    return 2 if running else 60


def decree_hazard_context(records, as_of_date=None, scheduled_date=None):
    """Empirical source-date cadence; not a probability of the next decree."""
    today = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date or datetime.now(BEIRUT).date()
    dates = sorted({date.fromisoformat(r['source_date']) for r in records
                    if r.get('verification_status') in VERIFIED | {PROVISIONAL_PRICE}
                    and r.get('price_lbp_20l') and r['source_date'] <= today.isoformat()})[-60:]
    n = len(dates)
    share = sum(d.weekday() in (1, 4) for d in dates) / n if n else None
    projected = None
    if scheduled_date:
        candidate = pd.Timestamp(scheduled_date).date()
        if candidate > today:
            projected = candidate
    if projected is None and n >= 20 and share >= .8:
        projected = next(today + timedelta(days=i) for i in range(1, 8)
                         if (today + timedelta(days=i)).weekday() in (1, 4))
    return dict(sample_size=n, tue_fri_share=share, projected_date=projected,
                basis='dated price observations; original decree publication times may be unknown')



def config(root):
    return tomllib.loads((root / "config/project.toml").read_text())


def read_json(path):
    return json.loads(path.read_text())


def database_paths(root, settings):
    if refresh_writer(root) == "github_actions":
        from lebanon_fuel.automation.publication import reader_root
        root = reader_root(root, credentials=object_store_credentials())
    return (root / settings["storage"]["database"],
            root / settings["validation"]["forecast_ledger"])


def object_store_credentials():
    """Read-only object-store credentials from Streamlit secrets or local environment."""
    access_key = os.environ.get("FUEL_STORAGE_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("FUEL_STORAGE_SECRET_ACCESS_KEY", "").strip()
    endpoint = os.environ.get("FUEL_STORAGE_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("FUEL_STORAGE_BUCKET", "").strip()
    if access_key and secret_key and endpoint and bucket:
        return dict(access_key_id=access_key, secret_access_key=secret_key,
                    endpoint_url=endpoint, bucket=bucket)
    try:
        import streamlit as st
        config = st.secrets.get("fuel_storage", {})
        return dict(access_key_id=str(config.get("access_key_id", "")).strip(),
                    secret_access_key=str(config.get("secret_access_key", "")).strip(),
                    endpoint_url=str(config.get("endpoint_url", "")).strip(),
                    bucket=str(config.get("bucket", "")).strip())
    except Exception:  # Secrets are optional for the checked-in GitHub bootstrap snapshot.
        return {}


def file_version(path):
    """Invalidate cached reads after file replacement or SQLite WAL commits."""
    versions = []
    for item in (path, path.with_name(path.name + "-wal")):
        try:
            stat = os.stat(item)
            versions.append((stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            versions.append(None)
    return tuple(versions)


def volatility_summary(history):
    """Latest point-in-time OVX features and regime, if history supports them."""
    from lebanon_fuel.forecasting.data import ovx_features

    if not history:
        return None
    latest = history[-1]
    features = ovx_features(history)
    return dict(observation_date=latest['observation_date'], level=latest['value'],
                source_url=latest.get('source_url'), retrieved_at=latest.get('retrieved_at'),
                change_5d=features['x_ovx_5d_change'], change_20d=features['x_ovx_20d_change'],
                percentile_252d=features['x_ovx_252d_percentile'], regime=features['ovx_regime'],
                regime_basis=features['ovx_regime_basis'])


def market_and_prices(root, db_path):
    now = datetime.now(timezone.utc)
    with closing(MarketStore(root, db_path, readonly=True)) as store:
        store.db.execute("BEGIN")
        prices = store.ledger()
        histories = {sid: store.history(sid, now.isoformat()) for sid in SERIES}
        runs = pd.read_sql_query("""
            SELECT r.source_id, r.status, r.started_at, r.finished_at, r.details
            FROM collection_runs r
            WHERE r.id IN (SELECT MAX(id) FROM collection_runs GROUP BY source_id)
            ORDER BY r.started_at DESC
        """, store.db)
        latest_capture = store.db.execute("""
            SELECT MAX(retrieved_at) FROM captures WHERE http_status BETWEEN 200 AND 299
            AND source_id IN ('ipt','totalenergies','ministry','taqtek','thefuelprice','official_document',
                              'market_eia','market_ec','market_fed','market_cboe','market_fred_ovx','market_official_review')
        """).fetchone()[0]
        clocks = store.db.execute("""
            SELECT COUNT(*) - COUNT(publication_timestamp),
                   COUNT(*) - COUNT(official_effective_date), COUNT(*) FROM observations
        """).fetchone()
    return {
        "prices": prices, "histories": histories,
        "market": from_histories(histories, now.isoformat(), "strict"),
        "runs": runs, "latest_capture": latest_capture, "missing_clocks": tuple(clocks[:2]), "raw_observation_count": clocks[2],
    }


def anchors(prices):
    dated = [row for row in prices if row["verification_status"] in VERIFIED | {PROVISIONAL_PRICE}
             and row["price_lbp_20l"] is not None]
    return (dated[-1] if dated else None, dated[-2] if len(dated) >= 2 else None)


# Both prospective modes can occur in one issuance and have separate snapshot IDs.
# The run ID and origin identify the batch across modes.
LIVE_BATCH_QUERY = """
    WITH latest_complete AS (
        SELECT run_id, origin, SUM(status = 'issued' AND predicted_price IS NOT NULL) AS issued_count
        FROM forecasts
        WHERE mode IN (:production, :research) AND origin <= :cutoff AND created_at <= :cutoff
          AND (:run_id IS NULL OR run_id = :run_id)
        GROUP BY run_id, origin
        HAVING COUNT(*) = :count AND COUNT(DISTINCT horizon) = :count
           AND SUM(horizon IN ({horizons})) = :count
           AND (issued_count = :count OR SUM(status = 'abstained') = :count
                OR SUM(json_extract(target_json, '$.pinned_family') = 'G_hybrid') = :count)
        ORDER BY origin DESC, MAX(id) DESC
        LIMIT 1
    )
"""
LEDGER_SELECT = """
            SELECT f.id, f.record_hash, f.run_id, f.horizon, f.created_at, f.origin, f.mode, f.status, f.model_version,
                   f.snapshot_id, f.base_price, f.predicted_price, f.predicted_change,
                   f.interval_low, f.interval_high, f.probabilities_json, f.reason_json, f.target_json,
                   json_extract(f.target_json, '$.endpoint') AS endpoint,
                   COALESCE(json_extract(f.target_json, '$.scheduled_effective'),
                            json_extract(f.target_json, '$.decision_date'),
                            json_extract(f.target_json, '$.decision_effective_at')) AS scheduled_effective,
                   json_extract(m.metadata_json, '$.family') AS family, m.approved,
                   o.price AS actual_price,
                   json_extract(o.payload_json, '$.source_date') AS recorded_target_date,
                   o.effective_timestamp, e.kind AS evaluation_kind
            FROM forecasts f JOIN models m ON m.id=f.model_version
            LEFT JOIN evaluations e ON e.id=(
                SELECT ev.id FROM evaluations ev WHERE ev.forecast_id=f.id
                  AND (ev.kind <> 'provisional_match' OR ev.outcome_id = (
                    SELECT CASE WHEN status='supplier_match' THEN json_extract(details_json, '$.outcome_id') END
                    FROM match_attempts WHERE forecast_id=f.id
                      AND json_extract(details_json, '$.channel')='supplier_next_update'
                    ORDER BY id DESC LIMIT 1
                  ))
                ORDER BY (ev.kind='official_match') DESC, ev.id DESC LIMIT 1
            )
            LEFT JOIN outcomes o ON o.id=e.outcome_id
"""


def live_ledger_rows(path, *, at=None, run_id=None):
    """Read one complete live batch in one SQLite statement.

    A fully recorded abstention supersedes previous estimates. A batch still
    missing horizons does not. Anchor, age and settlement checks run afterward.
    """
    cutoff = utc_timestamp(pd.Timestamp(at or datetime.now(timezone.utc)).isoformat())
    count = len(EXPECTED_HORIZONS)
    horizons = {f"horizon_{i}": horizon for i, horizon in enumerate(EXPECTED_HORIZONS)}
    query = LIVE_BATCH_QUERY.format(horizons=", ".join(f":{key}" for key in horizons))
    query += LEDGER_SELECT + """
        JOIN latest_complete batch ON batch.run_id = f.run_id AND batch.origin = f.origin
        WHERE f.mode IN (:production, :research) AND f.created_at <= :cutoff
          AND f.status = 'issued' AND f.predicted_price IS NOT NULL
        ORDER BY f.id
    """
    production, research = LIVE_MODES
    params = dict(production=production, research=research, cutoff=cutoff,
                  run_id=run_id, count=count, **horizons)
    with closing(sqlite_connection(path, readonly=True)) as db:
        return pd.read_sql_query(query, db, params=params)


def ledger_rows(path, horizon, mode, run_id=None):
    if mode in LIVE_MODES:
        rows = live_ledger_rows(path, run_id=run_id)
        return rows.loc[rows.horizon.eq(horizon) & rows["mode"].eq(mode)].copy()
    query = LEDGER_SELECT + """
        WHERE f.horizon = ? AND f.mode = ? AND (? IS NULL OR f.run_id = ?)
        ORDER BY f.origin, f.id
    """
    with closing(sqlite_connection(path, readonly=True)) as db:
        return pd.read_sql_query(query, db, params=(horizon, mode, run_id, run_id))


def prospective_comparisons(root, path, horizon):
    from lebanon_fuel.validation.decision_tracking import BATCH, protocol_start

    query = BATCH + LEDGER_SELECT + """
        JOIN complete c ON c.run_id=f.run_id AND c.origin=f.origin
        WHERE f.mode IN ('prospective','prospective_research') AND f.created_at >= :start
          AND f.horizon=:horizon AND f.status='issued' AND f.predicted_price IS NOT NULL
          AND json_extract(m.metadata_json, '$.family')='G_hybrid'
        ORDER BY f.created_at DESC, f.id DESC
    """
    with closing(sqlite_connection(path, readonly=True)) as db:
        return pd.read_sql_query(query, db, params=dict(start=protocol_start(root), horizon=horizon))


def approved_forecasts(rows, settings, decision, horizon, *, at=None):
    selected = decision.get("selection", {}).get(horizon, {}).get("production_model")
    if rows.empty or not (settings["forecasting"].get("enabled") is True
            and settings["validation"].get("production_approved") is True
            and decision.get("production_approved") is True
            and isinstance(selected, str) and selected):
        return rows.iloc[:0]
    # A later operational abstention must suppress even an earlier approved model.
    current = rows[rows["mode"].eq("prospective")].sort_values("id").tail(1)
    if current.empty or current.iloc[0]["status"] != "issued" or current.iloc[0]["model_version"] != selected:
        return rows.iloc[:0]
    rows = rows[rows["model_version"].eq(selected) & rows["mode"].eq("prospective")]
    latest = rows.sort_values("id").tail(1)
    if latest.empty or "origin" not in latest or "created_at" not in latest:
        return rows.iloc[:0]
    at = pd.Timestamp(at or datetime.now(timezone.utc))
    try:
        origin = pd.Timestamp(latest.iloc[0]["origin"])
        created = pd.Timestamp(latest.iloc[0]["created_at"])
        if origin.tzinfo is None or created.tzinfo is None or origin > at or created > at:
            return rows.iloc[:0]
        maximum_age = settings["forecasting"].get("maximum_forecast_age_hours", 12)
        if (at - origin).total_seconds() > maximum_age * 3600:
            return rows.iloc[:0]
        endpoint = latest.iloc[0].get("endpoint")
        if pd.notna(endpoint) and pd.Timestamp(endpoint) <= at:
            return rows.iloc[:0]
    except (ValueError, TypeError):
        return rows.iloc[:0]
    return latest[latest["approved"].eq(1) & latest["status"].eq("issued")
                  & latest["predicted_price"].notna() & latest["actual_price"].isna()]


def live_forecasts(rows, settings, decision, horizon, latest_record, *, at=None):
    """Apply per-horizon eligibility checks to the batch from live_ledger_rows."""
    if rows.empty or latest_record is None:
        return rows.iloc[:0]
    if 'horizon' in rows:
        rows = rows[rows.horizon.eq(horizon)]
    latest = rows[rows['mode'].isin(LIVE_MODES)].sort_values('id').tail(1).copy()
    if latest.empty:
        return latest
    row = latest.iloc[0]
    spec = json.loads(row.target_json)
    at = pd.Timestamp(at or datetime.now(timezone.utc))
    origin, created = pd.Timestamp(row.origin), pd.Timestamp(row.created_at)
    if (row.status != 'issued' or pd.isna(row.predicted_price) or pd.notna(row.actual_price)
            or origin.tzinfo is None or created.tzinfo is None or origin > at or created > at
            or (at-origin).total_seconds() > settings['forecasting'].get('maximum_forecast_age_hours',12)*3600
            or spec.get('base_revision_id') != latest_record['revision_id']
            or (latest_record['verification_status'] not in VERIFIED
                and not (latest_record['verification_status'] == PROVISIONAL_PRICE
                         and spec.get('anchor_verification') == PROVISIONAL_PRICE
                         and spec.get('tier') in (2, 4)))
            or (at.tz_convert(BEIRUT).date()-datetime.fromisoformat(latest_record['source_date']).date()).days > settings['collection']['stale_after_days']
            or (spec.get('endpoint') and pd.Timestamp(spec['endpoint']) <= at)):
        return latest.iloc[:0]
    tier = spec.get('tier')
    if tier == 1:
        latest = approved_forecasts(latest, settings, decision, horizon, at=at)
    elif tier not in (2,3,4) or row['mode'] != 'prospective_research' or row.approved != 0:
        return latest.iloc[:0]
    latest['forecast_tier'] = tier
    latest['forecast_label'] = (spec.get('label') or '').removesuffix(' · PROVISIONAL PRICE ANCHOR')
    return latest


def refresh_writer(root):
    deployment = config(Path(root)).get('deployment', {})
    return os.environ.get('LEBANON_FUEL_WRITER', deployment.get('dashboard_writer', 'local'))


def owner_refresh_available(root):
    writer = refresh_writer(root)
    return writer == 'local' or (writer == 'github_actions' and bool(os.environ.get('LEBANON_FUEL_ACTIONS_TOKEN', '').strip()))


def refresh_source(root, source, timeout_seconds=180):
    from lebanon_fuel.automation.schedule import SOURCES
    if source != 'all' and source not in SOURCES:
        raise ValueError('Unknown source')
    deployment = config(Path(root)).get('deployment',{})
    writer = refresh_writer(root)
    if writer == 'github_actions':
        import httpx
        import re
        repository = deployment.get('repository','drew-1423/fuelb')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
            return False,'Invalid durable writer repository configuration.'
        token = os.environ.get('LEBANON_FUEL_ACTIONS_TOKEN', '').strip()
        if not token:
            return False,'Read-only dashboard: scheduled GitHub Actions persists updates. Owner-triggered refresh needs the LEBANON_FUEL_ACTIONS_TOKEN secret. No local database writes were started.'
        try:
            response = httpx.post(f"https://api.github.com/repos/{repository}/actions/workflows/{deployment.get('refresh_workflow','refresh.yml')}/dispatches",
                headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'},json={'ref':'main','inputs':{'source':source}},timeout=10.)
        except httpx.HTTPError:
            return False,'The durable refresh request failed. Inspect GitHub Actions; stored prices were retained.'
        if response.status_code != 204:
            return False,f'Durable refresh was not accepted (HTTP {response.status_code}). Review the owner token/workflow permissions.'
        return True,'Refresh queued on GitHub Actions. Stored observations and forecasts remain unchanged until the durable run completes and the dashboard receives its committed snapshot.'
    if writer != 'local':
        return False,'Unknown writer mode; no database writes started.'
    command = [sys.executable, "-m", "lebanon_fuel.automation.cli", "--root", str(root), "run"]
    if source != "all":
        from lebanon_fuel.automation.schedule import SOURCES
        if source not in SOURCES:
            raise ValueError("Unknown source")
        command += ["--source", source]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Refresh did not complete. {exc}"
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return result.returncode == 0, output


def refresh_result_message(result):
    """Explain a refresh request without misreporting it as a collection failure."""
    ok, detail = result
    if ok:
        return 'Refresh requested. Check the next successful capture time before treating data as updated.'
    detail = str(detail)
    if 'LEBANON_FUEL_ACTIONS_TOKEN' in detail:
        return ('Owner refresh is not configured on this cloud deployment. '
                'Scheduled collection continues; no collection was attempted by this request.')
    if 'not accepted (HTTP' in detail:
        return 'GitHub rejected the refresh request. The owner should check the workflow token and permissions.'
    if 'durable refresh request failed' in detail.lower():
        return 'The refresh request could not reach GitHub Actions. Stored data is unchanged.'
    return ('The refresh cycle reported a failure. Check collection results and the separate '
            'evidence audit in Data Quality; stored observations keep their original dates.')


def beirut_time(value):
    if value is None or pd.isna(value):
        return "Unavailable"
    if isinstance(value, str) and len(value) == 10:
        # A projected calendar date has no announcement clock to convert.
        return date.fromisoformat(value).strftime("%d %b %Y") + " (date only)"
    return datetime.fromisoformat(value).astimezone(BEIRUT).strftime("%d %b %Y %H:%M %Z")


def forecast_bounds(row, *, tier=None):
    """Return finite price bounds that bracket the plotted point estimate."""
    if tier in (3, 4):
        return None
    fields = (row.get("base_price"), row.get("predicted_price"),
              row.get("interval_low"), row.get("interval_high"))
    if any(pd.isna(value) or not math.isfinite(value) for value in fields):
        return None
    base, point, lower, upper = fields
    low, high = base + lower, base + upper
    if 0 <= low <= point <= high and low < high and math.isfinite(high):
        return [float(low), float(high)]
    return None


def forecast_view(row):
    """Presentation only: never manufacture probabilities, bounds or market drivers."""
    spec=json.loads(row.target_json)
    tier = spec.get("tier")
    # Quantitative issuance copies the selected model's common-origin holdout
    # performance here. Calibration residual counts are a separate sample.
    performance = spec.get("performance")
    holdout_n = performance.get("n") if isinstance(performance, dict) else None
    supported = type(holdout_n) is int and holdout_n >= MINIMUM_PROBABILITY_HOLDOUT
    probability_status = "Not calibrated"
    probabilities = None
    if tier in (1, 2):
        if not supported:
            probability_status = "Insufficient sample"
        else:
            try:
                values = json.loads(row.probabilities_json or "null")
            except (TypeError, ValueError):
                values = None
            if (isinstance(values, list) and len(values) == 3
                    and all(type(p) in (int, float) and 0 <= p <= 1 for p in values)
                    and math.isclose(sum(values), 1, rel_tol=0, abs_tol=1e-8)):
                probabilities = values
                probability_status = "Available"
    bounds = forecast_bounds(row, tier=tier)
    stamp = pd.to_datetime(row.get('scheduled_effective'), errors='coerce')
    schedule = 'Date not established'
    endpoint=row.get('endpoint')
    if endpoint is not None and pd.notna(endpoint):
        schedule=beirut_time(endpoint)
    elif pd.notna(stamp):
        schedule=stamp.strftime('%d %b %Y') + (f" ({stamp.strftime('%a')} cadence)" if spec.get('schedule_estimated') else '')
    contributions=spec.get('driver_contributions') or {}
    labels={'commodity_pass_through':'Gasoline / Brent proxy contribution (combined)',
            'lagged_domestic_momentum':'Domestic lagged adjustment','fiscal_shock':'Fiscal shock indicator',
            'other_features':'Other model features','baseline_intercept':'Model intercept'}
    drivers=[{'Driver':label,'LBP / 20 L':float(contributions[key])} for key,label in labels.items()
             if key in contributions and pd.notna(contributions[key])]
    if not drivers and spec.get('tier')==4:
        drivers=[{'Driver':'Repeated domestic change' if spec.get('family')=='Z_last_change' else 'No-change baseline',
                  'LBP / 20 L':float(row.predicted_change)}]
    return dict(spec=spec, probabilities=probabilities, probability_status=probability_status,
                holdout_n=holdout_n, bounds=bounds, schedule=schedule, drivers=drivers,
                usd_equivalent=float(row.predicted_price)/DISPLAY_FX,display_fx=DISPLAY_FX)


def prospective_track_record(root, ledger_path, horizon="decision_1"):
    """Summarize live prospective evaluations since the sealed prospective_holdout.json cutoff."""
    proto_path = Path(root) / "config/prospective_holdout.json"
    proto = read_json(proto_path) if proto_path.exists() else {}
    start = proto.get("prospective_start", "2026-11-14T00:00:00+00:00")
    required = int(proto.get("minimum_distinct_base_decisions", 20))
    query = LEDGER_SELECT + """
        WHERE f.horizon = ? AND f.mode IN ('prospective', 'prospective_research')
          AND f.origin >= ? AND f.status = 'issued'
        ORDER BY f.origin, f.id
    """
    with closing(sqlite_connection(ledger_path, readonly=True)) as db:
        rows = pd.read_sql_query(query, db, params=(horizon, start))
    issued_n = len(rows)
    settled = rows[rows.actual_price.notna() & rows.predicted_price.notna()].copy() if not rows.empty else pd.DataFrame()
    if settled.empty:
        return dict(prospective_start=start, required_decisions=required, issued_n=issued_n,
                    settled_n=0, distinct_decisions=0, mae_lbp=None, direction_accuracy=None)
    settled["base_revision_id"] = settled.target_json.map(lambda s: json.loads(s).get("base_revision_id"))
    distinct = int(settled["base_revision_id"].nunique()) if settled["base_revision_id"].notna().any() else len(settled)
    errors = (settled.predicted_price - settled.actual_price).abs()
    pred_dir = settled.predicted_change.map(lambda x: -1 if x < -3000 else (1 if x > 3000 else 0))
    act_change = settled.actual_price - settled.base_price
    act_dir = act_change.map(lambda x: -1 if x < -3000 else (1 if x > 3000 else 0))
    return dict(prospective_start=start, required_decisions=required, issued_n=issued_n,
                settled_n=len(settled), distinct_decisions=distinct,
                mae_lbp=float(errors.mean()), direction_accuracy=float((pred_dir == act_dir).mean()))
