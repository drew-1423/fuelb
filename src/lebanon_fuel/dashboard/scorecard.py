"""Public presentation of the prospective next-decision track record."""
import sqlite3

import pandas as pd
import streamlit as st

from lebanon_fuel.dashboard.data import beirut_time, file_version
from lebanon_fuel.validation.scorecard import COHORTS, load_scorecard


@st.cache_data(max_entries=8, ttl=60, show_spinner=False)
def _scorecard(ledger, protocol, ledger_version, protocol_version):
    return load_scorecard(ledger, protocol)


def _comparison(metrics):
    table = pd.DataFrame(metrics).rename(columns={
        "method": "Method", "n": "Decisions", "mae": "Average miss · LBP / 20 L",
        "direction": "Direction accuracy",
    })
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Average miss · LBP / 20 L": st.column_config.NumberColumn(format="localized"),
        "Direction accuracy": st.column_config.NumberColumn(format="percent"),
    })


def render(root, ledger):
    st.subheader("Live forecast scorecard")
    st.caption("Next official decision · forecasts saved before the announcement")
    protocol = root / "config/prospective_holdout.json"
    try:
        result = _scorecard(ledger, protocol, file_version(ledger), file_version(protocol))
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.warning("The live forecast scorecard could not read the ledger or evaluation protocol.")
        return

    issued, abstained = result["issued"], result["abstained"]
    total = issued + abstained
    with st.container(horizontal=True):
        st.metric("Decisions scored", result["settled_decisions"], border=True)
        st.metric("Refreshes with an estimate", f"{issued} / {total} ({issued / total:.0%})" if total else "No complete runs", border=True)
        st.metric("Issued forecasts awaiting a match", issued - result["matched_issues"], border=True)
    st.caption(f"Tracking since {beirut_time(result['start'])}. The issuance rate counts complete logged "
               f"refreshes, including {abstained} abstentions. Repeated refreshes can target the same decision.")
    if result["incomplete"]:
        st.caption(f"{result['incomplete']} incomplete runs with a next-decision record were excluded.")
    if not result["settled_decisions"]:
        st.info("Awaiting a verified outcome that can be matched to a saved forecast. "
                "Accuracy and baseline comparisons will appear after a reviewed publication date, "
                "effective date and complete decision sequence support a match.")
        return

    options = list(COHORTS[:2])
    if result["groups"][COHORTS[2]]["cases"]:
        options.append(COHORTS[2])
    default = next(i for i, option in enumerate(options) if result["groups"][option]["cases"])
    cohort = st.selectbox("Price used when the forecast was issued", options, index=default, key="scorecard_anchor")
    group = result["groups"][cohort]
    n = len(group["cases"])
    if not n:
        st.info("No verified outcomes have been matched for this price-anchor group.")
        return
    if n < 10:
        st.info(f"Only {n} matched decision{'s' if n != 1 else ''} in this group. Accuracy is preliminary.")
    st.markdown("**Comparison on all matched decisions**")
    _comparison(group["primary"])
    if group["three_way"][0]["n"]:
        st.markdown("**Comparison where the prior price was saved**")
        _comparison(group["three_way"])
    else:
        st.caption("The last-change baseline needs a prior price saved with the forecast.")
    st.caption("Each group uses its latest eligible forecast per decision. The baseline uses the same starting "
               "price and outcome as the forecast. Direction treats changes within ±3,000 LBP as flat.")

    with st.expander("Matched decisions and sources"):
        table = pd.DataFrame(group["cases"]).rename(columns={
            "decision_date": "Announcement date", "issued_at": "Forecast issued", "family": "Method",
            "anchor": "Starting price", "forecast": "Forecast", "actual": "Actual", "source_url": "Outcome source",
        })
        table["Forecast issued"] = table["Forecast issued"].map(beirut_time)
        st.dataframe(table[["Announcement date", "Forecast issued", "Method", "Starting price",
                            "Forecast", "Actual", "Outcome source"]],
                     hide_index=True, width="stretch", column_config={
                         "Outcome source": st.column_config.LinkColumn(display_text="Source record"),
                     })
