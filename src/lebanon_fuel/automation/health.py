"""Structured Phase 1 health contract. Research status cannot mask operational failures."""
from datetime import datetime, timezone, date
from pathlib import Path
import json

from lebanon_fuel.domain import BEIRUT, VERIFIED, PROVISIONAL_PRICE


def state(status, reasons=(), recovery=None, **detail):
    return dict(status=status,reasons=list(reasons),recovery=recovery,**detail)


def contract(*, at, required, optional, anchor, forecast, calibration, integrity, release,
             last_attempt=None,last_capture=None,refresh_ok=None):
    now=datetime.fromisoformat(at)
    feeds={}
    for sid,row in required.items():
        age=(now.astimezone(BEIRUT).date()-date.fromisoformat(row['observation_date'])).days if row else None
        feeds[sid]=state('failed' if age is None or age<0 or age>14 else 'warning' if age>7 else 'ok',
            ['missing_or_stale_required_feed'] if age is None or age<0 or age>14 else ['lagged_required_feed'] if age>7 else [],
            'Run the durable scheduled collector; verify provider availability.',observation_date=row.get('observation_date') if row else None,age_days=age)
    anchors=state('failed',['missing_or_conflicting_anchor'],'Reconcile current dated government or IPT/Taqtek evidence.')
    if anchor and anchor.get('verification_status') in VERIFIED | {PROVISIONAL_PRICE} and anchor.get('price_lbp_20l',0)>0:
        age=(now.astimezone(BEIRUT).date()-date.fromisoformat(anchor['source_date'])).days
        anchors=state('ok' if 0<=age<=10 else 'failed',[] if 0<=age<=10 else ['stale_or_future_anchor'],
                      source_date=anchor['source_date'],verification_status=anchor['verification_status'],age_days=age)
    model=state('failed',['forecast_unavailable'],'Check issuance and anchor/market eligibility.')
    if forecast and forecast.get('predicted_price') is not None:
        age=(now-datetime.fromisoformat(forecast['origin'])).total_seconds()/3600
        spec=forecast.get('spec',{})
        model=state('failed' if age<0 or age>12 else 'warning' if spec.get('tier',2)>1 else 'ok',
                    ['forecast_stale_or_future'] if age<0 or age>12 else ['unapproved_research'] if spec.get('tier',2)>1 else [],
                    issued_at=forecast.get('created_at',forecast['origin']),age_hours=age,tier=spec.get('tier'))
    checks=dict(required_feeds=state('failed' if any(r['status']=='failed' for r in feeds.values()) else 'warning' if any(r['status']=='warning' for r in feeds.values()) else 'ok',feeds=feeds),
                optional_feeds=state('warning' if optional else 'ok',optional,'Review optional feeds; they do not automatically block the active model.'),
                domestic_anchor=anchors,forecast=model,calibration=calibration,operational_integrity=integrity,release_verification=release)
    checks['refresh']=state('failed' if refresh_ok is False else 'ok' if refresh_ok is True else 'unknown',
                            ['refresh_failed'] if refresh_ok is False else [],'Inspect the latest refresh log.')
    severity={'failed':3,'unknown':2,'warning':1,'ok':0}
    overall=max(checks.values(),key=lambda r:severity[r['status']])['status']
    return dict(as_of=at,overall=overall,checks=checks,clocks=dict(last_refresh_attempted=last_attempt,
                last_successful_capture=last_capture,market_observations={sid:r['observation_date'] for sid,r in feeds.items()},
                forecast_issued=model.get('issued_at')),production_approved=False)


def _read(root,path):
    try:return json.loads((root/path).read_text())
    except (OSError,ValueError):return {}


def build(root,snap,forecast=None,refresh=None):
    root=Path(root);policy=_read(root,'config/live_forecasting.json')
    required={sid:None for candidate in policy.get('quantitative_candidates',[]) if candidate.get('family')=='G_hybrid' for sid in candidate.get('required_market',[])}
    for sid in required:
        history=snap.get('histories',{}).get(sid,[]);required[sid]=history[-1] if history else None
    optional=[sid for sid,info in snap.get('market',{}).get('series',{}).items() if sid not in required and info.get('status')!='available']
    records=snap.get('prices',[]);anchor=records[-1] if records else None
    f=None;calibration=state('unknown',['no_issued_forecast'],'Inspect horizon readiness.')
    if forecast is not None:
        row=dict(forecast);spec=json.loads(row['target_json']);f=dict(row,spec=spec)
        measured=spec.get('public_calibration') or {}
        calibration=state('ok' if measured.get('radius') is not None else 'warning',
            [] if measured.get('radius') is not None else ['insufficient_validated_outcomes'],
            'Collect independent matured outcomes; do not manufacture interval widths.',horizon=row.get('horizon'),readiness=measured)
    latest=_read(root,'reports/operations/latest_run.json')
    audits=[s for s in latest.get('steps',[]) if s['name']=='integrity_and_financial_arithmetic']
    integrity=state('unknown',['strict_audit_not_recorded'],'Run fuel-ops audit.')
    if audits:
        integrity=state('ok' if audits[-1]['status']=='success' else 'failed',
            [] if audits[-1]['status']=='success' else [audits[-1].get('error','strict_audit_failed')],
            'Restore original checksum-matched evidence and rerun the strict audit.',checked_at=latest.get('finished_at'))
    missing=_read(root,'reports/operations/phase1_missing_raw_captures.json')
    if missing.get('missing_count',0) or missing.get('corrupt_count',0):
        integrity=state('failed',['missing_original_capture_files'],
            'Restore only original bytes matching recorded checksums; unresolved evidence remains failed.',missing_files=missing['missing_count'])
    release=state('unknown',['release_attestation_unavailable'],'Run release create/verify and inspect exact-commit CI evidence.')
    try:
        from .release import files,identity
        payload=_read(root,'reports/releases/current.json')
        matching=payload.get('source_identity')==identity(files(root))
        release=state('warning' if matching else 'failed',
            ['source_verified_commit_attestation_unbound'] if matching and not payload.get('commit_sha') else [] if matching else ['runtime_source_digest_mismatch'],
            'Inspect the exact-commit CI attestation and strict verification results.',source_identity=payload.get('source_identity'),commit_sha=payload.get('commit_sha'))
    except (OSError,ValueError,KeyError):pass
    return contract(at=datetime.now(timezone.utc).isoformat(),required=required,optional=optional,anchor=anchor,
        forecast=f,calibration=calibration,integrity=integrity,release=release,
        last_attempt=(refresh or {}).get('started_at') or latest.get('started_at'),
        last_capture=snap.get('latest_capture'),refresh_ok=(refresh or {}).get('ok'))
