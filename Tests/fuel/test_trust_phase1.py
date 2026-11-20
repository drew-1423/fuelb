"""Synthetic adversarial fixtures; never used as observed prices or performance."""
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from random import Random
from types import SimpleNamespace
import json
import sqlite3

import pytest

from lebanon_fuel.validation.provisional import select_target, validate
from lebanon_fuel.validation.decision_tracking import calibration
from lebanon_fuel.dashboard.scenarios import anchored_simulate
from lebanon_fuel.automation.health import contract,state
from lebanon_fuel.automation import release

ROOT=Path(__file__).resolve().parents[2]
HORIZONS=['decision_1','decision_2','decision_4','day_1','day_3','day_7','day_14','day_30']


def supplier_fixture(horizon):
    origin=datetime(2025,1,2,12,tzinfo=timezone.utc)
    kind,n=horizon.split('_');n=int(n)
    if kind=='decision':
        days=[date(2025,1,1)]+[date(2025,1,3)+timedelta(days=3*i) for i in range(n)]
        endpoint=None
    else:
        endpoint=origin+timedelta(days=n)
        days=[date(2025,1,1)]
        day=date(2025,1,3)
        while day<endpoint.date():
            days.append(day);day+=timedelta(days=3)
        if days[-1]!=endpoint.date():days.append(endpoint.date())
        days.append(endpoint.date()+timedelta(days=3))
    records={d.isoformat():dict(source_date=d.isoformat(),price_lbp_20l=1000000+1000*i,
                verification_status='provisional_corroborated',revision_id=i+1) for i,d in enumerate(days)}
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE observations(id INTEGER,source_id TEXT,price_lbp_20l REAL,source_url TEXT,first_retrieved_at TEXT,source_date TEXT,is_valid INTEGER)')
    for i,row in enumerate(records.values()):
        for k,sid in enumerate(['ipt','taqtek']):
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,1)',(i*2+k,sid,row['price_lbp_20l'],'https://example.test/'+sid,row['source_date']+'T09:00:00+00:00',row['source_date']))
    forecast=dict(horizon=horizon,mode='prospective_research',origin=origin.isoformat(),created_at=origin.isoformat(),base_price=1000000,
        target_json=json.dumps(dict(base_source_date='2025-01-01',endpoint=endpoint.isoformat() if endpoint else None)))
    return forecast,records,SimpleNamespace(db=db)


@pytest.mark.parametrize('horizon',HORIZONS)
def test_provisional_all_horizons_need_actual_path_and_endpoint_evidence(horizon):
    forecast,records,source=supplier_fixture(horizon)
    try:
        status,row,payload=select_target(forecast,records,sorted(records),source)
        assert status=='candidate'
        sources=[s for item in payload['path']+([payload['witness']] if payload['witness'] else []) for s in item['sources']]
        outcome=dict(payload_json=json.dumps(payload),verification_status='supplier_agreement',decision_key='supplier:'+row['source_date'],
                     price=row['price_lbp_20l'],available_at=max(s['first_retrieved_at'] for s in sources))
        validate(forecast,outcome)
        payload['sources'][0]['price_lbp_20l']+=1
        outcome['payload_json']=json.dumps(payload)
        with pytest.raises(ValueError,match='IPT and independent-source'):
            validate(forecast,outcome)
    finally:source.db.close()


def test_totalenergies_pair_can_score_a_later_provisional_update():
    forecast, records, source = supplier_fixture('decision_1')
    try:
        source.db.execute("UPDATE observations SET source_id='totalenergies' WHERE source_id='taqtek'")
        status, row, payload = select_target(forecast, records, sorted(records), source)
        assert status == 'candidate'
        assert {s['source_id'] for s in payload['sources']} == {'ipt', 'totalenergies'}
        outcome = dict(payload_json=json.dumps(payload), verification_status='supplier_agreement',
                       decision_key='supplier:' + row['source_date'], price=row['price_lbp_20l'],
                       available_at=max(s['first_retrieved_at'] for s in payload['sources']))
        validate(forecast, outcome)
    finally:
        source.db.close()


def test_missing_calendar_witness_and_late_capture_do_not_become_zero_changes():
    f,records,source=supplier_fixture('day_7')
    try:
        status,_,_=select_target(f,records,sorted(records)[:-1],source)
        assert status=='missing_calendar_witness'
        endpoint=json.loads(f['target_json'])['endpoint'][:10]
        source.db.execute('UPDATE observations SET first_retrieved_at=? WHERE source_date=?',(endpoint+'T23:00:00+00:00',endpoint))
        assert select_target(f,records,sorted(records),source)[0]=='endpoint_not_observed_in_time'
    finally:source.db.close()


def test_calendar_endpoint_does_not_shift_when_ledger_write_is_delayed():
    forecast,records,source=supplier_fixture('day_7')
    forecast['created_at']=(datetime.fromisoformat(forecast['origin'])+timedelta(seconds=30)).isoformat()
    try:
        status,row,payload=select_target(forecast,records,sorted(records),source)
        assert status=='candidate'
        available=max(s['first_retrieved_at'] for item in payload['path']+[payload['witness']] for s in item['sources'])
        outcome=dict(payload_json=json.dumps(payload),verification_status='supplier_agreement',
                     decision_key='supplier:'+row['source_date'],price=row['price_lbp_20l'],available_at=available)
        validate(forecast,outcome)
        payload['endpoint']=(datetime.fromisoformat(payload['endpoint'])+timedelta(seconds=30)).isoformat()
        outcome['payload_json']=json.dumps(payload)
        with pytest.raises(ValueError,match='Calendar endpoint'):
            validate(forecast,outcome)
    finally:source.db.close()


@pytest.mark.parametrize('horizon',HORIZONS)
def test_each_horizon_uses_its_own_independent_residuals_and_evidence(horizon):
    rng=Random(17);start=datetime(2024,1,1,tzinfo=timezone.utc)
    cases=[]
    for i in range(90):
        origin=start+timedelta(days=40*i)
        cases.append(dict(kind='provisional_match',cohort='government_backed',horizon=horizon,artifact='fixed',day=str(i),
            origin=origin,known=origin+timedelta(days=31),forecast=2000000,actual=2000000+rng.randrange(-30000,30000)))
    cutoff=start+timedelta(days=4000)
    result=calibration(cases,'government_backed','fixed',horizon,at=cutoff)
    assert result['evidence_category']=='provisional_match'
    assert result['levels']['80']['evaluation_n']>=20 and result['levels']['90']['evaluation_n']>=20
    assert result['radius'] is not None and result['radius_80'] is not None
    assert 5000 <= result['radius_80'] <= result['radius']
    assert calibration(cases,'government_backed','other',horizon,at=cutoff)['radius'] is None
    before=calibration(cases,'government_backed','fixed',horizon,at=cases[40]['origin'])
    mutated=[dict(r,actual=9000000) if r['known']>=cases[40]['origin'] else r for r in cases]
    assert calibration(mutated,'government_backed','fixed',horizon,at=cases[40]['origin'])==before


def test_overlapping_and_repeated_refreshes_cannot_manufacture_calibration_sample():
    origin=datetime(2025,1,1,tzinfo=timezone.utc)
    cases=[dict(kind='provisional_match',cohort='provisional',artifact='fixed',horizon='day_30',day=str(i),
                origin=origin+timedelta(days=i),known=origin+timedelta(days=i+31),forecast=1000,actual=1100) for i in range(60)]
    result=calibration(cases,'provisional','fixed','day_30')
    assert result['calibration_n']<=2 and result['radius'] is None


def test_anchored_status_quo_fx_and_display_conversion_are_separate():
    template=json.loads((ROOT/'config/structural_scenario_before_vat.json').read_text())
    now=datetime(2026,11,19,tzinfo=timezone.utc)
    anchor=dict(source_date='2026-11-17',price_lbp_20l=2343000,verification_status='archive_corroborated')
    base=dict(product=97.776,fx=89500,freight=30,vat_percent=11,charge=300000,charge_taxable=True)
    same=anchored_simulate(template,anchor=anchor,baseline_inputs=base,scenario_inputs=base,now=now)
    assert float(same['price_lbp_20l'])==2343000 and float(same['change_lbp_20l'])==0
    devalue=anchored_simulate(template,anchor=anchor,baseline_inputs=base,scenario_inputs=dict(base,fx=100000),now=now)
    assert float(devalue['price_lbp_20l'])>2343000
    display=anchored_simulate(template,anchor=anchor,baseline_inputs=base,scenario_inputs=base,display_fx=100000,now=now)
    assert display['price_lbp_20l']==same['price_lbp_20l'] and display['price_usd_20l']!=same['price_usd_20l']
    with pytest.raises(ValueError,match='verified or supplier'):
        anchored_simulate(template,anchor=dict(anchor,verification_status='conflict'),baseline_inputs=base,scenario_inputs=base,now=now)


def test_research_forecast_cannot_mask_failed_integrity_or_refresh():
    result=contract(at='2026-11-19T12:00:00+00:00',required={'gasoline':{'observation_date':'2026-11-17'}},optional=[],
        anchor=dict(source_date='2026-11-17',price_lbp_20l=2343000,verification_status='archive_corroborated'),
        forecast=dict(origin='2026-11-19T11:00:00+00:00',predicted_price=2300000,spec={'tier':2}),
        calibration=state('warning',['insufficient_outcomes']),integrity=state('failed',['missing_capture']),release=state('warning'),refresh_ok=False,
        last_attempt='2026-11-19T11:55:00+00:00',last_capture='2026-11-18T10:00:00+00:00')
    assert result['overall']=='failed' and result['checks']['forecast']['status']=='warning'
    assert result['checks']['refresh']['status']=='failed'
    assert result['clocks']['last_refresh_attempted']!=result['clocks']['last_successful_capture']


def test_release_checks_current_code_and_original_frozen_bytes_separately(tmp_path):
    from hashlib import sha256
    (tmp_path/'src').mkdir();(tmp_path/'src/view.py').write_text('original = 1\n')
    (tmp_path/'requirements.txt').write_text('');(tmp_path/'pyproject.toml').write_text('')
    (tmp_path/'reports/releases').mkdir(parents=True);(tmp_path/'reports/forecasting').mkdir()
    snapshot=tmp_path/'frozen.py';snapshot.write_text('original = 1\n');h=sha256(snapshot.read_bytes()).hexdigest()
    manifest=tmp_path/'reports/forecasting/run_manifest.json';manifest.write_text(json.dumps({'code_hashes':{'src/view.py':h}}))
    refs={'frozen_manifests':{'reports/forecasting/run_manifest.json':sha256(manifest.read_bytes()).hexdigest()},'source_archives':{h:'frozen.py'}}
    (tmp_path/'reports/releases/frozen_references.json').write_text(json.dumps(refs))
    release.create(tmp_path);release.verify_frozen(tmp_path,'reports/forecasting/run_manifest.json')
    (tmp_path/'src/view.py').write_text('ui_revision = 2\n')
    with pytest.raises(AssertionError,match='source checksum'):
        release.verify(tmp_path)
    release.create(tmp_path)
    release.verify_frozen(tmp_path,'reports/forecasting/run_manifest.json')
    snapshot.write_text('tampered\n')
    with pytest.raises(AssertionError,match='frozen source'):
        release.verify_frozen(tmp_path,'reports/forecasting/run_manifest.json')


def test_cloud_dashboard_never_starts_an_ephemeral_local_writer(tmp_path,monkeypatch):
    from lebanon_fuel.dashboard.data import refresh_source
    (tmp_path/'config').mkdir();(tmp_path/'config/project.toml').write_text('[deployment]\ndashboard_writer="github_actions"\n')
    monkeypatch.delenv('LEBANON_FUEL_WRITER',raising=False);monkeypatch.delenv('LEBANON_FUEL_ACTIONS_TOKEN',raising=False)
    import subprocess
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:pytest.fail('Cloud dashboard started a local writer'))
    ok,message=refresh_source(tmp_path,'all')
    assert not ok and 'No local database writes' in message


def test_all_horizon_supplier_scoring_is_append_only_and_idempotent(tmp_path,monkeypatch):
    from lebanon_fuel.validation import decision_tracking as tracking,ledger as ledger_module
    from lebanon_fuel.validation.ledger import ForecastLedger
    (tmp_path/'config').mkdir();(tmp_path/'config/prospective_holdout.json').write_text(json.dumps({'prospective_start':'2025-01-01T00:00:00+00:00','sealed_at':'2025-01-01T00:00:00+00:00'}))
    origin=datetime(2025,1,2,12,tzinfo=timezone.utc);clock={'now':origin}
    monkeypatch.setattr(ledger_module,'now',lambda:clock['now'].isoformat())
    days={date(2025,1,1),date(2025,1,3),date(2025,1,5),date(2025,1,9),date(2025,1,16),date(2025,2,1),date(2025,2,4)}
    days.update(date(2025,1,3)+timedelta(days=3*i) for i in range(11))
    records=[dict(source_date=d.isoformat(),price_lbp_20l=1000000+i*1000,verification_status='provisional_corroborated',revision_id=i+1) for i,d in enumerate(sorted(days))]
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE observations(id INTEGER,source_id TEXT,price_lbp_20l REAL,source_url TEXT,first_retrieved_at TEXT,source_date TEXT,is_valid INTEGER)')
    for i,r in enumerate(records):
        for k,sid in enumerate(['ipt','taqtek']):
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,1)',(i*2+k,sid,r['price_lbp_20l'],'https://example.test/'+sid,r['source_date']+'T09:00:00+00:00',r['source_date']))
    source=SimpleNamespace(db=db,ledger=lambda:records)
    path=tmp_path/'ledger.sqlite';cfg={'validation':{'forecast_ledger':'ledger.sqlite'}}
    with closing(ForecastLedger(path)) as ledger:
        items=[]
        for h in HORIZONS:
            kind,n=h.split('_');target=dict(pinned_family='G_hybrid',base_source_date='2025-01-01',anchor_verification='provisional_corroborated',artifact_sha256='synthetic',kind='decision' if kind=='decision' else 'calendar',steps=int(n))
            if kind=='day':target['endpoint']=(origin+timedelta(days=int(n))).isoformat()
            items.append(dict(run_id='fixture',origin=origin.isoformat(),mode='prospective_research',model_version='fixture',model_metadata={'family':'G_hybrid'},snapshot_payload={'fixture':True},horizon=h,target=target,base_price=1000000,prediction=20000,interval=None,probabilities=None,reasons=[]))
        ledger.issue_batch(items)
        before=ledger.integrity()
    clock['now']=datetime(2025,3,1,tzinfo=timezone.utc)
    try:
        assert tracking.settle_supplier_updates(tmp_path,cfg,source)=={'supplier_match':8}
        assert tracking.settle_supplier_updates(tmp_path,cfg,source)=={'supplier_match':8}
        with closing(ForecastLedger(path)) as ledger:
            assert ledger.db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0]==8
            assert ledger.integrity()['hash_chain_valid'] and ledger.integrity()['forecasts']==before['forecasts']
        with tracking._read(path) as connection:
            assert len(tracking._matched(connection,tracking.protocol_start(tmp_path),tracking.now()))==8
    finally:db.close()
