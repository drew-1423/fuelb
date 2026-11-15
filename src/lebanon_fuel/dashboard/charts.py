"""Plot saved results and source records with their distinct dates and evidence."""
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go

from .data import forecast_bounds

# Dashdark X Exact Sampled Chart Palette
TEAL = "#00C2FF"
AMBER = "#CB3CFF"
BLUE = "#0E43FB"
SECTION = "#0B1739"
TEXT = "#FFFFFF"
MUTED = "#AEB9E1"
GRID = "#1A254B"
HAIRLINE = "#1E294A"
GLASS = "#081028"


def style(fig, y_title, height=410):
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=SECTION,
        height=height, margin=dict(l=20, r=20, t=30, b=30), yaxis_title=y_title,
        font=dict(family="Inter, system-ui, sans-serif", color=TEXT),
        legend=dict(orientation="h", y=1.04, x=0, yanchor="bottom",
                    font=dict(size=11, color=MUTED), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=GLASS, bordercolor="#343B4F", font=dict(color=TEXT, size=12)),
        hovermode="closest",
    )
    fig.update_xaxes(automargin=True, zerolinecolor=HAIRLINE, gridcolor="rgba(26,37,75,0.45)",
                     tickfont=dict(color=MUTED, size=11))
    fig.update_yaxes(automargin=True, zerolinecolor=HAIRLINE, gridcolor=GRID, separatethousands=True,
                     tickfont=dict(color=MUTED, size=11))
    return fig


def target_date(value):
    if isinstance(value, str) and len(value) == 10:
        # Projected decision dates have no verified time of day.
        try:
            return pd.Timestamp(date.fromisoformat(value))
        except ValueError:
            return pd.NaT
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return pd.NaT
    return stamp.tz_convert("Asia/Beirut").tz_localize(None)


def forecast_points(rows, *, replay=False):
    if rows.empty:
        return rows
    # Assign positional indices before date sorting. Concatenated horizon frames
    # may each have index 0, and label-based indexing would expand those rows.
    points = rows.reset_index(drop=True).copy()
    if "id" in points:
        points = points.drop_duplicates(subset="id")
    points["plot_date"] = points.endpoint.fillna(points.scheduled_effective).map(target_date)
    if replay:
        points["plot_date"] = points.plot_date.fillna(points.recorded_target_date.map(target_date))
    return points.dropna(subset=["plot_date", "predicted_price"]).sort_values("plot_date", kind="stable")


def add_forecast_markers(fig, points, label, color, symbol):
    upper, lower = [], []
    for row in points.to_dict("records"):
        bounds = forecast_bounds(row, tier=row.get("forecast_tier"))
        upper.append(bounds[1] - row["predicted_price"] if bounds else None)
        lower.append(row["predicted_price"] - bounds[0] if bounds else None)
    error = {}
    if any(value is not None for value in upper):
        error = dict(error_y=dict(type="data", symmetric=False, array=upper,
                                  arrayminus=lower, color=color, visible=True))
    fig.add_scatter(
        x=points.plot_date, y=points.predicted_price, mode="markers", name=label,
        marker=dict(symbol=symbol, color=color, size=9,
                    line=dict(color=SECTION, width=1.5)), customdata=points.origin,
        hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} LBP / 20 L<br>Origin: %{customdata}",
        **error,
    )


def history_chart(prices, replay, current):
    fig = go.Figure()
    if not current.empty and replay.empty:
        start = (pd.to_datetime(current.origin, utc=True).min() - pd.Timedelta(days=90)).date().isoformat()
        prices=[r for r in prices if r['source_date']>=start]
    priority = {"government_archive": 1, "archive_corroborated": 2, "document_verified": 3}
    observed = [r for r in prices if r.get("verification_status") in priority
                and r.get("price_lbp_20l") is not None]
    # A step line carries the last observed pump price forward without implying
    # a smooth move between decisions. Markers below remain the original records.
    by_date = {}
    for row in observed:
        day = row["source_date"]
        if day not in by_date or priority[row["verification_status"]] > priority[by_date[day]["verification_status"]]:
            by_date[day] = row
    timeline = [by_date[day] for day in sorted(by_date)]
    if len(timeline) >= 2:
        x = [row["source_date"] for row in timeline]
        y = [row["price_lbp_20l"] for row in timeline]
        spread = max(y) - min(y)
        base = min(y) - max(spread * .08, min(y) * .01)
        fig.add_scatter(x=x, y=[base] * len(x), mode="lines",
                        line=dict(width=0, color="rgba(0,0,0,0)"),
                        hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=x, y=y, mode="lines", line=dict(width=0),
                        line_shape="hv", fill="tonexty",
                        fillcolor="rgba(203,60,255,.14)",
                        hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=x, y=y, mode="lines", line_shape="hv",
                        line=dict(color=AMBER, width=2.4),
                        hoverinfo="skip", showlegend=False)
    for status, label, color, symbol in [
        ("archive_corroborated", "Corroborated government archive", TEAL, "circle"),
        ("document_verified", "Original decision reviewed", AMBER, "diamond"),
        ("government_archive", "Government archive only", MUTED, "circle-open"),
    ]:
        rows = [r for r in prices if r["verification_status"] == status
                and r["price_lbp_20l"] is not None]
        fig.add_scatter(x=[r["source_date"] for r in rows],
                        y=[r["price_lbp_20l"] for r in rows], mode="markers", name=label,
                        marker=dict(color=color, symbol=symbol, size=6.5,
                                    line=dict(color=SECTION, width=1)),
                        customdata=[r.get("official_effective_date") or "Not documented" for r in rows],
                        hovertemplate="%{x}<br>%{y:,.0f} LBP / 20 L<br>Effective date: %{customdata}")
    historical = forecast_points(replay, replay=True)
    if not historical.empty:
        add_forecast_markers(fig, historical, "Saved research prediction", AMBER, "diamond-open")
    points = forecast_points(current)
    if not points.empty:
        # Separate target types and evidence tiers. These independent point
        # estimates have no interpolated path or joint uncertainty band.
        points["target_kind"] = points.endpoint.notna().map({True: "Calendar", False: "Decision"})
        for (label, kind), group in points.groupby(["forecast_label", "target_kind"], sort=False):
            symbol = "diamond-open" if kind == "Decision" else "square-open"
            add_forecast_markers(fig, group, f"{label} · {kind}", TEAL, symbol)
    fig.update_xaxes(type="date", rangeselector=dict(
        x=0, y=1.06, bgcolor=GLASS, activecolor="#131F47", font=dict(color="#FFFFFF"),
        buttons=[dict(count=3, label="3M", step="month", stepmode="backward"),
                 dict(count=1, label="1Y", step="year", stepmode="backward"),
                 dict(count=5, label="5Y", step="year", stepmode="backward"),
                 dict(step="all", label="All")]))
    if not points.empty and replay.empty:
        origin = pd.to_datetime(points.origin, utc=True).min().tz_convert("Asia/Beirut").tz_localize(None)
        fig.update_xaxes(range=[origin - pd.Timedelta(days=90), points.plot_date.max() + pd.Timedelta(days=3)])
    fig = style(fig, "LBP / 20 L", 440)
    fig.update_layout(legend=dict(orientation="h", y=-.2, x=0, yanchor="top",
                                  font=dict(size=11, color=MUTED), bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=20, r=20, t=48, b=92))
    return fig


def paired_chart(rows):
    fig = go.Figure()
    for field, label, color, symbol in [
        ("actual_price", "Matched recorded price", TEAL, "circle"),
        ("predicted_price", "Saved research prediction", AMBER, "diamond-open"),
    ]:
        fig.add_scatter(x=rows.origin, y=rows[field], mode="markers", name=label,
                        marker=dict(color=color, symbol=symbol, size=7),
                        customdata=rows.recorded_target_date,
                        hovertemplate="%{x}<br>%{y:,.0f} LBP / 20 L<br>Target record: %{customdata}")
    fig.update_xaxes(title="Forecast origin")
    return style(fig, "LBP / 20 L")


def decision_chart(row):
    fig = go.Figure(go.Bar(x=['Latest verified record', 'Next official decision'],
                           y=[row.base_price, row.predicted_price],
                           marker_color=[TEAL, AMBER], text=[f'{row.base_price:,.0f}', f'{row.predicted_price:,.0f}'],
                           textposition='auto', name=row.forecast_label))
    return style(fig, 'LBP / 20 L', 280)


def reliability_chart(rows):
    fig = go.Figure()
    fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration",
                    line=dict(color=MUTED, dash="dot"))
    for event, group in rows.groupby("event"):
        fig.add_scatter(x=group.mean_predicted, y=group.observed_frequency, mode="markers",
                        name=event.replace("_", " ").title(), customdata=group.n,
                        hovertemplate="Predicted %{x:.1%}<br>Observed %{y:.1%}<br>n=%{customdata}")
    fig.update_xaxes(title="Mean predicted probability", range=[0, 1], tickformat=".0%")
    fig.update_yaxes(range=[0, 1], tickformat=".0%")
    return style(fig, "Observed frequency", 340)


def probability_chart(probabilities):
    fig=go.Figure(go.Bar(x=['Decrease','No change (±3,000 LBP)','Increase'],y=probabilities,
                        marker_color=[TEAL,AMBER,BLUE],text=[f'{p:.1%}' for p in probabilities],textposition='auto'))
    fig.update_yaxes(range=[0,1],tickformat='.0%')
    return style(fig,'Directional probability',240)


def driver_chart(drivers):
    fig=go.Figure(go.Waterfall(x=[r['Driver'] for r in drivers]+['Predicted change'],
        y=[r['LBP / 20 L'] for r in drivers]+[0],measure=['relative']*len(drivers)+['total'],
        connector={'line':{'color':MUTED}},totals={'marker':{'color':TEAL}}))
    return style(fig,'Contribution · LBP / 20 L',290)


def ovx_history_chart(history):
    """Observed OVX closes with trailing one-year regime thresholds."""
    fig = go.Figure()
    if history:
        latest = date.fromisoformat(history[-1]['observation_date'])
        cutoff = latest - timedelta(days=180)
        rows = [row for row in history if date.fromisoformat(row['observation_date']) >= cutoff]
        x = [row['observation_date'] for row in rows]
        y = [row['value'] for row in rows]
        numeric = pd.to_numeric(pd.Series(y), errors='coerce').dropna()
        if len(numeric) >= 2:
            base = float(numeric.min() - max((numeric.max() - numeric.min()) * .08,
                                             abs(numeric.min()) * .01))
            fig.add_scatter(x=x, y=[base] * len(x), mode='lines',
                            line=dict(width=0, color='rgba(0,0,0,0)'),
                            hoverinfo='skip', showlegend=False)
        fig.add_scatter(x=x,
                        y=y, mode='lines+markers',
                        line=dict(color=AMBER, width=2.2, shape='spline', smoothing=0.8),
                        fill='tonexty' if len(numeric) >= 2 else None,
                        fillcolor='rgba(203,60,255,.14)',
                        marker=dict(size=5, color='#D864FF', line=dict(color=SECTION, width=1)),
                        name='Cboe OVX close',
                        customdata=[row.get('source_url', '') for row in rows],
                        hovertemplate='%{x}<br>%{y:.2f}% annualized<br>%{customdata}<extra></extra>')
        closes = pd.to_numeric(pd.Series([row['value'] for row in history[-252:]]), errors='coerce').dropna()
        if len(closes) == 252:
            colors = {25: '#00C2FF', 75: '#CB3CFF', 90: '#FF5A65'}
            names = {25: 'p25 · Low / Normal', 75: 'p75 · Elevated', 90: 'p90 · Stress'}
            for percentile in (25, 75, 90):
                level = float(closes.quantile(percentile / 100))
                fig.add_hline(y=level, line_dash='dash', line_width=1,
                              line_color=colors[percentile],
                              annotation_text=f"{names[percentile]} · {level:.1f}%",
                              annotation_position='top right',
                              annotation_font=dict(color=colors[percentile], size=11))
    fig = style(fig, 'OVX · annualized %', 360)
    if history and len(history) >= 252:
        fig.update_layout(margin=dict(l=20, r=150, t=30, b=30))
    return fig
