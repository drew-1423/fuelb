PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES (1);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, priority INTEGER NOT NULL, lineage TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_runs (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 details TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS captures (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 run_id INTEGER REFERENCES collection_runs(id), url TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, timezone TEXT NOT NULL DEFAULT 'Asia/Beirut',
 sha256 TEXT NOT NULL, raw_path TEXT NOT NULL, content_type TEXT,
 http_status INTEGER, metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 semantic_hash TEXT NOT NULL, source_date TEXT, date_role TEXT NOT NULL,
 official_effective_date TEXT, publication_date TEXT, publication_timestamp TEXT,
 source_timezone TEXT NOT NULL DEFAULT 'Asia/Beirut', price_lbp_20l INTEGER,
 unit TEXT NOT NULL, decision_number TEXT, source_url TEXT NOT NULL,
 first_retrieved_at TEXT NOT NULL, is_valid INTEGER NOT NULL,
 document_verified INTEGER NOT NULL, raw_json TEXT NOT NULL, issues_json TEXT NOT NULL,
 UNIQUE(source_id, semantic_hash), CHECK(price_lbp_20l IS NULL OR price_lbp_20l > 0)
);
CREATE INDEX IF NOT EXISTS obs_date ON observations(source_date);
CREATE TABLE IF NOT EXISTS sightings (
 capture_id INTEGER NOT NULL REFERENCES captures(id), row_key TEXT NOT NULL,
 observation_id INTEGER NOT NULL REFERENCES observations(id),
 PRIMARY KEY(capture_id,row_key)
);
CREATE TABLE IF NOT EXISTS resolutions (
 id INTEGER PRIMARY KEY, source_date TEXT NOT NULL,
 chosen_observation_id INTEGER NOT NULL REFERENCES observations(id),
 reason TEXT NOT NULL, evidence_url TEXT NOT NULL, reviewer TEXT NOT NULL,
 reviewed_at TEXT NOT NULL, basis_observation_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS decision_versions (
 id INTEGER PRIMARY KEY, source_date TEXT NOT NULL, created_at TEXT NOT NULL,
 fingerprint TEXT NOT NULL, previous_version_id INTEGER REFERENCES decision_versions(id),
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_versions_date ON decision_versions(source_date,id);
CREATE VIEW IF NOT EXISTS current_decisions AS
 SELECT d.* FROM decision_versions d JOIN
 (SELECT source_date, MAX(id) id FROM decision_versions GROUP BY source_date) newest
 ON d.id=newest.id;
CREATE VIEW IF NOT EXISTS price_history AS
 SELECT id AS revision_id, source_date,
 json_extract(payload_json,'$.official_effective_date') official_effective_date,
 json_extract(payload_json,'$.publication_date') publication_date,
 json_extract(payload_json,'$.publication_timestamp') publication_timestamp,
 json_extract(payload_json,'$.retrieved_at') retrieved_at,
 'Asia/Beirut' AS source_timezone,
 json_extract(payload_json,'$.price_lbp_20l') price_lbp_20l,
 json_extract(payload_json,'$.previous_verified_price') previous_verified_price,
 json_extract(payload_json,'$.absolute_price_change') absolute_price_change,
 json_extract(payload_json,'$.percentage_price_change') percentage_price_change,
 json_extract(payload_json,'$.verification_status') verification_status,
 json_extract(payload_json,'$.source_priority') source_priority,
 json_extract(payload_json,'$.source_url') source_url,
 json_extract(payload_json,'$.regime') regime,
 payload_json
 FROM current_decisions;
CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations
 BEGIN SELECT RAISE(ABORT,'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations
 BEGIN SELECT RAISE(ABORT,'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS versions_no_update BEFORE UPDATE ON decision_versions
 BEGIN SELECT RAISE(ABORT,'versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS versions_no_delete BEFORE DELETE ON decision_versions
 BEGIN SELECT RAISE(ABORT,'versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS resolutions_no_update BEFORE UPDATE ON resolutions
 BEGIN SELECT RAISE(ABORT,'resolutions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS resolutions_no_delete BEFORE DELETE ON resolutions
 BEGIN SELECT RAISE(ABORT,'resolutions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS captures_no_update BEFORE UPDATE ON captures
 BEGIN SELECT RAISE(ABORT,'captures are immutable'); END;
CREATE TRIGGER IF NOT EXISTS captures_no_delete BEFORE DELETE ON captures
 BEGIN SELECT RAISE(ABORT,'captures are immutable'); END;
