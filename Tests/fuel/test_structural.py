"""Arithmetic and information-time invariants; synthetic inputs are never market observations."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest

from lebanon_fuel.structural.engine import price, BARREL_LITERS
from lebanon_fuel.structural.research import chronological_predictions,fit_predict,ecm_gate,MarketWindows
from lebanon_fuel.market.catalog import SERIES

ROOT=Path(__file__).resolve().parents[2]


def recorded():
    return deepcopy(json.loads((ROOT/'data/manual/structural_annexes.json').read_text())[-1]['request'])


def param(value,unit):
    p=recorded()['vat']
    return dict(p,value=str(value),unit=unit,status='scenario',known_at='2025-05-28T10:00:00+00:00',note='Synthetic test assumption')


def hypothetical(unit='USD/mt',value='800'):
    r=recorded();r.pop('goods_lbp_kl')
    r.update(benchmark=dict(param(value,unit),identity='SYNTHETIC_TEST_ONLY',basis='FOB',window_description='Synthetic fixed input'),
             fx=param(90000,'LBP/USD'),density=param('.755','kg/L'),freight_usd_kl=param(20,'USD/kl'),other_import_usd_kl=param(5,'USD/kl'))
    return r


def test_original_annex_arithmetic_and_units():
    records=json.loads((ROOT/'data/manual/structural_annexes.json').read_text())
    for r,expected in zip(records,['174303.30','1634996.70','1488998.40']):
        result=price(r['request'])
        assert D(result['price_lbp_20l'])==D(expected)
        assert D(result['vat_lbp_kl'])==D(r['printed_vat_lbp_kl'])
        assert sum(D(v) for v in result['breakdown_lbp_20l'].values())==D(expected)
        assert result['exact_official_formula'] is False
        assert result['uncertainty']['kind']=='not_quantified'


def test_mass_volume_and_barrel_equivalence():
    r=hypothetical();a=price(r)
    by_kl=hypothetical('USD/kl','604');by_barrel=hypothetical('USD/bbl',D('604')*BARREL_LITERS/1000)
    assert D(a['price_lbp_20l'])==D(price(by_kl)['price_lbp_20l'])==D(price(by_barrel)['price_lbp_20l'])


def test_cif_double_freight_and_duplicate_goods_rejected():
    r=hypothetical();r['benchmark']['basis']='CIF'
    with pytest.raises(ValueError,match='double count'):price(r)
    r['freight_usd_kl']['value']='0';price(r)
    r['goods_lbp_kl']=param(100,'LBP/kl')
    with pytest.raises(ValueError,match='mutually exclusive'):price(r)


@pytest.mark.parametrize('field,value',[('value',None),('value','nan'),('value',-1),('unit','LBP/L'),('status','official_guess')])
def test_unknown_invalid_or_wrong_units_fail_closed(field,value):
    r=recorded();r['goods_lbp_kl'][field]=value
    with pytest.raises((ValueError,KeyError)):price(r)


def test_stale_validity_and_future_knowledge_are_distinct():
    r=recorded();r['effective_date']='2025-05-30'
    with pytest.raises(ValueError,match='validity'):price(r)
    r=recorded();r['mode']='as_of';r['origin']='2025-05-29T00:00:00+03:00'
    with pytest.raises(ValueError,match='unavailable'):price(r)
    r=recorded();r['origin']='2025-05-29T00:00:00'
    with pytest.raises(ValueError,match='timezone'):price(r)


def test_tax_base_and_conditional_bounds():
    r=recorded();r['goods_lbp_kl'].update(low='58000000',high='60000000')
    out=price(r);u=out['uncertainty']
    assert D(u['low_lbp_20l'])<D(out['price_lbp_20l'])<D(u['high_lbp_20l'])
    assert u['probability'] is None
    old=D(out['price_lbp_20l']);r['costs'][0]['taxable']=False
    assert old-D(price(r)['price_lbp_20l'])==D('1022000')*D('.11')/50
    r['vat'].update(low='.1',high='11')
    with pytest.raises(ValueError,match='fraction'):price(r)


def test_scenario_cannot_be_laundered_as_known_input():
    r=hypothetical();r['mode']='as_of';r['origin']='2025-05-29T00:00:00+03:00'
    with pytest.raises(ValueError,match='scenario'):price(r)


def synthetic_frame(n=85):
    dates=pd.date_range('2020-01-01',periods=n,freq='7D').strftime('%Y-%m-%d')
    x=np.sin(np.arange(n)/3);change=x*100+np.cos(np.arange(n))*5
    return pd.DataFrame(dict(date=dates,origin=[d+'T00:00:00+03:00' for d in dates],regime='test',
                             previous=10000,actual=10000+change,change=change,delta__nyh_gasoline__w1__lag0=x,
                             target_status='synthetic',target_revision_id=np.arange(n),previous_revision_id=np.arange(n)-1))


def test_chronological_fit_and_calibration_ignore_future_targets():
    f=synthetic_frame();config=dict(minimum_train=24,minimum_calibration=20,calibration_window=40,nominal_interval_coverage=.9,rolling_training_observations=40)
    candidate=dict(id='test',family='linear',series='nyh_gasoline',window=1,lag=0)
    a=chronological_predictions(f,candidate,config)
    altered=f.copy();altered.loc[70:,'actual']+=1e8;altered.loc[70:,'change']+=1e8
    b=chronological_predictions(altered,candidate,config)
    pd.testing.assert_frame_equal(a[a.date<f.date[70]],b[b.date<f.date[70]])
    # Current target can alter its error, but must not alter its prediction or interval.
    for column in ('predicted','lower','upper'):
        assert a.loc[a.date==f.date[70],column].iloc[0]==b.loc[b.date==f.date[70],column].iloc[0]
    assert (a.train_end<a.date).all()
    with pytest.raises(ValueError,match='precede'):fit_predict(f,f.iloc[[0]],candidate,config)


def test_ecm_refuses_irregular_time_and_short_history():
    dates=pd.date_range('2020-01-01',periods=80,freq='7D').delete(4)
    result=ecm_gate(dates.astype(str).tolist(),np.arange(79),np.arange(79))
    assert result['eligible'] is False
    assert ecm_gate(['2020-01-01'],[1],[1])['eligible'] is False


def test_feature_availability_and_staleness():
    rows=[dict(value=10,id=1,available_at='2025-01-15T23:59:59+00:00',observation_date='2025-01-01')]
    w=MarketWindows(rows,SERIES['nyh_gasoline'])
    assert w.mean('2025-01-15T22:00:00+00:00',1,0) is None
    assert w.mean('2025-01-16T00:00:00+00:00',1,0)[0]==10
    assert w.mean('2025-02-15T00:00:00+00:00',1,0) is None


def test_no_duplicate_costs_or_implicit_official_rounding():
    r=recorded();r['costs'].append(deepcopy(r['costs'][0]))
    with pytest.raises(ValueError,match='unique'):price(r)
    r=recorded();r['rounding']=dict(status='official',increment_lbp_20l='1000',note='unverified')
    with pytest.raises(ValueError,match='hypothetical'):price(r)
