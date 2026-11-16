"""Public views for the pinned Hybrid and its decision evidence."""
from datetime import date
from statistics import mean
import sqlite3

import pandas as pd
import streamlit as st

from lebanon_fuel.dashboard.data import STATUS, file_version
from lebanon_fuel.forecasting.uncertainty import direction_class
from lebanon_fuel.validation.decision_tracking import MAX_GAP_DAYS, dashboard_evidence


@st.cache_data(ttl=60, max_entries=8, show_spinner=False)
def _evidence(root, ledger, version):
    return dashboard_evidence(root, ledger)


def evidence(root, ledger):
    try:
        return _evidence(root, ledger, file_version(ledger))
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.warning("Decision tracking is temporarily unavailable.")
        return None


def performance(root, ledger):
    st.subheader("Live Hybrid scorecard")
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
                              ("provisional", "IPT and Taqtek starting price")):
            matches = [row for row in sample if row["cohort"] == cohort]
            if not matches:
                continue
            calls = direction_class([r["predicted_change"] for r in matches])
            actual = direction_class([r["actual"] - r["base"] for r in matches])
            rows.append({"Starting price evidence": label, "Updates": len(matches),
                         "Average miss · LBP / 20 L": round(mean(abs(r["actual"]-r["forecast"]) for r in matches)),
                         "Direction calls right": f"{int((calls == actual).sum())} of {len(matches)}"})
        st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("A supplier outcome can appear in both sections once officially reviewed. Within each section "
               "and starting-price group, repeated forecasts for one date count once.")


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
