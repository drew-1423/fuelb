"""Show saved walk-forward forecasts against their matched archive outcomes."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lebanon_fuel.dashboard import charts
from lebanon_fuel.domain import BEIRUT

HORIZONS = {
    "decision_1": "Next recorded decision",
    "decision_2": "Second recorded decision",
    "decision_4": "Fourth recorded decision",
    **{f"day_{days}": f"{days} calendar day{'s' if days > 1 else ''}" for days in (1, 3, 7, 14, 30)},
}
PREDICTED = "predicted_endpoint_price_lbp_20l"
OBSERVED = "endpoint_price_lbp_20l"
COLUMNS = {"origin", "horizon", "family", "regime", "endpoint", "target_source_date", PREDICTED, OBSERVED}


def render(rows, families, regimes, show_chart, *, research_note=None, only_family=None):
    if not COLUMNS.issubset(rows.columns):
        st.info("The saved walk-forward prediction report is unavailable.")
        return

    rows = rows.loc[rows["family"].eq(only_family)].copy() if only_family else rows.copy()
    endpoints = pd.to_datetime(rows["endpoint"], utc=True, errors="coerce").dt.tz_convert(BEIRUT)
    source_dates = pd.to_datetime(rows["target_source_date"], format="%Y-%m-%d", errors="coerce")
    rows["target_date"] = endpoints.dt.tz_localize(None).dt.normalize().where(
        rows["horizon"].str.startswith("day_"), source_dates)
    prices = rows[[PREDICTED, OBSERVED]].apply(pd.to_numeric, errors="coerce")
    valid = prices.gt(0).all(axis=1) & prices.lt(float("inf")).all(axis=1)
    rows = rows.loc[valid & rows["target_date"].notna() & rows["origin"].notna()].copy()
    rows[[PREDICTED, OBSERVED]] = prices.loc[rows.index]
    horizons = [key for key in HORIZONS if key in set(rows["horizon"])]
    if not horizons:
        st.info("There are no saved forecasts with matched historical prices to plot.")
        return

    st.caption(research_note or "Saved walk-forward research compared with matched archive prices. Sparse records and "
               "unverified official timing limit what this backtest can establish.")
    columns = st.columns(2 if only_family else 3)
    a, b = columns[:2]
    horizon = a.selectbox("Forecast horizon", horizons, format_func=HORIZONS.get)
    rows = rows.loc[rows["horizon"].eq(horizon)]
    regime = b.selectbox("Evaluation period", sorted(rows["regime"].dropna().unique()),
                         format_func=lambda value: regimes.get(value, value))
    rows = rows.loc[rows["regime"].eq(regime)]
    available = sorted(rows["family"].dropna().unique())
    if not available:
        st.info("No saved model results are available for this selection.")
        return
    family = only_family
    if only_family:
        st.caption("Forecast model · Hybrid")
    else:
        family = columns[2].selectbox("Model", available, index=available.index("G_hybrid") if "G_hybrid" in available else 0,
                                      format_func=lambda value: families.get(value, value))
    paired = rows.loc[rows["family"].eq(family)].sort_values(["target_date", "origin"])
    paired = paired.drop_duplicates(subset=["target_date", "origin", PREDICTED, OBSERVED])
    error = (paired[PREDICTED] - paired[OBSERVED]).abs()
    percentage_error = (error / paired[OBSERVED]).mean()
    with st.container(horizontal=True):
        st.metric("Average absolute error", f"{error.mean():,.0f} LBP / 20 L", border=True)
        st.metric("Average percentage error", f"{percentage_error:.2%}", border=True,
                  help="Average of each absolute miss divided by its observed price. Lower is better.")
        st.metric("Paired forecasts", f"{len(paired):,}", border=True)
    st.caption(f"{paired['target_date'].nunique():,} target dates. Metrics apply to the selected model, horizon and period.")
    show_chart(comparison_chart(paired))
    st.caption("Each pair uses the same target date. Multiple forecasts can share a date. "
               "Calendar horizons use the saved endpoint; decision horizons use the matched archive date.")

    with st.expander("Paired forecast records"):
        table = paired.assign(error=paired[PREDICTED] - paired[OBSERVED])
        table = table[["target_date", "origin", OBSERVED, PREDICTED, "error"]].rename(columns={
            "target_date": "Target date", "origin": "Forecast origin", OBSERVED: "Observed price",
            PREDICTED: "Backtest forecast", "error": "Forecast minus observed",
        })
        table["Target date"] = table["Target date"].dt.strftime("%d %b %Y")
        st.dataframe(table, hide_index=True, width="stretch")


def comparison_chart(paired):
    fig = go.Figure()
    for column, name, color, symbol, size in (
        (OBSERVED, "Observed archive price", charts.TEAL, "circle", 8),
        (PREDICTED, "Backtest forecast", charts.AMBER, "diamond-open", 13),
    ):
        fig.add_scatter(
            x=paired["target_date"], y=paired[column], mode="markers", name=name,
            marker=dict(color=color, size=size, symbol=symbol, line=dict(width=2)),
            customdata=paired["origin"],
            hovertemplate="%{y:,.0f} LBP / 20 L<br>Forecast origin: %{customdata}",
        )
    fig.update_xaxes(title="Target date · Beirut", tickformat="%d %b %Y", hoverformat="%d %b %Y")
    return charts.style(fig, "LBP / 20 L")

def next_update_comparison(rows):
    """Compare three methods on identical saved origins, base prices and realized targets."""
    methods = {"G_hybrid": "Hybrid", "A_no_change": "No price change", "Z_last_change": "Repeat last change"}
    keys = ["origin", "base_price_lbp_20l", "target_source_date", "target_revision_id", OBSERVED,
            "target_change_lbp_20l"]
    required = {*keys, "regime", "horizon", "family", PREDICTED, "prediction"}
    if not required.issubset(rows.columns):
        return 0, 0, pd.DataFrame()
    target = rows.loc[rows["horizon"].eq("decision_1") & rows["regime"].eq("stabilized_fx_2023_2026")]
    target = target.dropna(subset=keys + [PREDICTED, "prediction"])
    matched_dates = target["target_source_date"].nunique()
    target = target.loc[target["family"].isin(methods)].drop_duplicates(
        subset=keys + ["family", PREDICTED, "prediction"])
    # Ambiguous records never get resolved by choosing the better prediction.
    target = target.loc[~target.duplicated(keys + ["family"], keep=False)]
    shared = target.groupby(keys)["family"].transform("nunique").eq(len(methods))
    paired = target.loc[shared]
    if paired.empty:
        return matched_dates, 0, pd.DataFrame()

    from lebanon_fuel.forecasting.uncertainty import direction_class

    n = len(paired) // len(methods)
    result = []
    for family, label in methods.items():
        sample = paired.loc[paired["family"].eq(family)]
        hits = (direction_class(sample["prediction"]) == direction_class(sample["target_change_lbp_20l"])).sum()
        result.append({"Forecast method": label,
                       "Average miss · LBP / 20 L": int(round((sample[PREDICTED] - sample[OBSERVED]).abs().mean())),
                       "Direction calls right": f"{hits} of {n}"})
    return matched_dates, paired["target_source_date"].nunique(), pd.DataFrame(result)
