"""Issue the best available evidence tier without granting automatic model approval."""
from contextlib import closing
from hashlib import sha256
import json

from lebanon_fuel.forecasting.live import current_context, generate
from lebanon_fuel.validation.decision_tracking import apply_live_calibration
from lebanon_fuel.validation.ledger import ForecastLedger, hashed
from .state import now


def refresh(root, cfg, run_id):
    at = now()
    decision = json.loads((root / cfg['validation']['decision_file']).read_text())
    policy_path = root / 'config/live_forecasting.json'
    policy = json.loads(policy_path.read_text())
    records, histories = current_context(root, cfg, at)
    result = generate(root, cfg, policy, decision, records, histories, at)
    with closing(ForecastLedger(root / cfg['validation']['forecast_ledger'])) as ledger:
        if policy.get('pinned_family'):
            apply_live_calibration(root, root / cfg['validation']['forecast_ledger'], result['forecasts'], at.isoformat())
        policy_hash = sha256(policy_path.read_bytes()).hexdigest()
        snapshot_payload = dict(
            anchor=result['anchor'], prior_domestic_records=records[-30:],
            market_observation_ids={sid: [r['id'] for r in h] for sid, h in histories.items()},
            available_market_inputs=result['available_market_inputs'],
            hierarchy_policy=policy, policy_sha256=policy_hash,
            validation_decision=decision)
        items = []
        for output in result['forecasts']:
            tier = output['tier']
            mode = 'prospective' if tier == 1 else 'prospective_research'
            model_id = output.get('model_version', 'live-unavailable-v1')
            if tier == 2:
                model_id += '-experimental'
            metadata = dict(family=output.get('family'), tier=tier, issuer='live-v1',
                            artifact_sha256=output.get('artifact_sha256'))
            if tier == 1:
                metadata['decision_sha256'] = hashed(decision)
            kind, steps = output['horizon'].split('_')
            target = dict(output, kind='decision' if kind == 'decision' else 'calendar', steps=int(steps))
            items.append(dict(
                run_id=run_id, origin=at.isoformat(), mode=mode,
                model_version=model_id, model_metadata=metadata,
                decision=decision if tier == 1 else None,
                snapshot_payload=snapshot_payload, horizon=output['horizon'],
                target=target, base_price=output.get('base_price'),
                prediction=output['predicted_change'], interval=output['interval'],
                probabilities=output['probabilities'], reasons=output['critical_missing_inputs'],
            ))
        written = ledger.issue_batch(items)
        ids, snapshots = [], []
        for output, item, (fid, snapshot) in zip(result['forecasts'], items, written):
            output.update(forecast_id=fid, snapshot_id=snapshot, model_version=item['model_version'])
            ids.append(fid)
            snapshots.append(snapshot)
    result.update(forecast_ids=ids, snapshot_ids=sorted(set(snapshots)))
    from .state import write_json
    write_json(root/'reports/operations/calibration_readiness.json',dict(as_of=at.isoformat(),
        horizons={r['horizon']:r.get('public_calibration',dict(status='abstained',reasons=r['critical_missing_inputs'])) for r in result['forecasts']},
        forecast_ids=ids))
    return result
