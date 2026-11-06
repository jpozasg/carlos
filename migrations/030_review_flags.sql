-- Review flags (owner, 2026-11-06, #168): a problem found in the research (statistics vs faults, disagreeing sources, an
-- uncertain "fixed from" date …) is flagged on the level where it is, with what and why. It stays OPEN after a follow-up
-- review and is CLEARED only when two independent reviews (different workers or runs) reach the same conclusion;
-- every review is recorded (who, when, what it found).
CREATE TABLE review_flags (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id), engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id),
 body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
 kind TEXT NOT NULL CHECK (kind IN ('STATS_MISMATCH', 'SOURCES_DISAGREE', 'FIX_UNCERTAIN', 'OTHER')),
 what TEXT NOT NULL, why TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLEARED')),
 created_at TEXT NOT NULL DEFAULT (datetime('now')), created_by TEXT, cleared_at TEXT,
 owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) = 1));
CREATE TABLE flag_reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, flag_id INTEGER NOT NULL REFERENCES review_flags(id),
 worker TEXT NOT NULL, review_date TEXT NOT NULL DEFAULT (date('now')),
 outcome TEXT NOT NULL CHECK (outcome IN ('CONFIRMED', 'RESOLVED')),
 conclusion TEXT NOT NULL, finding TEXT NOT NULL, source_id INTEGER REFERENCES sources(id),
 UNIQUE (flag_id, worker, conclusion));
-- The report's average for the class and age (the statistics consistency check compares the model with it).
ALTER TABLE reliability_stats ADD COLUMN class_average REAL CHECK (class_average IS NULL OR class_average > 0);
-- Follow-up research (a flag's review) goes through the same queue as listings: kind FOLLOW_UP, the flag it reviews.
ALTER TABLE research_requests ADD COLUMN kind TEXT NOT NULL DEFAULT 'LISTING' CHECK (kind IN ('LISTING', 'FOLLOW_UP'));
ALTER TABLE research_requests ADD COLUMN flag_id INTEGER REFERENCES review_flags(id);
