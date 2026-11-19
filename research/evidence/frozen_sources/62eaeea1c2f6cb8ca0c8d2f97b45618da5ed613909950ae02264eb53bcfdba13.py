"""Reviewed outcome import and deterministic matching; clockless history is not guessed."""
from pathlib import Path
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from lebanon_fuel.storage.database import Store
from lebanon_fuel.domain import utc_timestamp
from .ledger import ForecastLedger,hashed


def settle(root,manifest_path):
    root=Path(root);payload=json.loads(Path(manifest_path).read_text())
    if not payload.get('reviewer') or not payload.get('clock_evidence_url'):raise ValueError('A named reviewer and original clock evidence URL are required')
    import tomllib
    config_path=root/'config/project.toml'
    config=tomllib.loads(config_path.read_text()) if config_path.exists() else {}
    source=Store(root,config.get('storage',{}).get('database','data/lebanon_fuel.sqlite'))
    ledger=ForecastLedger(root/config.get('validation',{}).get('forecast_ledger','data/forecast_ledger.sqlite'));imported=[]
    try:
        for item in payload['outcomes']:
            row=source.db.execute('SELECT * FROM observations WHERE id=?',(item['source_observation_id'],)).fetchone()
            if not row or not row['document_verified'] or not row['is_valid']:raise ValueError('Outcome must reference an existing valid original-document verified observation')
            if item['price_lbp_20l']!=row['price_lbp_20l']:raise ValueError('Outcome price disagrees with preserved original observation')
            if row['unit']!='LBP/20L':raise ValueError('Outcome unit is not LBP per 20 liters')
            if not item.get('publication_timestamp') or not item.get('effective_timestamp'):raise ValueError('Verified publication and effective timestamps are required; dates alone are insufficient')
            if row['publication_timestamp'] and utc_timestamp(item['publication_timestamp'])!=row['publication_timestamp']:raise ValueError('Publication timestamp contradicts source record')
            if datetime.fromisoformat(utc_timestamp(item['available_at']))<datetime.fromisoformat(row['first_retrieved_at']):raise ValueError('Reviewed outcome knowledge cannot precede the preserved source capture')
            effective_day=datetime.fromisoformat(utc_timestamp(item['effective_timestamp'])).astimezone(ZoneInfo('Asia/Beirut')).date().isoformat()
            if row['official_effective_date'] and effective_day!=row['official_effective_date']:raise ValueError('Effective timestamp contradicts original effective date')
            if not item.get('official_decision_key'):raise ValueError('A stable official decision identifier is required')
            evidence={'observation_id':row['id'],'raw_json':row['raw_json'],'reviewer':payload['reviewer'],
                'clock_evidence_url':payload['clock_evidence_url'],'clock_transcription':item}
            imported.append(ledger.outcome(item['official_decision_key'],item['available_at'],item['price_lbp_20l'],row['source_url'],'document_verified',
                hashed(evidence),evidence,item['publication_timestamp'],item['effective_timestamp'],item.get('source_revision_id')))
        matched={str(fid):ledger.match(fid,payload.get('coverage',{})) for fid in payload.get('forecast_ids',[])}
        return dict(imported_outcome_ids=imported,match_status=matched,**ledger.integrity())
    finally:source.close();ledger.close()
