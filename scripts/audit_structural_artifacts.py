"""Recalculate saved financial claims without refitting or changing model selection."""
from pathlib import Path
from decimal import Decimal as D
from hashlib import sha256
from datetime import datetime
import csv
import json
import math

from lebanon_fuel.storage.baseline import historical_database

ROOT=Path(__file__).resolve().parents[1]


def audit(root=ROOT):
    protocol=json.loads((root/'config/structural_research.json').read_text())
    freeze=json.loads((root/'research/evidence/structural_protocol_freeze.json').read_text())
    assert sha256((root/'config/structural_research.json').read_bytes()).hexdigest()==freeze['sha256']
    manifest=json.loads((root/'reports/structural/run_manifest.json').read_text())
    assert sha256((root/'data/exports/structural/research_design_matrix.csv').read_bytes()).hexdigest()==manifest['dataset_sha256']
    frame=list(csv.DictReader((root/'data/exports/structural/research_design_matrix.csv').open()))
    design={r['date']:r for r in frame}
    predictions=list(csv.DictReader((root/'data/exports/structural/historical_proxy_predictions_RESEARCH_ONLY.csv').open()))
    metrics=list(csv.DictReader((root/'reports/structural/test_metrics.csv').open()))
    checked_captures=set();checked_targets=set()
    with historical_database(root) as conn:
        for r in frame:
            assert datetime.fromisoformat(r['max_assumed_market_available_at'])<=datetime.fromisoformat(r['origin'])
            for key,field in [('target_revision_id','actual'),('previous_revision_id','previous')]:
                original=conn.execute('SELECT payload_json FROM decision_versions WHERE id=?',(int(r[key]),)).fetchone()[0]
                assert D(str(json.loads(original)['price_lbp_20l']))==D(r[field]);checked_targets.add(r[key])
            for obs,cap in json.loads(r['market_observation_capture_ids']):
                assert conn.execute('SELECT 1 FROM market_sightings WHERE observation_id=? AND capture_id=?',(obs,cap)).fetchone()
                if cap not in checked_captures:
                    raw=conn.execute('SELECT raw_path,sha256 FROM captures WHERE id=?',(cap,)).fetchone()
                    assert sha256((root/raw['raw_path']).read_bytes()).hexdigest()==raw['sha256'];checked_captures.add(cap)
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    for p in predictions:
        assert p['train_end']<p['date']
        assert math.isclose(float(p['actual'])-float(p['previous']),float(p['actual_change']),abs_tol=1e-7)
        fit=json.loads(p['parameters_json']);row=design[p['date']]
        value=fit['intercept']
        for key,coefficient in fit['slopes'].items():
            if key.startswith('positive_'):x=max(float(row[key.removeprefix('positive_')]),0)
            elif key.startswith('negative_'):x=min(float(row[key.removeprefix('negative_')]),0)
            else:x=float(row[key])
            value+=coefficient*x
        assert math.isclose(float(p['predicted_change']),value,abs_tol=1e-7)
        assert math.isclose(float(p['predicted']),float(p['previous'])+value,abs_tol=1e-7)
    for summary in metrics:
        rows=[p for p in predictions if p['regime']==summary['regime'] and p['model']==summary['model']]
        errors=[float(p['predicted'])-float(p['actual']) for p in rows]
        assert len(rows)==int(summary['n'])
        assert math.isclose(sum(abs(e) for e in errors)/len(rows),float(summary['mae_lbp_20l']),abs_tol=1e-7)
        assert math.isclose(sum(errors)/len(rows),float(summary['bias_lbp_20l']),abs_tol=1e-7)
        bounded=[p for p in rows if p['lower'] and p['upper']]
        covered=sum(float(p['lower'])<=float(p['actual'])<=float(p['upper']) for p in bounded)
        assert math.isclose(covered/len(bounded),float(summary['coverage_90']),abs_tol=1e-12)
    for regime in protocol['regimes']:
        groups=[{p['date'] for p in predictions if p['regime']==regime['id'] and p['family']==family} for family in protocol['families']]
        assert all(g==groups[0] for g in groups)
    ann=json.loads((root/'data/manual/structural_annexes.json').read_text())
    recomputed=[]
    for r in ann:
        req=r['request'];subtotal=D(req['goods_lbp_kl']['value'])+sum(D(c['value']) for c in req['costs'])
        assert subtotal==D(r['printed_pretax_lbp_kl'])
        assert subtotal*D('.11')==D(r['printed_vat_lbp_kl'])
        recomputed.append(abs(subtotal*D('1.11')/50-D(r['printed_price_lbp_20l'])))
    assert not any(manifest['strict_market_counts_at_last_origin'].values())
    result=dict(review_kind='implementing_agent_recomputation_not_independent_external_audit',
                design_rows=len(frame),prediction_rows=len(predictions),distinct_test_origins=len({p['date'] for p in predictions}),
                target_versions_checked=len(checked_targets),market_capture_hashes_checked=len(checked_captures),
                saved_metric_groups_checked=len(metrics),annex_mae_lbp_20l=str(sum(recomputed)/len(recomputed)),
                strict_historical_evaluation_n=0,result='passed',
                code_hashes={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in sorted((root/'src/lebanon_fuel/structural').glob('*.py'))})
    (root/'reports/structural/artifact_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    print(json.dumps(audit(),indent=2))
