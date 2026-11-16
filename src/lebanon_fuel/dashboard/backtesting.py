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


def render(rows, families, regimes, show_chart):
    if not COLUMNS.issubset(rows.columns):
        st.info("The saved walk-forward prediction report is unavailable.")
        return

    rows = rows.copy()
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

    st.caption("Saved walk-forward research compared with matched archive prices. Sparse records and "
               "unverified official timing limit what this backtest can establish.")
    a, b, c = st.columns(3)
    horizon = a.selectbox("Forecast horizon", horizons, format_func=HORIZONS.get)
    rows = rows.loc[rows["horizon"].eq(horizon)]
    regime = b.selectbox("Evaluation period", sorted(rows["regime"].dropna().unique()),
                         format_func=lambda value: regimes.get(value, value))
    rows = rows.loc[rows["regime"].eq(regime)]
    available = sorted(rows["family"].dropna().unique())
    if not available:
        st.info("No saved model results are available for this selection.")
        return
    family = c.selectbox("Model", available, index=available.index("G_hybrid") if "G_hybrid" in available else 0,
                         format_func=lambda value: families.get(value, value))
    paired = rows.loc[rows["family"].eq(family)].sort_values(["target_date", "origin"])
    paired = paired.drop_duplicates(subset=["target_date", "origin", PREDICTED, OBSERVED])
    error = (paired[PREDICTED] - paired[OBSERVED]).abs()
    st.caption(f"{len(paired):,} paired forecasts across {paired['target_date'].nunique():,} target dates · "
               f"Average absolute error {error.mean():,.0f} LBP / 20 L.")
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
