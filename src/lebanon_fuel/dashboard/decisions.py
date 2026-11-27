"""Public views for the pinned Hybrid and its decision evidence."""
from datetime import date, datetime, timezone
from html import escape
from statistics import mean
import sqlite3

import pandas as pd
import streamlit as st

from lebanon_fuel.dashboard.data import STATUS, beirut_time, file_version, prospective_comparisons
from lebanon_fuel.domain import BEIRUT
from lebanon_fuel.forecasting.uncertainty import direction_class
from lebanon_fuel.validation.decision_tracking import MAX_GAP_DAYS, _read, dashboard_evidence
from lebanon_fuel.validation.live_score import protocol, report


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def _evidence(root, ledger, version):
    return dashboard_evidence(root, ledger)


def evidence(root, ledger):
    try:
        return _evidence(root, ledger, file_version(ledger))
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.warning("Decision tracking is temporarily unavailable.")
        return None


@st.cache_data(ttl=60, max_entries=24, show_spinner=False)
def score_report(root, ledger, horizon, version):
    policy = protocol(root)
    if policy:
        with _read(ledger) as db:
            return report(db, policy, datetime.now(timezone.utc), horizon=horizon)
    return None


def performance(root, ledger):
    st.subheader("Live Hybrid scorecard")
    labels = {"Next update": "decision_1", "Next two updates": "decision_2", "Next four updates": "decision_4",
              **{f"{days} days": f"day_{days}" for days in (1, 3, 7, 14, 30)}}
    label = st.selectbox("Scoring horizon", list(labels), key="fixed_score_horizon")
    try:
        score = score_report(root, ledger, labels[label], file_version(ledger))
    except (OSError, sqlite3.Error, KeyError, ValueError):
        score = None
        st.warning("The fixed-rule scorecard is temporarily unavailable.")
    if score:
        st.caption(f"Protocol {score['version']} · effective {beirut_time(score['starts_at'])}. "
                   "The first eligible issuance is selected before outcome matching.")
        names = {"selected": "Selected", "matched": "Matched", "pending": "Pending",
                 "expired": "Expired", "disputed": "Disputed", "coverage_gap": "Coverage gap",
                 "missed_entry": "Missed cutoff", "awaiting_eligible": "Awaiting eligible batch",
                 "duplicate_target": "Repeated actual date"}
        st.caption(" · ".join(f"{label} {score['counts'].get(key, 0)}" for key, label in names.items()))
        if score["comparisons"]:
            st.dataframe(pd.DataFrame([{
                "Compared with": r["comparison"], "Model": r["model"], "Outcomes": r["n"],
                "MAE · LBP / 20 L": round(r["mae"]), "RMSE · LBP / 20 L": round(r["rmse"]),
                "Mean error · LBP / 20 L": round(r["bias"]),
                "Direction hits": f"{r['direction_hits']} of {r['n']}",
            } for r in score["comparisons"]]), hide_index=True, width="stretch")
        else:
            st.caption("No matched outcomes under the fixed protocol yet.")
        if score["entries"]:
            with st.expander("Selected forecast records"):
                st.dataframe(pd.DataFrame(score["entries"]), hide_index=True, width="stretch")
    st.subheader("Earlier prospective research")
    view = evidence(root, ledger)
    if view is None:
        return
    st.caption(f"{view['issued']} of {view['complete']} complete refreshes issued a next-update Hybrid estimate. "
               "Repeated refreshes can target the same update.")
    for kind, title in (("official_match", "Official outcomes"), ("provisional_match", "Provisional supplier outcomes")):
        sample = [row for row in view["cases"] if row["kind"] == kind]
        st.markdown(f"**{title}**")
        if not sample:
            st.caption("No scored updates yet.")
            continue
        rows = []
        for cohort, label in (("government_backed", "Government-backed starting price"),
                              ("provisional", "Matching dated supplier starting price")):
            matches = [row for row in sample if row["cohort"] == cohort]
            if not matches:
                continue
            calls = direction_class([r["predicted_change"] for r in matches])
            actual = direction_class([r["actual"] - r["base"] for r in matches])
            rows.append({"Starting price evidence": label, "Updates": len(matches),
                         "First target": min(r['day'] for r in matches), "Last target": max(r['day'] for r in matches),
                         "Average miss · LBP / 20 L": round(mean(abs(r["actual"]-r["forecast"]) for r in matches)),
                         "Direction calls right": f"{int((calls == actual).sum())} of {len(matches)}"})
        st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Direction counts use increase, decrease and no-change with a 3,000 LBP deadband. A supplier outcome can appear in both sections once officially reviewed. Within each section "
               "and starting-price group, repeated forecasts for one date count once.")


@st.cache_data(ttl=60, max_entries=16, show_spinner=False)
def _comparisons(root, ledger, horizon, version):
    return prospective_comparisons(root, ledger, horizon)


def _daily_comparison_table(rows, today, *, scored_ids=(), archive=False):
    evidence_types = {"official_match": "Official", "provisional_match": "Supplier agreement"}
    actual = rows.actual_price.where(rows.evaluation_kind.isin(evidence_types))
    endpoint = pd.to_datetime(rows.endpoint, format="mixed", utc=True, errors="coerce")
    endpoint_date = endpoint.dt.tz_convert(BEIRUT).dt.tz_localize(None).dt.normalize()
    scheduled = pd.to_datetime(rows.scheduled_effective.str.slice(0, 10), format="%Y-%m-%d", errors="coerce")
    recorded = pd.to_datetime(rows.recorded_target_date, errors="coerce").where(actual.notna())
    issued = pd.to_datetime(rows.created_at, format="mixed", utc=True)
    issued_date = issued.dt.tz_convert(BEIRUT).dt.tz_localize(None).dt.normalize()
    target = endpoint_date.fillna(scheduled)
    # A settled decision uses its recorded date. Calendar outcomes retain the fixed endpoint.
    day = endpoint_date.fillna(recorded).fillna(scheduled).fillna(issued_date)
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=7)
    outcomes = rows.evaluation_kind.map(evidence_types).where(actual.notna()).fillna("Awaiting match")
    scored = rows["id"].isin(scored_ids) if "id" in rows else pd.Series(False, index=rows.index)
    table = pd.DataFrame({
        "Date · Beirut": day.dt.date,
        "Forecast": rows.predicted_price.round(), "Actual": actual.round(),
        "Error": (rows.predicted_price - actual).round(), "Outcome": outcomes,
        "Issued · Beirut": rows.created_at.map(beirut_time),
        "Expected date": target.dt.date, "Recorded date": recorded.dt.date,
        "Forecast ID": rows.get("id"), "Selected for scoring": scored,
        "_issued": issued, "_matched": actual.notna(),
    })
    keep = table if archive else table.loc[actual.notna() | day.gt(cutoff) | scored]
    return (keep
            .sort_values(["Date · Beirut", "Selected for scoring", "_matched", "_issued"],
                         ascending=False, kind="stable")
            .drop_duplicates("Date · Beirut")
            .drop(columns=["_issued", "_matched"]))


def predicted_vs_actual(root, ledger):
    st.subheader("Predicted vs actual")
    st.caption("One forecast per displayed date and horizon. Matched updates use the recorded date. Other rows use the expected date when available. After seven days, unmatched rows are shown only if selected for scoring or in Full details. Prices in LBP per 20 L.")
    horizons = {"Next update": "decision_1", "Next two updates": "decision_2", "Next four updates": "decision_4",
                **{f"{days} days" if days != 1 else "1 day": f"day_{days}" for days in (1, 3, 7, 14, 30)}}
    with st.container(key='comparison_controls'):
        picker, details = st.columns([1, 1], vertical_alignment='bottom')
        selected = picker.selectbox('Horizon', list(horizons), key='prospective_comparison_horizon')
        full_details = details.checkbox('Show full details', key='comparison_full_details')
    try:
        rows = _comparisons(root, ledger, horizons[selected], file_version(ledger))
    except (OSError, sqlite3.Error, ValueError, KeyError, pd.errors.DatabaseError):
        st.warning("The saved forecast ledger is temporarily unavailable.")
        return
    if rows.empty:
        st.info("No forecasts have been issued for this horizon yet.")
        return
    try:
        score = score_report(root, ledger, horizons[selected], file_version(ledger))
    except (OSError, sqlite3.Error, KeyError, ValueError):
        score = None
    scored_ids = {item["forecast_id"] for item in (score or {}).get("entries", [])}
    table = _daily_comparison_table(rows, pd.Timestamp.now(tz=BEIRUT).date(),
                                    scored_ids=scored_ids, archive=full_details)
    if table.empty:
        st.info("No matched or recent forecasts for this horizon.")
        return
    if full_details:
        st.dataframe(table, hide_index=True, width='stretch', column_config={
            name: st.column_config.NumberColumn(format='localized') for name in ('Forecast', 'Actual', 'Error')
        })
    else:
        parts = []
        for item in table.head(20).to_dict('records'):
            matched = pd.notna(item['Actual'])
            recorded = f"{item['Actual']:,.0f}" if matched else '—'
            expected = item["Expected date"]
            schedule = (f'<small>Expected {expected:%d %b %Y}</small>'
                        if pd.notna(expected) and expected != item["Date · Beirut"] else '')
            error = f'<small>Error {item["Error"]:+,.0f} LBP</small>' if matched else ''
            selection = '<small>Selected for scoring</small>' if item["Selected for scoring"] else ''
            outcome_class = 'matched' if matched else 'pending'
            parts.append(f'<tr><td><strong>{item["Forecast"]:,.0f}</strong>'
                         f'<small>{escape(item["Date · Beirut"].strftime("%d %b %Y"))}</small>{schedule}</td>'
                         f'<td><strong>{recorded}</strong>{error}</td>'
                         f'<td><span class="comparison-outcome {outcome_class}">{escape(item["Outcome"])}</span>{selection}</td></tr>')
        st.html('<div class="comparison-table-wrap"><table class="comparison-table" aria-label="Live price comparisons in LBP per 20 liters">'
                '<thead><tr><th scope="col">Forecast</th><th scope="col">Actual</th><th scope="col">Outcome</th></tr></thead>'
                '<tbody>' + ''.join(parts) + '</tbody></table></div>')
        if len(table) > 20:
            st.caption(f'Showing the 20 most recent of {len(table)} forecasts. Full details shows issuance time and pricing error.')
    st.caption("Error is forecast minus actual. Actual prices appear after the outcome passes the matching checks.")


def timeline(records, root, ledger):
    st.subheader("Recorded gasoline price updates")
    st.caption("Dated source records and any gaps between them. Some updates may be missing from the archive.")
    table = []
    previous = None
    for record in records[-24:]:
        day = date.fromisoformat(record["source_date"])
        distance = (day - previous).days if previous else 0
        previous = day
        table.append({"Source date": day.isoformat(), "Price · LBP / 20 L": record.get("price_lbp_20l"),
                      "Evidence": STATUS.get(record["verification_status"], record["verification_status"].replace("_", " ")),
                      "Gap before record": f"{distance} days · possible missing updates" if distance > MAX_GAP_DAYS else "",
                      "Publication date": record.get("publication_date"), "Effective date": record.get("official_effective_date"),
                      "Source": record.get("source_url")})
    if table:
        st.dataframe(list(reversed(table)), hide_index=True, width="stretch", column_config={
            "Source": st.column_config.LinkColumn(display_text="Open source"),
        })
    else:
        st.info("No dates have been recorded.")
    st.subheader("Recent forecasts awaiting or matched to outcomes")
    view = evidence(root, ledger)
    if view and view["checks"]:
        st.dataframe(pd.DataFrame(view["checks"]).rename(columns={
            "issued":"Issued · Beirut", "start_date":"Starting price date", "target_date":"Candidate date", "status":"Outcome status",
        }), hide_index=True, width="stretch")
    elif view:
        st.caption("No Hybrid next-update forecasts have been issued in the tracking period.")
