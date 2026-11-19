"""Build an explicit hypothetical request for the existing Decimal cost engine."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from lebanon_fuel.domain import BEIRUT
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
