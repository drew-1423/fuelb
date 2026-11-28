"""Forecast review and research export for the saved Hybrid forecast."""
from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import streamlit as st

from lebanon_fuel.validation import review_journal
from .data import beirut_time, file_version
from .experience import permalink

HORIZONS = {"Next update": "decision_1", "Next two updates": "decision_2",
            "Next four updates": "decision_4", "1 day": "day_1", "3 days": "day_3",
            "7 days": "day_7", "14 days": "day_14", "30 days": "day_30"}
EVIDENCE = {"official_match": "Official record", "provisional_match": "Matching dated sources"}
STATUSES = {"pending": "Awaiting actual price", "expired": "Expired without a match",
            "disputed": "Disputed evidence", "coverage_gap": "Missing outcome evidence",
            "duplicate_target": "Outcome already counted"}
ATTRIBUTION_LABELS = {"commodity_pass_through": "Commodity pass-through",
                      "lagged_domestic_momentum": "Previous domestic price change",
                      "fiscal_shock": "Fiscal shock feature", "other_features": "Other features",
                      "baseline_intercept": "Model intercept"}
MARKET_LABELS = {"nyh_gasoline": "EIA New York Harbor gasoline proxy", "brent_spot": "EIA Brent spot",
                 "rbob_futures": "RBOB gasoline futures", "brent_futures": "Brent futures"}


@st.cache_data(ttl=60, max_entries=24, show_spinner=False)
def _journal(root, ledger, horizon, version):
    return review_journal.load(root, ledger, horizon, datetime.now(timezone.utc).isoformat())


def _packet(journal, label, notes):
    return dict(journal, horizon_label=label, analyst_notes=notes.strip(),
                research_brief=(
                    "Treat each test topic as a hypothesis. Compare private challengers with the frozen Hybrid "
                    "and both available baselines on the same chronological origins. Use only input vintages "
                    "available at issuance. Keep earlier cases separate from prospective metrics. Report paired "
                    "MAE, RMSE, signed bias, direction hits and sample size. Recommend model changes for human "
                    "review after an untouched forward evaluation."
                ))


def _prices(cases):
    table = pd.DataFrame([{
        "Recorded date": case["recorded_date"], "Forecast": case["forecast"],
        "Actual": case["actual"], "Error": case["signed_error"],
        "Evidence": EVIDENCE[case["evidence"]],
    } for case in cases])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        name: st.column_config.NumberColumn(format="localized") for name in ("Forecast", "Actual", "Error")
    })


def _case(case):
    st.markdown(f'**Starting price** {case["base_price"]:,.0f} LBP · **Forecast move** '
                f'{case["forecast_change"]:+,.0f} LBP · **Actual move** {case["actual_change"]:+,.0f} LBP')
    st.caption(f'Issued {beirut_time(case["issued_at"])} · Outcome known {beirut_time(case["outcome_known_at"])}')
    if "Move size" in case["test_topics"]:
        missed = "smaller" if abs(case["forecast_change"]) < abs(case["actual_change"]) else "larger"
        st.write(f"The direction was right. The forecast move was {missed} than the actual move.")
    elif "Directional miss" in case["test_topics"]:
        st.write("The forecast and actual price moved in different direction categories.")
    if case["days_from_projection"]:
        days = case["days_from_projection"]
        st.write(f'The price was recorded {abs(days)} day{"s" if abs(days) != 1 else ""} '
                 f'{"after" if days > 0 else "before"} the projected date of {case["expected_date"]}.')
    if case["baselines"]:
        errors = " · ".join(f'{name} {values["absolute_error"]:,.0f} LBP'
                            for name, values in case["baselines"].items())
        st.write(f'**Absolute error** Hybrid {case["absolute_error"]:,.0f} LBP · {errors}')
    if case["attribution"]:
        drivers = " · ".join(f'{ATTRIBUTION_LABELS[key]} {value:+,.0f} LBP'
                             for key, value in case["attribution"].items() if value)
        if drivers:
            st.write(f'**Saved forecast contributions** {drivers}')
    if case["market"]:
        inputs = " · ".join(f'{MARKET_LABELS[item["series"]]} {item["date"]}' for item in case["market"])
        st.write(f'**Market observation dates at issuance** {inputs}')
    if case["test_topics"]:
        st.markdown("**What to test**")
        for topic in case["test_topics"]:
            st.write(review_journal.TESTS[topic])
    st.markdown(f'[Open saved forecast]({permalink(case["record_hash"])}) · Forecast ID {case["forecast_id"]}')


def _case_details(cases, key):
    by_id = {case["forecast_id"]: case for case in cases}
    latest = sorted(by_id, key=lambda fid: (by_id[fid]["recorded_date"], fid), reverse=True)
    choice = st.selectbox("Review a matched update", latest, format_func=lambda fid: (
        f'{by_id[fid]["recorded_date"]} · {by_id[fid]["signed_error"]:+,.0f} LBP error'
    ), key=key)
    _case(by_id[choice])


def render(root, ledger):
    st.title("Forecast Review")
    st.caption("Compare saved estimates with actual prices and collect ideas for the next manual model review.")
    label = st.selectbox("Forecast horizon", list(HORIZONS), key="forecast_review_horizon")
    horizon = HORIZONS[label]
    try:
        journal = _journal(root, ledger, horizon, file_version(ledger))
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.warning("The forecast journal could not load. Reload after the published snapshot is available.")
        return

    matched = journal["current_matches"]
    pending = journal["counts"].get("pending", 0)
    with st.container(border=True):
        st.markdown("**Evidence for the next model review**")
        st.write(f'{matched} of {journal["review_checkpoint"]} matched outcomes for the latest selected model version.')
        st.progress(min(1.0, matched / journal["review_checkpoint"]))
        st.caption("Use 30 outcomes as a review checkpoint. Any model change requires separate validation and approval.")
        if matched:
            st.write(f'Mean absolute error **{journal["mae"]:,.0f} LBP** · '
                     f'RMSE **{journal["rmse"]:,.0f} LBP** · Mean error **{journal["mean_error"]:+,.0f} LBP** · '
                     f'Direction **{journal["direction_hits"]} of {matched}**')
        elif pending:
            st.info(f'{pending} selected forecast{"s" if pending != 1 else ""} awaiting an actual price.')
        else:
            st.info("A qualifying forecast and a matched price will start this journal.")

    st.subheader("Predicted vs actual")
    st.caption("LBP per 20 L. Error is forecast minus actual. A positive error means the forecast was too high.")
    cases = sorted(journal["cases"], key=lambda case: case["recorded_date"], reverse=True)
    if cases:
        _prices(cases)
        _case_details(cases, f"review_case_{horizon}")
    unmatched = [case for case in journal["selections"] if case["status"] in STATUSES]
    if unmatched:
        with st.expander("Pending and unscored forecasts"):
            st.dataframe([{"Expected date": case["expected_date"], "Forecast": round(case["forecast"]),
                           "Status": STATUSES[case["status"]], "Forecast ID": case["forecast_id"]}
                          for case in reversed(unmatched)], hide_index=True, width="stretch")

    st.subheader("Ideas to test")
    if journal["hypotheses"]:
        for idea in journal["hypotheses"]:
            st.markdown(f'**{idea["topic"]}** · flagged in {idea["cases"]} of {idea["sample"]} matched outcomes')
            st.write(idea["test"])
    else:
        st.caption("Test ideas appear when a matched outcome flags a pattern worth checking.")
    st.caption("The flags are research leads. Saved model contributions describe how the forecast was calculated.")

    if journal["earlier_cases"]:
        with st.expander("Earlier matched forecasts"):
            st.caption("These matches used the earlier scoring rules and sit outside the review checkpoint.")
            earlier = sorted(journal["earlier_cases"], key=lambda case: case["recorded_date"], reverse=True)
            _prices(earlier)
            _case_details(earlier, f"review_earlier_{horizon}")

    with st.expander("Export for model review"):
        st.caption("Download the matched outcomes, source evidence and test ideas for the next research session. "
                   "Personal notes are session-only. Download a copy to keep them.")
        saved = st.session_state.get("review_private_notes", "")
        with st.form("review_note_form"):
            notes = st.text_area("Personal research notes", value=saved, max_chars=4000)
            if st.form_submit_button("Add notes to packet"):
                st.session_state["review_private_notes"] = saved = notes
                st.success("Notes added to this session’s research packet.")
        st.download_button("Download research packet", json.dumps(_packet(journal, label, saved), indent=2),
                           f"fuel-forecast-review-{horizon}.json", "application/json", on_click="ignore")
