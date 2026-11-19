"""Reproducible ledger exports, coverage and quality reporting."""
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
import csv
import json
from hashlib import sha256

from lebanon_fuel.domain import BEIRUT, VERIFIED, now_utc


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def export_data(store, directory):
    directory=Path(directory)
    ledger=store.ledger()
    fields=['source_date','official_effective_date','date_role','publication_date','publication_timestamp','retrieved_at','timezone',
        'price_lbp_20l','unit','previous_verified_date','previous_verified_price','absolute_price_change','percentage_price_change',
        'change_basis','verification_status','source_priority','source_url','decision_numbers','regime','regime_status','revision_id',
        'chosen_observation_id','observation_ids','candidate_values','issues','resolution_id']
    write_csv(directory/'gasoline_95_history.csv',ledger,fields)
    write_csv(directory/'gasoline_95_verified.csv',[r for r in ledger if r['verification_status'] in VERIFIED],fields)
    observations=[dict(r) for r in store.db.execute('SELECT o.*,s.priority source_priority FROM observations o JOIN sources s ON s.id=o.source_id ORDER BY source_date,o.id')]
    write_csv(directory/'source_observations.csv',observations,list(observations[0]) if observations else ['id','source_id','source_date','price_lbp_20l','raw_json'])


def coverage_gaps(dates, source):
    dates=sorted(set(dates))
    intervals=[(a,b,(date.fromisoformat(b)-date.fromisoformat(a)).days) for a,b in zip(dates,dates[1:])]
    by_year=defaultdict(list)
    for a,b,n in intervals:
        by_year[b[:4]].append(n)
    gaps=[]
    for a,b,n in intervals:
        typical=median(by_year[b[:4]])
        threshold=max(5,1.5*typical)
        if n>threshold:
            gaps.append({'source':source,'previous_observation':a,'next_observation':b,'elapsed_days':n,
                'within_year_median_days':typical,'status':'suspected_gap_not_proven_missing_decisions'})
    return gaps


def report(store, directory, as_of, stale_after_days=10):
    as_of=date.fromisoformat(as_of)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    ledger=store.ledger()
    verified=[r for r in ledger if r['verification_status'] in VERIFIED]
    documents=[r for r in ledger if r['verification_status']=='document_verified']
    source_rows=defaultdict(list)
    for row in store.db.execute('SELECT * FROM observations ORDER BY source_date,id'):
        source_rows[row['source_id']].append(dict(row))
    counts={}
    all_gaps=[]
    frequency=[]
    missing=[]
    dates_by_source={s:{r['source_date'] for r in rows if r['source_date'] and r['is_valid']} for s,rows in source_rows.items()}
    union=set().union(*dates_by_source.values()) if dates_by_source else set()
    for source,rows in source_rows.items():
        dates=sorted(dates_by_source[source])
        source_prices=defaultdict(set)
        for row in rows:
            if row['is_valid']: source_prices[row['source_date']].add(row['price_lbp_20l'])
        successful_runs=[dict(r) for r in store.db.execute("SELECT id,finished_at,details FROM collection_runs WHERE source_id=? AND status='success' ORDER BY id DESC LIMIT 1",(source,))]
        for run in successful_runs:run['details']=json.loads(run['details'])
        counts[source]={
            'unique_source_observations':len(rows),'valid_unique_dates':len(dates),
            'earliest_source_date':dates[0] if dates else None,'latest_source_date':dates[-1] if dates else None,
            'age_days':(as_of-date.fromisoformat(dates[-1])).days if dates else None,
            'stale':bool(dates and (as_of-date.fromisoformat(dates[-1])).days>stale_after_days),
            'invalid_observations':sum(not r['is_valid'] for r in rows),
            'within_source_conflict_dates':[d for d,v in source_prices.items() if len(v)>1],
            'duplicate_date_extra_observations':len([r for r in rows if r['is_valid']])-len(dates),
            'exact_duplicate_rows_in_captures':store.db.execute('SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM sightings si JOIN captures c ON c.id=si.capture_id WHERE c.source_id=? GROUP BY si.capture_id,si.observation_id HAVING n>1)',(source,)).fetchone()[0],
            'last_successful_run':successful_runs[0] if successful_runs else None,
        }
        all_gaps+=coverage_gaps(dates,source)
        for year in sorted({d[:4] for d in dates}):
            year_dates=[date.fromisoformat(d) for d in dates if d.startswith(year)]
            deltas=[(b-a).days for a,b in zip(year_dates,year_dates[1:])]
            frequency.append({'source':source,'year':year,'unique_dates':len(year_dates),'median_interval_days':median(deltas) if deltas else None,'weekdays':dict(Counter(d.strftime('%A') for d in year_dates))})
        if source in {'ipt','ministry'}:
            for day in sorted(union-set(dates)):
                if dates and dates[0]<=day<=as_of.isoformat():
                    missing.append({'source_missing_date':source,'date':day,'present_in_sources':sorted(s for s,ds in dates_by_source.items() if day in ds),'status':'cross_source_date_absent_not_proven_missing_decision'})
    integrity=[]
    for capture in store.db.execute('SELECT DISTINCT raw_path,sha256 FROM captures'):
        path=store.root/capture['raw_path']
        if not path.is_file() or sha256(path.read_bytes()).hexdigest()!=capture['sha256']:
            integrity.append(capture['raw_path'])
    official=source_rows.get('ministry',[])
    official_ids={(r['source_date'][:4],r['decision_number']) for r in official if r['source_date'] and r['decision_number']}
    duplicate_keys=defaultdict(set)
    for r in official:
        if r['decision_number']:duplicate_keys[(r['source_date'][:4],r['decision_number'])].add(r['source_date'])
    summary={
        'generated_at':now_utc(),'as_of_beirut':as_of.isoformat(),'timezone':'Asia/Beirut',
        'ledger_unique_dates':len(ledger),'status_counts':dict(Counter(r['verification_status'] for r in ledger)),
        'earliest_verified_archive_or_document':verified[0]['source_date'] if verified else None,
        'latest_verified_archive_or_document':verified[-1]['source_date'] if verified else None,
        'earliest_document_verified':documents[0]['source_date'] if documents else None,
        'latest_document_verified':documents[-1]['source_date'] if documents else None,
        'document_verified_count':len(documents),
        'raw_integrity_failures':integrity,
        'unique_observed_official_archive_decision_ids':len(official_ids),
        'official_archive_dates_without_decision_id':len({r['source_date'] for r in official if not r['decision_number']}),
        'total_historical_official_decisions':'unknown: archive coverage is incomplete; date-only rows do not certify unique decisions',
        'conflict_dates':[r['source_date'] for r in ledger if r['verification_status']=='conflict'],
        'issue_counts':dict(Counter(i for r in ledger for i in r['issues'])),
        'missing_publication_timestamp_observations':sum(not r['publication_timestamp'] for rows in source_rows.values() for r in rows),
        'unknown_effective_date_observations':sum(not r['official_effective_date'] for rows in source_rows.values() for r in rows),
        'gap_candidates':len(all_gaps),'cross_source_absent_dates':len(missing),
        'official_ids_on_multiple_dates':{f'{k[0]}/{k[1]}':sorted(v) for k,v in duplicate_keys.items() if len(v)>1},
        'sources':counts,
        'collection_runs':[dict(r) for r in store.db.execute('SELECT id,source_id,started_at,finished_at,status,details FROM collection_runs ORDER BY id')],
        'readiness':'Adequate for source reconciliation and exploratory target analysis. Not ready for an institutional as-of forecasting backtest: effective/release times, unresolved conflicts, coverage and regimes need review.',
    }
    (directory/'data_quality.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    write_csv(directory/'gap_candidates.csv',all_gaps,['source','previous_observation','next_observation','elapsed_days','within_year_median_days','status'])
    write_csv(directory/'cross_source_missing_dates.csv',missing,['source_missing_date','date','present_in_sources','status'])
    write_csv(directory/'frequency_by_year.csv',frequency,['source','year','unique_dates','median_interval_days','weekdays'])
    conflicts=[r for r in ledger if r['verification_status']=='conflict']
    write_csv(directory/'conflicting_observations.csv',conflicts,['source_date','candidate_values','observation_ids','issues'])
    lines=['# Lebanese gasoline 95 data quality report','',f'As of {as_of.isoformat()}, Asia/Beirut. Generated {summary["generated_at"]}. Counts are database queries over actual captures.','',
        '| Completion measure | Observed result |','| --- | --- |',
        f'| Earliest archive-corroborated or document-verified date | {summary["earliest_verified_archive_or_document"]} |',
        f'| Latest archive-corroborated or document-verified date | {summary["latest_verified_archive_or_document"]} |',
        f'| Original-document verified dates | {summary["document_verified_count"]}; {summary["earliest_document_verified"]} to {summary["latest_document_verified"]} |',
        f'| Unique observed official archive IDs (year + number) | {len(official_ids)}; incomplete archive, not the total historical decision count |',
        f'| Archive dates without ID | {summary["official_archive_dates_without_decision_id"]} |',
        f'| Candidate ledger dates | {len(ledger)} |',
        f'| Conflict dates, quarantined | {len(conflicts)} |','',
        'Verification: `document_verified` requires an original government PDF and recorded review. `archive_corroborated` means government HTML and IPT agree on a dated price; it does not authenticate an original decision or its publication time. Taqtek shares ministry lineage and cannot independently establish official truth. No source-labelled date is invented as an effective date.','',
        '## Source coverage','', '| Source | Observations | Unique valid dates | Earliest | Latest | Age days | Stale |','| --- | ---: | ---: | --- | --- | ---: | --- |']
    for source,c in counts.items():
        lines.append(f'| {source} | {c["unique_source_observations"]} | {c["valid_unique_dates"]} | {c["earliest_source_date"]} | {c["latest_source_date"]} | {c["age_days"]} | {c["stale"]} |')
    ipt_run=counts.get('ipt',{}).get('last_successful_run')
    if ipt_run:
        lines+=['',f'Latest successful IPT import parsed {ipt_run["details"].get("parsed_rows")} original rows. Semantic observations and unique dates differ because all raw row occurrences, including duplicates and same-day alternatives, are retained in `sightings`.']
    lines+=['','## Retrieved examples','', '| Source-labelled date | Price LBP/20 L | Verification | Official effective date |','| --- | ---: | --- | --- |']
    example_days={counts.get('ipt',{}).get('earliest_source_date'),counts.get('ipt',{}).get('latest_source_date'),summary['earliest_document_verified'],summary['latest_document_verified'],summary['latest_verified_archive_or_document']}
    for row in ledger:
        if row['source_date'] in example_days:
            lines.append(f'| {row["source_date"]} | {row["price_lbp_20l"]} | {row["verification_status"]} | {row["official_effective_date"] or "unknown"} |')
    lines+=['','## Gaps and frequency','',f'{len(all_gaps)} unusually long observed intervals are listed in [gap_candidates.csv](gap_candidates.csv). The threshold is greater than max(5 days, 1.5 × that source/year median interval). These are investigation candidates, not fabricated missing decision dates. Cross-source absent dates are listed in [cross_source_missing_dates.csv](cross_source_missing_dates.csv). A source gap is not proof of a nonpublication.',
        '', 'Observed frequency by year is in [frequency_by_year.csv](frequency_by_year.csv); the ledger is a decision-event series, not a generated daily panel. No forward fill or interpolation is applied. Regime labels are provisional research buckets, not verified tax/FX boundaries.','',
        '## Conflicts and limitations','',f'Status counts: `{json.dumps(summary["status_counts"],sort_keys=True)}`. All contradictory valid source values remain in the immutable observation table; disputed dates have null canonical prices. [conflicting_observations.csv](conflicting_observations.csv) links them to observation IDs.',
        '',f'Unknown publication timestamps: {summary["missing_publication_timestamp_observations"]} observations. Unknown official effective dates: {summary["unknown_effective_date_observations"]}. Original Excel/HTML dates have no invented midnight release timestamp. Retrieval is stored in UTC and rendered with Asia/Beirut rules.',
        '', 'Changes in the export are relative to the previous eligible verified record, with its date and an explicit basis. They are not asserted to be changes from the immediately preceding official decision. Sparse verified history cannot establish that predecessor.','',
        'Source/revision priority: original decision 1, ministry HTML 2, IPT 3, Taqtek 4, unverified manual 5. Priority never silently settles a contradiction. A reviewed resolution appends an audit event and a ledger version. Same-day multiple official decisions remain ambiguous without decision IDs/times; they are not guessed or collapsed into a verified event sequence.','',
        '## Model readiness','',summary['readiness'],'', 'See [source assessment](../research/data_source_assessment.md), [assumptions](../research/verified_assumptions.md) and [update instructions](../docs/data_updates.md).']
    lines+=['',f'Raw integrity: {len(integrity)} missing or hash-mismatched captured files. `date_alignment_review` records are excluded from verified exports pending review of inconsistent source weekday/date labels.']
    longest=sorted([g for g in all_gaps if g['source']=='ipt'],key=lambda g:g['elapsed_days'],reverse=True)[:5]
    if longest:
        lines+=['','## Longest IPT intervals to investigate','', '| Previous observation | Next observation | Elapsed days |','| --- | --- | ---: |']
        for gap in longest:
            lines.append(f'| {gap["previous_observation"]} | {gap["next_observation"]} | {gap["elapsed_days"]} |')
    (directory/'data_quality.md').write_text('\n'.join(lines)+'\n')
    return summary
