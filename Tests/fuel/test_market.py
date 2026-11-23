"""Synthetic fixtures exercise invariants; no fixture is reported as market data."""
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json
import sqlite3

from openpyxl import Workbook
import pytest

from lebanon_fuel.domain import utc_timestamp
from lebanon_fuel.domain import Observation
from lebanon_fuel.market.catalog import SERIES
from lebanon_fuel.market.collectors import ec_rows, eia_rows, fed_rows, manual_import, parse_capture
from lebanon_fuel.market.store import MarketStore
from lebanon_fuel.features.market import snapshot, trailing_features


@pytest.fixture
def market(tmp_path):
    s=MarketStore(tmp_path)
    yield s
    s.close()


def add(store,day='2025-01-01',value=100,seen='2025-01-02T12:00:00+00:00',sid='brent_spot',**extra):
    cap=store.capture(SERIES[sid].source,'https://example.org/public',str((day,value,extra)).encode(),
                      'text/csv',http_status=200,retrieved_at=seen)
    return store.ingest_market(cap,sid,[dict(date=day,value=value,row_key='1',**extra)])


def test_capture_availability_not_observation_or_publication_date(market):
    add(market,publication_timestamp='2025-01-01T18:00:00+00:00')
    assert market.history('brent_spot','2025-01-02T11:59:59+00:00')==[]
    assert market.history('brent_spot','2025-01-02T12:00:00+00:00')[0]['value']==100


def test_duplicate_prevention_and_audit(market):
    assert add(market)['new_observations']==1
    assert add(market)['new_observations']==0
    assert market.db.execute('SELECT COUNT(*) FROM market_sightings').fetchone()[0]==2
    with pytest.raises(sqlite3.IntegrityError):market.db.execute('UPDATE market_observations SET value=0')
    with pytest.raises(sqlite3.IntegrityError):market.db.execute('DELETE FROM market_sightings')


def test_changed_row_locations_and_package_metadata_are_not_new_prices(market):
    add(market,raw={'row':5,'package_prepared':'first','value':100})
    result=add(market,value='100.0',raw={'row':6,'package_prepared':'second','value':'100.0'},seen='2025-01-03T12:00:00+00:00')
    assert result['new_observations']==0
    assert market.db.execute('SELECT COUNT(*) FROM market_sightings').fetchone()[0]==2
    assert market.history('brent_spot','2025-01-04T00:00:00+00:00')[0]['value']==100


def test_revision_and_reversal_as_of(market):
    add(market,value=100)
    add(market,value=110,seen='2025-01-03T12:00:00+00:00')
    add(market,value=100,seen='2025-01-04T12:00:00+00:00')
    assert market.history('brent_spot','2025-01-02T18:00:00+00:00')[0]['value']==100
    assert market.history('brent_spot','2025-01-03T18:00:00+00:00')[0]['value']==110
    assert market.history('brent_spot','2025-01-04T18:00:00+00:00')[0]['value']==100
    assert market.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]==2


def test_simultaneous_conflict_quarantined(market):
    cap=market.capture('market_eia','https://example.org',b'conflict','text/csv',retrieved_at='2025-01-02T12:00:00+00:00')
    market.ingest_market(cap,'brent_spot',[{'date':'2025-01-01','value':v,'row_key':str(i)} for i,v in enumerate([100,110])])
    assert market.history('brent_spot','2025-01-03T00:00:00+00:00')==[]


@pytest.mark.parametrize('value',[None,'','.',0,-1,'nan','inf',True])
def test_invalid_values_preserved_but_excluded(market,value):
    add(market,value=value)
    assert market.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]==1
    assert market.history('brent_spot','2025-01-03T00:00:00+00:00')==[]


def test_invalid_revision_does_not_restore_older_value(market):
    add(market)
    add(market,value=None,seen='2025-01-03T12:00:00+00:00')
    assert market.history('brent_spot','2025-01-04T00:00:00+00:00')==[]


def test_unit_conversion_and_mismatch(market):
    add(market,sid='nyh_gasoline',value=2.5)
    r=market.history('nyh_gasoline','2025-01-03T00:00:00+00:00')[0]
    assert r['value']==105 and r['unit']=='USD/bbl' and r['raw_value']=='2.5'
    add(market,day='2025-01-02',unit='EUR/ton')
    assert market.history('brent_spot','2025-01-03T00:00:00+00:00')==[]


def test_future_date_and_publication(market):
    add(market,day='2025-01-05')
    add(market,publication_timestamp='2025-01-05T00:00:00+00:00')
    assert market.history('brent_spot','2025-01-06T00:00:00+00:00')==[]


def test_naive_origin_rejected(market):
    with pytest.raises(ValueError):snapshot(market,'2025-01-02T12:00:00')


def test_documented_vintage_needs_evidence_and_period_order(market):
    with pytest.raises(ValueError):add(market,vintage_timestamp='2025-01-01T22:00:00+00:00')
    with pytest.raises(ValueError):add(market,publication_timestamp='2024-12-30T10:00:00+00:00',
        vintage_timestamp='2024-12-30T22:00:00+00:00',vintage_evidence_url='https://example.org/archive')
    add(market,publication_timestamp='2025-01-01T20:00:00+00:00',
        vintage_timestamp='2025-01-01T22:00:00+00:00',vintage_evidence_url='https://example.org/original-edition')
    row=market.history('brent_spot','2025-01-01T22:00:00+00:00')[0]
    assert row['availability_basis']=='documented_historical_vintage'


def test_research_not_mislabeled_as_strict(market):
    add(market,seen='2026-01-01T12:00:00+00:00')
    assert snapshot(market,'2025-01-20T00:00:00+00:00')['series']['brent_spot']['value'] is None
    r=snapshot(market,'2025-01-20T00:00:00+00:00','research')
    assert r['series']['brent_spot']['value']==100
    assert r['backtest_eligible'] is False
    assert 'NOT_BACKTEST' in r['series']['brent_spot']['availability_basis'][0]


def test_future_mutation_cannot_change_past_snapshot(market):
    for i in range(25):
        day=date(2025,1,1)+timedelta(days=i)
        add(market,day=str(day),value=100+i,seen=f'{day}T23:00:00+00:00')
    origin='2025-01-25T23:00:00+00:00'
    before=snapshot(market,origin)
    add(market,day='2025-01-20',value=900,seen='2025-02-01T12:00:00+00:00')
    add(market,day='2025-02-01',value=1000,seen='2025-02-02T12:00:00+00:00')
    assert snapshot(market,origin)==before
    f=before['series']['brent_spot']
    assert f['rolling_mean_5_observations']==122
    assert f['return_7_calendar_days']==pytest.approx(124/117-1)
    assert f['max_available_at']<=origin


def test_no_long_gap_interpolation_or_stale_policy_carry(market):
    add(market,day='2025-01-01')
    add(market,day='2025-02-01',value=110,seen='2025-02-02T12:00:00+00:00')
    f=snapshot(market,'2025-02-03T00:00:00+00:00')['series']['brent_spot']
    assert f['return_1_observation'] is None and f['return_7_calendar_days'] is None
    assert snapshot(market,'2025-03-01T00:00:00+00:00')['series']['brent_spot']['status']=='stale'


def test_spread_matches_dates_and_units(market):
    add(market,value=80)
    add(market,sid='nyh_gasoline',value=2)
    f=snapshot(market,'2025-01-03T00:00:00+00:00')['nyh_gasoline_minus_brent']
    assert f['value']==4 and 'NOT_refinery_profit' in f['role']
    add(market,day='2025-01-02',value=90)
    assert snapshot(market,'2025-01-03T00:00:00+00:00')['nyh_gasoline_minus_brent']['value']==4


def test_weekends_and_dst_use_aware_capture_time(market):
    add(market,day='2025-10-24',seen='2025-10-27T16:00:00+02:00')
    assert snapshot(market,'2025-10-27T13:59:59+00:00')['series']['brent_spot']['value'] is None
    assert snapshot(market,'2025-10-27T14:00:00+00:00')['series']['brent_spot']['value']==100
    assert utc_timestamp('2025-10-27T16:00:00+02:00')=='2025-10-27T14:00:00+00:00'


def workbook_bytes(unit='1000 l',product='Euro-super 95  (I)'):
    w=Workbook();s=w.active;s.title='Prices wo taxes'
    s.append(['Consumer prices','IT_price_wo_tax_euro95','GR_price_wo_tax_euro95'])
    s.append([None,product,product]);s.append(['Date',unit,unit])
    s.append([datetime(2025,1,6),900,950]);s.append([datetime(2025,1,13),None,960])
    s.append(['Notes:',None,None])
    b=BytesIO();w.save(b);return b.getvalue()


def test_ec_product_and_unit_schema():
    rows=list(ec_rows(workbook_bytes(),'italy_gasoline_ex_tax'))
    assert rows[0]['value']==900 and rows[1]['value'] is None
    assert rows[0]['date']=='2025-01-06'
    with pytest.raises(ValueError):list(ec_rows(workbook_bytes(unit='t'),'italy_gasoline_ex_tax'))
    with pytest.raises(ValueError):list(ec_rows(workbook_bytes(product='Diesel'),'italy_gasoline_ex_tax'))


def test_fed_missing_and_schema():
    xml=b'''<Message><Prepared>2025-01-03T12:00:00</Prepared><Series SERIES_NAME="RXI$US_N.B.EU" FREQ="9" CURRENCY="EUR"><AnnotationText>USD per EUR</AnnotationText><Obs TIME_PERIOD="2025-01-01" OBS_STATUS="ND" OBS_VALUE="-9999"/><Obs TIME_PERIOD="2025-01-02" OBS_STATUS="A" OBS_VALUE="1.1"/></Series></Message>'''
    def zipped(content):
        b=BytesIO()
        with ZipFile(b,'w') as z:z.writestr('H10_data.xml',content)
        return b.getvalue()
    rows=list(fed_rows(zipped(xml)))
    assert rows[0]['value'] is None and rows[1]['value']=='1.1'
    with pytest.raises(ValueError):list(fed_rows(zipped(xml.replace(b'USD per EUR',b'EUR per USD'))))


def test_atomic_parse_failure(market):
    cap=market.capture('market_eia','https://example.org',b'original','text/csv',retrieved_at='2025-01-03T12:00:00+00:00')
    rows=[{'date':'2025-01-01','value':100,'row_key':'1'},{'date':'bad-date','value':101,'row_key':'2'}]
    with pytest.raises(ValueError):market.ingest_market(cap,'brent_spot',rows)
    assert market.db.execute('SELECT COUNT(*) FROM market_observations').fetchone()[0]==0


def test_actual_download_replays_and_header_guard(market):
    # An actual saved EIA download; test never performs network access.
    path=Path(__file__).parents[2]/'research/evidence/market_probe/brent.xls'
    raw=path.read_bytes()
    rows=list(eia_rows(raw,'brent_spot'))
    assert rows[0]['date']=='1987-05-20' and rows[0]['value']==18.63
    with pytest.raises(ValueError):list(eia_rows(raw,'nyh_gasoline'))
    cap=market.capture('market_eia','https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls',raw,'application/vnd.ms-excel',http_status=200,retrieved_at='2026-11-10T23:00:00+00:00')
    a=parse_capture(market,cap,'brent_spot');b=parse_capture(market,cap,'brent_spot')
    assert a['parsed_rows']==len(rows) and b['new_observations']==0


def test_manual_authorization_and_official_evidence(market,tmp_path):
    p=tmp_path/'sample.csv';p.write_text('date,value,unit\n2025-01-01,100,USD/bbl\n')
    with pytest.raises(ValueError):manual_import(market,p,'brent_spot','https://example.org','')
    assert manual_import(market,p,'brent_spot','https://example.org','authorized public fixture')['new_observations']==1
    with pytest.raises(ValueError):manual_import(market,p,'lbp_payment_fx','https://example.org','fixture')


def test_research_comparison_uses_same_trailing_return_and_labels(market):
    from lebanon_fuel.market.reports import historical_comparison
    from lebanon_fuel.domain import now_utc
    for day,price in [('2025-02-01',1000000),('2025-02-08',1010000)]:
        for source in ['ipt','ministry']:
            cap=market.capture(source,'https://example.org',f'{day}:{price}'.encode(),'text/plain',retrieved_at='2026-11-10T12:00:00+00:00')
            market.ingest(cap,[Observation(source,day,price,'https://example.org',{'test_fixture':True},'1')])
    market.reconcile()
    for i in range(30):
        day=date(2025,1,1)+timedelta(days=i)
        add(market,day=str(day),value=100+i,seen='2026-11-10T12:00:00+00:00')
    cutoff='2026-11-10T23:00:00+00:00'
    histories={sid:market.history(sid,cutoff,'research') for sid in SERIES}
    rows,_,strict=historical_comparison(market,histories,cutoff)
    assert len(rows)==1 and strict['origins_with_any_strict_market_observation']==0
    row=rows[0]
    expected=snapshot(market,row['assumed_origin_utc'],'research')['series']['brent_spot']['return_7_calendar_days']
    assert row['brent_spot_7d_return_lag0']==expected
    assert row['lebanon_change_fraction']==pytest.approx(.01)
    assert 'NOT_BACKTEST' in row['mode']


def test_market_join_index_exists(market):
    indexes={r[1] for r in market.db.execute('PRAGMA index_list(market_sightings)')}
    assert 'market_sightings_observation' in indexes


@pytest.mark.parametrize('sid,day,available', [
    ('brent_spot','2025-06-06','2025-06-06T23:59:59+00:00'),
    ('rbob_futures','2025-06-06','2025-06-06T23:59:59+00:00'),
    ('us_gasoline_stocks','2025-06-06','2025-06-11T23:59:59+00:00'),
    ('us_refinery_utilization','2025-06-06','2025-06-11T23:59:59+00:00'),
])
def test_close_mode_has_no_daily_fourteen_day_delay_and_keeps_capture_clock(market,sid,day,available):
    add(market,sid=sid,day=day,seen='2026-11-10T10:00:00+00:00')
    before=(datetime.fromisoformat(available)-timedelta(seconds=1)).isoformat()
    assert market.history(sid,before,'as_of_close')==[]
    row=market.history(sid,available,'as_of_close')[0]
    assert row['available_at']==available
    assert row['captured_available_at']=='2026-11-10T10:00:00+00:00'
    assert market.history(sid,available,'strict')==[]
    assert 'NOT_STRICT' in row['availability_basis']


def test_close_mode_midnight_beirut_is_not_previous_session_close(market):
    add(market,day='2025-06-06',seen='2026-11-10T10:00:00+00:00')
    assert market.history('brent_spot','2025-06-07T00:00:00+03:00','as_of_close')==[]
    assert len(market.history('brent_spot','2025-06-07T03:00:00+03:00','as_of_close'))==1
    assert snapshot(market,'2025-06-07T03:00:00+03:00','as_of_close')['backtest_eligible'] is False


def test_known_later_publication_overrides_close_assumption(market):
    add(market,publication_timestamp='2025-01-02T10:00:00+00:00')
    assert market.history('brent_spot','2025-01-02T00:00:00+00:00','as_of_close')==[]
    assert len(market.history('brent_spot','2025-01-02T10:00:00+00:00','as_of_close'))==1


def yahoo_fixture(symbol='RB=F',currency='USD',instrument='FUTURE'):
    from datetime import timezone
    stamps=[int(datetime(2025,1,d,15,tzinfo=timezone.utc).timestamp()) for d in [2,3]]
    return json.dumps({'chart':{'error':None,'result':[{'meta':dict(symbol=symbol,currency=currency,instrumentType=instrument,
                exchangeTimezoneName='America/New_York'), 'timestamp':stamps,
                'indicators':{'quote':[{'close':[2.5,2.6],'open':[2.4,2.5],'volume':[100,120]}]}}]}}).encode()


def test_futures_parse_finalized_bars_only_and_units(market):
    from lebanon_fuel.market.collectors import yahoo_rows
    from lebanon_fuel.market.catalog import BARREL_LITERS
    raw=yahoo_fixture()
    rows=list(yahoo_rows(raw,'rbob_futures',at=datetime.fromisoformat('2025-01-03T16:00:00+00:00')))
    assert len(rows)==1 and rows[0]['value']==2.5
    assert rows[0]['raw']['publication_timestamp'] is None
    cap=market.capture('market_yahoo','https://query1.finance.yahoo.com/v8/finance/chart/RB%3DF',raw,'application/json',
                      http_status=200,retrieved_at='2025-01-03T16:00:00+00:00')
    market.ingest_market(cap,'rbob_futures',rows)
    row=market.history('rbob_futures','2025-01-04T00:00:00+00:00')[0]
    assert row['value']==105 and row['value_usd_kl']==pytest.approx(105*1000/BARREL_LITERS)
    assert row['raw_value']=='2.5'
    assert parse_capture(market,cap,'rbob_futures')['new_observations']==0
    for raw in [yahoo_fixture(symbol='HO=F'),yahoo_fixture(currency='EUR'),yahoo_fixture(instrument='EQUITY')]:
        with pytest.raises(ValueError):list(yahoo_rows(raw,'rbob_futures'))


def test_provider_denial_falls_back_without_relabeling_spot(market,monkeypatch):
    from lebanon_fuel.market import collectors
    add(market,value=100)
    add(market,sid='nyh_gasoline',value=2.5)
    requests=[]
    class Client:
        def __init__(self,*args):pass
        def fetch(self,url):
            requests.append(url)
            raise collectors.AccessStopped('robots policy denied')
        def close(self):pass
    monkeypatch.setattr(collectors,'PublicClient',Client)
    results=collectors.collect_futures(market)
    assert len(requests)==1 and all(r['status']=='unavailable' for r in results)
    assert results[0]['fallback_series']=='brent_spot'
    assert results[1]['fallback_series']=='nyh_gasoline'
    assert results[2]['fallback_series'] is None
    assert market.db.execute("SELECT COUNT(*) FROM market_observations WHERE series_id LIKE '%futures'").fetchone()[0]==0


def research_config():
    return dict(series=['brent_spot','nyh_gasoline','brent_futures','rbob_futures','gasoil_futures'],
                market_availability_mode='as_of_close',origin_local_time='03:00',minimum_domestic_history=2,
                maximum_gap_days=14,target_statuses=['archive_corroborated'],targets={'decisions':[1], 'calendar_days':[1,3]},
                structural_delta=dict(enabled=True,bank_factor=1.01,vat_factor=1.11,fx_lbp_per_usd=89700,
                                      stabilized_start='2023-05-12',shock_threshold_lbp=150000))


def feature_history(market,start=date(2025,1,1),count=30):
    for i in range(count):
        day=start+timedelta(days=i)
        for sid,value in [('nyh_gasoline',(100+i)/42),('brent_spot',70+i)]:
            add(market,sid=sid,day=day.isoformat(),value=value,seen='2026-11-10T12:00:00+00:00')


def test_short_windows_delta_units_fallback_and_no_future_mutation(market):
    import numpy as np
    from lebanon_fuel.forecasting.data import MarketFeatures,features_at,BEIRUT
    from lebanon_fuel.market.catalog import BARREL_LITERS
    feature_history(market)
    config=research_config()
    rows=[dict(source_date='2025-01-15',price_lbp_20l=1000000,revision_id=1,verification_status='archive_corroborated'),
          dict(source_date='2025-01-20',price_lbp_20l=1160000,revision_id=2,verification_status='archive_corroborated')]
    origin=datetime(2025,1,23,3,tzinfo=BEIRUT)
    market_features=MarketFeatures(market,config)
    result=features_at(rows,1,origin,market_features,config)
    # T-1 Jan 22 is index 21: current mean4=119.5; Jan20 decision cutoff mean4=116.5.
    assert result['x_nyh_gasoline_mean3']==pytest.approx(120)
    assert result['x_nyh_gasoline_mean5']==pytest.approx(119)
    assert result['x_nyh_gasoline_mean10']==pytest.approx(116.5)
    assert result['x_nyh_gasoline_return3']==pytest.approx(121/118-1)
    assert result['x_nyh_gasoline_return5']==pytest.approx(121/116-1)
    assert result['x_structural_delta_lbp_20l']==pytest.approx(3*1000/BARREL_LITERS*89700*1.01*1.11/50)
    assert result['structural_benchmark_source']=='nyh_gasoline'
    assert result['refined_gasoline_source']=='nyh_gasoline' and np.isnan(result['x_rbob_futures_value'])
    assert result['x_fiscal_shock_lag1']==1
    assert result['max_assumed_market_available_at']<origin.isoformat()
    add(market,day='2025-02-01',value=999,sid='nyh_gasoline',seen='2026-11-10T12:00:00+00:00')
    changed=features_at(rows,1,origin,MarketFeatures(market,config),config)
    assert changed['x_structural_delta_lbp_20l']==result['x_structural_delta_lbp_20l']


def test_structural_comparison_never_splices_different_product_levels(market):
    from lebanon_fuel.forecasting.data import MarketFeatures,structural_delta,BEIRUT
    feature_history(market)
    # Futures only cover the current window, not the previous domestic decision window.
    for i in range(4):
        add(market,day=f'2025-01-{21+i}',value=5,sid='rbob_futures',seen='2026-11-10T12:00:00+00:00')
    records=[dict(source_date='2025-01-20',price_lbp_20l=1000000,revision_id=1,verification_status='archive_corroborated')]
    result=structural_delta(records,datetime(2025,1,25,3,tzinfo=BEIRUT),MarketFeatures(market,research_config()),research_config())
    assert result['structural_benchmark_source']=='nyh_gasoline'


def test_build_keeps_evaluation_labels_out_of_development(market):
    import pandas as pd
    from lebanon_fuel.forecasting.data import build,mature_training
    feature_history(market,start=date(2026,5,1),count=45)
    for day,value in [('2026-05-18',1000000),('2026-05-22',1010000),('2026-05-26',1020000),
                      ('2026-05-29',1030000),('2026-06-02',1040000),('2026-06-05',1050000),('2026-06-09',1060000)]:
        for source in ['ministry','ipt']:
            cap=market.capture(source,'https://example.org',f'{source}:{day}'.encode(),'text/plain',retrieved_at='2026-11-10T12:00:00+00:00')
            market.ingest(cap,[Observation(source,day,value,'https://example.org',{'fixture':True},'1')])
    market.reconcile()
    cfg=research_config();cfg['regimes']=[dict(id='stabilized_fx_2023_2026',start='2026-05-01',development_end='2026-05-31',evaluation_start='2026-06-01',evaluation_end='2026-06-09')]
    development,_=build(market.root,cfg)
    evaluation=pd.read_csv(market.root/'data/exports/forecasting/holdout_evaluation_design.csv')
    origins=pd.read_csv(market.root/'data/exports/forecasting/holdout_origin_features.csv')
    assert len(development)>0 and len(evaluation)>0
    assert development.partition.eq('development').all() and evaluation.partition.eq('evaluation').all()
    assert development.target_source_date.max()<='2026-05-31'
    assert development.origin_date.max()<='2026-05-31' and evaluation.origin_date.min()>='2026-06-01'
    assert origins.origin_date.max()=='2026-06-09'
    first=origins[origins.origin_date.eq('2026-06-01')].iloc[0]
    assert first.x_domestic_change_lag1==10000
    assert pd.notna(first.x_structural_delta_lbp_20l)
    together=pd.concat([development,evaluation])
    assert mature_training(together,'2027-01-01T00:00:00+00:00').partition.eq('development').all()


def test_explicit_spot_override_never_silently_switches_to_futures(market):
    from lebanon_fuel.forecasting.data import MarketFeatures,structural_delta,BEIRUT
    feature_history(market)
    for i in range(30):
        add(market,sid='rbob_futures',day=(date(2025,1,1)+timedelta(days=i)).isoformat(),value=5+i/10,seen='2026-11-10T12:00:00+00:00')
    config=research_config()
    config['energy_source_override']={'refined_gasoline':'nyh_gasoline','brent':'brent_spot'}
    config['structural_delta']['benchmark_series']='nyh_gasoline'
    source=MarketFeatures(market,config);at=datetime(2025,1,25,3,tzinfo=BEIRUT)
    row=source.at(at)
    assert row['refined_gasoline_source']=='nyh_gasoline' and row['brent_source']=='brent_spot'
    records=[dict(source_date='2025-01-20',price_lbp_20l=1000000,revision_id=1,verification_status='archive_corroborated')]
    assert structural_delta(records,at,source,config)['structural_benchmark_source']=='nyh_gasoline'
