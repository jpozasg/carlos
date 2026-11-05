-- Shared catalogue (issue #109, part of #106): generations, engines, variants and their research are shared between
-- accounts. owner_id NULL = catalogue row; set = private to that account. Knowledge rows get an owner_id too: NULL
-- follows its level, set = a private row of that account on a shared level (an insurance quote, an owner's figure).
-- catalogue_links says which catalogue levels an account sees (through its listings). Existing rows keep their owner.
CREATE TABLE generations_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 make TEXT NOT NULL,
 model TEXT NOT NULL,
 name TEXT NOT NULL,
 start_year INTEGER,
 end_year INTEGER,
 facelift_year INTEGER,
 status TEXT,
 notes TEXT,
 owner_id INTEGER REFERENCES users(id)
);
INSERT INTO generations_new SELECT id, make, model, name, start_year, end_year, facelift_year, status, notes, owner_id FROM generations;
DROP TABLE generations;
ALTER TABLE generations_new RENAME TO generations;

CREATE TABLE engines_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL,
 family TEXT,
 description TEXT,
 fuel_type TEXT,
 displacement_cc INTEGER,
 cylinders INTEGER,
 power_kw REAL,
 power_ps REAL,
 aspiration TEXT CHECK (aspiration IS NULL OR aspiration IN ('NATURALLY ASPIRATED', 'TURBO', 'SUPERCHARGED')),
 injection TEXT CHECK (injection IS NULL OR injection IN ('PORT', 'DIRECT', 'DUAL', 'CARBURETTOR')),
 timing_drive TEXT CHECK (timing_drive IS NULL OR timing_drive IN ('CHAIN', 'BELT', 'WET BELT', 'GEAR')),
 status TEXT,
 notes TEXT,
 owner_id INTEGER REFERENCES users(id)
);
INSERT INTO engines_new SELECT id, code, family, description, fuel_type, displacement_cc, cylinders, power_kw, power_ps,
  aspiration, injection, timing_drive, status, notes, owner_id FROM engines;
DROP TABLE engines;
ALTER TABLE engines_new RENAME TO engines;

CREATE TABLE vehicles_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 generation_id INTEGER NOT NULL REFERENCES generations(id),
 engine_id INTEGER NOT NULL REFERENCES engines(id),
 trim TEXT,
 transmission TEXT,
 body_style TEXT,
 model_year INTEGER,
 emissions_standard TEXT,
 co2_g_km REAL,
 hsn TEXT,
 tsn TEXT,
 technical_status TEXT,
 notes TEXT,
 owner_id INTEGER REFERENCES users(id)
);
INSERT INTO vehicles_new SELECT id, generation_id, engine_id, trim, transmission, body_style, model_year, emissions_standard,
  co2_g_km, hsn, tsn, technical_status, notes, owner_id FROM vehicles;
DROP TABLE vehicles;
ALTER TABLE vehicles_new RENAME TO vehicles;

CREATE TABLE sources_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 title TEXT NOT NULL, url TEXT, source_type TEXT, quality TEXT,
 accessed_date TEXT, supports TEXT, limitations TEXT, owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) <= 1)
);
INSERT INTO sources_new SELECT id, vehicle_id, engine_id, generation_id, title, url, source_type, quality, accessed_date,
  supports, limitations, owner_id FROM sources;
DROP TABLE sources;
ALTER TABLE sources_new RENAME TO sources;

ALTER TABLE observations ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE insurance_data ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE tax_data ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE maintenance_items ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE reliability_items ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE repair_risks ADD COLUMN owner_id INTEGER REFERENCES users(id);
ALTER TABLE tyre_data ADD COLUMN owner_id INTEGER REFERENCES users(id);

CREATE TABLE catalogue_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE INDEX idx_catalogue_links_owner ON catalogue_links (owner_id);
CREATE INDEX idx_vehicles_hsn_tsn ON vehicles (hsn, tsn);
-- every account keeps seeing its variants once they move to the catalogue
INSERT INTO catalogue_links (owner_id, vehicle_id) SELECT owner_id, id FROM vehicles WHERE owner_id IS NOT NULL;
