"""Conditional calendar targets and decision targets, with explicit label maturity.

No row here is an observed daily official price. The latest-vintage research
assumption is exposed in every exported design row; strict mode is separate.
"""
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import numpy as np
import pandas as pd

from lebanon_fuel.market.catalog import SERIES, BARREL_LITERS
from lebanon_fuel.market.store import MarketStore

BEIRUT=ZoneInfo('Asia/Beirut')
STATUS='LATEST_VINTAGE_CONDITIONAL_ARCHIVE_RESEARCH_NOT_REAL_TIME'


def midnight(day):
    return datetime.combine(date.fromisoformat(day),time(),BEIRUT)


def known_at(row):
    # This is an explicitly assumed research timestamp, not a stored source publication time.
    return datetime.combine(date.fromisoformat(row['source_date'])+timedelta(days=1),time(),BEIRUT)


def horizon_ids(config):
    return [f'decision_{n}' for n in config['targets']['decisions']]+[f'day_{n}' for n in config['targets']['calendar_days']]


def valid_record(row,config):
    return row['verification_status'] in config['target_statuses'] and row.get('price_lbp_20l') is not None and row['price_lbp_20l']>0


def ovx_features(rows):
    """Leak-free features from eligible OVX closes already selected at an origin."""
    result=dict(x_ovx_level=np.nan,x_ovx_5d_change=np.nan,x_ovx_20d_change=np.nan,
                x_ovx_252d_percentile=np.nan,ovx_regime=None,x_ovx_regime=np.nan,
                ovx_regime_basis='unavailable_insufficient_or_stale_cboe_ovx_history')
    if not rows:return result
    values=np.asarray([row['value'] for row in rows],dtype=float)
    days=[date.fromisoformat(row['observation_date']) for row in rows]
    gaps=[(b-a).days for a,b in zip(days,days[1:])]
    result['x_ovx_level']=float(values[-1])
    if len(values)>=6 and max(gaps[-5:])<=10:
        result['x_ovx_5d_change']=float(values[-1]-values[-6])
    if len(values)>=21 and max(gaps[-20:])<=10:
        result['x_ovx_20d_change']=float(values[-1]-values[-21])
    window=values[-252:]
    window_days=days[-252:]
    if len(window)==252 and (window_days[-1]-window_days[0]).days<=366 and max(gaps[-251:])<=10:
        percentile=100.0*float(np.count_nonzero(window<=values[-1]))/252.0
        if percentile<25:regime,ordinal='Low',0
        elif percentile<75:regime,ordinal='Normal',1
        elif percentile<90:regime,ordinal='Elevated',2
        else:regime,ordinal='Stress',3
        result.update(x_ovx_252d_percentile=percentile,ovx_regime=regime,x_ovx_regime=float(ordinal),
                      ovx_regime_basis='252 observed closes; percentile thresholds: <25 Low, <75 Normal, <90 Elevated, otherwise Stress')
    return result


def label_for(rows,index,at,horizon,config):
    """Require contiguous eligible source records. Missing coverage is never a zero change."""
    kind,n=horizon.split('_');n=int(n)
    if kind=='decision':
        end=index+n
        if end>=len(rows):return None,'right_censored'
        witness=end;endpoint=known_at(rows[end])
    else:
        endpoint=datetime.combine(at.date()+timedelta(days=n),time.fromisoformat(config.get('origin_local_time','00:00')),BEIRUT)
        times=[known_at(r) for r in rows]
        end=bisect_right(times,endpoint)-1;witness=end+1
        if witness>=len(rows):return None,'missing_calendar_coverage_witness'
    if end<index:return None,'endpoint_before_origin'
    path=rows[index:witness+1]
    if not all(valid_record(r,config) for r in path):return None,'unverified_or_conflicting_path'
    if any((date.fromisoformat(b['source_date'])-date.fromisoformat(a['source_date'])).days>config['maximum_gap_days'] for a,b in zip(path,path[1:])):
        return None,'coverage_gap_over_limit'
    final=rows[end]
    maturity=max(endpoint,known_at(rows[witness]))
    return dict(target_change_lbp_20l=final['price_lbp_20l']-rows[index]['price_lbp_20l'],
                endpoint_price_lbp_20l=final['price_lbp_20l'],label_end=maturity.astimezone(timezone.utc).isoformat(),
                endpoint=endpoint.isoformat(),target_source_date=final['source_date'],
                target_revision_id=final['revision_id'],witness_revision_id=rows[witness]['revision_id'],
                target_status=final['verification_status'],observed_updates=end-index,
                target_interpretation='kth_next_recorded_decision' if kind=='decision' else 'conditional_last_recorded_price_at_endpoint',
                effective_price_certified=False),None


class MarketFeatures:
    """Explicit close-based research or strict captured information, never conflated."""
    def __init__(self,store,config):
        self.config=config
        now=datetime.now(timezone.utc).isoformat()
        self.mode=config.get('market_availability_mode','research')
        self.histories={s:store.history(s,now,mode=self.mode) for s in config['series']}
        self.timestamps={s:np.array([datetime.fromisoformat(r['available_at']).timestamp() for r in h]) for s,h in self.histories.items()}
        self.cache={}

    def at(self,at):
        key=at.isoformat()
        if key in self.cache:return self.cache[key]
        result={};used=set();available=[];last={};ovx_rows=[]
        for sid,history in self.histories.items():
            stop=int(np.searchsorted(self.timestamps[sid],at.timestamp(),side='right'))
            history_window=273 if sid=='cboe_ovx' else 80
            h=history[max(0,stop-history_window):stop];prefix='x_'+sid+'_'
            value=ret7=ret30=vol=mean5=mean20=lag7=lag14=np.nan
            short = {k:np.nan for k in ('mean3','mean4','mean10','return3','return5')}
            age=(at.date()-date.fromisoformat(h[-1]['observation_date'])).days if h else None
            legacy = getattr(self,'mode','strict')=='research'
            if h and age is not None and 0<=age<=SERIES[sid].stale_days+(SERIES[sid].research_lag_days if legacy else 0):
                values=np.array([r['value'] for r in h]);days=[date.fromisoformat(r['observation_date']) for r in h]
                value=float(values[-1]);last[sid]=h[-1]
                if sid=='cboe_ovx':ovx_rows=h
                maxgap=10 if SERIES[sid].frequency=='daily' else 21
                def lag_value(n):
                    pos=bisect_right(days,days[-1]-timedelta(days=n))-1
                    if pos<0 or (days[-1]-timedelta(days=n)-days[pos]).days>maxgap:return np.nan
                    return values[pos]
                lag7,lag14=lag_value(7),lag_value(14);old30=lag_value(30)
                ret7=value/lag7-1 if np.isfinite(lag7) else np.nan
                ret30=value/old30-1 if np.isfinite(old30) else np.nan
                gaps=[(b-a).days for a,b in zip(days,days[1:])]
                if len(values)>=5 and max(gaps[-4:])<=maxgap:mean5=float(values[-5:].mean())
                for n in (3,4,10):
                    if len(values)>=n and max(gaps[-n+1:])<=maxgap:short[f'mean{n}']=float(values[-n:].mean())
                for n in (3,5):
                    if len(values)>n and max(gaps[-n:])<=maxgap:short[f'return{n}']=float(values[-1]/values[-n-1]-1)
                if len(values)>=21 and max(gaps[-20:])<=maxgap:
                    mean20=float(values[-20:].mean());vol=float(np.std(np.diff(np.log(values[-21:])),ddof=1))
                for r in h:used.add((r['id'],r['capture_id']))
                available.append(h[-1]['available_at'])
            for k,v in dict(value=value,return7=ret7,momentum30=ret30,volatility20=vol,mean5=mean5,mean20=mean20,lag7=lag7,lag14=lag14,**short).items():
                if sid in {'nyh_gasoline','brent_spot','rbob_futures','brent_futures','gasoil_futures'} or k in {'value','return7'}:
                    result[prefix+k]=v
            if sid in {'nyh_gasoline','brent_spot','rbob_futures','brent_futures','gasoil_futures'}:
                result[prefix+'value_usd_kl']=value*1000/BARREL_LITERS
        a,b=last.get('nyh_gasoline'),last.get('brent_spot')
        result['x_nyh_minus_brent']=a['value']-b['value'] if a and b and a['observation_date']==b['observation_date'] else np.nan
        a,b=last.get('rbob_futures'),last.get('brent_futures')
        result['x_rbob_minus_brent']=a['value']-b['value'] if a and b and a['observation_date']==b['observation_date'] else np.nan
        result.update(ovx_features(ovx_rows))
        for name,preferred,fallback in [('refined_gasoline','rbob_futures','nyh_gasoline'),('brent','brent_futures','brent_spot')]:
            required=self.config.get('energy_source_override',{}).get(name)
            selected=(required if required in last else None) if required else (preferred if preferred in last else fallback if fallback in last else None)
            result[name+'_source']=selected
            for k in ('value','value_usd_kl','mean3','mean4','mean5','mean10','mean20','return3','return5','return7'):
                result[f'x_{name}_{k}']=result.get(f'x_{selected}_{k}',np.nan) if selected else np.nan
        result['market_provenance_json']=json.dumps(sorted(used))
        result['max_assumed_market_available_at']=max(available) if available else None
        if available:assert datetime.fromisoformat(result['max_assumed_market_available_at'])<=at
        self.cache[key]=result
        return result


def structural_delta(past, at, market, config):
    """First-difference sensitivity under explicit constant-policy assumptions.

    Compare the same product series at both window endpoints. No cross-product
    splice, actual FX assertion, or tax-causation claim is made by this feature.
    """
    assumptions=config.get('structural_delta',{})
    bank=assumptions.get('bank_factor',1.01);vat=assumptions.get('vat_factor',1.11)
    clock=time.fromisoformat(config.get('origin_local_time','03:00'))
    base=past[-1]
    previous_origin=datetime.combine(date.fromisoformat(base['source_date']),clock,BEIRUT)
    current=market.at(at);previous=market.at(previous_origin)
    candidates=[assumptions['benchmark_series']] if assumptions.get('benchmark_series') else ['rbob_futures','nyh_gasoline']
    selected=next((sid for sid in candidates
                   if np.isfinite(current.get(f'x_{sid}_mean4',np.nan)) and np.isfinite(previous.get(f'x_{sid}_mean4',np.nan))),None)
    output=dict(x_structural_delta_lbp_20l=np.nan,structural_benchmark_source=selected,
                structural_previous_window_origin=previous_origin.isoformat(),structural_fx_assumption=None,
                structural_assumptions='constant_charges_and_FX_between_decisions; user-specified_bank_1.01_VAT_1.11; latest-vintage_market_proxy')
    if not selected:return output
    change_kl=(current[f'x_{selected}_mean4']-previous[f'x_{selected}_mean4'])*1000/BARREL_LITERS
    if at.date()>=date.fromisoformat(assumptions.get('stabilized_start','2023-05-12')):
        fx=assumptions.get('fx_lbp_per_usd',89700.)
        scale=fx*bank*vat/50
        output['structural_fx_assumption']=f'{fx} LBP/USD constant research assumption, not verified daily pricing FX'
    else:
        ratios=[]
        for row in past[-20:]:
            if not valid_record(row,config):continue
            when=datetime.combine(date.fromisoformat(row['source_date']),clock,BEIRUT)
            mean4=market.at(when).get(f'x_{selected}_mean4',np.nan)
            if np.isfinite(mean4) and mean4>0:
                ratios.append(row['price_lbp_20l']/(mean4*1000/BARREL_LITERS))
        if len(ratios)<5:return output
        # All-in ratio already includes tax/fees; applying them again double counts.
        scale=float(np.median(ratios))
        output['structural_fx_assumption']='trailing median domestic-price/product ratio; includes charges, not an exchange-rate observation'
    output['x_structural_delta_lbp_20l']=float(change_kl*scale)
    output['structural_market_provenance_json']=json.dumps(sorted(set(map(tuple,json.loads(current['market_provenance_json'])))|set(map(tuple,json.loads(previous['market_provenance_json'])))))
    return output


def features_at(rows,index,at,market,config):
    """Future rows are never passed to this function by the dataset constructor."""
    past=rows[:index+1];base=past[-1]
    if len(past)<config['minimum_domestic_history'] or not valid_record(base,config):return None
    result=dict(market.at(at));changes=[];intervals=[]
    tail_rows=past[-21:]
    for a,b in zip(tail_rows,tail_rows[1:]):
        gap=(date.fromisoformat(b['source_date'])-date.fromisoformat(a['source_date'])).days
        if valid_record(a,config) and valid_record(b,config) and gap<=config['maximum_gap_days']:
            changes.append(b['price_lbp_20l']-a['price_lbp_20l']);intervals.append(gap)
        else:changes.append(np.nan)
    for lag in (1,2,3):result[f'x_domestic_change_lag{lag}']=changes[-lag] if len(changes)>=lag else np.nan
    tail=np.array(changes[-5:],float)
    result['x_domestic_change_mean5']=float(np.mean(tail)) if len(tail)==5 and np.isfinite(tail).all() else np.nan
    result['x_domestic_change_vol5']=float(np.std(tail,ddof=1)) if len(tail)==5 and np.isfinite(tail).all() else np.nan
    result['x_interval_median']=float(np.median(intervals)) if intervals else np.nan
    result['x_days_since_source_date']=(at.date()-date.fromisoformat(base['source_date'])).days
    result['x_weekday']=at.weekday()
    result['x_month_sin']=float(np.sin(2*np.pi*at.month/12));result['x_month_cos']=float(np.cos(2*np.pi*at.month/12))
    result['x_last_price']=float(base['price_lbp_20l'])
    result['base_price_lbp_20l']=base['price_lbp_20l'];result['base_revision_id']=base['revision_id']
    result['base_source_date']=base['source_date'];result['base_status']=base['verification_status']
    result['domestic_provenance_json']=json.dumps([r['revision_id'] for r in past[-21:]])
    result['next_announcement_expected_wait_days']=float(np.mean([x-result['x_days_since_source_date'] for x in intervals if x>result['x_days_since_source_date']])) if sum(x>result['x_days_since_source_date'] for x in intervals)>=5 else None
    result['next_announcement_timing_status']='empirical_observed_intervals_not_official_schedule'
    # Anchored cost change: current product level vs trailing 20-quote cost window.
    result['x_structural_cost_gap']=result['x_nyh_gasoline_value']-result['x_nyh_gasoline_mean20']
    if config.get('structural_delta',{}).get('enabled'):
        result.update(structural_delta(past,at,market,config))
        last_change=result['x_domestic_change_lag1']
        result['x_fiscal_shock_lag1']=float(abs(last_change)>config['structural_delta'].get('shock_threshold_lbp',150000)) if np.isfinite(last_change) else np.nan
        result['fiscal_shock_interpretation']='large_lagged_price_move_not_verified_tax_event'
    return result


def build(root,config):
    root=Path(root);store=MarketStore(root);market=MarketFeatures(store,config)
    try:
        full=store.ledger();records=[];evaluation=[];excluded=[];snapshots=[];evaluation_snapshots=[]
        for regime in config['regimes']:
            end=regime.get('evaluation_end',regime['development_end'])
            rows=[r for r in full if regime['start']<=r['source_date']<=end]
            if not rows:continue
            times=[known_at(r) for r in rows]
            clock=time.fromisoformat(config.get('origin_local_time','00:00'))
            first=datetime.combine(times[0].date(),clock,BEIRUT)
            last=datetime.combine(date.fromisoformat(end),clock,BEIRUT)
            at=first
            while at<=last:
                index=bisect_right(times,at)-1
                if index<0:at+=timedelta(days=1);continue
                r=rows[index]
                if (at.date()-date.fromisoformat(r['source_date'])).days>config['maximum_gap_days']:
                    at+=timedelta(days=1);continue
                feature=features_at(rows[:index+1],index,at,market,config)
                if feature is None:at+=timedelta(days=1);continue
                origin=at.astimezone(timezone.utc).isoformat()
                partition='development' if at.date().isoformat()<=regime['development_end'] else 'evaluation'
                if partition=='evaluation' and at.date().isoformat()<regime.get('evaluation_start','9999-12-31'):
                    at+=timedelta(days=1);continue
                common=dict(origin=origin,origin_beirut=at.isoformat(),origin_date=at.date().isoformat(),regime=regime['id'],
                            sequence_index=index,day_index=(at-first).days,information_status=STATUS,
                            availability_mode=config.get('market_availability_mode','research'),partition=partition,**feature)
                (snapshots if partition=='development' else evaluation_snapshots).append(common)
                horizons=[f'day_{n}' for n in config['targets']['calendar_days']]
                if at.date()==times[index].date():horizons += [f'decision_{n}' for n in config['targets']['decisions']]
                for horizon in horizons:
                    label,reason=label_for(rows,index,at,horizon,config)
                    if reason:excluded.append(dict(regime=regime['id'],origin=origin,horizon=horizon,reason=reason));continue
                    if partition=='development' and datetime.fromisoformat(label['label_end'])>midnight(regime['development_end'])+timedelta(days=1):
                        excluded.append(dict(regime=regime['id'],origin=origin,horizon=horizon,reason='label_after_development_cutoff'));continue
                    (records if partition=='development' else evaluation).append(dict(**common,horizon=horizon,**label))
                at+=timedelta(days=1)
        frame=pd.DataFrame(records);snap=pd.DataFrame(snapshots)
        export=root/'data/exports/forecasting';export.mkdir(parents=True,exist_ok=True)
        frame.to_csv(export/'development_design.csv',index=False);snap.to_csv(export/'origin_features.csv',index=False)
        pd.DataFrame(evaluation,columns=frame.columns).to_csv(export/'holdout_evaluation_design.csv',index=False)
        pd.DataFrame(evaluation_snapshots,columns=snap.columns).to_csv(export/'holdout_origin_features.csv',index=False)
        reports=root/'reports/forecasting';reports.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(excluded).to_csv(reports/'excluded_targets.csv',index=False)
        return frame,snap
    finally:store.close()


def mature_training(frame,cutoff):
    """Mandatory purge for overlapping decision/calendar labels and coverage witnesses."""
    eligible=(pd.to_datetime(frame.origin,utc=True)<pd.Timestamp(cutoff)) & (pd.to_datetime(frame.label_end,utc=True)<pd.Timestamp(cutoff))
    if 'partition' in frame:eligible &= frame.partition.eq('development')
    return frame[eligible].copy()


def feature_columns(frame,distributed=False):
    columns=[c for c in frame if c.startswith('x_')]
    if not distributed:columns=[c for c in columns if not c.endswith(('_lag7','_lag14'))]
    return sorted(columns)
