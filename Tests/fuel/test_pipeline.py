from datetime import datetime, timezone
from io import BytesIO
import json
import sqlite3
import pytest
import httpx
from openpyxl import Workbook

from lebanon_fuel.domain import Observation, price_integer, utc_timestamp, BEIRUT
from lebanon_fuel.storage.database import Store
from lebanon_fuel.ingestion.adapters import parse_ipt,parse_ministry,parse_taqtek,parse_manual,arabic_date,form_post
from lebanon_fuel.ingestion.http import PublicClient,AccessStopped
from lebanon_fuel.validation.quality import report,export_data

@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path)
    yield s
    s.close()

def add(store,source='ipt',day='2025-01-01',price=1000000,**kwargs):
    c=store.capture(source,'https://example.com',b'original','text/plain',retrieved_at='2026-11-10T17:00:00+00:00')
    row=Observation(source,day,price,'https://example.com',{'value':price},'1',**kwargs)
    return store.ingest(c,[row])

@pytest.mark.parametrize('value',[None,0,-1,'USD 20','1,00','123.4',float('nan'),True])
def test_reject_invalid_prices(value):
    with pytest.raises(ValueError):price_integer(value)

def test_arabic_units_and_dates():
    assert price_integer('٢٬٤٤٥٬٠٠٠')==2445000
    assert arabic_date('الثلاثاء, 10 تشرين ثاني 2026')=='2026-11-10'
    assert arabic_date('الأربعاء, ٢٧ تشرين أول ٢٠١٠')=='2010-10-27'
    with pytest.raises(ValueError):utc_timestamp('2025-10-26T00:30:00')
    assert datetime.fromisoformat(utc_timestamp('2025-10-26T00:30:00+03:00')).astimezone(BEIRUT).utcoffset() is not None
    assert utc_timestamp('2025-01-01T12:00:00+02:00').startswith('2025-01-01T10:00:00')

def test_idempotent_import_and_audit_sightings(store):
    assert add(store)['new_observations']==1
    assert add(store)['new_observations']==0
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
    assert store.db.execute('SELECT COUNT(*) FROM sightings').fetchone()[0]==2
    assert store.reconcile()==1
    assert store.reconcile()==0
    with pytest.raises(sqlite3.IntegrityError):store.db.execute('DELETE FROM observations')

def test_conflicts_and_reviewed_revision(store):
    add(store);store.reconcile()
    add(store,'ministry',price=1100000);store.reconcile()
    assert store.ledger()[0]['verification_status']=='conflict'
    assert store.ledger()[0]['price_lbp_20l'] is None
    chosen=store.db.execute("SELECT id FROM observations WHERE source_id='ministry'").fetchone()[0]
    store.resolve('2025-01-01',chosen,'Original decision checked','https://energyandwater.gov.lb/evidence','reviewer')
    store.reconcile()
    assert store.ledger()[0]['price_lbp_20l']==1100000
    assert store.ledger()[0]['verification_status']=='reviewed_resolution'
    assert store.db.execute('SELECT COUNT(*) FROM decision_versions').fetchone()[0]==3
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==2

def test_corrections_do_not_discard_earlier_source_version(store):
    add(store);store.reconcile()
    add(store,price=1001000);store.reconcile()
    assert store.ledger()[0]['verification_status']=='conflict'
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==2

def test_new_evidence_invalidates_old_resolution(store):
    add(store);add(store,price=1100000)
    obs=store.db.execute('SELECT id FROM observations ORDER BY id DESC LIMIT 1').fetchone()[0]
    store.resolve('2025-01-01',obs,'reviewed','https://example.com/evidence','reviewer')
    store.reconcile()
    assert store.ledger()[0]['verification_status']=='reviewed_resolution'
    add(store,'ministry',price=1200000)
    store.reconcile()
    row=store.ledger()[0]
    assert row['verification_status']=='conflict'
    assert 'new_evidence_requires_resolution_review' in row['issues']

def test_export_postback_uses_observed_state_and_target():
    html='''<form id="form1" action="/Sub.aspx?pageid=22"><input name="__VIEWSTATE" value="current-token"><a id="x_lbtnExport" href='javascript:WebForm_DoPostBackWithOptions(new WebForm_PostBackOptions("site$export", ""))'>Export</a></form>'''
    action,fields=form_post(html,'lbtnExport')
    assert action=='/Sub.aspx?pageid=22'
    assert fields['__VIEWSTATE']=='current-token'
    assert fields['__EVENTTARGET']=='site$export'

def test_verification_timing_and_change_basis(store):
    add(store);add(store,'ministry')
    add(store,day='2025-01-03',price=1200000)
    store.reconcile();a,b=store.ledger()
    assert a['verification_status']=='archive_corroborated'
    assert b['absolute_price_change']==200000
    assert b['percentage_price_change']==pytest.approx(20)
    assert b['previous_verified_date']=='2025-01-01'
    assert b['official_effective_date'] is None
    assert b['publication_timestamp'] is None

def test_invalid_units_and_future_dates_are_retained(store):
    add(store,unit='USD/gallon')
    add(store,day='2030-01-01')
    store.reconcile()
    assert all(r['verification_status']=='invalid' for r in store.ledger())
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==2

def test_workbook_schema_and_original_price():
    w=Workbook();s=w.active;s.title='Fuel Prices'
    s.append(['Date','Octane98','Octane95','Diesel','GasOil','Gas'])
    s.append([datetime(2025,1,1),'1,020,000','1,000,000',None,None,None])
    b=BytesIO();w.save(b)
    row=list(parse_ipt(b.getvalue()))[0]
    assert row.source_date=='2025-01-01'
    assert row.raw['Octane95']=='1,000,000'
    assert row.publication_timestamp is None
    with pytest.raises(ValueError):list(parse_ipt(b'<html>denied</html>'))

def test_ministry_parser_columns_and_missing_id():
    html='<table><thead><tr><th>تاريخ</th><th>قرار رقم</th><th>أوكتان 95</th><th>أوكتان 98</th><th>تحميل</th></tr></thead><tbody><tr><td>الثلاثاء, 10 تشرين ثاني 2026</td><td></td><td>2,445,000</td><td>2,463,000</td><td><a href="/file.pdf">PDF</a></td></tr></tbody></table>'
    row=list(parse_ministry(html))[0]
    assert row.price_lbp_20l=='2,445,000'
    assert row.decision_number is None
    assert row.raw['links']==['https://energyandwater.gov.lb/file.pdf']
    assert row.official_effective_date is None

def test_structured_taqtek_no_usd_conversion():
    payload='x:'+json.dumps({'series':[{'id':'gasoline_95','points':[{'d':'2025-01-01','p':1000000}]}]})
    html='<p>per tin (20 L), LBP</p><script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
    row=list(parse_taqtek(html.encode()))[0]
    assert row.price_lbp_20l==1000000
    assert row.source_date=='2025-01-01'

def test_manual_publication_effective_distinct():
    data=b'source_date,price_lbp_20l,unit,source_url,official_effective_date,publication_date,publication_timestamp\n2025-01-01,1000000,LBP/20L,https://example.com,2025-01-02,2025-01-01,2025-01-01T12:00:00+02:00\n'
    row=list(parse_manual(data))[0].checked('2026-01-01T00:00:00Z')
    assert row.official_effective_date=='2025-01-02'
    assert row.publication_date=='2025-01-01'
    assert row.publication_timestamp=='2025-01-01T10:00:00+00:00'
    with pytest.raises(ValueError):list(parse_manual(data,'official_document'))

def test_robots_blocks_request_without_requesting_target(store):
    calls=[]
    def route(request):
        calls.append(str(request.url))
        return httpx.Response(200,text='User-agent: *\nDisallow: /private/')
    client=PublicClient(store,'ipt',None,transport=httpx.MockTransport(route))
    with pytest.raises(AccessStopped):client.fetch('https://example.com/private/data')
    client.close()
    assert calls==['https://example.com/robots.txt']

def test_calendar_label_errors_excluded_from_verification(store):
    cap=store.capture('ministry','https://energyandwater.gov.lb/ar/prices',b'html','text/html')
    row=Observation('ministry','2025-01-01',1000000,'https://energyandwater.gov.lb/ar/prices',{'cells':['الجمعة, 01 كانون ثاني 2025']},'1')
    store.ingest(cap,[row]);add(store);store.reconcile()
    assert store.ledger()[0]['verification_status']=='date_alignment_review'
    assert 'source_weekday_mismatch' in store.ledger()[0]['issues']

def test_raw_hash_tampering_is_reported(store,tmp_path):
    add(store);store.reconcile()
    path=store.db.execute('SELECT raw_path FROM captures LIMIT 1').fetchone()[0]
    (store.root/path).write_bytes(b'changed')
    assert report(store,tmp_path/'reports','2026-11-10')['raw_integrity_failures']==[path]

@pytest.mark.parametrize('status',[403,406,429])
def test_access_denials_are_not_retried(store,status):
    calls=[]
    def route(request):
        calls.append(str(request.url))
        return httpx.Response(200,text='User-agent: *\nAllow: /') if request.url.path=='/robots.txt' else httpx.Response(status,text='Denied')
    client=PublicClient(store,'ipt',None,transport=httpx.MockTransport(route))
    client.interval=0
    with pytest.raises(AccessStopped):client.fetch('https://example.com/data')
    assert len(calls)==2
    assert store.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0]==2
    client.close()

def test_report_staleness_no_synthetic_dates(store,tmp_path):
    add(store);add(store,'ministry');add(store,day='2025-01-08');add(store,day='2025-01-15');add(store,day='2025-02-05')
    store.reconcile()
    summary=report(store,tmp_path/'reports','2026-11-10')
    assert summary['ledger_unique_dates']==4
    assert summary['sources']['ipt']['stale']
    assert summary['gap_candidates']>0
    export_data(store,tmp_path/'exports')
    import csv
    with (tmp_path/'exports/gasoline_95_history.csv').open() as f:
        assert len(list(csv.DictReader(f)))==4

def test_import_transaction_rolls_back_on_schema_failure(store):
    cap=store.capture('ipt','https://example.com',b'raw','text/plain')
    def broken():
        yield Observation('ipt','2025-01-01',1000,'https://example.com',{},'1')
        raise ValueError('bad second row')
    with pytest.raises(ValueError):store.ingest(cap,broken())
    assert store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
    assert store.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0]==1
