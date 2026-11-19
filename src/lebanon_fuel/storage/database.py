from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import tomllib

from lebanon_fuel.domain import SOURCES, VERIFIED, PROVISIONAL_PRICE, now_utc, utc_timestamp, regime_label, weekday_disagreement


def sqlite_connection(path, *, readonly=False):
    """Bound waits for concurrent writers without changing database journal mode."""
    path = Path(path).resolve()
    target = path.as_uri() + "?mode=ro" if readonly else path
    connection = sqlite3.connect(target, uri=readonly, timeout=15.0)
    try:
        connection.execute("PRAGMA busy_timeout = 5000;")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


class Store:
    def __init__(self, root, db_path="data/lebanon_fuel.sqlite", *, readonly=False):
        self.root = Path(root).resolve()
        cfg_path=self.root/'config/project.toml'
        self.config=tomllib.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        path = self.root / db_path
        if readonly:
            self.db = sqlite_connection(path, readonly=True)
            self.db.row_factory = sqlite3.Row
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite_connection(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path(__file__).with_name("schema.sql").read_text())
        if 'basis_observation_ids' not in {r[1] for r in self.db.execute('PRAGMA table_info(resolutions)')}:
            self.db.execute("ALTER TABLE resolutions ADD COLUMN basis_observation_ids TEXT NOT NULL DEFAULT '[]'")
        self.db.executemany("INSERT OR IGNORE INTO sources VALUES (?,?,?)", [(s, *v) for s, v in SOURCES.items()])
        self.db.commit()

    def close(self):
        self.db.close()

    def start_run(self, source):
        with self.db:
            return self.db.execute("INSERT INTO collection_runs(source_id,started_at,status) VALUES (?,?,'running')", (source, now_utc())).lastrowid

    def finish_run(self, run, status, details):
        with self.db:
            self.db.execute("UPDATE collection_runs SET status=?,finished_at=?,details=? WHERE id=?", (status, now_utc(), json.dumps(details, ensure_ascii=False), run))

    def capture(self, source, url, raw, content_type, run=None, http_status=None, metadata=None, retrieved_at=None):
        digest = sha256(raw).hexdigest()
        suffix = ".zip" if raw[:2] == b"PK" and "zip" in content_type and "openxml" not in content_type else ".xlsx" if raw[:2] == b"PK" else ".xls" if raw[:4] == b"\xd0\xcf\x11\xe0" else ".pdf" if raw[:4] == b"%PDF" else ".json" if "json" in content_type else ".html" if "html" in content_type else ".txt"
        relative = Path(self.config.get('storage',{}).get('raw_dir','data/raw')) / source / (digest + suffix)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Raw artifact hash mismatch")
        else:
            with path.open("xb") as file:
                file.write(raw)
        with self.db:
            return self.db.execute("""INSERT INTO captures(source_id,run_id,url,retrieved_at,sha256,raw_path,content_type,http_status,metadata_json)
             VALUES (?,?,?,?,?,?,?,?,?)""", (source, run, url, utc_timestamp(retrieved_at or now_utc()), digest, str(relative), content_type, http_status, json.dumps(metadata or {}, sort_keys=True))).lastrowid

    def ingest(self, capture_id, records):
        cap = self.db.execute("SELECT * FROM captures WHERE id=?", (capture_id,)).fetchone()
        count = added = 0
        with self.db:
            for observation in records:
                if observation.source != cap["source_id"]:
                    raise ValueError("Observation/capture source mismatch")
                observation.checked(cap["retrieved_at"])
                digest = sha256(observation.semantic().encode()).hexdigest()
                cur = self.db.execute("""INSERT OR IGNORE INTO observations
                (source_id,semantic_hash,source_date,date_role,official_effective_date,publication_date,publication_timestamp,
                price_lbp_20l,unit,decision_number,source_url,first_retrieved_at,is_valid,document_verified,raw_json,issues_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (observation.source,digest,observation.source_date,observation.date_role,
                observation.official_effective_date,observation.publication_date,observation.publication_timestamp,
                observation.price_lbp_20l,observation.unit,observation.decision_number,observation.source_url,cap["retrieved_at"],
                int(observation.valid),int(observation.document_verified),json.dumps(observation.raw,ensure_ascii=False,default=str),json.dumps(observation.issues)))
                added += cur.rowcount
                obs_id = self.db.execute("SELECT id FROM observations WHERE source_id=? AND semantic_hash=?", (observation.source,digest)).fetchone()[0]
                self.db.execute("INSERT OR IGNORE INTO sightings VALUES (?,?,?)", (capture_id,observation.row_key,obs_id))
                count += 1
        return {"parsed_rows": count, "new_observations": added, "capture_id":capture_id}

    def resolve(self, day, observation_id, reason, evidence, reviewer):
        row = self.db.execute("SELECT * FROM observations WHERE id=?", (observation_id,)).fetchone()
        if not row or row["source_date"] != day or not row["is_valid"]:
            raise ValueError("Resolution must select a valid observation on the same source date")
        if not all(str(v).strip() for v in (reason,evidence,reviewer)):
            raise ValueError("Resolution requires reason, evidence and reviewer")
        with self.db:
            basis=[r[0] for r in self.db.execute('SELECT id FROM observations WHERE source_date=? ORDER BY id',(day,))]
            self.db.execute("INSERT INTO resolutions(source_date,chosen_observation_id,reason,evidence_url,reviewer,reviewed_at,basis_observation_ids) VALUES (?,?,?,?,?,?,?)", (day,observation_id,reason,evidence,reviewer,now_utc(),json.dumps(basis)))

    def reconcile(self):
        groups = {}
        for row in self.db.execute("SELECT o.*, s.priority FROM observations o JOIN sources s ON s.id=o.source_id ORDER BY source_date,o.id"):
            if row["source_date"]:
                groups.setdefault(row["source_date"], []).append(dict(row))
        previous_verified = None
        previous_observed = None
        changed = 0
        with self.db:
            for day, rows in sorted(groups.items()):
                valid = [r for r in rows if r["is_valid"]]
                values = {r["price_lbp_20l"] for r in valid}
                ids = sorted(r["id"] for r in rows)
                flags = sorted({i for r in rows for i in json.loads(r["issues_json"])})
                res = self.db.execute("SELECT * FROM resolutions WHERE source_date=? ORDER BY id DESC LIMIT 1",(day,)).fetchone()
                chosen = min(valid, key=lambda r:(r["priority"],r["id"])) if valid else None
                status = "invalid"
                if chosen:
                    status = "supplier_observed" if chosen["source_id"] == "ipt" else "supplementary_observed"
                    if chosen["source_id"] == "ministry":
                        status = "government_archive"
                    if any(r["source_id"]=="ministry" for r in valid) and any(r["source_id"]=="ipt" for r in valid):
                        status = "archive_corroborated"
                    if status == "supplier_observed" and len(values) == 1 and any(
                            r["source_id"] == "taqtek" for r in valid):
                        status = PROVISIONAL_PRICE
                    if chosen["document_verified"]:
                        status = "document_verified"
                    calendar_errors=[r for r in valid if r['source_id']=='ministry' and weekday_disagreement(json.loads(r['raw_json']).get('cells',[''])[0],day)]
                    if calendar_errors:
                        flags.append('source_weekday_mismatch')
                        if status!='document_verified': status='date_alignment_review'
                    if len(values)>1:
                        chosen = None
                        status = "conflict"
                        flags.append("contradictory_observations")
                resolution_stale=bool(res and json.loads(res['basis_observation_ids'])!=ids)
                if resolution_stale:
                    flags.append('new_evidence_requires_resolution_review')
                if res and not resolution_stale:
                    chosen = next(r for r in valid if r["id"] == res["chosen_observation_id"])
                    status = "document_verified" if chosen["document_verified"] else "reviewed_resolution"
                    flags.append("reviewed_resolution")
                if len(rows)>len({(r["source_id"],r["price_lbp_20l"]) for r in rows}):
                    flags.append("duplicate_date_source_price")
                if previous_observed and chosen:
                    if abs(chosen["price_lbp_20l"] / previous_observed["price"] - 1)>0.25:
                        flags.append("suspicious_change_over_25pct")
                payload = {
                    "source_date":day,"date_role":chosen["date_role"] if chosen else "disputed",
                    "official_effective_date":chosen["official_effective_date"] if chosen else None,
                    "publication_date":chosen["publication_date"] if chosen else None,
                    "publication_timestamp":chosen["publication_timestamp"] if chosen else None,
                    "retrieved_at":chosen["first_retrieved_at"] if chosen else None,
                    "price_lbp_20l":chosen["price_lbp_20l"] if chosen else None,
                    "verification_status":status,"source_priority":chosen["priority"] if chosen else None,
                    "source_url":chosen["source_url"] if chosen else None,
                    "chosen_observation_id":chosen["id"] if chosen else None,
                    "observation_ids":ids,"candidate_values":sorted(values),"issues":sorted(set(flags)),
                    "decision_numbers":sorted({r["decision_number"] for r in valid if r["decision_number"]}),
                    "regime":regime_label(day),"regime_status":"provisional_research_bucket",
                    "unit":"LBP/20L","timezone":"Asia/Beirut",
                    "previous_verified_date":previous_verified["date"] if previous_verified else None,
                    "previous_verified_price":previous_verified["price"] if previous_verified else None,
                    "absolute_price_change":None,"percentage_price_change":None,
                    "change_basis":"previous_verified_record_not_certified_previous_decision",
                    "resolution_id":res["id"] if res else None,
                }
                if chosen and previous_verified:
                    delta=chosen["price_lbp_20l"]-previous_verified["price"]
                    payload["absolute_price_change"]=delta
                    payload["percentage_price_change"]=100*delta/previous_verified["price"]
                if status == PROVISIONAL_PRICE:
                    payload["corroborating_sources"] = [
                        {"id": sid, "url": min(r["source_url"] for r in valid if r["source_id"] == sid)}
                        for sid in ("ipt", "taqtek")
                    ]
                if chosen:
                    previous_observed={"date":day,"price":chosen["price_lbp_20l"]}
                    if status in VERIFIED:
                        previous_verified=previous_observed
                serialized=json.dumps(payload,sort_keys=True,ensure_ascii=False)
                digest=sha256(serialized.encode()).hexdigest()
                prev=self.db.execute("SELECT id,fingerprint FROM decision_versions WHERE source_date=? ORDER BY id DESC LIMIT 1",(day,)).fetchone()
                if prev is None or prev["fingerprint"]!=digest:
                    self.db.execute("INSERT INTO decision_versions(source_date,created_at,fingerprint,previous_version_id,payload_json) VALUES (?,?,?,?,?)",(day,now_utc(),digest,prev["id"] if prev else None,serialized))
                    changed+=1
        return changed

    def ledger(self):
        return [dict(json.loads(r["payload_json"]),revision_id=r["id"]) for r in self.db.execute("SELECT * FROM current_decisions ORDER BY source_date")]
