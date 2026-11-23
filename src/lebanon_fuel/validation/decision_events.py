"""Conservative event matching for exact clocks and explicitly reviewed Beirut dates."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json

from lebanon_fuel.domain import BEIRUT, utc_timestamp


def stamp(value):
    return datetime.fromisoformat(utc_timestamp(value))


@dataclass(frozen=True)
class Clock:
    lower: datetime
    upper: datetime
    upper_exclusive: bool = False

    def by(self, at):
        return self.upper <= at

    def after(self, other):
        if isinstance(other, Clock):
            return self.lower > other.upper or (self.lower == other.upper and other.upper_exclusive)
        return self.lower > other

    def strictly_before(self, at):
        return self.upper < at or (self.upper == at and self.upper_exclusive)


def clock(timestamp, day=None):
    if timestamp:
        at = stamp(timestamp)
        if day and at.astimezone(BEIRUT).date() != date.fromisoformat(day):
            raise ValueError('Reviewed date and exact timestamp disagree')
        return Clock(at, at)
    if day:
        day = date.fromisoformat(day)
        lower = datetime.combine(day, time.min, BEIRUT).astimezone(timezone.utc)
        upper = datetime.combine(day + timedelta(days=1), time.min, BEIRUT).astimezone(timezone.utc)
        return Clock(lower, upper, True)
    return None


def event_clocks(row):
    # Only the reviewed importer writes these fields. Legacy exact-clock outcomes
    # are still supported, without extracting or inferring any dates from raw text.
    reviewed = json.loads(row['payload_json']).get('reviewed_clock_dates', {})
    return (clock(row['publication_timestamp'], reviewed.get('publication_date')),
            clock(row['effective_timestamp'], reviewed.get('effective_date')))


def event_editions(rows):
    editions = {}
    for row in rows:
        if row['verification_status'] == 'document_verified':
            published, effective = event_clocks(row)
            if published is not None:
                editions.setdefault(row['decision_key'], []).append((row, published, effective))
    return editions


def select_event(rows, target, origin, through):
    """Return (outcome, status) only when the target identity is provable."""
    editions = event_editions(rows)
    if target['kind'] == 'decision':
        return _decision(editions, origin, through, target['steps'])
    return _calendar(editions, stamp(target['endpoint']), through)


def _decision(editions, origin, through, steps):
    candidates = []
    for versions in editions.values():
        possible = [v for v in versions if not v[1].by(origin) and v[1].lower <= through]
        if possible:
            candidates.append((min(v[1].lower for v in possible), versions))
    candidates.sort(key=lambda item: item[0])
    # Examine just the prefix needed to prove the kth announcement. Look at all
    # editions of a key if any edition can cross or compete for that boundary.
    previous = None
    for i, (_, versions) in enumerate(candidates[:steps], 1):
        row, published, effective = versions[-1]
        if len({(p, e) for _, p, e in versions}) > 1:
            return None, 'timing_revision_requires_review'
        if not published.after(origin) or not published.by(through):
            return None, 'publication_order_unresolved'
        if previous is not None and not published.after(previous):
            return None, 'ambiguous_simultaneous_announcements'
        if i == steps:
            if any(not min((v[1] for v in others), key=lambda c: c.lower).after(published)
                   for _, others in candidates[i:]):
                return None, 'ambiguous_simultaneous_announcements'
            if effective is None:
                return None, 'awaiting_reviewed_effective_date'
            return row, 'matched_verified_outcome'
        previous = published
    return None, 'awaiting_verified_complete_coverage'


def _calendar(editions, endpoint, through):
    if endpoint > through:
        return None, 'awaiting_verified_complete_coverage'
    candidates = []
    for versions in editions.values():
        # A later release with a retroactive effective clock is not yet known
        # at the calendar endpoint.
        if not any(p.lower <= endpoint and (e is None or e.lower <= endpoint)
                   for _, p, e in versions):
            continue
        candidates.append(versions)
    proven = [(versions[-1][0], versions[-1][2]) for versions in candidates
              if len({(p, e) for _, p, e in versions}) == 1
              and versions[-1][2] is not None and versions[-1][1].by(endpoint)
              and versions[-1][2].by(endpoint)]
    if not candidates:
        return None, 'awaiting_verified_complete_coverage'
    winner, effective_at = max(proven, key=lambda pair: pair[1].lower) if proven else (None, None)
    for versions in candidates:
        row, published, effective = versions[-1]
        if winner is not None and row['id'] == winner['id']:
            continue
        if effective_at is not None and all(e is not None and effective_at.after(e) for _, _, e in versions):
            continue
        if len({(p, e) for _, p, e in versions}) > 1:
            return None, 'timing_revision_requires_review'
        return None, 'ambiguous_effective_price'
    return winner, 'matched_verified_outcome'
