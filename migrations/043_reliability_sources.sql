-- #353 (plan #351 §2): reliability comes from a few fixed external sources, each on the level it covers.
-- source_keys maps a Carlos level (engine or generation) to a source's page; source_ratings holds what the source
-- publishes, verbatim, keyed by the external key so engines sharing one page store the rating once. Shared catalogue
-- (owner_id NULL). Per-source rules (level, required fields, scale) live in config.RATING_SOURCES and the API.
CREATE TABLE source_keys (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_key TEXT NOT NULL,
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 fuel_type TEXT CHECK (fuel_type IS NULL OR fuel_type IN ('Petrol', 'Diesel', 'Hybrid', 'Plug-in hybrid', 'Electric')),
 external_key TEXT NOT NULL,
 url TEXT NOT NULL CHECK (url LIKE 'https://%'),
 source_id INTEGER NOT NULL REFERENCES sources(id),
 checked_date TEXT NOT NULL, notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 owner_id INTEGER REFERENCES users(id) CHECK (owner_id IS NULL),
 CHECK ((engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1));
CREATE UNIQUE INDEX ux_source_keys ON source_keys
 (source_key, coalesce(engine_id, -1), coalesce(generation_id, -1), coalesce(fuel_type, '')) WHERE archived = 0;
CREATE TABLE source_ratings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_key TEXT NOT NULL,
 external_key TEXT NOT NULL,
 edition TEXT NOT NULL,
 age_from INTEGER, age_to INTEGER,
 reg_year INTEGER,
 value_num REAL CHECK (value_num IS NULL OR value_num >= 0),
 value_text TEXT,
 band INTEGER CHECK (band IS NULL OR band BETWEEN 1 AND 5),
 class_average REAL CHECK (class_average IS NULL OR class_average > 0),
 cost_min_eur REAL CHECK (cost_min_eur IS NULL OR cost_min_eur >= 0),
 cost_max_eur REAL,
 sample_count INTEGER CHECK (sample_count IS NULL OR sample_count > 0),
 url TEXT NOT NULL CHECK (url LIKE 'https://%'),
 source_id INTEGER NOT NULL REFERENCES sources(id),
 checked_date TEXT NOT NULL, notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 owner_id INTEGER REFERENCES users(id) CHECK (owner_id IS NULL),
 CHECK (age_to IS NULL OR (age_from IS NOT NULL AND age_to >= age_from)),
 CHECK (age_from IS NULL OR reg_year IS NULL),
 CHECK (cost_max_eur IS NULL OR cost_min_eur IS NULL OR cost_max_eur >= cost_min_eur));
CREATE UNIQUE INDEX ux_source_ratings ON source_ratings
 (source_key, upper(external_key), edition, coalesce(age_from, -1), coalesce(reg_year, -1)) WHERE archived = 0;
-- reliability_stats is replaced by source_ratings. Dropped only while empty (owner's yes, 2026-11-10): a row makes the
-- guard's CHECK fail and the whole migration rolls back.
CREATE TEMP TABLE _guard_043 (n INTEGER CHECK (n = 0));
INSERT INTO _guard_043 SELECT count(*) FROM reliability_stats;
DROP TABLE _guard_043;
DROP TABLE reliability_stats;
