"""Read-only presentation contracts; no fitting, issuance or financial pricing model."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
import sqlite3

import pandas as pd

from lebanon_fuel.domain import BEIRUT, VERIFIED, PROVISIONAL_PRICE
from lebanon_fuel.storage.database import sqlite_connection
from . import data

PERSPECTIVES = {
    '🚗 Driver Pulse': {'Overview': 'Pump Pulse & Overview', 'Scenario simulator': 'What-If Fuel Calculator', 'Alerts': 'Alert center'},
    '📊 Market & Intelligence': {'Price & forecasts': 'Price & Forecast Trajectory', 'Global markets': 'Global Energy Markets', 'Analyst report': 'Analyst Briefing'},
    '🔬 Quantitative & Governance': {'Model performance': 'Model Performance & Backtesting', 'Decision timeline': 'Decision Timeline & Ledgers', 'Volatility & options': 'Implied Volatility (OVX) & Options', 'Data quality': 'Data Quality & Gap Audit'},
}
SLUGS = dict(zip(['driver','calculator','alerts','trajectory','markets','briefing','performance','timeline','volatility','quality'],
                [v for views in PERSPECTIVES.values() for v in views]))


def destination(slug):
    view = SLUGS.get(slug, 'Overview')
    return next((p, view) for p, views in PERSPECTIVES.items() if view in views)


def clock(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('A timezone-aware timestamp is required')
    return stamp


def current_price(records, *, at=None, maximum_age_days=10):
    """Never step backwards over a newer conflict or uncorroborated quote."""
    if not records:
        return None, 'No dated price is stored. Check the posted station price.'
    row = max(records, key=lambda r:r['source_date'])
    price = row.get('price_lbp_20l')
    if row.get('verification_status') not in VERIFIED | {PROVISIONAL_PRICE} or not price or not math.isfinite(price) or price <= 0:
        return None, 'The newest price is disputed or needs a second source. An older quote is not substituted.'
    age = ((at or datetime.now(timezone.utc)).astimezone(BEIRUT).date()-datetime.fromisoformat(row['source_date']).date()).days
    if not 0 <= age <= maximum_age_days:
        return None, 'The newest corroborated record is stale or future-dated. Verify the posted price.'
    return dict(row, age_days=age), None


def freshness(row, settings, *, at=None):
    if row is None:
        return dict(status='Unavailable', expires=None, issued=None, message='No eligible current estimate. Check data and source evidence.')
    origin = clock(row['origin'])
    issued = clock(row.get('created_at',row['origin']))
    expires = origin + timedelta(hours=settings.get('forecasting',{}).get('maximum_forecast_age_hours',12))
    now = at or datetime.now(timezone.utc)
    valid = issued <= now < expires
    return dict(status='Within freshness window' if valid else 'Expired or not yet issued', expires=expires.isoformat(),
        issued=issued.isoformat(), message='Input or source gates can invalidate it earlier; this is not a guarantee of accuracy.')


def permalink(record_hash):
    if not isinstance(record_hash,str) or not re.fullmatch('[0-9a-f]{64}',record_hash):
        raise ValueError('A saved forecast hash is required')
    return 'https://fuelb95.streamlit.app/?forecast='+record_hash


def saved_forecast(path, record_hash):
    """Exact immutable row, never replaced by the newest run or current anchor."""
    permalink(record_hash)
    query = data.LEDGER_SELECT + " WHERE f.record_hash=? AND f.mode IN ('prospective','prospective_research') AND f.status='issued' AND f.predicted_price IS NOT NULL AND json_extract(m.metadata_json,'$.family')='G_hybrid'"
    with closing(sqlite_connection(path,readonly=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(query,(record_hash,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['record_hash'] = record_hash
        result['snapshot'] = json.loads(db.execute('SELECT payload_json FROM snapshots WHERE id=?',(row['snapshot_id'],)).fetchone()[0])
        return result


def availability(root,path):
    from lebanon_fuel.validation.decision_tracking import BATCH, FORECASTS, protocol_start
    with closing(sqlite_connection(path,readonly=True)) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute(BATCH+FORECASTS.replace("WHERE f.horizon='decision_1'","WHERE 1=1"),{'start':protocol_start(root)}).fetchall()
    result=[]
    for horizon in data.EXPECTED_HORIZONS:
        sample=[r for r in rows if r['horizon']==horizon]
        result.append({'Horizon':horizon,'Complete attempts':len(sample),
            'Hybrid estimates':sum(r['status']=='issued' and r['family']=='G_hybrid' for r in sample),
            'Abstentions':sum(r['status']=='abstained' for r in sample),
            'First attempt':min((r['origin'] for r in sample),default=None),'Last attempt':max((r['origin'] for r in sample),default=None)})
    return result


def released_bounds(row, level):
    """Original saved bounds only, with that exact level's Phase 1 release proof."""
    try:
        spec = json.loads(row.get('target_json') or '{}')
        proof = spec.get('public_calibration') or {}
        check = proof.get('levels',{}).get(str(level),{})
        if (spec.get('tier') not in (1,2) or proof.get('horizon') != row.get('horizon')
                or not spec.get('artifact_sha256') or proof.get('artifact') != spec['artifact_sha256']
                or check.get('status') != 'released' or check.get('nominal') != level/100
                or check.get('calibration_n',0) < proof.get('minimum_calibration_n',30)
                or check.get('evaluation_n',0) < proof.get('minimum_evaluation_n',20)):
            return None
        delta = [row.get('interval_low'),row.get('interval_high')] if level == 90 else spec.get('interval_80')
        if not isinstance(delta,(list,tuple)) or len(delta)!=2:
            return None
        base,point = float(row['base_price']),float(row['predicted_price'])
        low,high = [base+float(x) for x in delta]
        if not all(math.isfinite(v) for v in (base,point,low,high)) or not 0 < low <= point <= high or low == high:
            return None
        if level == 80:
            outer = released_bounds(row,90)
            if outer and not outer[0] <= low <= high <= outer[1]:
                return None
        return low,high
    except (ValueError,TypeError,KeyError):
        return None


def readiness(row):
    proof = json.loads(row.get('target_json') or '{}').get('public_calibration') or {} if row is not None else {}
    return dict(cases=int(proof.get('calibration_n',0)),tests=int(proof.get('evaluation_n',0)),
        minimum_cases=int(proof.get('minimum_calibration_n',30)),minimum_tests=int(proof.get('minimum_evaluation_n',20)),
        evidence=proof.get('evidence_category','No matched outcomes for this forecast artifact'),levels=proof.get('levels',{}))


def briefing(current, forecast, settings, *, at=None):
    lines=['⛽ LEBANON GASOLINE 95 OUTLOOK · Levant Energy Terminal']
    if current:
        values=data.currency_values(current['price_lbp_20l'])
        lines += [f"📍 Current recorded price: {values['lbp_20l']:,.0f} LBP (~${values['usd_20l']:.2f} / 20L)",
                  f"Source date: {current['source_date']} · {data.STATUS.get(current['verification_status'],'Under review')}"]
    if forecast is None:
        return '\n'.join(lines+['No eligible current forecast. Check the posted station price.','https://fuelb95.streamlit.app/?view=driver'])
    spec=json.loads(forecast['target_json']);change=float(forecast['predicted_change']);status=freshness(forecast,settings,at=at)
    view=data.forecast_view(pd.Series(forecast))
    lines += [f"⚡ Target: {view['schedule']} · estimated; announcement time unconfirmed",
        f"🔮 Estimated price: {forecast['predicted_price']:,.0f} LBP / 20L",
        f"Change: {change:+,.0f} LBP (~{'−' if change<0 else '+'}${abs(change)/data.DISPLAY_FX:.2f} USD; {change/forecast['base_price']:+.2%}) from {forecast['base_price']:,.0f} LBP",
        f"Issued: {data.beirut_time(status['issued'])}", f"Freshness: {status['status']} · expires {data.beirut_time(status['expires'])}",
        'Research estimate; production approval withheld.' if spec.get('tier')!=1 else 'Validated model; outcomes remain uncertain.',
        'No released prediction range for this forecast.' if not any(released_bounds(forecast,level) for level in (80,90)) else 'A released pointwise prediction range is saved with this forecast; see its exact supported level at the link.',
        '💡 The change is conditional, not a guarantee. Check the posted station price before filling.',
        'USD display equivalents assume 89,500 LBP/USD.', '🔗 Exact saved forecast: '+permalink(forecast.get('record_hash'))]
    return '\n'.join(lines)


def alerts(records, forecast, health, operations, threshold, *, at=None):
    """Deterministic in-app events. No notification transport or database writes."""
    result={}
    def add(kind,key,title,message,timestamp,evidence):
        identity=sha256(json.dumps([kind,key],sort_keys=True,default=str).encode()).hexdigest()
        result[identity]=dict(id=identity,kind=kind,title=title,message=message,timestamp=timestamp,evidence=evidence)
    dated=sorted(records,key=lambda r:r['source_date'])
    if dated:
        last=dated[-1];ts=last.get('version_known_at') or last.get('retrieved_at')
        if last.get('verification_status')=='conflict':
            add('conflict',last['source_date'],'Current sources disagree','The newest date has conflicting prices. No older quote replaces it.',ts,last.get('source_url'))
        elif len(dated)>1 and all(r.get('verification_status') in VERIFIED|{PROVISIONAL_PRICE} and r.get('price_lbp_20l') for r in dated[-2:]) and last.get('price_lbp_20l')!=dated[-2].get('price_lbp_20l'):
            add('price', [last['source_date'],last.get('price_lbp_20l')], 'New corroborated price record',
                f"{last.get('price_lbp_20l'):,.0f} LBP / 20 L on {last['source_date']}. This differs from the previous stored record; intervening decisions may be missing.",ts,last.get('source_url'))
    if forecast is not None:
        spec=json.loads(forecast['target_json']);key=[spec.get('base_source_date'),forecast['base_price'],spec.get('artifact_sha256'),forecast.get('scheduled_effective') or forecast.get('endpoint')]
        eligible=all(health['checks'][key]['status']!='failed' for key in ('forecast','domestic_anchor','required_feeds'))
        if eligible and abs(forecast['predicted_change'])>=threshold and threshold>0:
            add('threshold',key+[threshold,forecast['predicted_change']>0],'Estimate exceeds your alert threshold',
                f"Estimated change {forecast['predicted_change']:+,.0f} LBP / 20 L; threshold {threshold:,.0f}. Conditional research estimate, not a confirmed price change.",forecast['created_at'],permalink(forecast['record_hash']))
    forecast_state=health['checks']['forecast']
    if forecast is None or forecast_state['status']=='failed':
        add('unavailable',forecast.get('record_hash') if forecast is not None else (dated[-1]['source_date'] if dated else 'no-data'),
            'Forecast stale or unavailable','Check feed dates and the latest source evidence. An expired estimate is not a current forecast.',
            forecast.get('origin') if forecast is not None else None,forecast_state.get('reasons'))
    if operations.get('status') not in (None,'success','ok','completed'):
        add('refresh',operations.get('run_id') or operations.get('started_at'),'Scheduled refresh needs attention',
            'The last scheduled run failed or was incomplete. Earlier captures retain their original dates.',operations.get('finished_at'),operations.get('status'))
    return sorted(result.values(),key=lambda r:r['timestamp'] or '',reverse=True)
