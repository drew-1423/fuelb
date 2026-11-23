"""Append-only market revisions. Capture knowledge time is not observation time."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from lebanon_fuel.domain import utc_timestamp
from lebanon_fuel.storage.database import Store
from .catalog import SERIES, BARREL_LITERS


def close_availability(day, spec):
    """Explicit research convention, not proof of original publication or vintage.

    Daily close: 23:59:59 UTC on d. Weekly EIA: d+5 at that time.
    Other sources retain their documented project-specific research convention.
    Existing metadata and strict capture clocks are never rewritten.
    """
    lag = 0 if spec.frequency == 'daily' else (5 if spec.source == 'market_eia' and spec.frequency == 'weekly' else spec.research_lag_days)
    return datetime.combine(date.fromisoformat(day)+timedelta(days=lag), time(23,59,59), ZoneInfo('UTC')).isoformat()


def semantic_digest(day,raw_value,raw_unit,pub,vintage,evidence,issues):
    """Row positions/package timestamps are capture provenance, not new prices."""
    try:
        number=Decimal(str(raw_value))
        canonical=str(number.normalize()) if number.is_finite() else str(raw_value)
    except InvalidOperation:
        canonical=str(raw_value)
    semantic=json.dumps([day,canonical,raw_unit,pub,vintage,evidence,sorted(set(issues))],ensure_ascii=False)
    return sha256(semantic.encode()).hexdigest()


class MarketStore(Store):
    def __init__(self, root, db_path="data/lebanon_fuel.sqlite", *, readonly=False):
        super().__init__(root, db_path, readonly=readonly)
        if readonly:
            return
        self.db.executescript(Path(__file__).with_name("schema.sql").read_text())
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?)", ("market_fred_ovx", 10, "market_fred_ovx"))
            for spec in SERIES.values():
                self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?)", (spec.source, 10, spec.source))
                metadata = json.dumps(spec.metadata(), sort_keys=True)
                existing = self.db.execute("SELECT metadata_json FROM market_series WHERE id=?", (spec.id,)).fetchone()
                if existing and existing[0] != metadata:
                    raise ValueError("Series specification changed: create a versioned series identity")
                self.db.execute("INSERT OR IGNORE INTO market_series VALUES (?,?)", (spec.id, metadata))

    def ingest_market(self, capture_id, series_id, rows):
        spec = SERIES[series_id]
        cap = self.db.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
        allowed_sources = {spec.source} | ({"market_fred_ovx"} if series_id == "cboe_ovx" else set())
        if cap is None or cap['source_id'] not in allowed_sources:
            raise ValueError("Market capture source mismatch")
        seen = cap['retrieved_at']
        count = added = 0
        with self.db:
            for row in rows:
                day = row['date']
                date.fromisoformat(day)
                raw_value = row.get('value')
                issues = list(row.get('issues', []))
                value = None
                try:
                    number = Decimal(str(raw_value))
                    if not number.is_finite() or number <= 0:
                        raise ValueError("Nonpositive/nonfinite market value")
                    value = float(number) * spec.factor
                    if not Decimal(str(value)).is_finite():
                        raise ValueError("Normalized overflow")
                    # Utilization can exceed 100 historically: flag for review, don't erase it.
                    if series_id == 'us_refinery_utilization' and value > 100:
                        issues.append('utilization_above_100_review')
                except (ValueError, InvalidOperation, TypeError):
                    issues.append('missing_or_invalid_value')
                raw_unit = row.get('unit', spec.unit)
                if raw_unit != spec.unit:
                    issues.append('unexpected_unit')
                if day > datetime.fromisoformat(seen).astimezone(ZoneInfo(spec.timezone)).date().isoformat():
                    issues.append('future_observation_date')
                pub = utc_timestamp(row['publication_timestamp']) if row.get('publication_timestamp') else None
                vintage = utc_timestamp(row['vintage_timestamp']) if row.get('vintage_timestamp') else None
                evidence = row.get('vintage_evidence_url')
                if (vintage is None) != (evidence is None):
                    raise ValueError("A historical vintage needs both a timestamp and evidence URL")
                if vintage and (not pub or vintage < pub or vintage > seen):
                    raise ValueError("Vintage must be documented, at/after publication and no later than capture")
                if vintage and datetime.fromisoformat(vintage).astimezone(ZoneInfo(spec.timezone)).date().isoformat() < day:
                    raise ValueError('Vintage cannot precede the observation period date')
                if pub and pub > seen:
                    issues.append('future_publication_timestamp')
                available = vintage or seen
                basis = 'documented_historical_vintage' if vintage else 'capture_time_latest_vintage'
                valid = not set(issues) & {'missing_or_invalid_value','unexpected_unit','future_observation_date','future_publication_timestamp'}
                raw = json.dumps(row.get('raw', row), sort_keys=True, default=str, ensure_ascii=False)
                digest = semantic_digest(day,raw_value,raw_unit,pub,vintage,evidence,issues)
                cur = self.db.execute("""INSERT OR IGNORE INTO market_observations
                 (series_id,semantic_hash,observation_date,raw_value,raw_unit,value,unit,
                  publication_timestamp,vintage_timestamp,vintage_evidence_url,first_seen_at,valid,raw_json,issues_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (series_id,digest,day,str(raw_value) if raw_value is not None else None,
                 raw_unit,value,spec.normalized_unit,pub,vintage,evidence,seen,int(valid),raw,json.dumps(sorted(set(issues)))))
                added += cur.rowcount
                obs = self.db.execute("SELECT id FROM market_observations WHERE series_id=? AND semantic_hash=?", (series_id,digest)).fetchone()[0]
                self.db.execute("INSERT OR IGNORE INTO market_sightings VALUES (?,?,?,?,?)", (capture_id,str(row['row_key']),obs,available,basis))
                count += 1
        return {'series':series_id,'parsed_rows':count,'new_observations':added,'capture_id':capture_id}

    def history(self, series_id, origin, mode='strict'):
        """One value per date as known at origin; ambiguous simultaneous rows excluded.

        Research mode intentionally uses the newest captured revision plus an assumed
        date lag. It MUST NOT be used to report real-time backtest performance.
        """
        origin = utc_timestamp(origin)
        if mode not in {'strict', 'research', 'as_of_close'}:
            raise ValueError('mode must be strict, research or as_of_close')
        spec = SERIES[series_id]
        sql = """SELECT o.*, ms.available_at, ms.availability_basis, ms.capture_id,
                 c.retrieved_at, c.url AS source_url FROM market_observations o
                 JOIN market_sightings ms ON ms.observation_id=o.id
                 JOIN captures c ON c.id=ms.capture_id WHERE o.series_id=?"""
        rows = self.db.execute(sql, (series_id,)).fetchall()
        groups = {}
        for raw in rows:
            row = dict(raw)
            row['captured_available_at'] = row['available_at']
            if mode == 'research':
                dt = datetime.combine(date.fromisoformat(row['observation_date'])+timedelta(days=spec.research_lag_days),time(23,59,59),ZoneInfo(spec.timezone))
                row['available_at'] = utc_timestamp(dt.isoformat())
                row['availability_basis'] = 'assumed_lag_latest_vintage_NOT_BACKTEST'
            elif mode == 'as_of_close':
                row['available_at'] = close_availability(row['observation_date'], spec)
                # A supplied later publication timestamp takes precedence over an assumed close.
                if row['publication_timestamp']:
                    row['available_at'] = max(row['available_at'], row['publication_timestamp'])
                row['availability_basis'] = 'assumed_close_latest_vintage_NOT_STRICT_BACKTEST'
            if row['available_at'] <= origin:
                groups.setdefault(row['observation_date'], []).append(row)
        result = []
        for day, candidates in sorted(groups.items()):
            # A reversal A->B->A remains visible because every capture has a sighting.
            rank = (lambda r:(r['available_at'],r['retrieved_at'])) if mode == 'strict' else (lambda r:(r['retrieved_at'],))
            latest = max(rank(r) for r in candidates)
            edition = [r for r in candidates if rank(r)==latest]
            if any(not r['valid'] for r in edition):
                continue  # latest invalid/missing value must not resurrect stale prior edition
            if len({r['value'] for r in edition}) != 1:
                continue
            selected = min(edition,key=lambda r:r['id'])
            if selected['unit'] == 'USD/bbl':
                selected['value_usd_kl'] = selected['value'] * 1000 / BARREL_LITERS
            result.append(selected)
        return result
