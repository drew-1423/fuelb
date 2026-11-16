"""Review original observations and match outcomes without inventing publication clocks."""
from contextlib import closing
from pathlib import Path
import json
import tomllib
from datetime import datetime, timezone

from lebanon_fuel.domain import BEIRUT
from lebanon_fuel.storage.database import Store
from .decision_events import clock, stamp
from .ledger import ForecastLedger, hashed


def _prepare_outcome(source, payload, item):
    row = source.db.execute(
        'SELECT * FROM observations WHERE id=?', (item['source_observation_id'],)
    ).fetchone()
    if not row or not row['document_verified'] or not row['is_valid'] or row['source_id'] != 'official_document':
        raise ValueError('Outcome must reference an existing valid original-document verified observation')
    if item['price_lbp_20l'] != row['price_lbp_20l'] or row['unit'] != 'LBP/20L':
        raise ValueError('Outcome price or unit disagrees with the preserved original observation')
    publication = item.get('publication_timestamp')
    effective = item.get('effective_timestamp')
    publication_date = item.get('publication_date') or row['publication_date']
    effective_date = item.get('effective_date') or row['official_effective_date']
    pub_clock = clock(publication, publication_date)
    eff_clock = clock(effective, effective_date)
    if pub_clock is None or eff_clock is None:
        raise ValueError('Review publication and effective dates or provide verified exact clocks')
    for name, source_day, reviewed in (
        ('publication', row['publication_date'], pub_clock),
        ('effective', row['official_effective_date'], eff_clock),
    ):
        if source_day and reviewed.lower.astimezone(BEIRUT).date().isoformat() != source_day:
            raise ValueError(f'Reviewed {name} date contradicts the original observation')
    if row['publication_timestamp'] and (not publication or stamp(publication) != stamp(row['publication_timestamp'])):
        raise ValueError('Publication timestamp contradicts source record')
    available = stamp(item['available_at'])
    if available < max(stamp(row['first_retrieved_at']), pub_clock.lower):
        raise ValueError('Reviewed outcome knowledge cannot precede source capture or publication')
    if available > datetime.now(timezone.utc):
        raise ValueError('Reviewed outcome knowledge time cannot be in the future')
    if not item.get('official_decision_key'):
        raise ValueError('A stable official decision identifier is required')
    revision = item.get('source_revision_id')
    if revision is not None:
        ver = source.db.execute(
            'SELECT * FROM decision_versions WHERE id=?', (revision,)
        ).fetchone()
        observed = json.loads(ver['payload_json']) if ver else {}
        if (not ver or observed.get('source_date') != row['source_date']
                or observed.get('price_lbp_20l') != row['price_lbp_20l']
                or row['id'] not in observed.get('observation_ids', [])):
            raise ValueError('Source revision does not reference the reviewed date and price')
        if stamp(ver['created_at']) > available:
            raise ValueError('Review cannot predate the linked source revision')
    captures = source.db.execute('''SELECT c.id,c.sha256,c.metadata_json FROM captures c
        JOIN sightings s ON s.capture_id=c.id WHERE s.observation_id=? ORDER BY c.id''', (row['id'],))
    originals = []
    for capture in captures:
        original_id = json.loads(capture['metadata_json']).get('evidence_capture_id')
        original = source.db.execute(
            'SELECT id,sha256,url FROM captures WHERE id=?', (original_id,)
        ).fetchone()
        if original is not None:
            originals.append(dict(original))
    if (not publication or not effective) and not originals:
        raise ValueError('Date-only reviews require a linked original document capture')
    evidence = dict(observation_id=row['id'], raw_json=row['raw_json'], reviewer=payload['reviewer'],
                    clock_evidence_url=payload['clock_evidence_url'], clock_transcription=item,
                    original_captures=originals,
                    reviewed_clock_dates=dict(publication_date=publication_date, effective_date=effective_date))
    return (item['official_decision_key'], available.isoformat(), row['price_lbp_20l'], row['source_url'],
            'document_verified', hashed(evidence), evidence, publication, effective, revision)


def settle(root, manifest_path):
    root = Path(root).resolve()
    payload = json.loads(Path(manifest_path).read_text())
    if not payload.get('reviewer') or not payload.get('clock_evidence_url'):
        raise ValueError('A named reviewer and original clock evidence URL are required')
    config_path = root / 'config/project.toml'
    config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    with closing(Store(root, config.get('storage', {}).get('database', 'data/lebanon_fuel.sqlite'), readonly=True)) as source:
        outcomes = [_prepare_outcome(source, payload, item) for item in payload['outcomes']]
    with closing(ForecastLedger(root / config.get('validation', {}).get('forecast_ledger', 'data/forecast_ledger.sqlite'))) as ledger:
        imported = [ledger.outcome(*values) for values in outcomes]
        matched = {str(fid): ledger.match(fid, payload.get('coverage', {})) for fid in payload.get('forecast_ids', [])}
        return dict(imported_outcome_ids=imported, match_status=matched, **ledger.integrity())
