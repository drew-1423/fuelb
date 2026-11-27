"""Trailing financial features from an explicitly bounded information set."""
from bisect import bisect_right
from datetime import date, datetime, timedelta
from math import log, sqrt
from statistics import mean, median, stdev
from zoneinfo import ZoneInfo

from lebanon_fuel.domain import utc_timestamp
from lebanon_fuel.market.catalog import SERIES


def trailing_features(history,spec,origin):
    """No filling, fitting, centered windows, or whole-sample thresholds.

    Return units are fractions, volatility is annualized log-return standard
    deviation using 252 daily / 52 weekly observations as a stated convention.
    A 'daily' return is named one-observation return because holidays exist.
    """
    origin=utc_timestamp(origin)
    eligible=[r for r in history if r['available_at']<=origin]
    if not eligible:
        return {'status':'no_available_observation','value':None,'observation_ids':[]}
    last=eligible[-1]
    day=date.fromisoformat(last['observation_date'])
    local_day=datetime.fromisoformat(origin).astimezone(ZoneInfo(spec.timezone)).date()
    age=(local_day-day).days
    if age<0:
        raise ValueError('Future observation cannot enter features')
    assumed=any(r['availability_basis']=='assumed_lag_latest_vintage_NOT_BACKTEST' for r in eligible[-1:])
    allowed_age=spec.stale_days+(spec.research_lag_days if assumed else 0)
    if age>allowed_age:
        return {'status':'stale','value':None,'latest_observation_date':day.isoformat(),
                'age_calendar_days':age,'observation_ids':[last['id']]}
    # One sparse policy observation is not a daily rate; it expires after its limit.
    tail=eligible[-273:]
    days=[date.fromisoformat(r['observation_date']) for r in tail]
    values=[r['value'] for r in tail]
    max_gap=10 if spec.frequency=='daily' else 21
    def ratio_at(days_ago):
        idx=bisect_right(days,day-timedelta(days=days_ago))-1
        if idx<0 or (day-timedelta(days=days_ago)-days[idx]).days>max_gap:
            return None
        return values[-1]/values[idx]-1
    one=None
    if len(values)>1 and (days[-1]-days[-2]).days<=max_gap:
        one=values[-1]/values[-2]-1
    logs=[log(values[i]/values[i-1]) if (days[i]-days[i-1]).days<=max_gap else None for i in range(1,len(values))]
    annual=252 if spec.frequency=='daily' else 52
    def vol_at(end):
        sample=logs[max(0,end-20):end]
        return stdev(sample)*sqrt(annual) if len(sample)==20 and all(v is not None for v in sample) else None
    vol=vol_at(len(logs))
    past=[vol_at(i) for i in range(20,len(logs))]
    past=[v for v in past if v is not None]
    continuous20=len(values)>=20 and all((b-a).days<=max_gap for a,b in zip(days[-20:],days[-19:]))
    avg20=mean(values[-20:]) if continuous20 else None
    result={
        'status':'available','value':values[-1],'unit':spec.normalized_unit,
        'latest_observation_date':day.isoformat(),'age_calendar_days':age,'allowed_age_days':allowed_age,
        'return_1_observation':one,'return_7_calendar_days':ratio_at(7),
        'momentum_30_calendar_days':ratio_at(30),
        'rolling_mean_5_observations':mean(values[-5:]) if len(values)>=5 and all((b-a).days<=max_gap for a,b in zip(days[-5:],days[-4:])) else None,
        'rolling_mean_20_observations':avg20,
        'volatility_20_returns_annualized':vol,
        'trend_above_trailing_mean20':int(values[-1]>avg20) if avg20 is not None else None,
        'high_vol_vs_prior_trailing_median':int(vol>median(past)) if vol is not None and len(past)>=20 else None,
        'lag_1_observation_value':values[-2] if one is not None else None,
        'max_available_at':max(r['available_at'] for r in tail),
        'availability_basis':sorted({r['availability_basis'] for r in tail}),
        'observation_ids':[r['id'] for r in tail],
    }
    for window in (3,4,5,10):
        contiguous = len(values)>=window and all((b-a).days<=max_gap for a,b in zip(days[-window:],days[-window+1:]))
        result[f'mean{window}'] = mean(values[-window:]) if contiguous else None
    for window in (3,5):
        contiguous = len(values)>window and all((b-a).days<=max_gap for a,b in zip(days[-window-1:],days[-window:]))
        result[f'return{window}'] = values[-1]/values[-window-1]-1 if contiguous else None
    result['short_window_convention'] = 'trailing_observed_sessions_not_calendar_days'
    if spec.normalized_unit == 'USD/bbl':
        from lebanon_fuel.market.catalog import BARREL_LITERS
        result['value_usd_kl'] = values[-1]*1000/BARREL_LITERS
    return result


def snapshot(store,origin,mode='strict'):
    origin=utc_timestamp(origin)
    histories={sid:store.history(sid,origin,mode) for sid in SERIES}
    return from_histories(histories,origin,mode)


def from_histories(histories,origin,mode):
    origin=utc_timestamp(origin)
    result={'origin_utc':origin,'origin_beirut':datetime.fromisoformat(origin).astimezone(ZoneInfo('Asia/Beirut')).isoformat(),
            'mode':mode,'backtest_eligible':mode in {'strict', 'captured'},'series':{}}
    for sid,spec in SERIES.items():
        result['series'][sid]=trailing_features(histories.get(sid,[]),spec,origin)
    # Synchronized calendar observations, not independent stale leg fills.
    brent={r['observation_date']:r for r in histories.get('brent_spot',[]) if r['available_at']<=origin}
    gasoline={r['observation_date']:r for r in histories.get('nyh_gasoline',[]) if r['available_at']<=origin}
    dates=sorted(set(brent)&set(gasoline))
    spread={'value':None,'unit':'USD/bbl','role':'cross_region_gross_price_spread_NOT_refinery_profit'}
    if dates:
        a,b=brent[dates[-1]],gasoline[dates[-1]]
        age=(datetime.fromisoformat(origin).date()-date.fromisoformat(dates[-1])).days
        if age<=14:
            spread.update(value=b['value']-a['value'],observation_date=dates[-1],
                          observation_ids=[a['id'],b['id']],max_available_at=max(a['available_at'],b['available_at']))
    result['nyh_gasoline_minus_brent']=spread
    brent = {r['observation_date']:r for r in histories.get('brent_futures',[]) if r['available_at']<=origin}
    rbob = {r['observation_date']:r for r in histories.get('rbob_futures',[]) if r['available_at']<=origin}
    matched = sorted(set(brent)&set(rbob))
    futures_spread = dict(value=None,unit='USD/bbl',role='US_RBOB_minus_Brent_continuous_futures_NOT_refinery_profit')
    if matched and (datetime.fromisoformat(origin).date()-date.fromisoformat(matched[-1])).days<=7:
        a,b = rbob[matched[-1]], brent[matched[-1]]
        futures_spread.update(value=a['value']-b['value'],observation_date=matched[-1],
                              observation_ids=[a['id'],b['id']],max_available_at=max(a['available_at'],b['available_at']))
    result['rbob_minus_brent']=futures_spread
    return result
