"""Frozen next-decision research candidates and strict prospective evidence."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import platform
from pathlib import Path
import json
import math
import sqlite3
import tomllib
from uuid import uuid4

import numpy as np
import pandas as pd

from lebanon_fuel.domain import BEIRUT
from lebanon_fuel.forecasting.live import (
    anchor_check, current_context, estimate_next_decision_date, quantitative, strict_feature_frame,
)
from lebanon_fuel.forecasting.models import weights
from .decision_events import event_clocks, select_event, stamp
from .ledger import ForecastLedger, hashed
from .runner import Brent


MODE = 'prospective_shadow'
HORIZON = 'decision_1'
REQUIRED_SPOT = ('brent_spot', 'nyh_gasoline')
EXPECTED_CODES = {
    'A_no_change', 'Z_last_change', 'A_median', 'Z_brent',
    'B_structural_proxy', 'G_hybrid', 'B_official_structural',
}


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def _settings(root):
    return tomllib.loads((root / 'config/project.toml').read_text())


def _ledger_path(root, settings):
    return root / settings['validation']['forecast_ledger']


def _read_ledger(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return closing(db)


def _source_hashes(root):
    files = sorted((root / 'src/lebanon_fuel').rglob('*.py'))
    return {str(p.relative_to(root)): _sha(p) for p in files
            if not {'dashboard', 'news'}.intersection(p.relative_to(root / 'src/lebanon_fuel').parts)}


def _runtime():
    packages = ('numpy', 'pandas', 'scikit-learn', 'scipy', 'lightgbm', 'catboost', 'joblib')
    return dict(python=platform.python_version(), packages={package: version(package) for package in packages})


def freeze(root, path):
    """Freeze reference models before any new shadow outcome is observed."""
    root = Path(root).resolve()
    protocol = json.loads((root / 'config/forecast_shadow_protocol.json').read_text())
    if protocol['horizon'] != HORIZON or set(protocol['candidates']) != EXPECTED_CODES:
        raise ValueError('Unexpected shadow experiment')
    bundle_path = root / protocol['bundle']
    bundle_manifest = json.loads((bundle_path / 'manifest.json').read_text())
    cutoff = stamp(protocol['research_training_cutoff'])
    if (stamp(bundle_manifest['fit_cutoff']) > cutoff
            or stamp(bundle_manifest['training_maximum_label_end']) >= cutoff):
        raise ValueError('Model bundle contains data beyond the research training boundary')
    model_hash = _sha(bundle_path / 'bundle.joblib')
    if model_hash != bundle_manifest['files']['bundle.joblib']:
        raise ValueError('Bundle hash does not match its training manifest')
    design_path = root / protocol['development_design']
    design_hash = _sha(design_path)
    columns = ['regime', 'horizon', 'origin', 'label_end', 'base_revision_id',
               'target_change_lbp_20l', 'x_brent_spot_value', 'x_brent_spot_mean20']
    design = pd.read_csv(design_path, usecols=columns)
    use = ((design.regime == protocol['development_regime']) & (design.horizon == HORIZON)
           & (pd.to_datetime(design.origin, utc=True, format='mixed') < cutoff)
           & (pd.to_datetime(design.label_end, utc=True, format='mixed') < cutoff))
    train = design.loc[use].sort_values('origin')
    if train.base_revision_id.nunique() < 20 or not np.isfinite(train.target_change_lbp_20l).all():
        raise ValueError('Insufficient mature research development evidence for reference models')
    if _sha(design_path) != design_hash:
        raise ValueError('Development design changed during freeze')
    changes = train.target_change_lbp_20l.to_numpy(float)
    order = np.argsort(changes)
    w = weights(train)
    median = changes[order][np.searchsorted(np.cumsum(w[order]), sum(w) / 2)]
    manifest = dict(
        frozen_at=datetime.now(timezone.utc).isoformat(), protocol=protocol,
        runtime=_runtime(),
        source_hashes=_source_hashes(root), bundle_sha256=model_hash,
        bundle_manifest_sha256=_sha(bundle_path / 'manifest.json'),
        settings_sha256=_sha(root / 'config/project.toml'),
        feature_config_sha256=_sha(root / 'config/forecasting_research.json'),
        development=dict(sha256=design_hash, rows=len(train), distinct_base_decisions=train.base_revision_id.nunique(),
                         maximum_label_end=train.label_end.max(), evidence='conditional_archive_research_only'),
        median_change_lbp=float(median), brent_slope=Brent(train).slope,
        approval='withheld_pending_strict_prospective_evidence_and_independent_review',
    )
    manifest['experiment_id'] = hashed(manifest)
    with Path(path).open('x', encoding='utf-8') as output:
        json.dump(manifest, output, indent=2, allow_nan=False)
        output.write('\n')
    return manifest


def load_manifest(root, path, *, verify_runtime=True):
    manifest = json.loads(Path(path).read_text())
    content = {key: value for key, value in manifest.items() if key != 'experiment_id'}
    if hashed(content) != manifest['experiment_id']:
        raise ValueError('Shadow experiment manifest was changed')
    if verify_runtime:
        if _runtime() != manifest['runtime']:
            raise ValueError('Python or model dependencies changed since the shadow freeze')
        bundle = root / manifest['protocol']['bundle']
        files = {root / 'config/project.toml': manifest['settings_sha256'],
                 root / 'config/forecasting_research.json': manifest['feature_config_sha256'],
                 bundle / 'manifest.json': manifest['bundle_manifest_sha256'],
                 bundle / 'bundle.joblib': manifest['bundle_sha256']}
        if any(_sha(p) != expected for p, expected in files.items()) or _source_hashes(root) != manifest['source_hashes']:
            raise ValueError('Inputs or code changed. Freeze a new experiment instead of mixing forecast versions.')
    return manifest


def _known_official_events(db, at):
    ts = at.isoformat()
    return db.execute('''SELECT * FROM outcomes WHERE available_at<? AND created_at<? ORDER BY id''',
                      (ts, ts)).fetchall()


def _reviewed_anchor(records, db, at, limits):
    anchor, problem = anchor_check(records, at, limits['anchor_maximum_age_days'])
    if problem:
        return None, None, problem
    target = dict(kind='calendar', endpoint=at.isoformat())
    reviewed, status = select_event(_known_official_events(db, at), target, at, at)
    if reviewed is None or status != 'matched_verified_outcome':
        return None, None, 'No reviewed original Ministry decision establishes the prevailing price at the origin'
    published, effective = event_clocks(reviewed)
    if (reviewed['source_revision_id'] != anchor['revision_id'] or reviewed['price'] != anchor['price_lbp_20l']
            or not published.strictly_before(at) or not effective.strictly_before(at)):
        return None, None, 'The reviewed official decision does not establish the latest reconciled price before the origin'
    return anchor, reviewed, None


def _settled(db, experiment_id, *, at=None, family=None, market_age_band=None):
    where = ["f.mode=?", "json_extract(f.target_json,'$.experiment_id')=?"]
    params = [MODE, experiment_id]
    if at is not None:
        where.extend(['e.created_at<?', 'o.available_at<?', 'o.created_at<?'])
        params.extend([at.isoformat()] * 3)
    if family is not None:
        where.append("json_extract(f.target_json,'$.family')=?")
        params.append(family)
    if market_age_band is not None:
        where.append("json_extract(f.target_json,'$.market_age_band')=?")
        params.append(market_age_band)
    query = """SELECT f.*, e.prediction_error, e.actual_change, e.interval_hit, e.direction_hit,
        o.decision_key AS settled_decision, o.effective_timestamp, o.available_at AS actual_known_at
        FROM forecasts f JOIN evaluations e ON f.id=e.forecast_id JOIN outcomes o ON o.id=e.outcome_id
        WHERE """ + ' AND '.join(where) + """ AND e.kind='official_match' ORDER BY e.id"""
    latest = {r['id']: dict(r) for r in db.execute(query, params)}
    # A later review that makes the target ambiguous suspends its use. The
    # stored evaluation remains intact for audit.
    review_filter = 'AND a.created_at<?' if at is not None else ''
    reviews = db.execute(f"""SELECT a.forecast_id,a.status FROM match_attempts a
        JOIN forecasts f ON f.id=a.forecast_id
        WHERE f.mode=? AND json_extract(f.target_json,'$.experiment_id')=?
          AND a.status!='awaiting_verified_complete_coverage' {review_filter}
        ORDER BY a.id""", ([MODE, experiment_id, at.isoformat()] if at is not None else [MODE, experiment_id]))
    states = dict(reviews.fetchall())
    return [row for fid, row in latest.items()
            if states.get(fid, 'matched_verified_outcome') == 'matched_verified_outcome']


def _uncertainty(db, manifest, family, band, at, change):
    maturity = _settled(db, manifest['experiment_id'], at=at, family=family, market_age_band=band)
    distinct = {}
    for row in sorted(maturity, key=lambda r: (r['origin'], r['id'])):
        distinct.setdefault(row['settled_decision'], row)
    rows = sorted(distinct.values(), key=lambda r: r['origin'])[-manifest['protocol']['maximum_calibration_decisions']:]
    n = len(rows)
    details = dict(n=n, forecast_ids=[row['id'] for row in rows],
                   method='past_settled_shadow_absolute_residuals_and_exact_sign')
    if n < manifest['protocol']['minimum_calibration_decisions']:
        return None, None, details
    residuals = np.array([-r['prediction_error'] for r in rows], dtype=float)
    rank = math.ceil((n + 1) * .9)
    if rank > n:
        return None, None, details
    radius = max(5000., float(np.sort(abs(residuals))[rank - 1]))
    # Empirical exact-sign probabilities are kept in shadow, and only enabled
    # when the calibration sample represents all three outcome classes.
    classes = np.sign([row['actual_change'] for row in rows]).astype(int) + 1
    counts = np.bincount(classes, minlength=3)
    probs = None
    if counts.min() >= 5:
        signs = np.sign(change + residuals).astype(int) + 1
        probs = ((np.bincount(signs, minlength=3) + .03) / (n + .09)).tolist()
    details['actual_class_counts'] = counts.tolist()
    return [change - radius, change + radius], probs, details


def forecast_at(root, manifest, at):
    """Run the same clocked feature path for live issue and strict replay."""
    at = stamp(at.isoformat())
    if at <= stamp(manifest['frozen_at']):
        raise ValueError('Forecast origin must follow the candidate freeze')
    settings = _settings(root)
    limits = manifest['protocol']
    records, histories = current_context(root, settings, at)
    market = {sid: rows[-1] for sid, rows in histories.items() if rows}
    with _read_ledger(_ledger_path(root, settings)) as db:
        anchor, reviewed, problem = _reviewed_anchor(records, db, at, limits)
        frame = None
        frame_error = None
        if anchor:
            try:
                frame = strict_feature_frame(root, records, histories, at, HORIZON)
            except ValueError as exc:
                frame_error = str(exc)
        schedule = estimate_next_decision_date(records, at)
        features = json.loads(frame.to_json(orient='records'))[0] if frame is not None else {}
        snapshot = dict(
            experiment=manifest, origin_beirut=at.astimezone(BEIRUT).isoformat(),
            anchor=anchor, reviewed_anchor_outcome_id=reviewed['id'] if reviewed else None,
            latest_domestic_revision=records[-1]['revision_id'] if records else None,
            features=features, latest_market_sightings={
                sid: {k: r[k] for k in ('id', 'capture_id', 'available_at', 'observation_date', 'value', 'unit')}
                for sid, r in market.items()},
        )
        issued = []
        for family in limits['candidates']:
            band = 'domestic_only'
            change, interval, probs = None, None, None
            calibration = dict(n=0)
            reason = problem
            if not reason:
                try:
                    change, band = _candidate(root, manifest, family, frame, frame_error, anchor, market, at)
                    if not math.isfinite(change) or anchor['price_lbp_20l'] + change <= 0:
                        raise ValueError('Candidate produced an invalid absolute price')
                    interval, probs, calibration = _uncertainty(db, manifest, family, band, at, change)
                except (ValueError, KeyError, OSError, TypeError, ImportError, ArithmeticError) as exc:
                    change = None
                    reason = str(exc)
            target = dict(kind='decision', steps=1, family=family, experiment_id=manifest['experiment_id'],
                          origin_beirut=at.astimezone(BEIRUT).isoformat(), base_decision_key=reviewed['decision_key'] if reviewed else None,
                          base_revision_id=anchor['revision_id'] if anchor else None,
                          scheduled_effective=schedule['dates'].get(HORIZON), schedule_basis=schedule['schedule_basis'],
                          market_age_band=band, probability_order=['decrease', 'exact_no_change', 'increase'],
                          ovx_regime=features.get('ovx_regime'),
                          domestic_regime=anchor.get('regime') if anchor else None,
                          interval_nominal=.9 if interval else None, calibration=calibration)
            issued.append(dict(target=target, family=family, base_price=anchor['price_lbp_20l'] if anchor else None,
                               prediction=change, interval=interval, probabilities=probs, reasons=[reason] if reason else []))
    return snapshot, issued


def _candidate(root, manifest, family, frame, frame_error, anchor, market, at):
    if family == 'A_no_change':
        return 0., 'domestic_only'
    if family == 'A_median':
        return manifest['median_change_lbp'], 'domestic_only'
    if family == 'B_official_structural':
        raise ValueError('Awaiting a dated Ministry benchmark window, pricing FX, and verified cost components')
    if frame is None:
        raise ValueError(frame_error or 'No eligible feature frame')
    values = frame.iloc[0]
    if family == 'Z_last_change':
        if not math.isfinite(values.x_domestic_change_lag1):
            raise ValueError('Previous comparable domestic record unavailable')
        return float(values.x_domestic_change_lag1), 'domestic_only'
    limits = manifest['protocol']
    if family == 'Z_brent':
        row = market.get('brent_spot')
        if not row or manifest['brent_slope'] is None:
            raise ValueError('Captured Brent input or frozen slope unavailable')
        age = (at.astimezone(BEIRUT).date() - datetime.fromisoformat(row['observation_date']).date()).days
        if not 0 <= age <= limits['lagged_spot_maximum_age_days']:
            raise ValueError('Brent input exceeds the tested freshness policy')
        band = 'fresh' if age <= limits['fresh_spot_maximum_age_days'] else 'lagged_spot'
        return float(manifest['brent_slope'] * (values.x_brent_spot_value - values.x_brent_spot_mean20)), band
    candidate = dict(family=family, path=limits['bundle'],
                     artifact_sha256=manifest['bundle_sha256'], required_market=REQUIRED_SPOT)
    change, _, lagged = quantitative(root, candidate, frame, anchor, market, at,
                                    limits['fresh_spot_maximum_age_days'], allow_lagged_spot=True,
                                    lagged_spot_maximum_age_days=limits['lagged_spot_maximum_age_days'])
    return change, 'lagged_spot' if lagged else 'fresh'


def issue(root, manifest_path, *, run_id=None):
    root = Path(root).resolve()
    manifest = load_manifest(root, manifest_path)
    at = datetime.now(timezone.utc)
    snapshot, forecasts = forecast_at(root, manifest, at)
    run_id = run_id or 'shadow-' + uuid4().hex
    items = [dict(row, run_id=run_id, origin=at.isoformat(), mode=MODE, horizon=HORIZON,
                  model_version='shadow-' + manifest['experiment_id'] + '-' + row['family'],
                  model_metadata=dict(experiment_id=manifest['experiment_id'], family=row['family'],
                                      artifact_sha256=manifest['bundle_sha256'], approved=False),
                  snapshot_payload=snapshot) for row in forecasts]
    with closing(ForecastLedger(_ledger_path(root, _settings(root)))) as db:
        ids = db.issue_batch(items)
    return dict(run_id=run_id, experiment_id=manifest['experiment_id'], origin_beirut=snapshot['origin_beirut'],
                forecasts=[dict(row, forecast_id=fid, snapshot_id=sid,
                                predicted_price_lbp_20l=row['base_price'] + row['prediction']
                                if row['prediction'] is not None else None)
                           for row, (fid, sid) in zip(forecasts, ids)])


def replay(root, manifest_path, origin):
    root = Path(root).resolve()
    manifest = load_manifest(root, manifest_path)
    at = stamp(origin)
    if at >= datetime.now(timezone.utc):
        raise ValueError('Replay origin must be in the past')
    snapshot, forecasts = forecast_at(root, manifest, at)
    return dict(evidence='strict_replay_not_prospective', snapshot=snapshot, forecasts=forecasts)


def _scores(rows):
    # Score one saved forecast per official outcome. Duplicate updates to the
    # same decision remain in the ledger but do not increase the evidence count.
    distinct = {}
    for row in sorted(rows, key=lambda r: (r['origin'], r['id'])):
        distinct.setdefault(row['settled_decision'], row)
    rows = list(distinct.values())
    if not rows:
        return dict(n=0, mae_lbp=None, rmse_lbp=None, bias_lbp=None, direction_accuracy=None,
                    interval_n=0, interval_coverage=None, interval_width_lbp=None, brier_n=0, brier=None)
    errors = np.array([r['prediction_error'] for r in rows])
    intervals = [r for r in rows if r['interval_hit'] is not None]
    briers = []
    bins = {}
    for row in rows:
        probabilities = json.loads(row['probabilities_json'] or 'null')
        if probabilities is None:
            continue
        actual = int(np.sign(row['actual_change'])) + 1
        briers.append(sum((p - (i == actual)) ** 2 for i, p in enumerate(probabilities)))
        for i, p in enumerate(probabilities):
            bins.setdefault((i, min(int(p * 5), 4)), []).append((p, int(i == actual)))
    return dict(n=len(rows), mae_lbp=float(abs(errors).mean()), rmse_lbp=float(np.sqrt((errors**2).mean())),
                bias_lbp=float(errors.mean()), direction_accuracy=float(np.mean([r['direction_hit'] for r in rows])),
                first_origin=rows[0]['origin'], last_origin=rows[-1]['origin'],
                actual_class_counts=np.bincount(np.sign([r['actual_change'] for r in rows]).astype(int) + 1,
                                                minlength=3).tolist(),
                interval_n=len(intervals),
                interval_coverage=float(np.mean([r['interval_hit'] for r in intervals])) if intervals else None,
                interval_width_lbp=float(np.mean([r['interval_high'] - r['interval_low'] for r in intervals])) if intervals else None,
                brier_n=len(briers), brier=float(np.mean(briers)) if briers else None,
                reliability=[dict(event=['decrease', 'exact_no_change', 'increase'][i], bin_lower=b/5,
                                  bin_upper=(b+1)/5, n=len(s), mean_probability=float(np.mean([x[0] for x in s])),
                                  observed_frequency=float(np.mean([x[1] for x in s])))
                             for (i, b), s in sorted(bins.items())])


def report(root, manifest_path):
    root = Path(root).resolve()
    manifest = load_manifest(root, manifest_path, verify_runtime=False)
    experiment = manifest['experiment_id']
    with _read_ledger(_ledger_path(root, _settings(root))) as db:
        issued = [dict(r) for r in db.execute("""SELECT * FROM forecasts WHERE mode=?
                   AND json_extract(target_json,'$.experiment_id')=? ORDER BY id""", (MODE, experiment))]
        outcomes = _settled(db, experiment)
    detail, paired = {}, []
    for family in manifest['protocol']['candidates']:
        cases = [r for r in issued if json.loads(r['target_json'])['family'] == family]
        matches = [r for r in outcomes if json.loads(r['target_json'])['family'] == family]
        numeric = sum(r['status'] == 'issued' for r in cases)
        by_band = {band: _scores([r for r in matches if json.loads(r['target_json'])['market_age_band'] == band])
                   for band in ('fresh', 'lagged_spot', 'domestic_only')}
        detail[family] = dict(attempts=len(cases), numerical_issues=numeric,
                              issuance_rate=numeric / len(cases) if cases else None,
                              unscored_numerical=numeric - len(matches), reviewed_metrics=_scores(matches),
                              metrics_by_market_age=by_band)
        for baseline in ('A_no_change', 'Z_last_change', 'A_median', 'Z_brent'):
            if family == baseline:
                continue
            by_origin = {(r['run_id'], r['settled_decision']): r for r in outcomes
                         if json.loads(r['target_json'])['family'] == baseline}
            left = [r for r in matches if (r['run_id'], r['settled_decision']) in by_origin]
            right = [by_origin[(r['run_id'], r['settled_decision'])] for r in left]
            paired.append(dict(candidate=family, baseline=baseline, candidate_metrics=_scores(left),
                               baseline_metrics=_scores(right)))
    return dict(experiment_id=experiment, frozen_at=manifest['frozen_at'], horizon=HORIZON,
                minimum_review_decisions=manifest['protocol'].get('minimum_review_decisions'),
                target_review_decisions=manifest['protocol'].get('target_review_decisions'),
                evidence='strict prospective only; no replay or conditional archive outcomes counted',
                decision='production_approval_withheld', models=detail, paired_comparisons=paired,
                remaining_horizons={'day_7': 'awaiting separate effective-price evaluation',
                                    'day_30': 'conditional scenarios only'})
