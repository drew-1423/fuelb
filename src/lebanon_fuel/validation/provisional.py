"""Conservative, explicitly conditional supplier targets; no official timing claims."""
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
import json

from lebanon_fuel.domain import BEIRUT, PROVISIONAL_PRICE, VERIFIED, supplier_agreement
from .decision_events import stamp

MAX_GAP_DAYS = 7


def proof(source, record):
    if record['verification_status'] not in VERIFIED | {PROVISIONAL_PRICE}:
        return None
    rows = source.db.execute('''SELECT id,source_id,price_lbp_20l,source_url,first_retrieved_at
        FROM observations WHERE source_date=? AND is_valid=1 AND source_id IN ('ipt','totalenergies','taqtek')
        ORDER BY first_retrieved_at,id''', (record['source_date'],)).fetchall()
    selected = {}
    for row in rows:
        if row['price_lbp_20l'] != record['price_lbp_20l']:
            return None
        selected.setdefault(row['source_id'], dict(row))
    partner = 'totalenergies' if 'totalenergies' in selected else 'taqtek'
    return [selected['ipt'], selected[partner]] if 'ipt' in selected and partner in selected else None


def select_target(forecast, records, days, source):
    spec = json.loads(forecast['target_json'])
    base_day = spec.get('base_source_date')
    base = records.get(base_day)
    if not base or base.get('price_lbp_20l') != forecast['base_price'] or base['verification_status'] == 'conflict':
        return 'anchor_revised', None, None
    issued = max(stamp(forecast['origin']), stamp(forecast['created_at']))
    if spec.get('score_protocol'):
        from .live_score import update_records

        days = [row['source_date'] for row in update_records(records[day] for day in days)]
    first = bisect_right(days, base_day)
    kind, number = forecast['horizon'].split('_')
    number = int(number)
    endpoint = None
    if kind == 'decision':
        end = first + number - 1
        witness = end
    else:
        endpoint = stamp(spec['endpoint']) if spec.get('endpoint') else stamp(forecast['origin']).astimezone(BEIRUT) + timedelta(days=number)
        if endpoint <= issued:
            return 'invalid_endpoint', None, None
        if endpoint >= datetime.now(timezone.utc):
            return 'not_matured', None, None
        end = bisect_right(days, endpoint.astimezone(BEIRUT).date().isoformat()) - 1
        witness = end + 1
        if end < first or days[end] != endpoint.astimezone(BEIRUT).date().isoformat():
            return 'missing_endpoint_observation', None, None
        if witness >= len(days):
            return 'missing_calendar_witness', None, None
    if end >= len(days):
        return 'no_new_record', None, None
    target = records[days[end]]
    path = []
    previous = date.fromisoformat(base_day)
    for index in range(first, witness+1):
        row = records[days[index]]
        day = date.fromisoformat(row['source_date'])
        if row['verification_status'] == 'conflict':
            return 'conflict', row, None
        if day <= issued.astimezone(BEIRUT).date():
            return 'record_may_precede_forecast', row, None
        if not 0 < (day-previous).days <= MAX_GAP_DAYS:
            return 'gap', row, None
        sources = proof(source, row)
        if not sources:
            return 'unconfirmed', row, None
        if min(stamp(s['first_retrieved_at']) for s in sources) <= issued:
            return 'record_may_precede_forecast', row, None
        path.append(dict(source_date=row['source_date'], price_lbp_20l=row['price_lbp_20l'],
                         source_revision_id=row['revision_id'], verification_status=row['verification_status'], sources=sources))
        previous = day
    target_path = path[end-first]
    if endpoint and any(stamp(s['first_retrieved_at']) > endpoint or
                        stamp(s['first_retrieved_at']).astimezone(BEIRUT).date() != endpoint.astimezone(BEIRUT).date()
                        for s in target_path['sources']):
        return 'endpoint_not_observed_in_time', target, None
    payload = dict(source_date=target['source_date'], source_revision_id=target['revision_id'],
                   sources=target_path['sources'], horizon=forecast['horizon'], path=path[:end-first+1],
                   witness=path[-1] if endpoint else None, endpoint=endpoint.isoformat() if endpoint else None,
                   target_interpretation='same_day_observed_supplier_price_at_calendar_endpoint' if endpoint else 'kth_next_corroborated_recorded_price',
                   coverage_certified=False,
                   limitation='Source-date sequence and same-day quotes are provisional evidence, not certified complete official decisions/effective dates.')
    return 'candidate', target, payload


def validate(forecast, outcome):
    """Defend the ledger boundary independently of the matcher's implementation."""
    payload = json.loads(outcome['payload_json'])
    spec = json.loads(forecast['target_json'])
    issued = max(stamp(forecast['origin']), stamp(forecast['created_at']))
    day = payload.get('source_date')
    if (forecast['mode'] not in {'prospective','prospective_research'} or outcome['verification_status'] != 'supplier_agreement'
            or not day or date.fromisoformat(day) <= issued.astimezone(BEIRUT).date()
            or outcome['decision_key'] != 'supplier:'+day):
        raise ValueError('Provisional scoring requires a later, same-date IPT and independent-source agreement')
    def check_sources(item):
        sources = item.get('sources', [])
        if (not supplier_agreement(s['source_id'] for s in sources) or len(sources) != 2
                or any(s['price_lbp_20l'] != item['price_lbp_20l'] or stamp(s['first_retrieved_at']) <= issued
                       or stamp(s['first_retrieved_at']) > stamp(outcome['available_at']) for s in sources)):
            raise ValueError('Provisional scoring requires a later, same-date IPT and independent-source agreement')
    check_sources(dict(sources=payload.get('sources',[]),price_lbp_20l=outcome['price']))
    if forecast['horizon'] == 'decision_1' and 'path' not in payload:
        return  # Original immutable next-update payloads retain their original checks.
    kind, count = forecast['horizon'].split('_')
    path = payload.get('path', [])
    if not path or (kind == 'decision' and len(path) != int(count)) or payload.get('horizon') != forecast['horizon']:
        raise ValueError('Provisional target path does not match horizon')
    if path[-1]['source_date'] != day or path[-1]['price_lbp_20l'] != outcome['price']:
        raise ValueError('Provisional endpoint price differs from path')
    previous = date.fromisoformat(spec['base_source_date'])
    for item in path + ([payload.get('witness')] if kind == 'day' else []):
        if not item or item.get('verification_status') not in VERIFIED | {PROVISIONAL_PRICE}:
            raise ValueError('Unverified provisional path')
        current = date.fromisoformat(item['source_date'])
        if not 0 < (current-previous).days <= MAX_GAP_DAYS or current <= issued.astimezone(BEIRUT).date():
            raise ValueError('Provisional path has an unsupported gap or ordering')
        check_sources(item)
        previous = current
    if kind == 'day':
        endpoint = stamp(spec.get('endpoint') or payload['endpoint'])
        # Endpoint belongs to the recorded forecast origin, not the seconds-later
        # ledger insertion. Keep the stricter issuance clock for label eligibility.
        expected = stamp(forecast['origin']).astimezone(BEIRUT) + timedelta(days=int(count))
        if endpoint != expected or stamp(payload['endpoint']) != endpoint:
            raise ValueError('Calendar endpoint does not match forecast horizon')
        if day != endpoint.astimezone(BEIRUT).date().isoformat() or any(stamp(s['first_retrieved_at']) > endpoint for s in payload['sources']):
            raise ValueError('Calendar endpoint was not observed before its cutoff')
