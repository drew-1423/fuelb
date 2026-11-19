"""Part 5 mechanical integrity checks. This is not the independent Part 6 audit."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from lebanon_fuel.storage.database import Store
from lebanon_fuel.forecasting.pipeline import load_bundle,preview


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def run():
    root=ROOT;folder=root/'reports/forecasting'
    manifest=json.loads((folder/'run_manifest.json').read_text())
    config=json.loads((root/'config/forecasting_research.json').read_text())
    assert manifest['config_sha256']==digest(root/'config/forecasting_research.json')
    validation=json.loads((root/'reports/model_validation/input_manifest.json').read_text())
    for p,h in manifest['code_hashes'].items():
        if Path(p).name=='live.py':
            assert digest(root/p)==validation['source_sha256'][p],p
        elif Path(p).name=='reporting.py':
            assert digest(root/p)==manifest['report_code_sha256'],p
        else:assert digest(root/p)==h,p
    for p,h in manifest.get('release',{}).get('source_sha256',{}).items():
        assert digest(root/p)==h,p
    for p,h in manifest['output_hashes'].items():assert digest(folder/p)==h,p
    design_path=root/'data/exports/forecasting/development_design.csv'
    feature_path=root/'data/exports/forecasting/origin_features.csv'
    assert digest(design_path)==manifest['design_sha256']
    assert manifest['holdout_read'] is False
    design=pd.read_csv(design_path);features=design
    predictions=pd.read_csv(folder/'development_predictions.csv')
    assert not predictions.duplicated(['regime','horizon','origin','family']).any()
    assert (pd.to_datetime(predictions.maximum_training_label_end,utc=True)<pd.to_datetime(predictions.fit_cutoff,utc=True)).all()
    assert (pd.to_datetime(predictions.fit_cutoff,utc=True)<=pd.to_datetime(predictions.origin,utc=True)).all()
    assert np.isfinite(predictions.prediction).all()
    assert (predictions.predicted_endpoint_price_lbp_20l>=0).all()
    probs=predictions[['p_decrease','p_unchanged_price','p_increase']]
    assert (probs.notna().sum(axis=1).isin([0,3])).all()
    probs=probs.dropna()
    np.testing.assert_allclose(probs.sum(axis=1),1)
    assert ((probs>0)&(probs<1)).all().all()
    assert not predictions.production_approved.any()
    assert set(predictions.information_status)=={'LATEST_VINTAGE_CONDITIONAL_ARCHIVE_RESEARCH_NOT_REAL_TIME'}
    for regime in manifest['effective_config']['regimes']:
        d=design[design.regime==regime['id']]
        assert (d.target_source_date<=regime['development_end']).all()
        assert (d.origin_date<=regime['development_end']).all()
    cal=predictions[predictions.calibration_maximum_label_end.notna()]
    assert (pd.to_datetime(cal.calibration_maximum_label_end,utc=True)<pd.to_datetime(cal.origin,utc=True)).all()
    used=features[features.max_assumed_market_available_at.notna()]
    assert (pd.to_datetime(used.max_assumed_market_available_at,utc=True)<=pd.to_datetime(used.origin,utc=True)).all()
    store=Store(root)
    # Saved designs reference immutable revisions, including superseded ones.
    # The current reconciled ledger alone cannot verify historical provenance.
    ledger={r['id']:dict(json.loads(r['payload_json']),revision_id=r['id'])
            for r in store.db.execute('SELECT id,payload_json FROM decision_versions')}
    for row in design.itertuples():
        base=ledger[row.base_revision_id];target=ledger[row.target_revision_id]
        assert base['price_lbp_20l']==row.base_price_lbp_20l
        assert target['price_lbp_20l']-base['price_lbp_20l']==row.target_change_lbp_20l
        assert target['source_date']==row.target_source_date
        assert ledger[row.witness_revision_id]['verification_status'] in config['target_statuses']
    market_ids={r[0] for r in store.db.execute('SELECT id FROM market_observations')}
    capture_ids={r[0] for r in store.db.execute('SELECT id FROM captures')}
    for row in features.itertuples():
        assert all(i in ledger for i in json.loads(row.domestic_provenance_json))
        assert all(i in market_ids and c in capture_ids for i,c in json.loads(row.market_provenance_json))
    store.close()
    bundle_count=0;reloaded_forecasts=0
    for path in sorted((root/'data/models/part5'/manifest['effective_config']['regimes'][0]['id']).glob('*/manifest.json')):
        meta=json.loads(path.read_text())
        for name,h in meta['files'].items():assert digest(path.parent/name)==h
        bundle=load_bundle(path.parent);cut=pd.Timestamp(bundle['fit_cutoff'])
        assert pd.Timestamp(bundle['training_maximum_label_end'])<cut
        ensemble=bundle['ensemble'];assert abs(sum(ensemble['weights'].values())-1)<1e-10
        if ensemble.get('maximum_label_end'):assert pd.Timestamp(ensemble['maximum_label_end'])<cut
        for c in bundle['calibrations'].values():
            if c.get('maximum_label_end'):assert pd.Timestamp(c['maximum_label_end'])<cut
        result=preview(root,bundle['regime'],bundle['horizon']);reloaded_forecasts+=len(result['forecasts']);bundle_count+=1
        assert bundle['B_official_structural']['status']=='abstain'
    assert bundle_count==manifest['saved_bundles']
    result=dict(checked_at=datetime.now(timezone.utc).isoformat(),status='passed_mechanical_checks_not_independent_validation',
        design_labels=len(design),feature_origins=len(features.drop_duplicates(['regime','origin'])),prediction_rows=len(predictions),
        distinct_origin_horizon_cases=len(predictions.drop_duplicates(['regime','horizon','origin'])),
        saved_bundles=bundle_count,reloaded_forecasts=reloaded_forecasts,production_approved=False)
    (folder/'integrity_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':run()
