"""Consumer and immutable-record views over the existing read-only contracts."""
from datetime import datetime, timezone
from html import escape
import json
import math
import sqlite3

import pandas as pd
import streamlit as st

from lebanon_fuel.automation.health import build
from . import data, experience as ux


def money(price):
    values=data.currency_values(price)
    st.markdown(f'<p class="currency-secondary">~${values["usd_20l"]:,.2f} USD / 20 L</p>',unsafe_allow_html=True)
    st.caption(f'{values["lbp_liter"]:,.0f} LBP / L · ~${values["usd_liter"]:,.2f} USD / L')


def read_report(root,path):
    try:return data.read_json(root/path)
    except (OSError,ValueError):return {}


def health_strip(health,row):
    checks=health['checks'];progress=ux.readiness(row)
    parts=[]
    for key,title in [('required_feeds','Data freshness'),('forecast','Forecast status'),('calibration','Prediction range'),('operational_integrity','System integrity')]:
        state=checks[key];status=state['status']
        if key=='calibration':status='ok' if row is not None and ux.released_bounds(row,90) else 'warning'
        if key=='required_feeds':
            labels={'nyh_gasoline':'Gasoline proxy','brent_spot':'Brent spot'}
            detail=' · '.join(f'{labels.get(sid,sid.replace("_"," "))}: {v.get("observation_date") or "missing"}' for sid,v in state.get('feeds',{}).items()) or 'Required feed dates need review'
        elif key=='calibration':
            detail=(f'{progress["cases"]}/{progress["minimum_cases"]} matched cases · {progress["tests"]}/{progress["minimum_tests"]} range tests'
                    if row is not None else 'No current forecast to evaluate')
        elif key=='operational_integrity':
            detail=f'{state["missing_files"]} original captures missing' if state.get('missing_files') else 'Strict audit '+('passed' if status=='ok' else 'needs review')
        else:
            detail='Hybrid research estimate' if status=='warning' else 'No current eligible estimate' if status=='failed' else 'Model estimate within freshness limits'
        label={'ok':'Checked','warning':'Limited','failed':'Needs attention','unknown':'Not checked'}[status]
        parts.append(f'<div class="trust-item {status}"><strong>{title}</strong><span>{label}</span><small>{escape(detail)}</small></div>')
    st.markdown('<section class="trust-strip" aria-label="Forecast trust indicators">'+''.join(parts)+'</section>',unsafe_allow_html=True)
    if checks['operational_integrity']['status']=='failed':
        st.error('The latest evidence audit failed. Open Data Quality to see the checks that need attention.')
    if checks['refresh']['status']=='failed':
        st.warning(data.refresh_result_message(st.session_state.get('refresh_result',(False,''))))


def range_status(row):
    if row is None:
        st.info('A prediction range needs a current eligible forecast. No range is calculated for an unavailable estimate.')
        return
    progress=ux.readiness(row)
    available=[(level,ux.released_bounds(row,level)) for level in (80,90)] if row is not None else []
    available=[(level,bounds) for level,bounds in available if bounds]
    if available:
        for level,(low,high) in available:
            st.write(f'{level}% pointwise prediction range · **{low:,.0f}–{high:,.0f} LBP / 20 L**')
        if len(available)==1:st.caption('The other interval level remains withheld; no range is inferred by scaling this one.')
    else:
        st.info(f'Prediction range not ready: {progress["cases"]} matched cases and {progress["tests"]} chronological range tests for this horizon, model version and starting-price group. At least {progress["minimum_cases"]} cases and {progress["minimum_tests"]} tests are required; measured coverage must also pass.')


def share(current,row,settings):
    if row is not None and not row.get('record_hash'):
        st.caption('This estimate has no immutable sharing identifier. Share a saved ledger forecast instead.')
        return
    text=ux.briefing(current,row,settings)
    payload=json.dumps(text).replace('<',r'\u003c')
    st.html('''<button id="fuel-copy-brief" type="button" style="padding:12px 18px;border-radius:10px;background:#b4dfff;color:#101626;border:0;font-weight:700;cursor:pointer">📋 Copy WhatsApp Briefing</button>
    <span id="fuel-copy-status" role="status" style="display:block;margin-top:8px;color:#c5d2ec"></span><script>
    (()=>{document.getElementById('fuel-copy-brief').onclick=async()=>{try{await navigator.clipboard.writeText('''+payload+''');document.getElementById('fuel-copy-status').textContent='Copied. Paste into WhatsApp or your social app.';}catch(e){document.getElementById('fuel-copy-status').textContent='Clipboard blocked. Open the preview and select or copy the text, or download the briefing.';}};})();</script>''',unsafe_allow_javascript=True)
    with st.expander('Preview the shareable briefing'):
        st.code(text,language=None)
        st.download_button('Download briefing',text,'lebanon-gasoline-brief.txt','text/plain')
    if row is not None:
        st.link_button('Open exact saved forecast',ux.permalink(row['record_hash']))


def overview(root,snap,settings,row,refresh_controls):
    st.title('Your next fill-up, in focus')
    st.caption('Lebanon gasoline 95 · LBP per 20-liter tank · Beirut time')
    current,reason=ux.current_price(snap['prices'],maximum_age_days=settings['collection']['stale_after_days'])
    health=build(root,snap,row)
    refresh=st.session_state.get('refresh_result')
    if refresh and not refresh[0]:
        health['checks']['refresh']['status']='failed'
    with st.container(key='driver_prices'):
        a,b=st.columns([1.05,1])
        with a:
            st.subheader('At the pump')
            st.metric('Current recorded price',f'{current["price_lbp_20l"]:,.0f} LBP' if current else 'Needs verification')
            if current:
                money(current['price_lbp_20l'])
                st.write(data.STATUS.get(current['verification_status'],'Evidence under review'))
                st.caption(f'Observed {current["source_date"]} · {current["age_days"]} days old')
                if current['verification_status']==data.PROVISIONAL_PRICE:
                    matches = {item['id'] for item in current.get('corroborating_sources', [])}
                    partner = 'TotalEnergies' if 'totalenergies' in matches else 'Taqtek' if 'taqtek' in matches else 'another source'
                    st.caption(f'IPT and {partner} report the same dated price. Ministry confirmation and effective timing remain pending.')
                else:st.caption('Recorded source date; an official effective time may be undocumented.')
            else:
                st.warning(reason)
                if snap['prices']:
                    latest=max(snap['prices'],key=lambda record:record['source_date'])
                    quote=latest.get('price_lbp_20l')
                    if quote and math.isfinite(float(quote)) and float(quote)>0:
                        st.metric('Latest posted quote · unconfirmed',f'{quote:,.0f} LBP')
                        st.caption(f"{latest['source_date']} · {data.STATUS.get(latest['verification_status'],'Evidence under review')}. This quote is visible for reference and is not a forecast anchor.")
                        if (latest.get('source_url') or '').startswith('https://'):
                            st.link_button('View latest quoted source',latest['source_url'])
        with b:
            st.subheader('Next update estimate')
            if row is None:
                st.metric('Predicted price','Awaiting eligible inputs')
                st.warning('No current absolute-price forecast is available. Open Data Quality for the exact gate and recovery steps.')
            else:
                spec=json.loads(row['target_json']);view=data.forecast_view(pd.Series(row))
                st.metric('Predicted price',f'{row["predicted_price"]:,.0f} LBP',delta=f'{row["predicted_change"]:+,.0f} LBP ({row["predicted_change"]/row["base_price"]:+.2%})',delta_color='off')
                money(row['predicted_price'])
                sign='−' if row['predicted_change']<0 else '+'
                st.write(f'From exactly **{row["base_price"]:,.0f} LBP / 20 L** · ~{sign}${abs(row["predicted_change"])/data.DISPLAY_FX:.2f} USD change')
                st.caption('Estimated target · '+view['schedule']+' · announcement time unconfirmed')
                status=ux.freshness(row,settings)
                st.caption(f'Issued {data.beirut_time(status["issued"])} · expires {data.beirut_time(status["expires"])}')
                st.info('Hybrid research estimate · production approval withheld' if spec.get('tier')!=1 else 'Hybrid validated model estimate')
    st.caption('USD equivalents use a display assumption of 89,500 LBP/USD, not a verified ministry pricing-formula rate.')
    if row is not None:
        st.subheader('What it could mean for your tank')
        liters=st.number_input('Fill-up size · liters',min_value=1,max_value=200,value=int(st.session_state.get('_tank_liters',50)),key='tank_liters',on_change=lambda:st.session_state.update(_tank_liters=st.session_state.tank_liters))
        # Linear volume display conversion; forecast unit remains LBP / 20 liters.
        change=float(row['predicted_change'])*liters/20
        st.write(f'If the estimate is realized, a **{liters} L** fill-up would cost **{abs(change):,.0f} LBP (~${abs(change)/data.DISPLAY_FX:.2f}) {"less" if change<0 else "more"}** than at the starting price.')
        st.caption('A conditional comparison, not guaranteed savings or an instruction to postpone refueling.')
    health_strip(health,row)
    range_status(row)
    with st.expander('Why these indicators matter'):
        st.caption('Forecasts can remain available as research while the evidence audit fails. Neither a model label nor fresh inputs clears an audit failure.')
        st.json(health)
    share(current,row,settings)
    with st.expander('Source evidence and older comparisons'):
        cadence=data.decree_hazard_context(snap['prices'])
        if cadence['sample_size']:
            st.caption(f"{cadence['tue_fri_share']:.0%} of the latest {cadence['sample_size']} dated price observations fall on Tuesday or Friday. This is a historical source-date pattern, not an announcement probability or a verified publication time.")
        for record in reversed(snap['prices'][-8:]):
            st.write(f"{record['source_date']} · {record.get('price_lbp_20l') or 'Unresolved'} LBP / 20 L · {data.STATUS.get(record['verification_status'],'Under review')}")
            if (record.get('source_url') or '').startswith('https://'):st.link_button('View source · '+record['source_date'],record['source_url'])
        st.caption('Older quotes are evidence history, not competing current prices. Gaps between records may contain unobserved decisions.')
    refresh_controls(snap,row)
    st.link_button('Explore the price trajectory','?view=trajectory')
    st.link_button('Open alert center','?view=alerts')


def forecast_page(root,ledger_path,record_hash,settings,show_chart):
    st.title('Saved forecast')
    st.caption('An immutable research record · not a replacement with today’s estimate')
    try:row=ux.saved_forecast(ledger_path,record_hash)
    except (ValueError,OSError,sqlite3.Error):
        st.error('The forecast link is invalid or its ledger is unavailable. Open the current dashboard or retry later.')
        return
    if row is None:
        st.warning('This forecast was not found in this deployment. It may not yet be synchronized; no newer prediction has been substituted.')
        return
    spec=json.loads(row['target_json']);status=ux.freshness(row,settings)
    st.metric('Original predicted price',f'{row["predicted_price"]:,.0f} LBP / 20 L')
    money(row['predicted_price'])
    st.write(f'Original starting price **{row["base_price"]:,.0f} LBP** · predicted change **{row["predicted_change"]:+,.0f} LBP**')
    st.caption('Issued '+data.beirut_time(row['created_at'])+' · '+row['horizon']+' · target '+data.forecast_view(pd.Series(row))['schedule'])
    st.warning(status['status']+' · expiry '+data.beirut_time(status['expires'])+'. A saved record remains accessible after it expires.')
    st.caption('Only Hybrid is the active forecasting family. Production approval remains withheld unless a dated review says otherwise.')
    for level in (80,90):
        saved=spec.get('interval_80') if level==80 else [row.get('interval_low'),row.get('interval_high')]
        if saved and all(v is not None and math.isfinite(float(v)) for v in saved):
            lo,hi=[row['base_price']+float(v) for v in saved]
            nominal=spec.get('interval_nominal' if level==90 else 'interval_80_nominal')
            label=f'Originally published {level}% interval' if nominal==level/100 else 'Original saved interval · nominal level not documented'
            st.write(f'{label}: {lo:,.0f}–{hi:,.0f} LBP / 20 L')
            st.caption('Released live calibration evidence' if ux.released_bounds(row,level) else 'Original saved candidate interval; current release evidence does not support presenting it as calibrated.')
        else:st.caption(f'No {level}% interval was published with this forecast.')
    if row.get('actual_price') is not None:
        st.subheader('Subsequent matched outcome')
        st.write(f"{row['actual_price']:,.0f} LBP / 20 L · error {row['predicted_price']-row['actual_price']:+,.0f} LBP")
        st.caption(str(row.get('evaluation_kind'))+' · '+str(row.get('recorded_target_date'))+' · provisional evidence is not an official effective-time confirmation.')
    else:st.info('No eligible matched outcome is saved yet. This is not a zero-error result.')
    inputs=row['snapshot'].get('inputs',{})
    with st.expander('Original source evidence and market dates',expanded=True):
        anchor=inputs.get('anchor') or {}
        st.write('Original anchor date · '+str(anchor.get('source_date','Not saved'))+' · '+data.STATUS.get(anchor.get('verification_status'),'Evidence not saved'))
        market=inputs.get('available_market_inputs') or {}
        st.dataframe([{'Input':sid,'Observed':r.get('observation_date'),'Value':r.get('value'),'Source':r.get('source_url')} for sid,r in market.items() if isinstance(r,dict)],hide_index=True)
        st.caption('These dates come from the original saved snapshot, not today’s market feeds.')
        if (anchor.get('source_url') or '').startswith('https://'):st.link_button('Original anchor source',anchor['source_url'])
    with st.expander('Immutable identity and original inputs'):
        st.code('Forecast hash: '+record_hash+'\nArtifact: '+str(spec.get('artifact_sha256'))+'\nModel version: '+row['model_version']+'\nSnapshot: '+row['snapshot_id'])
        st.json(row['snapshot'])
    share(anchor,row,settings)
    st.link_button('Return to Driver Pulse','?view=driver')


def alert_center(root,snap,row,settings):
    st.title('Alert center')
    st.caption('In-app only · no messages are sent · acknowledgements last for this browser session')
    threshold=st.number_input('Alert when estimated change reaches · LBP / 20 L',min_value=1000,max_value=1000000,value=int(st.session_state.get('_alert_threshold',30000)),step=1000,key='alert_threshold',on_change=lambda:st.session_state.update(_alert_threshold=st.session_state.alert_threshold))
    if row is None:
        try:
            _,ledger_path=data.database_paths(root,settings)
            saved=data.live_ledger_rows(ledger_path)
            saved=saved.loc[saved.horizon.eq('decision_1') & saved.family.eq('G_hybrid')]
            row=saved.iloc[-1] if len(saved) else None
        except (OSError,sqlite3.Error):pass
    events=ux.alerts(snap['prices'],row,build(root,snap,row),read_report(root,'reports/operations/latest_run.json'),threshold)
    acknowledged=st.session_state.setdefault('_acknowledged_alerts',set())
    show_read=st.checkbox('Show acknowledged alerts',value=False)
    visible=[r for r in events if show_read or r['id'] not in acknowledged]
    st.caption(f'{len(visible)} visible / {len(events)} distinct current events. Repeated page loads do not create duplicate events.')
    if not visible:st.info('No unacknowledged alerts at this threshold. The data and governance views remain available.')
    for event in visible:
        with st.container(border=True):
            st.subheader(event['title'])
            st.write(event['message'])
            st.caption('Evidence timestamp · '+data.beirut_time(event['timestamp']) if event['timestamp'] else 'Event time unavailable; no timestamp invented')
            st.caption('Evidence · '+str(event['evidence']))
            if event['id'] not in acknowledged and st.button('Acknowledge',key='ack_'+event['id']):
                acknowledged.add(event['id']);st.rerun()
    st.caption('External delivery is disabled. This release has no email, SMS or WhatsApp delivery adapter; copying a briefing is a separate user action.')
