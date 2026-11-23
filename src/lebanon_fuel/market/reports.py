"""Observed coverage, quarantined issues and descriptive comparisons, no fitting."""
from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import json

from lebanon_fuel.domain import VERIFIED, now_utc, regime_label, utc_timestamp
from lebanon_fuel.features.market import snapshot
from .catalog import SERIES, MISSING


def write_csv(path,rows,columns=None):
    columns=columns or (list(rows[0]) if rows else [])
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def collection_summary(detail):
    """Summarize recorded counts without treating blocked downloads as zero rows."""
    results=detail.get('results') or []
    if not results:
        return detail.get('error') or f"{detail.get('parsed_rows','unknown')} reviewed/imported rows"
    notes=[str(detail['error'])] if detail.get('error') else []
    for field,label in [('parsed_rows','rows parsed'),('new_observations','new observations')]:
        counts=[r[field] for r in results if isinstance(r.get(field),int) and not isinstance(r[field],bool) and r[field]>=0]
        if not counts:
            notes.append(f'{label}: unavailable')
        else:
            qualification=f' across {len(counts)}/{len(results)} results with recorded counts' if len(counts)<len(results) else ''
            notes.append(f'{sum(counts):,} {label}{qualification}')
    for result in results:
        problem=result.get('error') or result.get('reason')
        status=result.get('status')
        if problem or status in {'failed','error','unavailable','blocked'}:
            notes.append(f"{result.get('series','unknown series')}: {status or 'failed'} — {problem or 'reason not recorded'}")
            if result.get('fallback_series'):
                notes.append(f"Stored fallback: {result['fallback_series']} (latest {result.get('fallback_latest_date') or 'unknown'}); not newly collected futures")
    return '; '.join(notes)


def report(store,as_of):
    as_of=utc_timestamp(as_of)
    reports=store.root/'reports'; reports.mkdir(exist_ok=True)
    exports=store.root/'data/exports'; exports.mkdir(parents=True,exist_ok=True)
    coverage=[]; gaps=[]; missing=[]; reported_missing=[]; changes=[]; conflicts=[]; shocks=[]; date_reviews=[]; latest={}; research={}
    for sid,spec in SERIES.items():
        all_rows=[dict(r) for r in store.db.execute('SELECT * FROM market_observations WHERE series_id=?',(sid,))]
        history=store.history(sid,as_of,'strict'); latest[sid]=history
        research[sid]=store.history(sid,as_of,'research')
        dates=[date.fromisoformat(r['observation_date']) for r in history]
        nulls=sum(not r['valid'] for r in all_rows)
        reported_missing.extend({'series':sid,'observation_date':r['observation_date'],'raw_value':r['raw_value'],
                                 'issues':r['issues_json'],'observation_id':r['id']} for r in all_rows if not r['valid'])
        last=dates[-1] if dates else None
        age=(datetime.fromisoformat(as_of).astimezone(ZoneInfo(spec.timezone)).date()-last).days if last else None
        issues=Counter(issue for r in all_rows for issue in json.loads(r['issues_json']))
        coverage.append({'series':sid,'role':spec.role,'valid_unique_dates':len(dates),'stored_observations':len(all_rows),
                         'invalid_or_missing_observations':nulls,'earliest':str(dates[0]) if dates else None,
                         'latest':str(last) if last else None,'latest_value':history[-1]['value'] if history else None,
                         'unit':spec.normalized_unit,'age_days':age,'stale':age is None or age>spec.stale_days,
                         'known_publication_timestamps':sum(r['publication_timestamp'] is not None for r in all_rows),
                         'documented_historical_vintages':sum(r['vintage_timestamp'] is not None for r in all_rows),
                         'issues':dict(issues)})
        explicit_days={date.fromisoformat(r['observation_date']) for r in all_rows}
        if spec.frequency in {'daily','weekly'} and dates:
            current=dates[0]
            while current<=dates[-1]:
                # Candidate weekdays are not a certified exchange or release calendar.
                candidate=current.weekday()<5 if spec.frequency=='daily' else current.weekday()==dates[-1].weekday()
                if candidate and current not in explicit_days:
                    missing.append({'series':sid,'date':str(current),'status':'unclassified_calendar_candidate_not_proven_missing','calendar_basis':'weekday_grid_not_holiday_adjusted'})
                current+=timedelta(days=1)
        for a,b in zip(dates,dates[1:]):
            limit=10 if spec.frequency=='daily' else 14
            if (b-a).days>limit and spec.frequency!='irregular':
                gaps.append({'series':sid,'previous_date':str(a),'next_date':str(b),'calendar_days':(b-a).days,'status':'investigate_not_imputed'})
        for a,b in zip(history,history[1:]):
            move=b['value']/a['value']-1
            threshold=.05 if sid=='eurusd' else .1 if 'stocks' in sid else .25
            if abs(move)>threshold:
                shocks.append({'series':sid,'previous_date':a['observation_date'],'date':b['observation_date'],
                               'change_fraction':move,'review_threshold_fraction':threshold,
                               'observation_ids':json.dumps([a['id'],b['id']]),'status':'review_large_move_not_automatically_invalid'})
        for r in history:
            weekday=date.fromisoformat(r['observation_date']).weekday()
            odd=(spec.frequency=='daily' and weekday>=5) or (sid.startswith('us_') and spec.frequency=='weekly' and weekday!=4) or (spec.source=='market_ec' and weekday!=0)
            if odd:
                date_reviews.append({'series':sid,'date':r['observation_date'],'weekday':weekday,'status':'reference_weekday_differs_usual_review_not_automatic_error'})
        bydate={}
        for r in all_rows:
            bydate.setdefault(r['observation_date'],[]).append(r)
        for day,rs in bydate.items():
            if len({r['value'] for r in rs if r['valid']})>1:
                changes.append({'series':sid,'date':day,'observation_ids':json.dumps([r['id'] for r in rs]),'status':'multiple_captured_versions_preserved'})
        ambiguous=store.db.execute('''SELECT o.observation_date,ms.capture_id,COUNT(DISTINCT o.value) AS n
         FROM market_observations o JOIN market_sightings ms ON ms.observation_id=o.id
         WHERE o.series_id=? AND o.valid=1 GROUP BY o.observation_date,ms.capture_id HAVING n>1''',(sid,))
        conflicts.extend({'series':sid,**dict(r),'status':'same_capture_conflict_quarantined'} for r in ambiguous)
    for name,rows,cols in [('market_gap_candidates',gaps,['series','previous_date','next_date','calendar_days','status']),
                           ('market_calendar_candidates',missing,['series','date','status','calendar_basis']),
                           ('market_reported_missing',reported_missing,['series','observation_date','raw_value','issues','observation_id']),
                           ('market_suspicious_changes',shocks,['series','previous_date','date','change_fraction','review_threshold_fraction','observation_ids','status']),
                           ('market_date_alignment',date_reviews,['series','date','weekday','status']),
                           ('market_revisions',changes,['series','date','observation_ids','status']),
                           ('market_conflicts',conflicts,['series','observation_date','capture_id','n','status'])]:
        write_csv(reports/(name+'.csv'),rows,cols)
    export=[]
    for sid,rows in latest.items():
        for r in rows:
            export.append({k:r.get(k) for k in ['series_id','observation_date','value','unit','raw_value','raw_unit','publication_timestamp',
                                               'vintage_timestamp','first_seen_at','available_at','availability_basis','source_url','capture_id','id']})
    write_csv(exports/'market_history.csv',export)
    raw_failures=[]
    caps=store.db.execute("SELECT DISTINCT c.* FROM captures c JOIN market_sightings ms ON ms.capture_id=c.id")
    for c in caps:
        path=store.root/c['raw_path']
        if not path.exists() or sha256(path.read_bytes()).hexdigest()!=c['sha256']:
            raw_failures.append(c['id'])
    current=snapshot(store,as_of,'strict')
    (exports/'market_features_current_strict.json').write_text(json.dumps(current,indent=2))
    comparison,correlations,strict_counts=historical_comparison(store,research,as_of)
    write_csv(exports/'market_lebanon_alignment_RESEARCH_ONLY.csv',comparison)
    write_csv(reports/'market_lead_lag_RESEARCH_ONLY.csv',correlations)
    runs={source:dict(row) if row else None for source in sorted({s.source for s in SERIES.values()})
          for row in [store.db.execute('SELECT id,source_id,started_at,finished_at,status,details FROM collection_runs WHERE source_id=? ORDER BY id DESC LIMIT 1',(source,)).fetchone()]}
    payload={'as_of':as_of,'series':coverage,'latest_source_runs':runs,'missing_datasets':MISSING,'large_gap_candidates':len(gaps),
             'calendar_candidates_not_proven_gaps':len(missing),'captured_revision_dates':len(changes),
             'large_move_review_candidates':len(shocks),'date_alignment_review_candidates':len(date_reviews),
             'conflicting_capture_dates':len(conflicts),'raw_hash_failures':raw_failures,
             'historical_strict_alignment':strict_counts,'comparison_rows':len(comparison),
             'historical_comparison_status':'assumed_date_origins_lags_latest_vintage_NOT_A_BACKTEST',
             'readiness':'research_ready_not_institutional_backtest_ready'}
    (reports/'market_coverage.json').write_text(json.dumps(payload,indent=2))
    lines=['# International market coverage and quality', '',f'Generated for {as_of}. Counts below are actual stored observations, not estimates.',
           '', '| Series | Unique valid dates | Earliest | Latest | Latest normalized value | Stale |',
           '| --- | ---: | --- | --- | --- | --- |']
    for r in coverage:
        displayed=f"{r['latest_value']:.6g}" if r['latest_value'] is not None else 'unknown'
        lines.append(f"| {r['series']} | {r['valid_unique_dates']} | {r['earliest']} | {r['latest']} | {displayed} {r['unit']} | {r['stale']} |")
    lines += ['', '## Latest collection outcomes', '', '| Source | Result | Completed UTC | Detail |', '| --- | --- | --- | --- |']
    for source,run in runs.items():
        detail=json.loads(run['details']) if run else {}
        note=collection_summary(detail).replace('|','\\|').replace('\n',' ')
        lines.append(f"| {source} | {run['status'] if run else 'no recorded run'} | {run['finished_at'] if run else 'unknown'} | {note} |")
    lines += ['', '## Availability and validation', '',
              f"{sum(r['stored_observations'] for r in coverage):,} immutable observations; {sum(r['invalid_or_missing_observations'] for r in coverage):,} invalid/missing rows retained. {len(changes)} dates with captured value revisions; {len(conflicts)} same-capture contradictions quarantined. Raw hash failures: {len(raw_failures)}.",
              f"{len(gaps)} long interval candidates; {len(missing)} unclassified weekday/weekly calendar candidates. These include holidays and cannot be called missing market sessions without an authoritative calendar. No filling or interpolation was applied.",
              f"{len(shocks)} large-move review candidates; {len(date_reviews)} unusual reference-weekday candidates. Review flags do not prove source errors or erase real market shocks.",
              f"Known per-observation publication timestamps: {sum(r['known_publication_timestamps'] for r in coverage)}. Documented original historical vintages: {sum(r['documented_historical_vintages'] for r in coverage)}. Dates in today's workbook are not release timestamps.",
              f"At {strict_counts['origins']} historical source-date origins, {strict_counts['origins_with_any_strict_market_observation']} have any market value proven available by this project's capture/vintage evidence. Origins are assumed 00:00 Asia/Beirut; Lebanese announcement times are still unknown.",
              '', '## Historical relationships', '',
              f'{len(comparison)} comparisons pair adjacent corroborated/document-verified Lebanese rows separated by at most 14 days. Conflict rows and unverified neighbors are excluded. These remain source-date comparisons, not certified consecutive official decisions.',
              'The CSV reports fixed 0, 3, 7 and 14 calendar-day additional lags, seven-day market returns and Lebanese decision-to-decision changes by provisional regime. Latest revised market histories and assumed release lags are used. Correlations are descriptive, dependent and confounded by FX/tax regimes; no causation, optimal transmission lag or forecast accuracy is established.',
              'For the provisional November 2022–May 2025 bucket, the fixed zero-additional-lag correlations are:', '',
              '| Market return | Pairs | Correlation |', '| --- | ---: | ---: |']
    for r in correlations:
        if r['regime']=='post_subsidy_fx_transition_unresolved' and r['additional_lag_calendar_days']==0:
            value=f"{r['pearson_correlation']:.3f}" if r['pearson_correlation'] is not None else 'insufficient data'
            lines.append(f"| {r['series']} | {r['pairs']} | {value} |")
    lines += ['', 'Zero additional lag still includes the assumed publication lag (14 EIA / 7 Commission / 10 H.10 calendar days). Results change with lag and regime; this analysis does not establish a reliable leading variable or a statutory transmission window.', '', '## Missing datasets', '']
    lines += [f'- **{key}**: {value}' for key,value in MISSING.items()]
    lines += ['', '## Readiness', '', 'Collectors, normalized storage, trailing features and audit checks are ready for research. Institutional historical backtesting is blocked by original release vintages, unknown Lebanese announcement times, incomplete formula/FX evidence and missing licensed Mediterranean assessments. No forecasting model was trained.',
              '', 'See `research/international_market_sources.md`, `docs/market_data.md`, the JSON report and companion quality CSVs for definitions and procedures.']
    (reports/'market_coverage.md').write_text('\n'.join(lines)+'\n')
    charts(store,latest,comparison,correlations)
    return payload


def historical_comparison(store,research,as_of):
    import numpy as np
    ledger=store.ledger(); comparison=[]; correlations=[]
    times={sid:[r['available_at'] for r in rows] for sid,rows in research.items()}
    observation_dates={sid:[r['observation_date'] for r in rows] for sid,rows in research.items()}
    # Research estimates are monotonic per series; no current-vintage cache is used in strict snapshots.
    def seven_day_return(sid,origin):
        rows=research[sid];spec=SERIES[sid]
        end=bisect_right(times[sid],origin)-1
        if end<0:return None
        last=rows[end];day=date.fromisoformat(last['observation_date'])
        local=datetime.fromisoformat(origin).astimezone(ZoneInfo(spec.timezone)).date()
        if (local-day).days>spec.stale_days+spec.research_lag_days:return None
        target=day-timedelta(days=7)
        start=bisect_right(observation_dates[sid],str(target),0,end+1)-1
        limit=10 if spec.frequency=='daily' else 21
        if start<0 or (target-date.fromisoformat(rows[start]['observation_date'])).days>limit:return None
        return last['value']/rows[start]['value']-1
    for prev,row in zip(ledger,ledger[1:]):
        if row['verification_status'] not in VERIFIED or prev['verification_status'] not in VERIFIED:
            continue
        day=date.fromisoformat(row['source_date'])
        if (day-date.fromisoformat(prev['source_date'])).days>14:
            continue
        origin=datetime.combine(day,time(),ZoneInfo('Asia/Beirut'))
        origin_utc=utc_timestamp(origin.isoformat())
        record={'source_date':str(day),'assumed_origin_utc':origin_utc,'origin_status':'assumed_start_of_source_date_NOT_actual_announcement',
                'mode':'research_latest_vintage_NOT_BACKTEST','regime':regime_label(str(day)),
                'lebanon_price_lbp_20l':row['price_lbp_20l'],'lebanon_change_fraction':row['price_lbp_20l']/prev['price_lbp_20l']-1,
                'previous_source_date':prev['source_date'],'decision_revision_id':row['revision_id']}
        for lag in (0,3,7,14):
            shifted=utc_timestamp((origin-timedelta(days=lag)).isoformat())
            for sid in ('brent_spot','nyh_gasoline','italy_gasoline_ex_tax','greece_gasoline_ex_tax','eurusd'):
                record[f'{sid}_7d_return_lag{lag}']=seven_day_return(sid,shifted)
        comparison.append(record)
    for regime in sorted({r['regime'] for r in comparison}):
        group=[r for r in comparison if r['regime']==regime]
        for sid in ('brent_spot','nyh_gasoline','italy_gasoline_ex_tax','greece_gasoline_ex_tax','eurusd'):
            for lag in (0,3,7,14):
                key=f'{sid}_7d_return_lag{lag}'
                pairs=[(r[key],r['lebanon_change_fraction']) for r in group if r[key] is not None]
                value=None
                if len(pairs)>=20:
                    a,b=np.asarray(pairs).T
                    if a.std()>0 and b.std()>0:
                        value=float(np.corrcoef(a,b)[0,1])
                correlations.append({'regime':regime,'series':sid,'additional_lag_calendar_days':lag,'pairs':len(pairs),
                                     'pearson_correlation':value,'status':'descriptive_no_causal_or_backtest_claim'})
    earliest_capture=store.db.execute('SELECT MIN(available_at) FROM market_sightings').fetchone()[0]
    strict_origins=0
    if earliest_capture:
        for row in ledger:
            origin=utc_timestamp(datetime.combine(date.fromisoformat(row['source_date']),time(),ZoneInfo('Asia/Beirut')).isoformat())
            if origin>=earliest_capture and any(store.history(sid,origin,'strict') for sid in SERIES):
                strict_origins+=1
    return comparison,correlations,{'origins':len(ledger),'origins_with_any_strict_market_observation':strict_origins}


def charts(store,histories,comparison,correlations):
    import os
    cache=store.root/'data/cache/matplotlib';cache.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(cache))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    folder=store.root/'reports/charts';folder.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(3,1,figsize=(12,10),sharex=True)
    ledger=[r for r in store.ledger() if r['price_lbp_20l'] and r['source_date']>='2023-01-01']
    axes[0].plot([date.fromisoformat(r['source_date']) for r in ledger],[r['price_lbp_20l']/1e6 for r in ledger],'.-',lw=.8,ms=2)
    axes[0].set_ylabel('Lebanon 95\nmillion LBP / 20 L')
    for sid,label in [('italy_gasoline_ex_tax','Italy'),('greece_gasoline_ex_tax','Greece')]:
        rows=[r for r in histories[sid] if r['observation_date']>='2023-01-01']
        axes[1].plot([date.fromisoformat(r['observation_date']) for r in rows],[r['value'] for r in rows],label=label,lw=1)
    axes[1].set_ylabel('Consumer gasoline ex tax\nEUR / L (retail proxies)');axes[1].legend()
    rows=[r for r in histories['brent_spot'] if r['observation_date']>='2023-01-01']
    axes[2].plot([date.fromisoformat(r['observation_date']) for r in rows],[r['value'] for r in rows],color='#ae4a25',lw=1)
    axes[2].set_ylabel('Brent spot\nUSD / bbl (crude proxy)')
    fig.suptitle('Historical comparison — different units; no fitted relationship',fontsize=15)
    fig.text(.08,.015,'Sources: MOEW / IPT ledger, European Commission, EIA. Latest downloaded vintages. Lebanese dates mostly source labels.',fontsize=9)
    fig.tight_layout(rect=(0,.04,1,.96))
    for ext in ('png','svg'):fig.savefig(folder/f'market_price_comparison.{ext}',dpi=160)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,5))
    for i,(sid,rows) in enumerate(histories.items()):
        if rows:
            ax.plot([date.fromisoformat(r['observation_date']) for r in rows],[i]*len(rows),'|',ms=7)
    ax.set_yticks(range(len(histories)),list(histories));ax.set_title('Actual valid observation coverage — marks are source dates')
    ax.grid(axis='x',alpha=.2);fig.tight_layout()
    for ext in ('png','svg'):fig.savefig(folder/f'market_coverage.{ext}',dpi=160)
    plt.close(fig)
    regime='post_subsidy_fx_transition_unresolved'
    sids=['brent_spot','nyh_gasoline','italy_gasoline_ex_tax','greece_gasoline_ex_tax']
    grid=np.full((4,4),np.nan);counts=np.zeros((4,4),int)
    for r in correlations:
        if r['regime']==regime and r['series'] in sids:
            i=sids.index(r['series']);j=[0,3,7,14].index(r['additional_lag_calendar_days'])
            if r['pearson_correlation'] is not None:grid[i,j]=r['pearson_correlation']
            counts[i,j]=r['pairs']
    fig,ax=plt.subplots(figsize=(10,5));im=ax.imshow(grid,vmin=-1,vmax=1,cmap='RdBu_r',aspect='auto')
    ax.set_xticks(range(4),['0','3','7','14']);ax.set_yticks(range(4),sids)
    ax.set_xlabel('Additional lag in calendar days, beyond assumed publication lag')
    for i in range(4):
        for j in range(4):
            val=f'{grid[i,j]:.2f}' if np.isfinite(grid[i,j]) else 'n/a'
            ax.text(j,i,f'{val}\nn={counts[i,j]}',ha='center',va='center',color='black')
    ax.set_title('Exploratory correlation, Nov 2022–May 2025 research bucket\n7-day market return vs Lebanese adjacent-record change; NOT a backtest')
    fig.colorbar(im,ax=ax,label='Pearson correlation')
    fig.text(.03,.015,'Latest vintages, assumed midnight origins and release lags. Policy/FX confounding and dependent samples; no causation or chosen optimal lag.',fontsize=8)
    fig.tight_layout(rect=(0,.05,1,1))
    for ext in ('png','svg'):fig.savefig(folder/f'market_lead_lag_RESEARCH_ONLY.{ext}',dpi=160)
    plt.close(fig)
