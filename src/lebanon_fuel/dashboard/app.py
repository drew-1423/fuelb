"""Local Streamlit terminal. Launch from the project root."""
from datetime import date, datetime, timezone
from decimal import DecimalException
from pathlib import Path
from html import escape
import json
import os
import sqlite3
import threading
import uuid

import pandas as pd
import streamlit as st

from lebanon_fuel.dashboard import analyst, backtesting, charts, data, decisions
from lebanon_fuel.dashboard.scenarios import simulate
from lebanon_fuel.storage.database import sqlite_connection
from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE
from lebanon_fuel.market.catalog import MISSING, SERIES

ROOT = Path(os.environ.get("LEBANON_FUEL_ROOT", Path.cwd())).resolve()
REPORTS = ROOT / "reports/model_validation"
VIEWS = ["Overview", "Price & forecasts", "Global markets", "Analyst report",
         "Model performance", "Backtesting", "Decision timeline", "Scenario simulator", "Volatility & options", "Data quality"]
REGIMES = {"pre_crisis": "2018–19 challenge", "recent_pre_fiscal": "2025 challenge", "stabilized_fx_2023_2026": "2026 holdout"}
FAMILIES = {"Z_last_change": "Last change", "A_no_change": "No change", "A_mean": "Historical mean",
            "Z_brent": "Brent baseline", "B_structural_proxy": "Structural proxy",
            "E_lightgbm": "LightGBM", "F_catboost": "CatBoost", "G_hybrid": "Hybrid",
            "H_ensemble": "Ensemble", "C_ridge": "Ridge", "D_sarimax": "SARIMAX"}

RESPONSIVE_CSS = """
.currency-secondary { color: #bfe9ff; font-size: 1.12rem; font-weight: 650; margin: .25rem 0; }
.provenance-badge { display: inline-block; padding: .35rem .6rem; border-radius: 8px;
  background: #22234c; color: #ded7ff; font-size: .83rem; line-height: 1.5; }
.provenance-badge.consensus { background: #163c49; color: #b9f1ff; }
.provenance-badge.single { background: #49371a; color: #ffe1a1; }
.provenance-badge.conflict { background: #4a2438; color: #ffd0df; }
.decree-outlook { padding: 1.2rem 1.4rem; background: #22234c; border: 1px solid #8b8fd9;
  border-radius: 14px; margin: .25rem 0 1.3rem; color: #f8faff; }
.decree-outlook h3 { margin: 0 0 .5rem; font-size: 1.2rem; }
.decree-outlook p { margin: .4rem 0; max-width: 72ch; }
.decree-outlook small { color: #ced7ee; }
[data-testid="stMetricValue"] > div { white-space: normal; overflow: visible;
  overflow-wrap: anywhere; font-size: clamp(1.45rem, 2.1vw, 2rem); }
[data-testid="stMetricDelta"] { white-space: normal; height: auto; }
.forecast-row { display: grid; grid-template-columns: .9fr 1.3fr 1.15fr; gap: .8rem;
  padding: .85rem 0; border-bottom: 1px solid #42486a; align-items: start; }
.forecast-row span { min-width: 0; overflow-wrap: anywhere; }
.forecast-row small { display: block; color: #bfe9ff; margin-top: .25rem; }
.forecast-head { font-size: .85rem; color: #c4cee4; }
@media (max-width: 1000px) {
  .st-key-price_sequence [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  .st-key-price_sequence [data-testid="stColumn"] { flex: 1 1 100% !important; width: 100% !important; }
}
@media (max-width: 480px) {
  .decree-outlook { padding: 1rem; }
  .forecast-row { gap: .45rem; font-size: .82rem; }
}
"""


def _signed_usd(change):
    return f"{'−' if change < 0 else '+'}${abs(change) / data.DISPLAY_FX:,.2f}"


def _currency_detail(price):
    values = data.currency_values(price)
    st.markdown(f'<p class="currency-secondary">~${values["usd_20l"]:,.2f} USD / 20 L</p>',
                unsafe_allow_html=True)
    st.caption(f'{values["lbp_liter"]:,.0f} LBP / L · ~${values["usd_liter"]:,.2f} USD / L')


def _provenance_badge(record):
    status = record['verification_status']
    style = 'consensus' if status == PROVISIONAL_PRICE else 'single' if status == 'supplier_observed' else 'conflict' if status == 'conflict' else ''
    st.markdown(f'<span class="provenance-badge {style}">{escape(data.STATUS.get(status, "Source under review"))}</span>',
                unsafe_allow_html=True)
    st.caption(record['source_date'])


def _decree_outlook(records, forecast):
    scheduled = forecast.scheduled_effective if forecast is not None and pd.notna(forecast.scheduled_effective) else None
    context = data.decree_hazard_context(records, scheduled_date=scheduled)
    target = context['projected_date']
    window = target.strftime('%A, %d %b %Y') + ' · estimated' if target else 'Next announcement window is unconfirmed'
    n, share = context['sample_size'], context['tue_fri_share']
    cadence = (f'{share:.0%} of the latest {n} dated price observations fall on Tuesday or Friday.'
               if n else 'Not enough dated observations to summarize the cadence.')
    advice = 'Check the latest posted station price before filling.'
    if forecast is not None:
        change = float(forecast.predicted_change)
        if abs(change) > 3000:
            direction = 'less' if change < 0 else 'more'
            advice = (f'The model estimates {abs(change):,.0f} LBP (~${abs(change) / data.DISPLAY_FX:.2f} USD) '
                      f'{direction} per 20 L. Check the posted price after the update; the change is not confirmed.')
        else:
            advice = 'The model estimates little change. Refuel when convenient and check the posted price.'
    st.markdown(f'<section class="decree-outlook" aria-label="Decree outlook">'
                f'<h3>Decree outlook · {escape(window)}</h3><p>{escape(advice)}</p>'
                f'<small>{escape(cadence)} Historical source-date pattern, not a calibrated announcement probability. '
                'Announcement time is not verified.</small></section>', unsafe_allow_html=True)


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def snapshot(root, path, version):
    return data.market_and_prices(root, path)


@st.cache_data(ttl=60, max_entries=24, show_spinner=False)
def ledger(path, horizon, mode, run_id, version):
    return data.ledger_rows(path, horizon, mode, run_id)


@st.cache_data(max_entries=32, show_spinner=False)
def csv(path, version):
    return pd.read_csv(path)


@st.cache_data(max_entries=8, show_spinner=False)
def json_file(path, version):
    return data.read_json(Path(path))


def table_file(path):
    try:
        return csv(path, data.file_version(path))
    except (OSError, ValueError):
        st.warning(f"{path.name} is unavailable.")
        return pd.DataFrame()


def show_chart(fig):
    st.plotly_chart(
        fig, width="stretch", theme=None,
        config={"displaylogo": False, "scrollZoom": True, "doubleClick": "reset",
                "displayModeBar": True,
                "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"]},
    )
    st.caption("Pinch or scroll to zoom. Drag to pan, or use the chart toolbar to zoom and reset.")


def amount(value, decimals=0):
    return "Unavailable" if value is None or pd.isna(value) else f"{value:,.{decimals}f}"


def percent(value):
    return "Unavailable" if value is None or pd.isna(value) else f"{value:+.2%}"


def title(heading, subtitle):
    st.title(heading)
    st.caption(subtitle)
    st.markdown('<hr class="terminal-rule">', unsafe_allow_html=True)


def get_ledger(horizon, mode, run_id=None):
    try:
        return ledger(LEDGER_PATH, horizon, mode, run_id, data.file_version(LEDGER_PATH))
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        st.warning("The forecast ledger is unavailable.")
        return pd.DataFrame()


def active(horizon):
    return ACTIVE_FORECASTS.loc[ACTIVE_FORECASTS.horizon.eq(horizon)]


def current_forecasts(path, settings, decision, latest_record):
    at = datetime.now(timezone.utc)
    try:
        batch = data.live_ledger_rows(path, at=at)
    except (OSError, sqlite3.Error, pd.errors.DatabaseError):
        st.warning("The forecast ledger is unavailable.")
        return pd.DataFrame(columns=["horizon"])
    if batch.empty:
        return batch
    batch = batch.loc[batch["family"].eq("G_hybrid")].copy()
    released_ranges = batch["target_json"].map(
        lambda value: (json.loads(value).get("public_calibration") or {}).get("radius") is not None)
    batch.loc[~released_ranges, ["interval_low", "interval_high"]] = None
    batch["probabilities_json"] = None
    if batch.empty:
        return batch
    return pd.concat([
        data.live_forecasts(rows, settings, decision, horizon, latest_record, at=at)
        for horizon, rows in batch.groupby("horizon", sort=False)
    ], ignore_index=True)


def forecast_details(forecast):
    spec = json.loads(forecast.target_json)
    st.info(spec['label'] + ' · ' + spec['methodology'])
    st.caption('Validation · ' + spec['validation_status'].replace('_', ' ') +
               ' · Issued ' + data.beirut_time(forecast.created_at))
    if spec.get('tier') != 4:
        evidence = spec.get("public_calibration") or {}
        st.caption(spec['uncertainty'] if evidence.get("radius") is not None
                   else "Prediction range is awaiting validated live outcomes.")
    calibration = spec.get("public_calibration")
    if calibration:
        st.caption(f"Range validation · {calibration['calibration_n']} settled prices · "
                   f"{calibration['evaluation_n']} tested live ranges for this starting-price group")
    with st.expander('Assumptions, missing inputs and forecast selection'):
        st.write(spec['future_market_assumption'])
        for missing in spec['critical_missing_inputs']:
            st.write(missing)
        for attempt in spec['attempts']:
            if attempt['reasons']:
                st.write(f"Tier {attempt['tier']}: " + '; '.join(attempt['reasons']))
        if spec.get('structural_output'):
            st.json(spec['structural_output'])
        st.caption(f"Saved forecast #{forecast.id} · {forecast.model_version} · Snapshot {forecast.snapshot_id}")


def unavailable_forecast():
    st.warning('No current absolute-price forecast is available · ' + forecast_unavailable_reason())
    try:
        check = data.read_json(ROOT / 'reports/operations/current_forecast_check.json')
        for reason in check.get('reasons', []):
            st.write(reason)
    except (OSError, ValueError):
        pass
    st.caption('Refresh sources and forecasts from Data quality. The Hybrid needs a current corroborated price and eligible market inputs.')


def forecast_unavailable_reason():
    labels = {
        "model_not_approved": "no model is approved for this horizon",
        "unsupported_regulatory_regime": "the latest pricing regime is not validated",
        "unverified_official_anchor": "the latest domestic price is not verified",
        "anchor_effective_at_missing": "the verified price has no confirmed effective date",
        "decision_coverage_unverified": "the historical decision sequence is incomplete",
    }
    try:
        check = data.read_json(ROOT / 'reports/operations/current_forecast_check.json')
        reasons = [labels.get(reason, str(reason).replace('_', ' ')) for reason in check.get('reasons', [])]
        if reasons:
            return '; '.join(reasons)
    except (OSError, ValueError, TypeError):
        pass
    return 'no eligible current forecast was issued'


def _configured_passcode():
    code = os.environ.get("LEBANON_FUEL_ADMIN_PASSCODE", "").strip()
    if code:
        return code
    try:
        return str(st.secrets.get("ADMIN_PASSCODE", "")).strip()
    except Exception:
        return ""


def _refresh_authorized():
    expected = _configured_passcode()
    if not expected:
        return False
    return st.session_state.get("admin_passcode_entered", "") == expected


@st.cache_resource
def _refresh_manager():
    return {"lock": threading.Lock(), "running": False, "job_id": None,
            "started_at": None, "finished_at": None, "result": None}


def _refresh_worker(manager, root, source, job_id):
    try:
        result = data.refresh_source(root, source, timeout_seconds=180)
    except Exception as exc:  # A refresh failure must never take down the dashboard.
        result = (False, f"Refresh failed safely: {exc}")
    with manager["lock"]:
        if manager["job_id"] == job_id:
            manager["result"] = result
            manager["finished_at"] = datetime.now(timezone.utc).isoformat()
            manager["running"] = False


def start_background_refresh(root, source="all"):
    if not _refresh_authorized():
        return False
    manager = _refresh_manager()
    with manager["lock"]:
        if manager["running"]:
            return False
        job_id = uuid.uuid4().hex
        manager.update(running=True, job_id=job_id,
                       started_at=datetime.now(timezone.utc).isoformat(), result=None)
    threading.Thread(target=_refresh_worker, args=(manager, root, source, job_id),
                     name="fuel-dashboard-refresh", daemon=True).start()
    return True


def _forecast_health(snap, forecast, refresh_result=None):
    tier, spec = 4, {}
    if forecast is not None:
        try:
            spec = json.loads(forecast.target_json)
            tier = int(spec.get('tier', 4))
        except (TypeError, ValueError, AttributeError):
            tier = 4
    failures = []
    runs = snap.get('runs')
    if isinstance(runs, pd.DataFrame) and not runs.empty:
        for _, row in runs.iterrows():
            if str(row.get('status', '')).lower() not in {'ok', 'success', 'completed'}:
                failures.append(str(row.get('source_id', 'a data source')).replace('market_', '').replace('_', ' '))
    if tier == 4 or forecast is None:
        why = forecast_unavailable_reason() if forecast is None else _forecast_limitation(spec)
        return 'red', why
    if tier in (2, 3):
        return 'yellow', _forecast_limitation(spec)
    if refresh_result and not refresh_result[0]:
        return 'yellow', 'The latest refresh failed; showing the last stored observations'
    if failures:
        return 'yellow', "Noncritical feed needs review: " + ', '.join(dict.fromkeys(failures))
    return 'green', 'Primary inputs are fresh and a Tier 1 forecast is active'


def refresh_status(snap, forecast):
    manager = _refresh_manager()
    with manager['lock']:
        running = manager['running']
    # Rebuild on completion via st.rerun below, dropping back to idle polling.
    st.fragment(run_every=data.refresh_poll_seconds(running))(_render_refresh_status)(snap, forecast)


def _render_refresh_status(snap, forecast):
    manager = _refresh_manager()
    with manager['lock']:
        running = manager['running']
        result = manager['result']
        finished_at = manager['finished_at']
        job_id = manager['job_id']
    if running:
        status, explanation = 'yellow', 'Refresh is running in the background'
    else:
        status, explanation = _forecast_health(snap, forecast, result)
    last_refresh = finished_at or snap.get('latest_capture')
    time_label = escape(data.beirut_time(last_refresh))
    st.markdown(
        f'<div class="refresh-health" role="status">'
        f'<strong><span class="health-dot {status}" aria-hidden="true"></span>{status.title()}</strong>'
        f'<span>{escape(explanation)}</span><small>Last refreshed · {time_label}</small></div>',
        unsafe_allow_html=True,
    )
    if result and job_id and st.session_state.get('refresh_rerun_job') != job_id:
        st.session_state['refresh_rerun_job'] = job_id
        # Re-read SQLite and version-keyed exports after the worker has committed.
        st.rerun()


def future_table():
    rows, dated = [], []
    for label, horizon in data.HORIZONS.items():
        current = active(horizon)
        if current.empty:
            rows.append({'Horizon':label, 'Forecast tier':'Unavailable'})
            continue
        row = current.iloc[0]
        spec = json.loads(row.target_json)
        has_endpoint = pd.notna(row.endpoint)
        rows.append({'Horizon':label, 'Target':data.beirut_time(row.endpoint) if has_endpoint else data.forecast_view(row)['schedule'],
                     'Starting price':row.base_price, 'Estimated price · LBP / 20 L':row.predicted_price,
                     'Change · LBP':row.predicted_change, 'Change · %':spec['percentage_change'],
                     'Forecast tier':spec['label'], 'Method':spec['methodology']})
        if has_endpoint or pd.notna(row.scheduled_effective):
            dated.append(current)
    parts = ['<div role="table" aria-label="Future price estimates"><div class="forecast-row forecast-head" role="row">'
             '<span role="columnheader">Horizon</span><span role="columnheader">Expected price / 20 L</span>'
             '<span role="columnheader">Change / 20 L</span></div>']
    for item in rows:
        price, change = item.get('Estimated price · LBP / 20 L'), item.get('Change · LBP')
        price_text = f'{price:,.0f} LBP<small>~${price / data.DISPLAY_FX:.2f} USD</small>' if price is not None else 'Awaiting inputs'
        change_text = f'{change:+,.0f} LBP<small>~{_signed_usd(change)} USD</small>' if change is not None else '—'
        parts.append(f'<div class="forecast-row" role="row"><span role="cell">{escape(item["Horizon"])}</span>'
                     f'<span role="cell">{price_text}</span><span role="cell">{change_text}</span></div>')
    st.markdown(''.join(parts) + '</div>', unsafe_allow_html=True)
    with st.expander('Forecast dates, methods and technical details'):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    st.caption('Calendar estimates describe the prevailing price at each endpoint. They do not assume a daily official update. No-change estimates allow intervening rises or falls; they are a central baseline, not certainty.')
    return pd.concat(dated, ignore_index=True) if dated else pd.DataFrame()


def evidence(row):
    if row is not None and (row.get("source_url") or "").startswith("https://"):
        st.link_button("View source record", row["source_url"])


def _forecast_limitation(spec):
    if spec.get("anchor_verification") == PROVISIONAL_PRICE:
        return "Based on matching IPT and Taqtek prices. Ministry confirmation is pending."
    if spec.get("tier") == 4:
        return "Live inputs are unavailable for a model forecast. The estimate uses a simple price baseline."
    if spec.get("lagged_market_inputs"):
        return "Some energy-market observations are older than the usual freshness limit."
    if spec.get("tier") == 3:
        return "This estimate uses a simplified pricing calculation and available market proxies."
    if spec.get("tier") == 2:
        return "This research estimate has yet to receive production approval."
    return "The forecast uses fresh primary inputs and a validated model."


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def _saved_market_dates(ledger_path, snapshot_id, version):
    connection = sqlite_connection(ledger_path, readonly=True)
    try:
        row = connection.execute("SELECT payload_json FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    finally:
        connection.close()
    inputs = json.loads(row[0]).get("inputs", {}).get("available_market_inputs", {}) if row else {}
    labels = {"brent_spot": "Brent spot", "nyh_gasoline": "NY Harbor gasoline",
              "brent_futures": "Brent futures", "rbob_futures": "RBOB futures"}
    return [f"{label} {inputs[key]['observation_date']}" for key, label in labels.items()
            if inputs.get(key) and inputs[key].get("observation_date")]


def _overview_price_sequence(latest, agreed, forecast):
    st.caption('USD equivalents use an assumed display rate of 89,500 LBP/USD; this is not a verified ministry conversion rate.')
    with st.container(key="price_sequence"):
        a, b, c = st.columns(3)
    with a:
        st.metric("Last government-archive price", amount(latest["price_lbp_20l"] if latest else None) + " LBP", border=True)
        if latest:
            _currency_detail(latest["price_lbp_20l"])
            _provenance_badge(latest)
            evidence(latest)
    with b:
        st.metric("Latest price agreed by IPT and Taqtek",
                  amount(agreed["price_lbp_20l"]) + " LBP" if agreed else "No provisional match", border=True)
        if agreed:
            _currency_detail(agreed["price_lbp_20l"])
            _provenance_badge(agreed)
    with c:
        if forecast is None:
            st.metric("Next estimated price", "Awaiting inputs", border=True)
            return
        spec = json.loads(forecast.target_json)
        change = forecast.predicted_change
        st.metric("Next estimated price", amount(forecast.predicted_price) + " LBP",
                  delta=f"{change:+,.0f} LBP ({change / forecast.base_price:+.2%})",
                  delta_color="off", border=True)
        _currency_detail(forecast.predicted_price)
        st.caption(f"Expected change · {change:+,.0f} LBP · ~{_signed_usd(change)} USD")
        st.caption(f"Starting price · {forecast.base_price:,.0f} LBP / 20 L")
    st.info(_forecast_limitation(spec))
    if spec.get("tier") == 4:
        market = "No market inputs used by the baseline"
    else:
        try:
            dates = _saved_market_dates(LEDGER_PATH, forecast.snapshot_id, data.file_version(LEDGER_PATH))
        except (OSError, ValueError, sqlite3.Error):
            dates = []
        market = " · ".join(dates) if dates else "Market dates were not recorded in this forecast snapshot"
    st.caption(f"Starting price observed · {spec.get('base_source_date') or 'Date unknown'}"
               f"  |  Market in forecast snapshot · {market}"
               f"  |  Forecast issued · {data.beirut_time(forecast.created_at)}")


def overview(snap, latest, previous):
    title("Lebanon gasoline 95", "Clear daily pump price tracker & next-decision outlook · LBP per 20-liter tank · Asia/Beirut")
    forecast_result = active("decision_1")
    active_forecast = forecast_result.iloc[0] if not forecast_result.empty else None
    agreed = next((r for r in reversed(snap["prices"])
                   if r["verification_status"] == PROVISIONAL_PRICE and r["price_lbp_20l"] is not None), None)
    _decree_outlook(snap["prices"], active_forecast)
    _overview_price_sequence(latest, agreed, active_forecast)
    with st.container(key="overview_refresh_controls"):
        controls, status = st.columns([1, 3], vertical_alignment="center")
        with controls:
            manager = _refresh_manager()
            with manager["lock"]:
                refresh_running = manager["running"]
            if st.button("Refreshing…" if refresh_running else "Refresh all data", type="primary",
                         key="overview_refresh", disabled=refresh_running):
                if not _refresh_authorized():
                    st.warning("Public read-only mode · Enter your admin passcode in the sidebar to run live refreshes.")
                elif start_background_refresh(ROOT, "all"):
                    st.rerun()
                else:
                    st.info("A full refresh is already running.")
        with status:
            refresh_status(snap, active_forecast)

    if latest or previous:
        with st.expander("Government price history details"):
            if previous:
                st.caption(f"Previous archive price · {previous['price_lbp_20l']:,} LBP / 20 L · {previous['source_date']}")
            if latest and previous:
                change = latest["price_lbp_20l"] - previous["price_lbp_20l"]
                st.caption(f"Change between archive records · {change:+,} LBP / 20 L "
                           f"({change / previous['price_lbp_20l']:+.2%}). Other decisions may have occurred between those dates.")
    if latest:
        if (datetime.now(BEIRUT).date() - date.fromisoformat(latest["source_date"])).days > SETTINGS["collection"]["stale_after_days"]:
            st.warning("The latest government-archive price exceeds the configured freshness limit.")
        if not latest["official_effective_date"]:
            st.caption("The latest government-archive record has a source date. Its official effective date is unknown.")
    document = next((r for r in reversed(snap["prices"])
                     if r["verification_status"] == "document_verified"), None)
    if document and document != latest:
        st.caption(f"Latest reviewed original decision · {document['source_date']} · {document['price_lbp_20l']:,} LBP / 20 L")
    supplier = next((r for r in reversed(snap["prices"]) if r["verification_status"] == "supplier_observed"
                     and r["price_lbp_20l"] is not None), None)
    if supplier and supplier["source_date"] > max((r["source_date"] for r in (latest, agreed) if r), default=""):
        st.caption(f"Newer single-source quote · {supplier['source_date']} · {supplier['price_lbp_20l']:,} LBP / 20 L")
    price_history = st.container()
    st.subheader("Next official decision")
    forecast = active_forecast
    if forecast is None:
        unavailable_forecast()
    else:
        forecast_details(forecast)
    if forecast is not None:
        view = data.forecast_view(forecast)
        bounds = view['bounds']
        stats=[('Expected decision date',view['schedule'].split(' (')[0]),
               ('Predicted price',amount(forecast.predicted_price) + ' LBP'),
               ('Predicted change · LBP',f'{forecast.predicted_change:+,.0f}'),
               ('Predicted change · %',percent(forecast.predicted_change/forecast.base_price)),
               ('90% prediction interval', f'{bounds[0]:,.0f} – {bounds[1]:,.0f}' if bounds else 'Awaiting live evidence')]
        active_stats = stats
        for offset in range(0, len(active_stats), 2):
            for col,(label,value) in zip(st.columns(2),active_stats[offset:offset+2]):
                col.metric(label,value)
                if label == 'Predicted price':
                    with col:
                        _currency_detail(forecast.predicted_price)
                if label == 'Predicted change · LBP':
                    col.caption(f'~{_signed_usd(forecast.predicted_change)} USD / 20 L')
                if label=='Expected decision date' and ' (' in view['schedule']:
                    col.caption(view['schedule'].split(' (',1)[1].rstrip(')')+' · estimated')
        st.caption(f"Prices and intervals: LBP / 20 L · USD equivalent: ${view['usd_equivalent']:,.2f} / 20 L at an assumed display rate of 89,500 LBP/USD. This is not a verified pricing-formula exchange rate.")
        st.subheader('Forecast Driver Attribution')
        if view['drivers']:
            show_chart(charts.driver_chart(view['drivers']))
            st.dataframe(pd.DataFrame(view['drivers']),hide_index=True,width='stretch')
        st.caption('Only saved model contributions are shown. Combined commodity attribution cannot be split into gasoline and Brent effects. EIA NY Harbor gasoline is a proxy, not a Mediterranean or RBOB assessment.')
    st.subheader('Future price estimates')
    dated = future_table()
    with price_history:
        st.subheader("Observed prices and future estimates")
        cutoff = datetime.now(BEIRUT).date().replace(day=1) - pd.Timedelta(days=180)
        recent = [r for r in snap["prices"] if r["source_date"] >= cutoff.isoformat()]
        show_chart(charts.history_chart(recent, pd.DataFrame(), dated))


def price_view(snap):
    title("Price & forecasts", "Official Lebanon pump price history and upcoming decision estimates in LBP per 20 liters")
    st.markdown(
        '<div class="plain-guide"><strong>How to read this chart:</strong> The solid step line tracks the official pump price '
        'for 20 liters of 95-octane gasoline. Solid dots mark verified records, while open diamonds/squares show where the model '
        'estimates the price will land next.</div>',
        unsafe_allow_html=True,
    )
    label = st.radio("Horizon", list(data.HORIZONS), horizontal=True, key="price_horizon")
    horizon = data.HORIZONS[label]
    production = active(horizon)
    if production.empty:
        unavailable_forecast()
    else:
        forecast = production.iloc[0]
        st.metric('Estimated future price · LBP / 20 L', amount(forecast.predicted_price), delta=f'{forecast.predicted_change:+,.0f} LBP')
        forecast_details(forecast)
        if horizon == 'decision_1':
            show_chart(charts.decision_chart(forecast))
            st.caption('Event-based estimate. The announcement date is not yet verified.')
    replay = pd.DataFrame()
    if st.checkbox("Overlay saved retrospective predictions", key="show_replay"):
        rows = get_ledger(horizon, "retrospective_research")
        if not rows.empty:
            replay = rows[rows.family.eq("G_hybrid")]
            st.caption("Saved research predictions use previously examined periods. Candidate intervals have unresolved calibration failures.")
    trajectory=[active(h) for h in data.HORIZONS.values()]
    trajectory=pd.concat([r for r in trajectory if not r.empty],ignore_index=True) if any(not r.empty for r in trajectory) else pd.DataFrame()
    show_chart(charts.history_chart(snap["prices"], replay, trajectory))
    st.caption('Decision and calendar estimates appear as separate points. Whiskers show saved pointwise intervals for individual targets.')
    st.caption("Dots are the archived observations at their source dates. A faint step trace carries the last observed price forward between dates; its timing is indicative where official effective dates are undocumented. Forecast estimates remain separate markers.")
    if not replay.empty:
        st.dataframe(replay[["origin", "created_at", "recorded_target_date", "endpoint", "predicted_price",
                             "actual_price", "model_version", "snapshot_id"]].tail(25), hide_index=True)


def markets_view(snap):
    title("Global energy markets", "International crude oil, wholesale gasoline, and currency benchmarks that drive Lebanon's pump price")
    st.caption("Mediterranean benchmark trial · awaiting licensed daily CIF Med AAWZB00 data with publication timestamps.")
    st.link_button("View benchmark access options",
                   "https://www.spglobal.com/energy/en/products-solutions/fuels-refined-products/fuels-refining-market-data")
    st.markdown(
        '<div class="plain-guide"><strong>Why global markets matter:</strong> Lebanon imports all of its refined gasoline in US dollars. '
        'When international crude oil (Brent) or wholesale gasoline rises overseas, Lebanon\'s official 20-liter pump price typically follows within 1–2 decisions.</div>',
        unsafe_allow_html=True,
    )
    rows = []
    for sid, spec in SERIES.items():
        history = snap["histories"][sid]
        latest = history[-1] if history else {}
        stats = snap["market"]["series"][sid]
        rows.append({"Instrument": spec.title, "Last stored": latest.get("value"), "Unit": spec.normalized_unit,
                     "Observation": latest.get("observation_date"),
                     "Daily close %": percent(stats.get("return_1_observation")) if spec.frequency == "daily" else "Unavailable",
                     "7-day %": percent(stats.get("return_7_calendar_days")), "Freshness": stats["status"].replace("_", " "),
                     "Captured in Beirut": data.beirut_time(latest.get("retrieved_at")),
                     "Publication time": data.beirut_time(latest.get("publication_timestamp")),
                     "Source": latest.get("source_url", spec.url)})
    st.dataframe(pd.DataFrame(rows), hide_index=True,
                 column_config={"Source": st.column_config.LinkColumn("Source", display_text="Open source")})
    st.caption("Daily close compares consecutive observations. Seven-day movement uses the latest available observation at or before the seven-day reference date within the existing gap limit.")
    failed = snap["runs"][snap["runs"].source_id.isin({"market_eia", "market_ec", "market_fed", "market_cboe", "market_fred_ovx"})
                          & snap["runs"].status.ne("success")]
    if not failed.empty:
        st.warning("Latest collection incomplete · " + ", ".join(failed.source_id.str.replace("market_", "").str.upper()))
    spread = snap["market"]["nyh_gasoline_minus_brent"]
    a, b = st.columns(2)
    a.metric(
        "NY Harbor gasoline minus Brent · USD/bbl",
        amount(spread["value"], 2),
        border=True,
        help="Roughly the price gap between refined US wholesale gasoline and raw Brent crude oil. Larger positive gaps usually signal tighter refining supply and upward pressure on pump prices.",
    )
    a.caption(f"Same-date cross-region gross spread · {spread.get('observation_date', 'Unavailable')}")
    b.metric(
        "Verified refining margin",
        "Unavailable",
        border=True,
        help="Actual Mediterranean 95-octane wholesale refining margin requires licensed Platts/Argus data that is not included in free public feeds.",
    )
    b.caption("The gross spread omits refinery costs, yields and regional basis.")
    sid = st.selectbox("Instrument history", list(SERIES), format_func=lambda key: SERIES[key].title)
    history = snap["histories"][sid][-365:]
    if history:
        import plotly.graph_objects as go
        x = [r["observation_date"] for r in history]
        y = [r["value"] for r in history]
        fig = go.Figure()
        base = min(y) - max((max(y) - min(y)) * .08, abs(min(y)) * .01)
        fig.add_scatter(x=x, y=[base] * len(x), mode="lines",
                        line=dict(width=0, color="rgba(0,0,0,0)"),
                        hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=x, y=y, mode="lines+markers",
                        line=dict(color=charts.BLUE, width=2),
                        fill="tonexty", fillcolor="rgba(139,92,246,.09)",
                        marker=dict(color=charts.TEAL, size=5,
                                    line=dict(color=charts.SECTION, width=1)), name=SERIES[sid].title,
                        hovertemplate="%{x}<br>%{y:,.3f}<extra></extra>")
        show_chart(charts.style(fig, SERIES[sid].normalized_unit, 325))
    with st.expander("Unavailable benchmarks and rates", expanded=True):
        for label, key in [("Platts FOB Mediterranean 95", "platts_AAWZA00"),
                           ("Platts CIF Mediterranean 95", "platts_AAWZB00"),
                           ("Mediterranean freight", "med_clean_freight"),
                           ("Official pricing USD/LBP history", "pricing_formula_fx")]:
            st.markdown(f"**{label}** · {MISSING[key]}")


def volatility_view(snap):
    title("Implied volatility & options", "Cboe OVX is a USO oil ETF options-derived volatility index, not gasoline or Mediterranean 95 implied volatility")
    st.markdown(
        '<div class="plain-guide"><strong>In plain English:</strong> Think of OVX as the oil market\'s turbulence gauge. '
        'A higher percentage means traders expect bigger price swings over the next month—it signals wider uncertainty, not whether fuel prices will go up or down.</div>',
        unsafe_allow_html=True,
    )
    history = snap['histories'].get('cboe_ovx', [])
    summary = data.volatility_summary(history)
    if summary is None:
        st.info("No OVX history is currently available. Import an authorized Cboe/FRED CSV or refresh the FRED OVXCLS source.")
    else:
        level = summary['level']
        change = summary['change_5d']
        percentile = summary['percentile_252d']
        from math import sqrt
        row_one = st.columns(3)
        row_one[0].metric(
            'Latest OVX close',
            f"{level:.2f}%" if pd.notna(level) else 'Unavailable',
            border=True,
            help="Cboe OVX measures annualized 30-day expected crude oil volatility from USO ETF options. Typical calm/normal readings sit around 20%–35%; 35%–50% is elevated; above 50% signals market stress. It measures turbulence, not price direction.",
        )
        row_one[1].metric(
            'Implied 30-day crude oil swing',
            f"{level / sqrt(12):.2f}%" if pd.notna(level) else 'Unavailable',
            border=True,
            help="Expected 1-standard-deviation move in crude oil over 30 days (OVX ÷ √12). Roughly 68% of monthly oil moves fall within ±this percentage.",
        )
        row_one[2].metric(
            'Implied 7-day crude oil swing',
            f"{level / sqrt(52):.2f}%" if pd.notna(level) else 'Unavailable',
            border=True,
            help="Expected 1-standard-deviation move in crude oil over 7 days (OVX ÷ √52). Higher values mean wider short-term uncertainty for fuel costs.",
        )
        row_two = st.columns(3)
        if pd.notna(change):
            direction = 'spiked' if change > 0 else 'cooled' if change < 0 else 'was unchanged'
            change_text = f"{change:+.2f} vol points · volatility {direction}"
        else:
            change_text = 'Insufficient recent closes'
        row_two[0].metric(
            '5-trading-session change',
            change_text,
            border=True,
            help="Change in OVX over the last 5 market days (1 trading week). A sharp positive jump means traders are suddenly pricing in larger oil swings.",
        )
        row_two[1].metric(
            '252-close percentile',
            f"{percentile:.1f}%" if pd.notna(percentile) else 'Insufficient history',
            border=True,
            help="252 trading days ≈ 1 full market year. This shows what % of the past year's closes were lower than today's OVX. Normal range: 25%–75% (0%–25% = unusually calm, 75%–90% = elevated turbulence, 90%–100% = stress / top 10% most volatile days).",
        )
        row_two[2].metric(
            'Volatility regime',
            summary['regime'] or 'Insufficient history',
            border=True,
            help="Classifies today's OVX against the past 252 trading days: Low/Normal (<75th percentile), Elevated (75th–90th percentile), or Stress (≥90th percentile, meaning wider forecast uncertainty).",
        )
        if pd.notna(level):
            st.caption(f"At this OVX reading, options imply a roughly {level / sqrt(12):.1f}% one-standard-deviation crude-oil move over 30 days and {level / sqrt(52):.1f}% over 7 days. This is a volatility proxy, not a prediction of direction or a gasoline-price interval.")
        if pd.notna(percentile):
            st.caption(f"The latest close is higher than about {percentile:.0f}% of the observed closes in the trailing one-year sample.")
        st.caption(f"Observation date {summary['observation_date']} · last retrieved {data.beirut_time(summary['retrieved_at'])} · percentile uses {summary['regime_basis']}.")
        if summary.get('source_url'):
            st.link_button('View OVX source', summary['source_url'])
        show_chart(charts.ovx_history_chart(history))
    st.caption("OVX measures expected volatility inferred from USO options. It is a broad crude-oil risk proxy; it does not measure Lebanese gasoline-price volatility or determine the direction of gasoline prices.")
    st.subheader('Options chain snapshot')
    options_path = ROOT / 'data/exports/options_chain_latest.json'
    try:
        options = json_file(str(options_path), data.file_version(options_path))
    except (OSError, ValueError, TypeError):
        options = None
    if not options:
        st.info("OVX history is active when available. An authorized USO, BNO or UGA options-chain JSON import is optional; no options-chain snapshot is stored yet.")
        return
    atm = options.get('atm_30d_iv')
    ratio = options.get('put_call_oi_ratio')
    a, b, c = st.columns(3)
    a.metric(
        'Nearest listed ~30-day IV',
        f"{100*atm:.1f}%" if isinstance(atm, (int, float)) else 'Unavailable',
        border=True,
        help="At-the-money implied volatility for the option contract expiring closest to 30 days out. Higher IV means larger expected price swings.",
    )
    b.metric(
        'Put / call open interest',
        f"{ratio:.2f}" if isinstance(ratio, (int, float)) else 'Unavailable',
        border=True,
        help="Ratio of open put contracts (downside hedges) to call contracts (upside bets). Above 1.0 suggests more hedging against price drops; below 1.0 suggests more upside positioning.",
    )
    c.metric(
        'Filtered contracts',
        f"{options.get('contracts_filtered', 0):,}",
        border=True,
        help="Number of liquid option contracts (7–60 days to expiry with active quotes/open interest) included in this snapshot.",
    )
    st.caption(f"{options.get('symbol', 'Unknown symbol')} · as of {options.get('as_of_date', 'date unavailable')} · captured {data.beirut_time(options.get('captured_at'))} · authorized local snapshot")
    contracts = options.get('contracts')
    if isinstance(contracts, list) and contracts:
        table = pd.DataFrame(contracts)
        if 'iv' in table:
            table['iv_pct'] = 100 * pd.to_numeric(table['iv'], errors='coerce')
        columns = [column for column in ['contract_symbol', 'expiration_date', 'option_type', 'strike', 'dte',
                                         'iv_pct', 'bid', 'ask', 'open_interest', 'volume'] if column in table]
        st.dataframe(table[columns], hide_index=True, width='stretch')
    else:
        st.info('The imported options snapshot contains no contracts passing the documented filters.')


def model_view():
    title("Model performance", "Hybrid forecasts scored against recorded prices")
    decisions.performance(ROOT, LEDGER_PATH)
    st.divider()
    st.subheader("Hybrid historical backtest")
    archive = ROOT / "reports/research/expanded_coverage/dashboard_predictions.csv"
    saved = table_file(archive if archive.is_file() else REPORTS / "research_walk_forward_predictions.csv")
    if not saved.empty:
        rows = saved.loc[saved["family"].eq("G_hybrid") & saved["horizon"].eq("decision_1")]
        if not rows.empty:
            actual = rows["endpoint_price_lbp_20l"]
            error = (rows["predicted_endpoint_price_lbp_20l"] - actual).abs()
            st.caption(f"{rows['target_source_date'].nunique()} historical target dates. "
                       f"Average miss {error.mean():,.0f} LBP / 20 L ({(error/actual).mean():.2%}).")
    st.caption("The archive backtest uses recorded prices. Live scores above track forecasts saved before new prices arrive.")
    st.button("Open the backtest chart", on_click=st.session_state.update, args=({"view": "Backtesting"},))


def scenario_view(snap):
    title("Scenario simulator", "Interactive what-if calculator · see how oil prices, shipping, taxes, and the USD/LBP rate build the 20L pump price")
    st.markdown(
        '<div class="plain-guide"><strong>Try your own assumptions:</strong> Adjust international gasoline cost, the USD/LBP exchange rate, '
        'or domestic fees below and click <strong>Calculate scenario</strong> to see the resulting 20-liter pump price and tax/margin breakdown.</div>',
        unsafe_allow_html=True,
    )
    template = data.read_json(ROOT / "config/structural_scenario_before_vat.json")
    st.info("Inputs are assumptions. Domestic duties, transport, retail margin and bank commission use the May 2025 scaffold.")
    mode = st.radio("Refined gasoline input", ["Direct product quote", "Brent plus assumed product spread"], horizontal=True)
    product_history = snap["histories"]["nyh_gasoline"]
    brent_history = snap["histories"]["brent_spot"]
    product_default = product_history[-1]["value"] if product_history else float(template["benchmark"]["value"])
    brent_default = brent_history[-1]["value"] if brent_history else product_default
    with st.form("scenario"):
        a, b, c = st.columns(3)
        brent = None
        spread = 0.0
        if mode == "Brent plus assumed product spread":
            brent = a.number_input("Brent assumption · USD/bbl", min_value=0.01, value=float(brent_default), step=1.0)
            spread = b.number_input("Assumed product spread · USD/bbl", value=float(product_default - brent_default), step=1.0)
            product = product_default
        else:
            product = a.number_input("Refined gasoline assumption · USD/bbl", min_value=0.01, value=float(product_default), step=1.0)
        fx = c.slider("USD/LBP assumption · LBP per USD", min_value=89500, max_value=100000,
                      value=min(100000,max(89500,int(template["fx"]["value"]))), step=500)
        freight = a.number_input("Freight assumption · USD/kL", min_value=0.0, value=float(template["freight_usd_kl"]["value"]), step=5.0)
        vat = b.number_input("VAT assumption · %", min_value=0.0, max_value=100.0, value=float(template["vat"]["value"]) * 100, step=1.0)
        charge = c.number_input("Government charge · LBP / 20 L", min_value=0, value=300000, step=10000)
        taxable = st.checkbox("Apply VAT to the government charge", value=True)
        calculate = st.form_submit_button("Calculate scenario", type="primary")
    st.caption(f"Product and Brent starting values use stored proxy observations where available. Other import costs are held at {template['other_import_usd_kl']['value']} USD/kL.")
    if calculate:
        try:
            result = simulate(template, product=product, fx=fx, freight=freight, vat_percent=vat,
                              charge=charge, charge_taxable=taxable, brent=brent, spread=spread)
        except (ValueError, DecimalException) as exc:
            st.error(f"Invalid scenario. {exc}")
            return
        st.metric("Hypothetical price · LBP / 20 L", amount(float(result["price_lbp_20l"])), border=True)
        if brent is not None:
            st.caption(f"Effective scenario product quote · {brent + spread:,.2f} USD/bbl")
        imported=result.get('import_breakdown') or {}
        if imported:
            cif_lbp_20l=(float(imported['benchmark_usd_kl'])+float(imported['freight_usd_kl']))*float(fx)/50
        else:
            cif_lbp_20l=float(result['breakdown_lbp_20l'].get('goods',0))
        wedge_lbp_20l=float(result['price_lbp_20l'])-cif_lbp_20l
        st.dataframe(pd.DataFrame([
            {"Component":"CIF Cargo Cost · modeled benchmark + freight", "LBP / 20 L":cif_lbp_20l},
            {"Component":"Fixed Tax/Margin Wedge · residual to pump price", "LBP / 20 L":wedge_lbp_20l},
        ]), hide_index=True)
        st.caption("The residual wedge includes modeled other import costs, government charges, VAT, margins and any rounding adjustment; it is not a separately verified official tariff schedule.")
        st.caption("Deterministic cost calculation. No probability or confidence interval applies.")


def quality_view(snap):
    title("Data quality & alerts", "Live feed health, source verification checks, and why safety gates pause unverified forecasts")
    st.markdown(
        '<div class="plain-guide"><strong>Why safety gates exist:</strong> Rather than guessing when official Ministry data is missing or market feeds are stale, '
        'this system automatically pauses live predictions or falls back to a clearly labeled baseline until fresh, corroborated records arrive.</div>',
        unsafe_allow_html=True,
    )
    a, b, c = st.columns(3)
    conflicts = [r for r in snap["prices"] if r["verification_status"] == "conflict"]
    a.metric("Quarantined conflict dates", len(conflicts), border=True)
    b.metric("Missing publication clocks", snap["missing_clocks"][0], border=True)
    c.metric("Unknown effective dates", snap["missing_clocks"][1], border=True)
    st.warning("Production approval withheld · Official timing, current regime and calibration remain unresolved.")
    with st.expander("Latest recorded prospective forecast checks"):
        try:
            current_check = ROOT / "reports/operations/current_forecast_check.json"
            checks = data.read_json(current_check if current_check.exists() else REPORTS / "current_abstentions.json")
            st.caption(f"Evaluation origin · {data.beirut_time(checks['origin'])}")
            labels = {"model_not_approved": "Model approval withheld",
                      "unsupported_regulatory_regime": "Regulatory regime unsupported",
                      "unverified_official_anchor": "Official anchor unverified",
                      "anchor_effective_at_missing": "Official effective time unavailable",
                      "decision_coverage_unverified": "Decision coverage unverified"}
            for reason in checks.get("reasons", []):
                st.write(labels.get(reason, reason.replace("_", " ")))
            st.caption("Forecast ledger entries " + ", ".join(map(str, checks.get("forecast_ids", []))))
        except (OSError, ValueError, KeyError):
            st.caption("The saved prospective checks are unavailable.")
    st.subheader("Scheduled operations")
    try:
        operations = data.read_json(ROOT / "reports/operations/latest_run.json")
        st.caption(f"Latest cycle · {data.beirut_time(operations['finished_at'])} · {operations['status']}")
        monitored = data.read_json(ROOT / "reports/operations/monitoring.json")
        st.caption(f"Verified prospective outcomes · {monitored['performance']['evaluated_forecasts']}")
        with st.expander("Operating alerts and review triggers"):
            for warning in monitored["alerts"]:
                st.write(warning["message"])
    except (OSError, ValueError, KeyError):
        st.caption("No completed automation cycle is available yet.")
    if st.button("Refresh all sources and reports"):
        if not _refresh_authorized():
            st.warning("Public read-only mode · Enter your admin passcode in the sidebar to run live refreshes.")
        else:
            with st.spinner("Running the complete local refresh cycle…"):
                st.session_state.refresh_result = data.refresh_source(ROOT, "all")
            snapshot.clear()
            st.rerun()
    st.subheader("Source refresh")
    st.caption(f"Last successful capture · {data.beirut_time(snap['latest_capture'])}. Observation dates determine freshness.")
    sources = {"ipt": "IPT", "ministry": "Ministry of Energy and Water", "taqtek": "Taqtek",
               "eia": "US Energy Information Administration", "ec": "European Commission", "fed": "Federal Reserve"}
    source = st.selectbox("Public source", list(sources), format_func=sources.get)
    if st.button("Refresh selected source", type="primary"):
        if not _refresh_authorized():
            st.warning("Public read-only mode · Enter your admin passcode in the sidebar to run live refreshes.")
        else:
            with st.spinner(f"Collecting {sources[source]} through the existing pipeline…"):
                st.session_state.refresh_result = data.refresh_source(ROOT, source)
            snapshot.clear()
            st.rerun()
    if "refresh_result" in st.session_state:
        ok, output = st.session_state.refresh_result
        if ok:
            st.success("Collection completed. Check the latest observation dates for new data.")
        else:
            st.error("Collection failed or was incomplete. Stored observations retain their original dates and evidence.")
        with st.expander("Refresh output"):
            st.code(output, language="text")
    if not snap["runs"].empty:
        runs = snap["runs"].drop(columns="details").copy()
        for column in ["started_at", "finished_at"]:
            runs[column] = runs[column].map(data.beirut_time)
        st.dataframe(runs, hide_index=True)
    stale = [SERIES[sid].title for sid, stats in snap["market"]["series"].items() if stats["status"] != "available"]
    if stale:
        st.warning("Stale or unavailable observations · " + ", ".join(stale))
    st.subheader("Source conflicts and price jumps")
    flags = conflicts + [r for r in snap["prices"] if r not in conflicts and
                         any("suspicious" in issue for issue in r["issues"])]
    if flags:
        st.dataframe(pd.DataFrame(flags)[["source_date", "verification_status", "candidate_values", "issues"]].sort_values("source_date", ascending=False), hide_index=True)
    with st.expander("Missing observations and unusual market moves"):
        try:
            audit = data.read_json(ROOT / "reports/data_quality.json")
            st.caption(f"Audit snapshot · {data.beirut_time(audit['generated_at'])}. Gaps are investigation candidates.")
        except (OSError, ValueError, KeyError):
            st.warning("The dated source quality audit is unavailable.")
        for name, heading in [("gap_candidates.csv", "Domestic date gaps"),
                              ("cross_source_missing_dates.csv", "Cross-source absences"),
                              ("market_reported_missing.csv", "Source-reported missing market data"),
                              ("market_suspicious_changes.csv", "Large market moves flagged for review")]:
            st.markdown(f"**{heading}**")
            result = table_file(ROOT / "reports" / name)
            if not result.empty:
                st.dataframe(result.tail(200), hide_index=True)


def main():
    global SETTINGS, DECISION, LEDGER_PATH, ACTIVE_FORECASTS
    st.set_page_config(page_title="Levant Energy Terminal", layout="wide", initial_sidebar_state="auto")
    stylesheet = Path(__file__).with_name("terminal.css").read_text(encoding="utf-8") + RESPONSIVE_CSS
    st.markdown(f"<style>{stylesheet}</style>", unsafe_allow_html=True)
    try:
        SETTINGS = data.config(ROOT)
        db_path, LEDGER_PATH = data.database_paths(ROOT, SETTINGS)
        snap = snapshot(ROOT, db_path, data.file_version(db_path))
        latest_record = snap['prices'][-1] if snap['prices'] else None
    except (OSError, ValueError, KeyError, sqlite3.Error, pd.errors.DatabaseError) as exc:
        st.error(f"The local market and price database could not be opened. {exc}")
        return
    try:
        DECISION = data.read_json(ROOT / SETTINGS["validation"]["decision_file"])
    except (OSError, ValueError):
        DECISION = {}
        st.warning("The validation decision file is unavailable. Production-approved forecasts are withheld.")
    ACTIVE_FORECASTS = current_forecasts(LEDGER_PATH, SETTINGS, DECISION, latest_record)
    with st.sidebar:
        st.markdown(
            '<div class="terminal-brand">'
            '<div class="brand-row"><span class="brand-mark">L</span><strong>Levantdark X</strong></div>'
            '<span>Lebanon Gasoline 95 Price &amp; Forecast Guide</span>'
            '<div class="brand-badge">LBP / 20L Tank · Beirut</div></div>',
            unsafe_allow_html=True,
        )
        view = st.radio("Workspace", VIEWS, key="view")
        st.divider()
        st.caption("Local time · Asia/Beirut")
        st.caption(f"Stored capture · {data.beirut_time(snap['latest_capture'])}")
        if not DECISION.get("production_approved"):
            st.caption("Production approval · Withheld")
        current = active('decision_1')
        st.caption('Available estimate · ' + (current.iloc[0].forecast_label if not current.empty else forecast_unavailable_reason()))
        if _configured_passcode():
            with st.expander("Owner refresh unlock"):
                st.text_input("Admin passcode", type="password", key="admin_passcode_entered",
                              help="Unlock live source collection on public cloud deployments.")
                st.caption("Unlocked · live refresh enabled" if _refresh_authorized() else "Read-only public mode")
    if view == "Overview" and not st.session_state.get("overview_auto_refresh_attempted", False):
        st.session_state["overview_auto_refresh_attempted"] = True
        # AppTest must remain hermetic; an actual browser session starts one safe background refresh.
        if not os.environ.get("PYTEST_CURRENT_TEST") and _refresh_authorized():
            start_background_refresh(ROOT, "all")
    latest, previous = data.anchors(snap["prices"])
    if view == "Overview":
        overview(snap, latest, previous)
    elif view == "Price & forecasts":
        price_view(snap)
    elif view == "Global markets":
        markets_view(snap)
    elif view == "Analyst report":
        title("Senior analyst report", "Plain-English market briefing · what is driving Lebanon's gasoline price right now")
        st.markdown(
            '<div class="plain-guide"><strong>Plain-language briefing:</strong> A structured summary of the latest verified pump price, '
            'international oil movements, regulatory context, and model accuracy—written without jargon and downloadable in one click.</div>',
            unsafe_allow_html=True,
        )
        result = active("decision_1")
        current = DECISION.get("selection", {}).get("decision_1", {})
        hybrid_decision = DECISION if current.get("family") == "G_hybrid" else {}
        sections = analyst.brief(latest, previous, snap["market"], pd.DataFrame(),
                                 hybrid_decision, result.iloc[0] if not result.empty else None)
        for heading, content in sections.items():
            st.subheader(heading)
            st.write(content)
        st.download_button("Download analyst report", "\n\n".join(f"## {k}\n\n{v}" for k, v in sections.items()),
                           "lebanon-energy-brief.md", "text/markdown")
    elif view == "Model performance":
        model_view()
    elif view == "Backtesting":
        title("Backtesting", "Historical forecasts and observed Lebanon gasoline 95 prices")
        archive_path = ROOT / "reports/research/expanded_coverage/dashboard_predictions.csv"
        archived = archive_path.is_file()
        dataset = st.radio("Backtest dataset", ["Current validation report", "Expanded archive research"],
                           horizontal=True, key="backtest_dataset") if archived else "Current validation report"
        if dataset == "Expanded archive research":
            backtesting.render(
                table_file(archive_path), FAMILIES,
                {"expanded_2026_research": "2026 expanded research"}, show_chart,
                research_note="Research comparison using recorded Ministry archive prices and exact IPT–LebVote matches. "
                              "Some decision timing remains unverified. All predictions shown use the pinned Hybrid.",
                only_family="G_hybrid",
            )
        else:
            backtesting.render(table_file(REPORTS / "research_walk_forward_predictions.csv"),
                               FAMILIES, REGIMES, show_chart, only_family="G_hybrid")
    elif view == "Decision timeline":
        title("Decision timeline", "Price evidence, gaps and forecast outcomes")
        decisions.timeline(snap["prices"], ROOT, LEDGER_PATH)
    elif view == "Scenario simulator":
        scenario_view(snap)
    elif view == "Volatility & options":
        volatility_view(snap)
    else:
        quality_view(snap)


if __name__ == "__main__":
    main()
