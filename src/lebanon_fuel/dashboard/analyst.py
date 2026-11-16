"""Deterministic commentary grounded in the current database and validation tables."""
from .data import STATUS, forecast_view
from lebanon_fuel.market.catalog import SERIES


def brief(latest, previous, market, best, decision, forecast=None):
    executive = "A corroborated gasoline price is unavailable."
    if latest:
        executive = (f"The latest verified-tier gasoline 95 record is **{latest['price_lbp_20l']:,} LBP / 20 L** "
                     f"on {latest['source_date']} ({STATUS[latest['verification_status']].lower()}).")
        if previous:
            change = latest["price_lbp_20l"] - previous["price_lbp_20l"]
            executive += f" It is {change:+,} LBP versus the previous verified-tier record on {previous['source_date']}."
        if (latest.get("source_url") or "").startswith("https://"):
            executive += f" [Source record]({latest['source_url']})"
    conditions = []
    for sid, name in [("brent_futures", "Brent futures"), ("rbob_futures", "RBOB futures"), ("brent_spot", "Brent spot proxy"), ("nyh_gasoline", "New York Harbor gasoline proxy")]:
        row = market["series"].get(sid,{"status":"missing"})
        if row["status"] == "available":
            movement = row.get("return_7_calendar_days")
            change_text = f", {movement:+.2%} over the trailing seven-day comparison" if movement is not None else ""
            conditions.append(f"{name} last printed {row['value']:,.2f} USD/bbl on {row['latest_observation_date']}{change_text}. [Source]({SERIES[sid].url})")
        else:
            conditions.append(f"{name} has no fresh stored observation.")
    selected=decision.get('selection',{}).get('decision_1',{})
    measured=selected.get('performance')
    all_measured=selected.get('all_origin_performance')
    if measured:
        distinct = measured.get('distinct_base_decisions') or measured.get('unique_base_decisions')
        distinct_note = f" ({distinct} distinct base decisions)" if distinct is not None and distinct != measured.get('n') else ""
        if all_measured and (all_measured.get('n') != measured.get('n') or all_measured.get('mae') != measured.get('mae')):
            performance = (
                f"Selected {selected.get('family')} measured all-origin MAE {all_measured['mae']:,.0f} LBP / 20 L, "
                f"direction accuracy {all_measured['direction_accuracy']:.1%}, n={all_measured['n']} "
                f"(common-origin MAE {measured['mae']:,.0f} LBP / 20 L, n={measured['n']}{distinct_note}) on 2026 holdout origins. "
            )
        else:
            performance = (
                f"Selected {selected.get('family')} measured MAE {measured['mae']:,.0f} LBP / 20 L, "
                f"direction accuracy {measured['direction_accuracy']:.1%}, n={measured['n']}{distinct_note} on common 2026 holdout origins. "
            )
    else:
        performance = 'No current-horizon holdout performance established. '
    reasons=selected.get('reasons',[])
    movement='No current estimate tied to the verified price. Refresh the forecast ledger.'
    drivers='No saved contribution breakdown. Commodity context does not establish a causal price forecast.'
    if forecast is not None:
        view=forecast_view(forecast)
        movement=(f"{forecast.get('forecast_label','Saved estimate')}: {forecast['predicted_price']:,.0f} LBP / 20 L, "
                  f"{forecast['predicted_change']:+,.0f} LBP ({forecast['predicted_change']/forecast['base_price']:+.2%}). "
                  f"Estimated announcement: {view['schedule']}. ")
        if view['bounds']:movement+=f"90% pointwise interval: {view['bounds'][0]:,.0f}–{view['bounds'][1]:,.0f} LBP / 20 L. "
        else:movement+='A calibrated 90% interval is not supported for this issuance. '
        if view['probabilities']:
            down,flat,up=view['probabilities'];movement+=f"Increase {up:.1%}, decrease {down:.1%}, no change within ±3,000 LBP {flat:.1%}."
        else:movement+='Directional probabilities are awaiting calibrated live evidence.'
        if view['drivers']:drivers='; '.join(f"{r['Driver']}: {r['LBP / 20 L']:+,.0f} LBP" for r in view['drivers'])+'. Statistical attribution, not causation.'
    return {
        "Executive summary": executive,
        "Expected price movement": movement,
        "Primary market drivers": drivers+' '+' '.join(conditions),
        "Commodity market conditions": " ".join(conditions),
        "Domestic regulatory factors": "The current pricing formula and regulatory regime remain unresolved in the project evidence. The simulator uses a May 2025 cost scaffold and explicit tax and government-charge assumptions.",
        "Risks and uncertainty": (" ".join(reasons) + ". " if reasons else "") + "Sparse holdout outcomes, assumed historical availability and stale live inputs limit reliability.",
        "What could change the forecast": "A verified official decision with timing, current tax and FX treatment, or a licensed Mediterranean product series would improve the information set. An approved model would also require a fresh holdout and acceptable calibration.",
        "Historical model performance": performance + " Selection consumed this holdout; it is not an untouched final test. Market vintages remain revised.",
    }
