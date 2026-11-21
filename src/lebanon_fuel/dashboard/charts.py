"""Plot saved results and source records with their distinct dates and evidence."""
from datetime import date, timedelta
import json
import math

import pandas as pd
import plotly.graph_objects as go

from .data import forecast_bounds
from .experience import released_bounds

TEAL = "#20734F"
AMBER = "#8B5B17"
BLUE = "#515F83"
FOREST = "#123F2E"
SECTION = "#FFFFFF"
TEXT = "#18251E"
MUTED = "#53645B"
GRID = "#E1E9E3"
HAIRLINE = "#AFBEB4"
GLASS = "#EDF4EE"


def style(fig, y_title, height=410):
    fig.update_layout(
        template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=SECTION,
        height=height, margin=dict(l=16, r=16, t=36, b=36), yaxis_title=y_title,
        dragmode="pan",
        font=dict(family="Inter, system-ui, sans-serif", color=TEXT, size=12),
        legend=dict(orientation="h", y=1.04, x=0, yanchor="bottom",
                    font=dict(size=12, color=MUTED), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=GLASS, bordercolor=TEAL, font=dict(color=TEXT, size=12)),
        modebar=dict(color=MUTED, activecolor=FOREST),
        colorway=[TEAL, BLUE, AMBER, "#AD4537"],
        hovermode="x unified",
    )
    fig.update_xaxes(
        automargin=True, zerolinecolor=HAIRLINE, gridcolor=GRID,
        tickfont=dict(color=MUTED, size=12),
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikecolor=TEAL, spikethickness=1.5, spikedash="dot",
    )
    fig.update_yaxes(
        automargin=True, zerolinecolor=HAIRLINE, gridcolor=GRID, separatethousands=True,
        tickfont=dict(color=MUTED, size=12),
        title_font=dict(size=12, color=MUTED),
    )
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
    points["plot_date"] = points.endpoint.astype(object).where(points.endpoint.notna(), points.scheduled_effective.astype(object)).map(target_date)
    if replay:
        points["plot_date"] = points.plot_date.fillna(points.recorded_target_date.map(target_date))
    return points.dropna(subset=["plot_date", "predicted_price"]).sort_values("plot_date", kind="stable")


def add_forecast_markers(fig, points, label, color, symbol):
    upper, lower = [], []
    for row in points.to_dict("records"):
        bounds = released_bounds(row, 90)
        upper.append(bounds[1] - row["predicted_price"] if bounds else None)
        lower.append(row["predicted_price"] - bounds[0] if bounds else None)
    error = {}
    if any(value is not None for value in upper):
        error = dict(error_y=dict(type="data", symmetric=False, array=upper,
                                  arrayminus=lower, color=color, visible=True))
    fig.add_scatter(
        x=points.plot_date, y=points.predicted_price, mode="markers", name=label,
        marker=dict(symbol=symbol, color=color, size=9,
                    line=dict(color=color if symbol.endswith('-open') else SECTION, width=1.5)), customdata=[[r["origin"],
                        f'{released_bounds(r,90)[0]:,.0f}–{released_bounds(r,90)[1]:,.0f} LBP / 20 L' if released_bounds(r,90) else 'Not released'] for r in points.to_dict("records")],
        hovertemplate="%{x|%d %b %Y}<br>Estimate %{y:,.0f} LBP / 20 L<br>90% range: %{customdata[1]}<br>Issued %{customdata[0]}<extra></extra>",
        **error,
    )


def conformal_bounds(row, level):
    return released_bounds(row, level)


def add_conformal_cone(fig, points, *, single=False):
    """Connect only contiguous released endpoints with identical issuance identity."""
    if points.empty or 'target_json' not in points:
        return
    points=points.copy()
    specs=points.target_json.map(json.loads)
    points['_family']=specs.map(lambda s:s.get('family'))
    points['_artifact']=specs.map(lambda s:s.get('artifact_sha256'))
    points['_kind']=points.horizon.str.split('_').str[0] if 'horizon' in points else 'unknown'
    keys=['origin','base_price','_family','_artifact','_kind']
    # Without an immutable run and snapshot identity, endpoints stay isolated.
    for key in ('run_id','snapshot_id','model_version'):
        if key not in points:points[key]=None
        keys.append(key)
    for _,group in points.groupby(keys,dropna=False,sort=False):
        rows=group.sort_values('plot_date').drop_duplicates('plot_date').to_dict('records')
        for level,color in [(90,'rgba(81,95,131,.14)'),(80,'rgba(81,95,131,.24)')]:
            runs=[];run=[];last_index=None
            for r in rows:
                order=['decision_1','decision_2','decision_4'] if r['_kind']=='decision' else ['day_1','day_3','day_7','day_14','day_30']
                idx=order.index(r['horizon']) if r.get('horizon') in order else None
                valid=conformal_bounds(r,level)
                identity=all(pd.notna(r.get(k)) for k in ('run_id','snapshot_id','model_version','_artifact'))
                if run and (not valid or not identity or idx is None or idx!=last_index+1):
                    runs.append(run);run=[]
                if valid:
                    run.append(r);last_index=idx
                    if not identity:runs.append(run);run=[]
            if run:runs.append(run)
            for run in runs:
                bounds=[conformal_bounds(r,level) for r in run]
                if len(run)==1:
                    # Outer whisker comes from the point trace; inner interval is
                    # a second error bar, never an artificial cone to the anchor.
                    if level==80:
                        r=run[0];lo,hi=bounds[0]
                        fig.add_scatter(x=[r['plot_date']],y=[r['predicted_price']],mode='markers',marker=dict(size=1,color=TEAL),
                            error_y=dict(type='data',symmetric=False,array=[hi-r['predicted_price']],arrayminus=[r['predicted_price']-lo],color=TEAL,thickness=4),
                            name='80% calibrated pointwise interval',customdata=[[lo,hi]],hovertemplate='%{x|%d %b %Y}<br>80% range %{customdata[0]:,.0f}–%{customdata[1]:,.0f} LBP / 20 L<extra></extra>')
                    continue
                x=[r['plot_date'] for r in run];lo=[b[0] for b in bounds];hi=[b[1] for b in bounds]
                hover=[[r['predicted_price'],l,h] for r,l,h in zip(run,lo,hi)]
                fig.add_scatter(x=x,y=lo,mode='lines',line=dict(width=0),showlegend=False,hoverinfo='skip')
                fig.add_scatter(x=x,y=hi,mode='lines',line=dict(width=0),fill='tonexty',fillcolor=color,
                    name=f'{level}% calibrated pointwise prediction band',customdata=hover,
                    hovertemplate=f'%{{x|%d %b %Y}}<br>Estimate %{{customdata[0]:,.0f}} LBP / 20 L<br>{level}% range %{{customdata[1]:,.0f}}–%{{customdata[2]:,.0f}}<extra></extra>')
        # Forecasts remain markers; ribbons interpolate bounds only between
        # supported endpoints, not an asserted realized price path.


def history_chart(prices, replay, current, *, compact=False):
    fig = go.Figure()
    if not current.empty and replay.empty:
        start = (pd.to_datetime(current.origin, utc=True).min() - pd.Timedelta(days=90)).date().isoformat()
        prices=[r for r in prices if r['source_date']>=start]
    priority = {"supplier_observed": 0, "government_archive": 1, "archive_corroborated": 2, "document_verified": 3}
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
                        fillcolor="rgba(87,166,121,.16)",
                        hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=x, y=y, mode="lines", line_shape="hv",
                        line=dict(color=FOREST, width=2.5),
                        hoverinfo="skip", showlegend=False)
    for status, label, color, symbol in [
        ("archive_corroborated", "Corroborated archive", TEAL, "circle"),
        ("document_verified", "Reviewed decree", FOREST, "diamond"),
        ("government_archive", "Archive only", MUTED, "circle-open"),
        ("provisional_corroborated", "Matching supplier quotes", TEAL, "circle-open"),
        ("supplier_observed", "Supplier / news schedule", BLUE, "circle-open"),
    ]:
        rows = [r for r in prices if r["verification_status"] == status
                and r["price_lbp_20l"] is not None]
        if compact and not rows:
            continue
        fig.add_scatter(x=[r["source_date"] for r in rows],
                        y=[r["price_lbp_20l"] for r in rows], mode="markers", name=label,
                        marker=dict(color=color, symbol=symbol, size=7,
                                    line=dict(color=SECTION, width=1)),
                        customdata=[r.get("official_effective_date") or "Not documented" for r in rows],
                        hovertemplate="%{x}<br>%{y:,.0f} LBP / 20 L<br>Effective date: %{customdata}")
    historical = forecast_points(replay, replay=True)
    if not historical.empty:
        add_forecast_markers(fig, historical, "Saved research prediction", AMBER, "diamond-open")
    points = forecast_points(current)
    add_conformal_cone(fig, points)
    if not points.empty:
        # Separate target types and evidence tiers. These independent point
        # estimates have no interpolated path or joint uncertainty band.
        points["target_kind"] = points.endpoint.notna().map({True: "Calendar", False: "Decision"})
        for (label, kind), group in points.groupby(["forecast_label", "target_kind"], sort=False):
            symbol = "diamond-open" if kind == "Decision" else "square-open"
            marker_label = ("Next estimate" if kind == "Decision" else "Calendar estimate") if compact else f"{label} · {kind}"
            add_forecast_markers(fig, group, marker_label, BLUE, symbol)
    buttons = [dict(count=1, label="1M", step="month", stepmode="backward"),
               dict(count=3, label="3M", step="month", stepmode="backward"),
               dict(step="all", label="All")]
    if not current.empty and replay.empty:
        buttons[-1]["label"] = "Reset"
    if not compact:
        buttons.insert(0, dict(count=7, label="1W", step="day", stepmode="backward"))
        buttons.insert(-1, dict(count=1, label="1Y", step="year", stepmode="backward"))
    fig.update_xaxes(type="date", rangeselector=dict(
        x=0, y=1.015, bgcolor=GLASS, activecolor="#BFE0CC", bordercolor=HAIRLINE, borderwidth=1,
        font=dict(color=TEXT, size=12), buttons=buttons))
    if not points.empty and replay.empty:
        origin = pd.to_datetime(points.origin, utc=True).min().tz_convert("Asia/Beirut").tz_localize(None)
        fig.update_xaxes(range=[origin - pd.Timedelta(days=90), points.plot_date.max() + pd.Timedelta(days=3)])
    fig = style(fig, "LBP / 20 L", 365 if compact else 440)
    if compact:
        fig.update_xaxes(nticks=5)
        fig.update_yaxes(nticks=5)
    fig.update_layout(legend=dict(orientation="h", y=-.2, x=0, yanchor="top",
                                  font=dict(size=12, color=MUTED), bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=16, r=16, t=60 if compact else 74, b=82 if compact else 92))
    return fig


def paired_chart(rows):
    fig = go.Figure()
    for field, label, color, symbol in [
        ("actual_price", "Matched recorded price", TEAL, "circle"),
        ("predicted_price", "Saved research prediction", AMBER, "diamond-open"),
    ]:
        fig.add_scatter(x=rows.origin, y=rows[field], mode="markers", name=label,
                        marker=dict(color=color, symbol=symbol, size=7.5),
                        customdata=rows.recorded_target_date,
                        hovertemplate="%{x}<br>%{y:,.0f} LBP / 20 L<br>Target record: %{customdata}")
    fig.update_xaxes(title="Forecast origin")
    return style(fig, "LBP / 20 L")


def decision_chart(row):
    points = forecast_points(pd.DataFrame([row]))
    fig = go.Figure()
    if not points.empty:
        add_conformal_cone(fig, points, single=True)
        fig.add_scatter(x=[target_date(row.origin)], y=[row.base_price], mode='markers',
                        name='Known price at forecast origin', marker=dict(color=AMBER))
        add_forecast_markers(fig, points, row.forecast_label, TEAL, 'diamond-open')
    else:
        fig.add_bar(x=['Known price', 'Next decision · date unconfirmed'],
                    y=[row.base_price,row.predicted_price],name=row.forecast_label)
    if isinstance(row.get('scheduled_effective'),str) and len(row['scheduled_effective'])==10:
        # A projected source date has no announcement clock. Do not let Plotly
        # turn its midnight plotting coordinate into an apparent update time.
        dates=[target_date(row.origin),target_date(row.scheduled_effective)]
        fig.update_xaxes(tickmode='array',tickvals=dates,
            ticktext=[dates[0].strftime('%d %b')+' · issued',dates[1].strftime('%d %b')+' · estimated date'],hoverformat='%d %b %Y')
    return style(fig, 'LBP / 20 L', 340)


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
                        line=dict(color=AMBER, width=2.4, shape='spline', smoothing=0.8),
                        fill='tonexty' if len(numeric) >= 2 else None,
                        fillcolor='rgba(87,166,121,.16)',
                        marker=dict(size=5.5, color=TEAL, line=dict(color=SECTION, width=1)),
                        name='Cboe OVX close',
                        customdata=[row.get('source_url', '') for row in rows],
                        hovertemplate='%{x}<br>%{y:.2f}% annualized<br>%{customdata}<extra></extra>')
        closes = pd.to_numeric(pd.Series([row['value'] for row in history[-252:]]), errors='coerce').dropna()
        if len(closes) == 252:
            colors = {25: TEAL, 75: AMBER, 90: '#A62D32'}
            names = {25: 'p25 · Low / Normal', 75: 'p75 · Elevated', 90: 'p90 · Stress'}
            for percentile in (25, 75, 90):
                level = float(closes.quantile(percentile / 100))
                fig.add_hline(y=level, line_dash='dash', line_width=1,
                              line_color=colors[percentile],
                              annotation_text=f"{names[percentile]} · {level:.1f}%",
                              annotation_position='top right',
                              annotation_font=dict(color=colors[percentile], size=12))
    return style(fig, 'OVX · annualized %', 360)
