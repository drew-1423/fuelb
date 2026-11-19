"""Explicit fail-closed operational decisions, separate from research model functions."""
from datetime import datetime
from lebanon_fuel.domain import utc_timestamp


def gate(origin,anchor,market,model,context):
    at=datetime.fromisoformat(utc_timestamp(origin));reasons=[]
    if not model.get('approved') and context.get('intended_use')!='prospective_research':reasons.append('model_not_approved')
    if context.get('regime') not in model.get('supported_regimes',[]):reasons.append('unsupported_regulatory_regime')
    if not anchor.get('official_verified'):reasons.append('unverified_official_anchor')
    for key in ['known_at','effective_at']:
        if not anchor.get(key):reasons.append('anchor_'+key+'_missing')
        elif datetime.fromisoformat(utc_timestamp(anchor[key]))>=at:reasons.append('anchor_'+key+'_not_before_origin')
    for sid in model.get('required_market',[]):
        row=market.get(sid)
        if not row or row.get('value') is None:reasons.append(sid+'_missing');continue
        if not row.get('available_at') or datetime.fromisoformat(utc_timestamp(row['available_at']))>=at:reasons.append(sid+'_not_known_before_origin')
        if not row.get('observation_date'):reasons.append(sid+'_observation_date_missing')
        elif (at.date()-datetime.fromisoformat(row['observation_date']).date()).days<0:reasons.append(sid+'_future_observation_date')
        elif (at.date()-datetime.fromisoformat(row['observation_date']).date()).days>context.get('maximum_market_age_days',7):reasons.append(sid+'_stale_observation')
        if not row.get('vintage_certified'):reasons.append(sid+'_vintage_unverified')
    for risk in ['fx_disruption','tax_change','government_intervention','input_out_of_support']:
        if context.get(risk):reasons.append(risk+'_requires_review')
    if not context.get('complete_decision_coverage'):reasons.append('decision_coverage_unverified')
    return dict(status='abstain' if reasons else 'eligible',reasons=reasons,
                intervals_allowed=not reasons and model.get('intervals_validated',False),
                probabilities_allowed=not reasons and model.get('probabilities_validated',False))
