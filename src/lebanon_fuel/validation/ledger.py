"""Append-only forecast accountability. Creation time never masquerades as historical issuance."""
from datetime import date,datetime,timezone
from hashlib import sha256
from pathlib import Path
import json
import math
import sqlite3
import itertools
from lebanon_fuel.domain import utc_timestamp
from .decision_events import event_clocks, select_event


def now():return datetime.now(timezone.utc).isoformat()
def normalize(value):
    # SQLite REAL normalizes -0.0 to 0.0. Hash the value that will be persisted.
    if isinstance(value,float) and value==0:return 0.0
    if isinstance(value,dict):return {k:normalize(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [normalize(v) for v in value]
    return value
def canonical(value):return json.dumps(normalize(value),sort_keys=True,separators=(',',':'),allow_nan=False)
def hashed(value):return sha256(canonical(value).encode()).hexdigest()


class ForecastLedger:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path, timeout=30);self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,origin TEXT NOT NULL,mode TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,approved INTEGER NOT NULL CHECK(approved IN (0,1)),metadata_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS forecasts(id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,created_at TEXT NOT NULL,origin TEXT NOT NULL,mode TEXT NOT NULL,
          model_version TEXT NOT NULL REFERENCES models(id),snapshot_id TEXT NOT NULL REFERENCES snapshots(id),horizon TEXT NOT NULL,target_json TEXT NOT NULL,
          status TEXT NOT NULL,base_price REAL,predicted_price REAL,predicted_change REAL,interval_low REAL,interval_high REAL,
          probabilities_json TEXT,reason_json TEXT NOT NULL,previous_hash TEXT,record_hash TEXT NOT NULL UNIQUE,
          UNIQUE(run_id,origin,model_version,horizon));
        CREATE TABLE IF NOT EXISTS outcomes(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,decision_key TEXT NOT NULL,available_at TEXT NOT NULL,
          publication_timestamp TEXT,effective_timestamp TEXT,price REAL NOT NULL CHECK(price>0),source_url TEXT NOT NULL,verification_status TEXT NOT NULL,
          source_revision_id INTEGER,source_hash TEXT NOT NULL,payload_json TEXT NOT NULL,UNIQUE(decision_key,source_hash));
        CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,forecast_id INTEGER NOT NULL REFERENCES forecasts(id),
          outcome_id INTEGER NOT NULL REFERENCES outcomes(id),kind TEXT NOT NULL,prediction_error REAL NOT NULL,actual_change REAL NOT NULL,
          interval_hit INTEGER,direction_hit INTEGER NOT NULL,supersedes_id INTEGER REFERENCES evaluations(id),UNIQUE(forecast_id,outcome_id,kind));
        CREATE TABLE IF NOT EXISTS match_attempts(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,forecast_id INTEGER NOT NULL REFERENCES forecasts(id),status TEXT NOT NULL,details_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS forecast_origin ON forecasts(origin,horizon);
        CREATE INDEX IF NOT EXISTS outcomes_decision ON outcomes(decision_key,id);
        ''')
        for table in ['snapshots','models','forecasts','outcomes','evaluations','match_attempts']:
            for operation in ['UPDATE','DELETE']:
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'accountability records are immutable'); END")
        self.db.commit()

    def close(self):self.db.close()

    def snapshot(self,origin,mode,payload):
        origin=utc_timestamp(origin)
        forbidden={'target_change_lbp_20l','target_revision_id','witness_revision_id','endpoint_price_lbp_20l','actual_price'}
        if forbidden.intersection(payload):raise ValueError('Future outcomes cannot enter the forecast input snapshot')
        content=dict(origin=origin,mode=mode,inputs=payload);identity=hashed(content)
        with self.db:self.db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?)',(identity,now(),origin,mode,canonical(content)))
        return identity

    def model(self,identity,metadata,approved=False):
        if approved:raise ValueError('No production approval can be registered by this research ledger API')
        existing=self.db.execute('SELECT metadata_json FROM models WHERE id=?',(identity,)).fetchone()
        if existing and existing[0]!=canonical(metadata):raise ValueError('Model identity reused for changed metadata')
        with self.db:self.db.execute('INSERT OR IGNORE INTO models VALUES (?,?,?,?)',(identity,now(),0,canonical(metadata)))

    def reviewed_model(self, identity, metadata, decision, horizon):
        """Register an explicitly reviewed artifact; a configuration boolean is insufficient."""
        spec = decision.get('selection', {}).get(horizon, {})
        if not (decision.get('production_approved') is True and decision.get('decided_at')
                and pd_time(decision['decided_at']) < pd_time(now())
                and spec.get('production_model') == identity
                and spec.get('artifact_sha256') == metadata.get('artifact_sha256')
                and spec.get('review_evidence') and spec.get('complete_decision_coverage') is True
                and metadata.get('decision_sha256') == hashed(decision)):
            raise ValueError('Artifact-specific production review evidence required')
        existing = self.db.execute('SELECT approved,metadata_json FROM models WHERE id=?', (identity,)).fetchone()
        if existing and (existing[0] != 1 or existing[1] != canonical(metadata)):
            raise ValueError('Approval needs a new immutable model version')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO models VALUES (?,?,?,?)', (identity,now(),1,canonical(metadata)))

    def _prepare_model(self, identity, metadata, approved=False, decision=None, horizon=None):
        if decision is not None:
            spec = decision.get('selection', {}).get(horizon, {})
            if not (decision.get('production_approved') is True and decision.get('decided_at')
                    and pd_time(decision['decided_at']) < pd_time(now())
                    and spec.get('production_model') == identity
                    and spec.get('artifact_sha256') == metadata.get('artifact_sha256')
                    and spec.get('review_evidence') and spec.get('complete_decision_coverage') is True
                    and metadata.get('decision_sha256') == hashed(decision)):
                raise ValueError('Artifact-specific production review evidence required')
            existing = self.db.execute('SELECT approved,metadata_json FROM models WHERE id=?', (identity,)).fetchone()
            if existing and (existing[0] != 1 or existing[1] != canonical(metadata)):
                raise ValueError('Approval needs a new immutable model version')
            return (identity, now(), 1, canonical(metadata))
        if approved:
            raise ValueError('No production approval can be registered by this research ledger API')
        existing = self.db.execute('SELECT metadata_json FROM models WHERE id=?', (identity,)).fetchone()
        if existing and existing[0] != canonical(metadata):
            raise ValueError('Model identity reused for changed metadata')
        return (identity, now(), 0, canonical(metadata))

    def _validate_forecast_row(self, run_id, created, origin, mode, model_version, model_approved,
                               snapshot_id, snap_origin, snap_mode, horizon, target, base_price,
                               prediction=None, interval=None, probabilities=None, reasons=None,
                               max_origin_age_seconds=60):
        if mode not in {'retrospective_research', 'strict_replay', 'prospective', 'prospective_research', 'prospective_shadow'}:
            raise ValueError('Explicit issuance mode required')
        origin = utc_timestamp(origin or created)
        if snap_origin != origin or snap_mode != mode:
            raise ValueError('Forecast snapshot origin/mode mismatch')
        if mode.startswith('prospective') and abs((datetime.fromisoformat(created) - datetime.fromisoformat(origin)).total_seconds()) > max_origin_age_seconds:
            raise ValueError('A historical replay cannot be relabelled as a prospectively issued forecast')
        if mode == 'prospective' and prediction is not None and not model_approved:
            raise ValueError('Unapproved model cannot issue a numerical prospective forecast')
        if base_price is not None and (not math.isfinite(base_price) or base_price <= 0):
            raise ValueError('Invalid base price')
        if prediction is None and (interval is not None or probabilities is not None):
            raise ValueError('An abstention cannot carry numerical uncertainty')
        if prediction is not None and (not math.isfinite(prediction) or base_price is None or base_price + prediction <= 0):
            raise ValueError('Invalid price forecast')
        if probabilities is not None:
            if len(probabilities) != 3 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities) or abs(sum(probabilities) - 1) > 1e-8:
                raise ValueError('Invalid directional distribution')
        if interval is not None and (len(interval) != 2 or not all(math.isfinite(x) for x in interval) or interval[0] > interval[1]):
            raise ValueError('Invalid interval')
        base_price = float(base_price) if base_price is not None else None
        prediction = float(prediction) if prediction is not None else None
        interval = [float(x) for x in interval] if interval is not None else None
        return dict(
            run_id=run_id, created_at=created, origin=origin, mode=mode, model_version=model_version,
            snapshot_id=snapshot_id, horizon=horizon, target_json=canonical(target),
            status='abstained' if prediction is None else 'issued', base_price=base_price,
            predicted_price=base_price + prediction if prediction is not None else None,
            predicted_change=prediction,
            interval_low=interval[0] if interval is not None else None,
            interval_high=interval[1] if interval is not None else None,
            probabilities_json=canonical(probabilities) if probabilities is not None else None,
            reason_json=canonical(reasons or []),
        )

    def issue(self,run_id,origin,mode,model_version,snapshot_id,horizon,target,base_price,prediction=None,interval=None,probabilities=None,reasons=None):
        created=now();origin=utc_timestamp(origin or created)
        snap=self.db.execute('SELECT * FROM snapshots WHERE id=?',(snapshot_id,)).fetchone()
        if not snap:raise ValueError('Forecast snapshot origin/mode mismatch')
        model=self.db.execute('SELECT approved FROM models WHERE id=?',(model_version,)).fetchone()
        if not model:raise ValueError('Unknown model version')
        row=self._validate_forecast_row(
            run_id,created,origin,mode,model_version,model[0],snapshot_id,snap['origin'],snap['mode'],
            horizon,target,base_price,prediction=prediction,interval=interval,probabilities=probabilities,reasons=reasons)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')  # Serialize hash-chain tail reads and inserts.
            previous=self.db.execute('SELECT record_hash FROM forecasts ORDER BY id DESC LIMIT 1').fetchone()
            row['previous_hash']=previous[0] if previous else None
            row['record_hash']=hashed(row)
            cursor=self.db.execute(f"INSERT INTO forecasts({','.join(row)}) VALUES ({','.join(['?']*len(row))})",tuple(row.values()))
        return cursor.lastrowid

    def issue_batch(self, items, max_origin_age_seconds=300):
        """Atomically register models, snapshots, and all forecasts in one transaction."""
        if not items:
            return []
        created = now()
        forbidden = {'target_change_lbp_20l', 'target_revision_id', 'witness_revision_id', 'endpoint_price_lbp_20l', 'actual_price'}
        prepared = []
        seen_models = {}
        for item in items:
            mode = item['mode']
            origin = utc_timestamp(item.get('origin') or created)
            model_id = item['model_version']
            metadata = item['model_metadata']
            decision = item.get('decision')
            horizon = item['horizon']
            if model_id in seen_models:
                prev_approved, prev_meta = seen_models[model_id]
                cur_approved = 1 if decision is not None else 0
                if prev_approved != cur_approved or prev_meta != canonical(metadata):
                    raise ValueError('Model identity reused for changed metadata')
                model_tuple = None
                model_approved = prev_approved
            else:
                model_tuple = self._prepare_model(model_id, metadata, approved=False, decision=decision, horizon=horizon)
                model_approved = model_tuple[2]
                seen_models[model_id] = (model_approved, model_tuple[3])

            payload = item['snapshot_payload']
            if forbidden.intersection(payload):
                raise ValueError('Future outcomes cannot enter the forecast input snapshot')
            snap_content = dict(origin=origin, mode=mode, inputs=payload)
            snapshot_id = hashed(snap_content)
            snap_tuple = (snapshot_id, created, origin, mode, canonical(snap_content))

            row = self._validate_forecast_row(
                item['run_id'], created, origin, mode, model_id, model_approved,
                snapshot_id, origin, mode, horizon, item['target'], item.get('base_price'),
                prediction=item.get('prediction'), interval=item.get('interval'),
                probabilities=item.get('probabilities'), reasons=item.get('reasons'),
                max_origin_age_seconds=max_origin_age_seconds,
            )
            prepared.append((model_tuple, snap_tuple, row))

        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous_row = self.db.execute('SELECT record_hash FROM forecasts ORDER BY id DESC LIMIT 1').fetchone()
            previous_hash = previous_row[0] if previous_row else None
            out = []
            for model_tuple, snap_tuple, row in prepared:
                if model_tuple is not None:
                    self.db.execute('INSERT OR IGNORE INTO models VALUES (?,?,?,?)', model_tuple)
                self.db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?)', snap_tuple)
                existing = self.db.execute('''SELECT * FROM forecasts
                    WHERE run_id=? AND origin=? AND model_version=? AND horizon=?''',
                    (row['run_id'], row['origin'], row['model_version'], row['horizon'])).fetchone()
                if existing:
                    existing = dict(existing)
                    identity_fields = set(row) - {'created_at', 'previous_hash', 'record_hash'}
                    if any(row[key] != existing[key] for key in identity_fields):
                        raise ValueError('Forecast retry conflicts with immutable issuance')
                    out.append((existing['id'], snap_tuple[0]))
                    continue
                row['previous_hash'] = previous_hash
                row['record_hash'] = hashed(row)
                cursor = self.db.execute(f"INSERT INTO forecasts({','.join(row)}) VALUES ({','.join(['?']*len(row))})", tuple(row.values()))
                previous_hash = row['record_hash']
                out.append((cursor.lastrowid, snap_tuple[0]))
        return out

    def outcome(self,decision_key,available_at,price,source_url,verification_status,source_hash,payload,publication_timestamp=None,effective_timestamp=None,source_revision_id=None):
        available_at=utc_timestamp(available_at)
        if publication_timestamp:publication_timestamp=utc_timestamp(publication_timestamp)
        if effective_timestamp:effective_timestamp=utc_timestamp(effective_timestamp)
        if publication_timestamp and pd_time(publication_timestamp)>pd_time(available_at):raise ValueError('Actual outcome cannot be known before publication')
        if pd_time(available_at)>pd_time(now()):raise ValueError('Actual outcome knowledge time cannot be in the future')
        if not source_url or not source_hash or price<=0 or not math.isfinite(price):raise ValueError('Actual outcome needs source evidence and a positive price')
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO outcomes(created_at,decision_key,available_at,publication_timestamp,effective_timestamp,price,
                source_url,verification_status,source_revision_id,source_hash,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (now(),decision_key,available_at,publication_timestamp,effective_timestamp,price,source_url,verification_status,source_revision_id,source_hash,canonical(payload)))
        return self.db.execute('SELECT id FROM outcomes WHERE decision_key=? AND source_hash=?',(decision_key,source_hash)).fetchone()[0]

    def score_research(self,forecast_id,outcome_id):
        return self._score(forecast_id,outcome_id,'research_replay')

    def _score(self,forecast_id,outcome_id,kind):
        f=self.db.execute('SELECT * FROM forecasts WHERE id=?',(forecast_id,)).fetchone();o=self.db.execute('SELECT * FROM outcomes WHERE id=?',(outcome_id,)).fetchone()
        if not f or not o or f['status']!='issued':raise ValueError('An issued numerical forecast and actual observation are required')
        if kind=='research_replay' and f['mode']!='retrospective_research':raise ValueError('Research labels cannot settle a prospective official forecast')
        if kind not in {'official_match','research_replay','provisional_match'}:raise ValueError('Unknown evaluation kind')
        if kind == 'provisional_match':
            from .provisional import validate
            validate(f, o)
        if kind == 'official_match':
            publication, effective = event_clocks(o)
            if o['verification_status'] != 'document_verified' or publication is None or effective is None:
                raise ValueError('Official matching needs reviewed publication and effective timing')
            if json.loads(f['target_json'])['kind'] == 'decision':
                origin = pd_time(f['origin'])
                if f['mode'].startswith('prospective'):
                    origin = max(origin, pd_time(f['created_at']))
                if not publication.after(origin):
                    raise ValueError('Target publication was not proven to follow issuance')
        delta=o['price']-f['base_price'];error=f['predicted_price']-o['price']
        hit=None if f['interval_low'] is None else int(f['interval_low']<=delta<=f['interval_high'])
        sign=lambda x:(x>0)-(x<0)
        previous=self.db.execute('SELECT id FROM evaluations WHERE forecast_id=? AND kind=? ORDER BY id DESC LIMIT 1',(forecast_id,kind)).fetchone()
        with self.db:self.db.execute('''INSERT OR IGNORE INTO evaluations(created_at,forecast_id,outcome_id,kind,prediction_error,actual_change,interval_hit,direction_hit,supersedes_id)
            VALUES (?,?,?,?,?,?,?,?,?)''',(now(),forecast_id,outcome_id,kind,error,delta,hit,int(sign(f['predicted_change'])==sign(delta)),previous[0] if previous else None))

    def match(self,forecast_id,coverage):
        """Auto-match only with a certified complete sequence; absence of a row is never proof of no decision.

        coverage must cover (origin, through] and include its source evidence. It is
        a reviewed attestation, not inferred from observed gaps or a calendar.
        """
        f=self.db.execute('SELECT * FROM forecasts WHERE id=?',(forecast_id,)).fetchone()
        status='awaiting_verified_complete_coverage';chosen=None
        if f and f['status']=='issued' and coverage.get('certified') is True and coverage.get('evidence_url') and coverage.get('from') and coverage.get('through'):
            start=utc_timestamp(coverage['from']);through=utc_timestamp(coverage['through']);spec=json.loads(f['target_json'])
            if pd_time(through)>pd_time(now()):raise ValueError('Complete-coverage attestation cannot extend into the future')
            if pd_time(start)<=pd_time(f['origin'])<pd_time(through):
                lower = pd_time(f['origin'])
                rows = self.db.execute("SELECT * FROM outcomes ORDER BY id").fetchall()
                chosen, status = select_event(rows, spec, lower, pd_time(through))
                if chosen is not None:
                    publication, _ = event_clocks(chosen)
                    if (spec['kind'] == 'decision' and f['mode'].startswith('prospective')
                            and not publication.after(pd_time(f['created_at']))):
                        status = 'target_publication_not_proven_after_creation'
                    elif (spec['kind'] == 'calendar' and publication.by(lower)
                            and chosen['price'] != f['base_price']):
                        status = 'base_anchor_disagrees_requires_review'
                    elif 'base_decision_key' in spec:
                        anchor, _ = select_event(rows, {'kind': 'calendar', 'endpoint': f['origin']}, lower, lower)
                        if (anchor is None or anchor['decision_key'] != spec['base_decision_key']
                                or anchor['price'] != f['base_price']):
                            status = 'base_anchor_disagrees_requires_review'
                        else:
                            self._score(forecast_id, chosen['id'], 'official_match')
                    else:
                        self._score(forecast_id, chosen['id'], 'official_match')
        with self.db:self.db.execute('INSERT INTO match_attempts(created_at,forecast_id,status,details_json) VALUES (?,?,?,?)',(now(),forecast_id,status,canonical(coverage)))
        return status

    def integrity(self):
        previous=None;count=0;legacy=0
        for row in self.db.execute('SELECT * FROM forecasts ORDER BY id'):
            payload=dict(row);payload.pop('id');checksum=payload.pop('record_hash')
            if payload['previous_hash']!=previous:raise ValueError('Forecast hash chain damaged')
            if hashed(payload)!=checksum:
                # Version-1 entries made before the signed-zero fix are retained.
                # Accept only an exact match to their original IEEE signed-zero encoding.
                zeros=[k for k,v in payload.items() if isinstance(v,float) and v==0]
                matched=False
                for signs in itertools.product([0.0,-0.0],repeat=len(zeros)):
                    candidate=dict(payload);candidate.update(zip(zeros,signs))
                    raw=json.dumps(candidate,sort_keys=True,separators=(',',':'),allow_nan=False)
                    if sha256(raw.encode()).hexdigest()==checksum:matched=True;break
                if not matched:raise ValueError('Forecast hash chain damaged')
                legacy+=1
            previous=checksum;count+=1
        return dict(forecasts=count,evaluations=self.db.execute('SELECT COUNT(*) FROM evaluations').fetchone()[0],hash_chain_valid=True,legacy_signed_zero_matches=legacy)


def pd_time(value):return datetime.fromisoformat(utc_timestamp(value))
