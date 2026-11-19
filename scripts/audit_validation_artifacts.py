"""Audit the current frozen-model holdout without tuning or overwriting evidence."""
from pathlib import Path
import sys,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from lebanon_fuel.forecasting.pipeline import digest,dump,load_bundle
from lebanon_fuel.forecasting.uncertainty import direction_class
from lebanon_fuel.validation.backtest import load_holdout,walk_forward_bundle
from lebanon_fuel.validation.ledger import ForecastLedger,now
from lebanon_fuel.storage.database import Store
from lebanon_fuel.automation.release import verify_frozen


def main():
    folder=ROOT/'reports/model_validation';manifest=verify_frozen(ROOT,'reports/model_validation/input_manifest.json')
    protocol=manifest['protocol']
    assert manifest['protocol_sha256']==digest(ROOT/'config/validation_protocol.json')
    assert digest(ROOT/manifest['design_path'])==manifest['design_sha256']
    assert digest(ROOT/protocol['development_predictions'])==manifest['development_predictions_sha256']
    design=load_holdout(ROOT,protocol)
    pred=pd.read_csv(folder/'research_walk_forward_predictions.csv')
    dev=pd.read_csv(ROOT/protocol['development_predictions'])
    dev=dev[dev.regime.eq(protocol['regime'])]
    assert not pred.duplicated(['horizon','family','origin']).any()
    assert (pd.to_datetime(pred.maximum_training_label_end,utc=True)<pd.to_datetime(pred.fit_cutoff,utc=True)).all()
    assert (pd.to_datetime(pred.fit_cutoff,utc=True)<=pd.to_datetime(pred.origin,utc=True)).all()
    cal=pred[pred.calibration_maximum_label_end.notna()]
    assert (pd.to_datetime(cal.calibration_maximum_label_end,utc=True)<pd.to_datetime(cal.origin,utc=True)).all()
    metrics=pd.read_csv(folder/'metrics.csv');replayed=0
    selection=json.loads((folder/'production_selection.json').read_text())
    for horizon,sha in manifest['artifact_sha256'].items():
        path=ROOT/'data/models/part5'/protocol['regime']/horizon
        assert digest(path/'bundle.joblib')==sha
        bundle=load_bundle(path)
        actual=pred[pred.horizon.eq(horizon)].sort_values(['origin','family']).reset_index(drop=True)
        fresh=walk_forward_bundle(bundle,design[design.horizon.eq(horizon)],dev[dev.horizon.eq(horizon)])
        assert len(actual)==len(fresh)
        if len(fresh):
            fresh=fresh.sort_values(['origin','family']).reset_index(drop=True)
            assert actual[['origin','family']].equals(fresh[['origin','family']])
            for col in ['prediction','interval_low','interval_high','p_decrease','p_unchanged_price','p_increase']:
                np.testing.assert_allclose(actual[col],fresh[col],rtol=1e-10,atol=1e-6,equal_nan=True)
            replayed+=len(fresh)
        assert selection['selection'][horizon]['artifact_sha256']==sha
    for (h,f),rows in pred.groupby(['horizon','family']):
        stored=metrics[metrics.horizon.eq(h)&metrics.family.eq(f)].iloc[0]
        y=rows.target_change_lbp_20l.to_numpy();point=rows.prediction.to_numpy()
        assert stored.n==len(rows)
        np.testing.assert_allclose(stored.mae,np.mean(abs(point-y)))
        np.testing.assert_allclose(stored.direction_accuracy,np.mean(direction_class(point)==direction_class(y)))
        probs=rows[['p_decrease','p_unchanged_price','p_increase']].to_numpy();good=np.isfinite(probs).all(axis=1)
        if good.any():
            np.testing.assert_allclose(probs[good].sum(axis=1),1)
            np.testing.assert_allclose(stored.brier_multiclass,np.mean(np.sum((probs[good]-np.eye(3)[direction_class(y[good])+1])**2,axis=1)))
        good=rows.interval_low.notna()&rows.interval_high.notna()
        assert stored.interval_n==good.sum()
        if good.any():
            np.testing.assert_allclose(stored.interval_coverage,np.mean((rows.loc[good,'interval_low']<=y[good])&(rows.loc[good,'interval_high']>=y[good])))
    store=Store(ROOT)
    # Match the exact immutable revision used by each saved prediction.
    raw={r['id']:dict(json.loads(r['payload_json']),revision_id=r['id'])
         for r in store.db.execute('SELECT id,payload_json FROM decision_versions')}
    store.close()
    for row in design.itertuples():
        assert raw[row.base_revision_id]['price_lbp_20l']==row.base_price_lbp_20l
        assert raw[row.target_revision_id]['price_lbp_20l']-row.base_price_lbp_20l==row.target_change_lbp_20l
    ledger=ForecastLedger(ROOT/'data/forecast_ledger.sqlite');integrity=ledger.integrity();ledger.close()
    assert integrity['hash_chain_valid']
    result=dict(checked_at=now(),status='passed_integrity_and_replay_checks_not_production_approval',
                prediction_rows=len(pred),saved_prediction_replays=replayed,metric_groups=len(metrics),**integrity)
    dump(folder/'artifact_audit.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
