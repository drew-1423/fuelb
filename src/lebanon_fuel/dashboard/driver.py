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
    checks=health['checks']
    parts=[]
    for key,title in [('required_feeds','Market inputs'),('calibration','Prediction range'),('operational_integrity','System integrity')]:
        state=checks[key];status=state['status']
        label = {'ok':'Checked','warning':'Limited','failed':'Needs attention','unknown':'Not checked'}[status]
        if key=='required_feeds':
            label = {'ok':'Within freshness limit','warning':'Delayed','failed':'Missing or stale','unknown':'Not checked'}[status]
            labels={'nyh_gasoline':'EIA gasoline proxy','brent_spot':'EIA Brent'}
            detail=' · '.join(f'{labels.get(sid,sid.replace("_"," "))}: {v.get("observation_date") or "missing"}' for sid,v in state.get('feeds',{}).items()) or 'Required feed dates need review'
        elif key=='calibration':
            levels = [f'{level}%' for level in (80,90) if row is not None and ux.released_bounds(row,level)]
            status = 'ok' if levels else 'warning' if row is not None else 'unknown'
            label = 'Available' if levels else 'Collecting outcomes' if row is not None else 'Awaiting forecast'
            detail = ' and '.join(levels) + ' prediction ranges' if levels else 'See validation details'
        elif key=='operational_integrity':
            label = 'Passed' if status=='ok' else label
            detail=f'{state["missing_files"]} original captures missing' if state.get('missing_files') else 'Strict audit '+('passed' if status=='ok' else 'needs review')
        parts.append(f'<div class="trust-item {status}"><strong>{title}</strong><span>{label}</span><small>{escape(detail)}</small></div>')
    st.markdown('<section class="trust-strip" aria-label="Forecast trust indicators">'+''.join(parts)+'</section>',unsafe_allow_html=True)
    if checks['operational_integrity']['status']=='failed':
        st.error('The latest evidence audit failed. Open Data Quality to see the checks that need attention.')


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
        st.caption(f'Range validation needs {progress["minimum_cases"]} matched outcomes and {progress["minimum_tests"]} chronological tests with acceptable coverage. So far, {progress["cases"]} outcomes and {progress["tests"]} tests qualify.')


def share(current,row,settings):
    if row is not None and not row.get('record_hash'):
        st.caption('This estimate has no immutable sharing identifier. Share a saved ledger forecast instead.')
        return
    text=ux.briefing(current,row,settings)
    payload=json.dumps(text).replace('<',r'\u003c')
    st.html('''<button id="fuel-copy-brief" type="button">📋 Copy WhatsApp Briefing</button>
    <span id="fuel-copy-status" role="status"></span><script>
    (()=>{document.getElementById('fuel-copy-brief').onclick=async()=>{try{await navigator.clipboard.writeText('''+payload+''');document.getElementById('fuel-copy-status').textContent='Copied. Paste into WhatsApp or your social app.';}catch(e){document.getElementById('fuel-copy-status').textContent='Clipboard blocked. Open the preview and select or copy the text, or download the briefing.';}};})();</script>''',unsafe_allow_javascript=True)
    with st.expander('Preview the shareable briefing'):
        st.code(text,language=None)
        st.download_button('Download briefing',text,'lebanon-gasoline-brief.txt','text/plain')
    if row is not None:
        st.link_button('Open exact saved forecast',ux.permalink(row['record_hash']))


def price_panels(current, reason, prices, forecast):
    with st.container(key='driver_prices'):
        recorded, estimate = st.columns([1, 1])
        with recorded, st.container(key='recorded_quote'):
            st.metric('Current recorded price', f'{current["price_lbp_20l"]:,.0f} LBP' if current else 'Needs verification')
            if current:
                money(current['price_lbp_20l'])
                if current['verification_status'] == data.PROVISIONAL_PRICE:
                    sources = {item['id'] for item in current.get('corroborating_sources', [])}
                    partner = 'TotalEnergies' if 'totalenergies' in sources else 'Taqtek' if 'taqtek' in sources else 'another source'
                    st.caption(f'IPT + {partner} · Observed {current["source_date"]}')
                    st.caption('Ministry confirmation and effective timing pending.')
                else:
                    status = data.STATUS.get(current['verification_status'], 'Evidence under review')
                    st.caption(f'{status} · Observed {current["source_date"]}')
            else:
                st.caption(reason)
                latest = max(prices, key=lambda record: record['source_date']) if prices else {}
                quote = latest.get('price_lbp_20l')
                if quote and math.isfinite(float(quote)) and float(quote) > 0:
                    st.caption(f'Unconfirmed quote · {quote:,.0f} LBP / 20 L · {latest["source_date"]}')
                    if (latest.get('source_url') or '').startswith('https://'):
                        st.link_button('View latest quoted source', latest['source_url'])
        with estimate, st.container(key='forecast_quote'):
            if forecast is None:
                st.metric('Predicted price', 'Awaiting eligible inputs')
                st.caption('Open Data Quality for the reason and recovery steps.')
                st.link_button('Open Data Quality', '?view=quality')
            else:
                spec = json.loads(forecast['target_json'])
                tier = spec.get('tier')
                view = data.forecast_view(pd.Series(forecast))
                price = forecast['predicted_price']
                base = forecast['base_price']
                change = forecast['predicted_change']
                st.metric('Predicted price', f'{price:,.0f} LBP', delta=f'{change:+,.0f} LBP ({change / base:+.2%})',
                          delta_color='off')
                money(price)
                label = 'Validated estimate' if tier == 1 else 'Research estimate'
                st.caption(f'{label} · {view["schedule"]}')
                if spec.get('schedule_estimated'):
                    st.caption('Projected date · Announcement time unconfirmed')
                if current is None or current['price_lbp_20l'] != base:
                    base_date = spec.get('base_source_date')
                    date_note = f' · {base_date}' if base_date else ''
                    st.caption(f'Change measured from {base:,.0f} LBP / 20 L{date_note}')


def fill_up(forecast):
    st.subheader('Your fill-up')
    if forecast is None:
        st.caption('A fill-up comparison needs a current price estimate.')
        return
    liters = st.number_input('Fill-up size · liters', min_value=1, max_value=200,
                             value=int(st.session_state.get('_tank_liters', 50)), key='tank_liters',
                             on_change=lambda: st.session_state.update(_tank_liters=st.session_state.tank_liters))
    change = float(forecast['predicted_change']) * liters / 20
    direction = 'less' if change < 0 else 'more'
    st.markdown(f'**{abs(change):,.0f} LBP {direction}**' if change else '**No estimated change**')
    usd = f' · about ${abs(change) / data.DISPLAY_FX:,.2f} USD {direction}' if change else ''
    st.caption(f'For {liters} L if the estimate is realized{usd}.')


def overview(root, snap, settings, row, refresh_controls, open_workspace, price_history):
    current, reason = ux.current_price(snap['prices'], maximum_age_days=settings['collection']['stale_after_days'])
    health = build(root, snap, row)
    with st.container(key='driver_header'):
        heading, actions = st.columns([2.25, 1], vertical_alignment='bottom')
        with heading:
            st.title('Lebanon gasoline 95')
            st.caption('Prices in LBP per 20 L · Beirut time')
        with actions:
            refresh_controls(snap, row)
            st.caption('Last successful capture · ' + data.beirut_time(snap.get('latest_capture')))
        with st.container(key='driver_actions'):
            st.button('Price trajectory', on_click=open_workspace, args=('trajectory',), key='overview_trajectory', type='primary')
            st.button('Predicted vs actual', on_click=open_workspace, args=('performance', 'actual'), key='overview_comparison')
    price_panels(current, reason, snap['prices'], row)
    st.caption(f'USD display rate: {data.DISPLAY_FX:,.0f} LBP per USD.')
    with st.container(key='driver_workspace'):
        utility, chart = st.columns([1, 2.2])
        with utility, st.container(key='driver_utility'):
            fill_up(row)
            health_strip(health, row)
        with chart, st.container(key='driver_chart'):
            st.subheader('Observed prices and next estimate')
            price_history()
    with st.expander('Validation details'):
        if row is not None:
            status = ux.freshness(row, settings)
            st.caption(f'Issued {data.beirut_time(status["issued"])} · Expires {data.beirut_time(status["expires"])}')
            if json.loads(row['target_json']).get('tier') != 1:
                st.caption('Production approval pending.')
        range_status(row)
        st.json(health)
    share(current, row, settings)
    with st.expander('Source evidence and older comparisons'):
        cadence=data.decree_hazard_context(snap['prices'])
        if cadence['sample_size']:
            st.caption(f"{cadence['tue_fri_share']:.0%} of the latest {cadence['sample_size']} dated price observations fall on Tuesday or Friday. This is a historical source-date pattern, not an announcement probability or a verified publication time.")
        for record in reversed(snap['prices'][-8:]):
            st.write(f"{record['source_date']} · {record.get('price_lbp_20l') or 'Unresolved'} LBP / 20 L · {data.STATUS.get(record['verification_status'],'Under review')}")
            if (record.get('source_url') or '').startswith('https://'):st.link_button('View source · '+record['source_date'],record['source_url'])
        st.caption('Older quotes are evidence history, not competing current prices. Gaps between records may contain unobserved decisions.')
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
