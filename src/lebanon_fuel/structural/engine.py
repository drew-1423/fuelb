"""Decimal cost accounting. No built-in Lebanese tariff, FX or rounding defaults."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
from zoneinfo import ZoneInfo

D = Decimal
BARREL_LITERS = D('158.987294928')  # 42 US gallons; exact volume conversion
STATUSES = {'verified_document', 'estimated', 'scenario'}


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('Missing or boolean numeric input')
    result = D(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Values must be finite and nonnegative')
    return result


def aware(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('A timezone-aware timestamp is required')
    return result


def parameters(request):
    if 'goods_lbp_kl' in request:
        if any(k in request for k in ('benchmark', 'fx', 'freight_usd_kl', 'other_import_usd_kl')):
            raise ValueError('Recorded goods and benchmark-derived goods are mutually exclusive')
        yield 'goods_lbp_kl', request['goods_lbp_kl'], 'LBP/kl'
    else:
        b = request['benchmark']
        if b['basis'] not in {'FOB', 'CIF'} or not b.get('identity') or not b.get('window_description'):
            raise ValueError('Benchmark identity, FOB/CIF basis and observation window are required')
        if b['unit'] not in {'USD/mt', 'USD/kl', 'USD/bbl', 'USD/L'}:
            raise ValueError('Unsupported benchmark unit')
        yield 'benchmark', b, b['unit']
        yield 'fx', request['fx'], 'LBP/USD'
        yield 'freight_usd_kl', request['freight_usd_kl'], 'USD/kl'
        yield 'other_import_usd_kl', request['other_import_usd_kl'], 'USD/kl'
        if b['unit'] == 'USD/mt':
            yield 'density', request['density'], 'kg/L'
    yield 'vat', request['vat'], 'fraction'
    names = set()
    for cost in request['costs']:
        if cost['name'] in names or cost['name'] == 'goods':
            raise ValueError('Cost names must be unique and cannot be goods')
        names.add(cost['name'])
        if not isinstance(cost.get('taxable'), bool):
            raise ValueError('Each cost needs an explicit VAT-base choice')
        yield cost['name'], cost, 'LBP/kl'


def validate(request):
    day = date.fromisoformat(request['effective_date'])
    mode = request['mode']
    if mode not in {'reconciliation', 'scenario', 'as_of'}:
        raise ValueError('Unknown pricing mode')
    origin = aware(request['origin'])
    if mode != 'reconciliation' and day < origin.astimezone(ZoneInfo('Asia/Beirut')).date():
        raise ValueError('Forecast/scenario effective date precedes origin')
    if not request.get('coverage_note') or not isinstance(request.get('goods_taxable'), bool):
        raise ValueError('Declare component coverage and the goods VAT base')
    for name, p, unit in parameters(request):
        n = number(p['value'])
        if p['unit'] != unit or p['status'] not in STATUSES:
            raise ValueError(f'{name}: unsupported unit or evidence status')
        if not p.get('evidence') or not p.get('note'):
            raise ValueError(f'{name}: evidence and interpretation are required')
        start, end = date.fromisoformat(p['valid_from']), date.fromisoformat(p['valid_to'])
        if not start <= day <= end:
            raise ValueError(f'{name}: parameter is outside its evidenced/scenario validity')
        known = aware(p['known_at']) if p.get('known_at') else None
        if mode != 'reconciliation' and (known is None or known > origin):
            raise ValueError(f'{name}: parameter unavailable at origin')
        if mode == 'as_of' and p['status'] == 'scenario':
            raise ValueError('Unknown future inputs require scenario mode')
        if 'low' in p or 'high' in p:
            if not number(p['low']) <= n <= number(p['high']):
                raise ValueError(f'{name}: invalid scenario bounds')
        extrema = [n] + [number(p[k]) for k in ('low','high') if k in p]
        if name in {'fx', 'density', 'benchmark'} and min(extrema) == 0:
            raise ValueError(f'{name}: value must be positive')
        if name == 'vat' and max(extrema) > 1:
            raise ValueError('VAT must be a fraction, not percentage points')
        if name == 'density' and max(extrema) > 2:
            raise ValueError('Density must be kg/L, not kg/m3')
    if 'benchmark' in request and request['benchmark']['basis'] == 'CIF':
        p = request['freight_usd_kl']
        if number(p['value']) != 0 or number(p.get('high', 0)) != 0:
            raise ValueError('CIF includes freight: adding it again would double count')
    rounding = request['rounding']
    if rounding is not None:
        if rounding.get('status') not in {'estimated', 'scenario'} or number(rounding['increment_lbp_20l']) == 0:
            raise ValueError('Only explicitly hypothetical positive rounding increments are supported')
        if not rounding.get('note'):
            raise ValueError('Explain the rounding hypothesis; no official rule is implemented')


def _evaluate(request):
    if 'goods_lbp_kl' in request:
        goods = number(request['goods_lbp_kl']['value'])
        imported = None
    else:
        b = request['benchmark']; q = number(b['value'])
        q_kl = {'USD/kl': lambda:q, 'USD/mt': lambda:q*number(request['density']['value']),
                'USD/bbl': lambda:q*1000/BARREL_LITERS, 'USD/L': lambda:q*1000}[b['unit']]()
        freight = number(request['freight_usd_kl']['value'])
        other = number(request['other_import_usd_kl']['value'])
        imported = dict(benchmark_usd_kl=str(q_kl), freight_usd_kl=str(freight), other_import_usd_kl=str(other))
        goods = (q_kl + freight + other)*number(request['fx']['value'])
    lines = [('goods', goods, request['goods_taxable'])]
    lines += [(c['name'], number(c['value']), c['taxable']) for c in request['costs']]
    pretax = sum((v for _,v,_ in lines), D(0))
    taxable = sum((v for _,v,t in lines if t), D(0))
    vat = taxable*number(request['vat']['value'])
    raw = (pretax+vat)/50
    rounding = request['rounding']
    price = raw if rounding is None else (raw/number(rounding['increment_lbp_20l'])).quantize(D(1), rounding=ROUND_HALF_UP)*number(rounding['increment_lbp_20l'])
    return {'price_lbp_20l':str(price), 'unrounded_lbp_20l':str(raw),
            'pretax_lbp_kl':str(pretax), 'vat_base_lbp_kl':str(taxable), 'vat_lbp_kl':str(vat),
            'breakdown_lbp_20l':{**{k:str(v/50) for k,v,_ in lines}, 'vat':str(vat/50)},
            'import_breakdown':imported, 'rounding_adjustment_lbp_20l':str(price-raw)}


def price(request):
    """Input bounds form a conditional sensitivity box, never a probability interval."""
    validate(request)
    result = _evaluate(request)
    bounds = []
    for endpoint in ('low', 'high'):
        req = deepcopy(request)
        for _,p,_ in parameters(req):
            if endpoint in p:
                p['value'] = p[endpoint]
        bounds.append(_evaluate(req)['price_lbp_20l'])
    bounded = [n for n,p,_ in parameters(request) if 'low' in p]
    result.update(mode=request['mode'], effective_date=request['effective_date'], origin=request['origin'],
                  exact_official_formula=False, coverage_note=request['coverage_note'],
                  parameter_evidence={n:{k:p.get(k) for k in ('status','evidence','known_at','valid_from','valid_to','note')} for n,p,_ in parameters(request)},
                  uncertainty={'kind':'conditional_input_box_not_calibrated' if bounded else 'not_quantified',
                               'low_lbp_20l':bounds[0] if bounded else None,
                               'high_lbp_20l':bounds[1] if bounded else None,
                               'bounded_inputs':bounded,'probability':None,
                               'limitations':'Excludes omitted costs, benchmark basis risk and unknown government action.'})
    return result
