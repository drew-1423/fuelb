"""Build an explicit hypothetical request for the existing Decimal cost engine."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from lebanon_fuel.domain import BEIRUT, supplier_agreement
from lebanon_fuel.structural.engine import parameters, price


def simulate(template, *, product, fx, freight, vat_percent, charge,
             charge_taxable, brent=None, spread=0, now=None):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(BEIRUT).date().isoformat()
    request = deepcopy(template)
    request.update(origin=now.isoformat(), effective_date=day, mode="scenario",
                   coverage_note="Hypothetical FOB cost calculation using the May 2025 domestic cost scaffold.")
    refined = Decimal(str(product)) if brent is None else Decimal(str(brent)) + Decimal(str(spread))
    request["benchmark"].update(value=str(refined), identity="Hypothetical FOB refined gasoline",
                                window_description="User-defined scenario point",
                                evidence="Dashboard scenario inputs",
                                note="Direct product quote or Brent plus user-assumed product spread.")
    request["fx"]["value"] = str(fx)
    request["freight_usd_kl"]["value"] = str(freight)
    request["vat"]["value"] = str(Decimal(str(vat_percent)) / 100)
    adjustment = next(cost for cost in request["costs"] if cost["name"] == "hypothetical_additional_charge")
    adjustment.update(value=str(Decimal(str(charge)) * 50), taxable=charge_taxable)
    for _, field, _ in parameters(request):
        field.update(valid_from=day, valid_to=day, known_at=now.isoformat(), status="scenario")
        field.pop("low", None)
        field.pop("high", None)
    return price(request)


MACRO_PRESETS = ('Middle East Geopolitical Spike', 'Global Demand Slump',
                 'Currency Devaluation Shock', 'Status Quo Baseline')


def macro_preset(name, *, product=None, brent=None):
    """Hypothetical inputs only; missing closes remain missing."""
    if name not in MACRO_PRESETS:
        raise ValueError('Unknown macro scenario')
    result = dict(scenario_fx=89500)
    if product is not None:
        result['scenario_product'] = float(product)
    if brent is not None:
        result['scenario_brent'] = float(brent)
    if product is not None and brent is not None:
        result['scenario_spread'] = float(product-brent)
    if name in MACRO_PRESETS[:2]:
        crude, spread = (95., 18.) if name == MACRO_PRESETS[0] else (65., 10.)
        result.update(scenario_brent=crude, scenario_spread=spread,
                      scenario_product=crude+spread,
                      scenario_mode='Brent plus assumed product spread')
    else:
        if product is None:
            raise ValueError('A stored refined gasoline close is required for this preset')
        result['scenario_mode'] = 'Direct product quote'
        if name == 'Currency Devaluation Shock':
            result['scenario_fx'] = 100000
    return result


def economic_breakdown(output, fx):
    """Separate modeled USD imports, LBP scaffold charges, VAT and residuals."""
    imported = output.get('import_breakdown') or {}
    lines = output['breakdown_lbp_20l']
    factor = Decimal(str(fx)) / 50
    rows = [dict(component=label, lbp_20l=str(Decimal(imported.get(key,'0'))*factor),
                 basis='USD-linked model assumption') for key,label in (
                    ('benchmark_usd_kl','Refined-product cargo'),('freight_usd_kl','Freight'),
                    ('other_import_usd_kl','Other import costs'))]
    rows += [dict(component=key.replace('_',' ').title(),lbp_20l=value,
                  basis='Percentage tax on modeled taxable base' if key=='vat' else 'LBP cost scaffold assumption; not verified current tariff')
             for key,value in lines.items() if key != 'goods']
    rows.append(dict(component='Rounding adjustment',lbp_20l=output['rounding_adjustment_lbp_20l'],basis='Model rounding assumption'))
    return rows


def anchored_simulate(template, *, anchor, baseline_inputs, scenario_inputs, display_fx=89500, now=None,
                      maximum_anchor_age_days=10):
    """Apply a structural *difference* to an observed anchor; never assert an official formula."""
    from datetime import date
    from lebanon_fuel.domain import VERIFIED, PROVISIONAL_PRICE
    now = now or datetime.now(timezone.utc)
    if anchor.get('verification_status') not in VERIFIED | {PROVISIONAL_PRICE}:
        raise ValueError('Scenario anchor must be verified or supplier-corroborated')
    if anchor['verification_status'] == PROVISIONAL_PRICE:
        if not supplier_agreement(r['id'] for r in anchor.get('corroborating_sources',[])):
            raise ValueError('Provisional anchor needs both supplier sources')
    age = (now.astimezone(BEIRUT).date()-date.fromisoformat(anchor['source_date'])).days
    if not 0 <= age <= maximum_anchor_age_days:
        raise ValueError('Scenario anchor is stale or future-dated')
    observed = Decimal(str(anchor['price_lbp_20l']))
    display_fx = Decimal(str(display_fx))
    if not observed.is_finite() or observed <= 0 or not display_fx.is_finite() or display_fx <= 0:
        raise ValueError('Anchor and display exchange rate must be positive and finite')
    baseline = simulate(template,**baseline_inputs,now=now)
    scenario = simulate(template,**scenario_inputs,now=now)
    delta = Decimal(scenario['price_lbp_20l'])-Decimal(baseline['price_lbp_20l'])
    endpoint = observed+delta
    if endpoint <= 0:
        raise ValueError('Hypothetical scenario implies a nonpositive pump price')
    residual = observed-Decimal(baseline['price_lbp_20l'])
    breakdown = economic_breakdown(scenario,scenario_inputs['fx'])
    breakdown.append(dict(component='Anchor reconciliation residual',lbp_20l=str(residual),
        basis='Unexplained baseline difference held constant; not an official duty or margin'))
    precision_residual = endpoint-sum((Decimal(r['lbp_20l']) for r in breakdown),Decimal(0))
    if abs(precision_residual)>Decimal('0.000001'):
        raise ValueError('Scenario component reconciliation failed')
    breakdown.append(dict(component='Decimal precision reconciliation',lbp_20l=str(precision_residual),basis='Arithmetic precision only; not a financial charge'))
    return dict(mode='anchored_hypothetical_scenario',anchor=deepcopy(anchor),price_lbp_20l=str(endpoint),
        change_lbp_20l=str(delta),price_usd_20l=str(endpoint/display_fx),display_fx=str(display_fx),
        baseline_price_lbp_20l=str(observed),illustrative_model_baseline_lbp_20l=baseline['price_lbp_20l'],
        baseline_reconciliation_residual_lbp_20l=str(residual),components=breakdown,
        baseline_model=baseline,scenario_model=scenario,baseline_inputs=deepcopy(baseline_inputs),scenario_inputs=deepcopy(scenario_inputs),
        undocumented_components=['Distribution margin is not separately documented in this illustrative scaffold'],
        assumptions='Structural difference under the May 2025 illustrative cost scaffold; anchor residual and unadjusted charges held constant. Pricing FX is an explicit scenario input, separate from display conversion. No calibrated probability applies.',
        exact_official_formula=False,uncertainty={'probability':None})
