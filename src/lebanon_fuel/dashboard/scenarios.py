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
