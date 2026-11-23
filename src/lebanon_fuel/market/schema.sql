CREATE TABLE IF NOT EXISTS market_series (
 id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_observations (
 id INTEGER PRIMARY KEY, series_id TEXT NOT NULL REFERENCES market_series(id),
 semantic_hash TEXT NOT NULL, observation_date TEXT NOT NULL,
 raw_value TEXT, raw_unit TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
 publication_timestamp TEXT, vintage_timestamp TEXT, vintage_evidence_url TEXT,
 first_seen_at TEXT NOT NULL, valid INTEGER NOT NULL,
 raw_json TEXT NOT NULL, issues_json TEXT NOT NULL,
 UNIQUE(series_id,semantic_hash)
);
CREATE TABLE IF NOT EXISTS market_sightings (
 capture_id INTEGER NOT NULL REFERENCES captures(id), row_key TEXT NOT NULL,
 observation_id INTEGER NOT NULL REFERENCES market_observations(id),
 available_at TEXT NOT NULL, availability_basis TEXT NOT NULL,
 PRIMARY KEY(capture_id,row_key,observation_id)
);
CREATE INDEX IF NOT EXISTS market_dates ON market_observations(series_id,observation_date);
CREATE INDEX IF NOT EXISTS market_available ON market_sightings(available_at);
CREATE INDEX IF NOT EXISTS market_sightings_observation ON market_sightings(observation_id,capture_id);
CREATE TRIGGER IF NOT EXISTS market_observations_no_update BEFORE UPDATE ON market_observations
 BEGIN SELECT RAISE(ABORT,'market observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_observations_no_delete BEFORE DELETE ON market_observations
 BEGIN SELECT RAISE(ABORT,'market observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_sightings_no_update BEFORE UPDATE ON market_sightings
 BEGIN SELECT RAISE(ABORT,'market sightings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS market_sightings_no_delete BEFORE DELETE ON market_sightings
 BEGIN SELECT RAISE(ABORT,'market sightings are immutable'); END;
