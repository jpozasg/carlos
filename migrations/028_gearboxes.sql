-- Gearbox level (issue #164, owner decision 2026-11-06): gearbox faults follow the gearbox type (a DQ200 DSG, a CVT),
-- not the model, so a shared `gearboxes` row (like an engine: owner_id NULL = catalogue) is referenced by each variant
-- and carries the gearbox's weak points, source checks and maintenance (DSG/AT/CVT oil). Knowledge rows that can live on
-- it (maintenance, risks, reliability, research checks) and sources get gearbox_id as a fourth level: still exactly one
-- level per knowledge row, at most one per source. Existing rows stay where they are until the research reset (#167).
CREATE TABLE gearboxes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL,
 type TEXT CHECK (type IS NULL OR type IN ('MANUAL', 'DCT', 'AT', 'CVT', 'SINGLE-SPEED')),
 gears INTEGER CHECK (gears IS NULL OR gears >= 1),
 maker TEXT,
 description TEXT,
 status TEXT,
 notes TEXT,
 owner_id INTEGER REFERENCES users(id)
);
ALTER TABLE vehicles ADD COLUMN gearbox_id INTEGER REFERENCES gearboxes(id);

CREATE TABLE maintenance_items_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 item TEXT NOT NULL, interval_km INTEGER, interval_months INTEGER,
 reference_cost_eur REAL, diy_parts_cost_eur REAL, labor_included INTEGER,
 status TEXT, source_id INTEGER, notes TEXT,
 schedule TEXT NOT NULL DEFAULT 'PACKAGE' CHECK (schedule IN ('PACKAGE', 'ITEM')),
 diy INTEGER NOT NULL DEFAULT 0 CHECK (diy IN (0, 1)),
 diy_hours REAL CHECK (diy_hours IS NULL OR diy_hours >= 0),
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), job TEXT, applies_from TEXT, applies_to TEXT,
 gearbox_id INTEGER REFERENCES gearboxes(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL) = 1)
);
INSERT INTO maintenance_items_new SELECT *, NULL FROM maintenance_items;
DROP TABLE maintenance_items;
ALTER TABLE maintenance_items_new RENAME TO maintenance_items;
CREATE INDEX idx_maintenance_scope ON maintenance_items (vehicle_id, engine_id, generation_id);

CREATE TABLE repair_risks_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 component TEXT NOT NULL,
 km_from INTEGER NOT NULL CHECK (km_from >= 0),
 km_to INTEGER NOT NULL,
 probability REAL NOT NULL CHECK (probability >= 0 AND probability <= 1),
 parts_eur REAL CHECK (parts_eur IS NULL OR parts_eur >= 0),
 labor_eur REAL CHECK (labor_eur IS NULL OR labor_eur >= 0),
 diy INTEGER NOT NULL DEFAULT 0 CHECK (diy IN (0, 1)),
 diy_hours REAL CHECK (diy_hours IS NULL OR diy_hours >= 0),
 status TEXT, evidence TEXT,
 source_id INTEGER REFERENCES sources(id),
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), job TEXT, applies_from TEXT, applies_to TEXT,
 gearbox_id INTEGER REFERENCES gearboxes(id),
 CHECK (km_to > km_from),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL) = 1)
);
INSERT INTO repair_risks_new SELECT *, NULL FROM repair_risks;
DROP TABLE repair_risks;
ALTER TABLE repair_risks_new RENAME TO repair_risks;
CREATE INDEX idx_risks_scope ON repair_risks (vehicle_id, engine_id, generation_id);

CREATE TABLE reliability_items_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 component TEXT NOT NULL, issue TEXT, evidence TEXT, severity TEXT,
 frequency_status TEXT, source_id INTEGER, inspection_action TEXT, part TEXT CHECK (part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')), is_recall INTEGER NOT NULL DEFAULT 0 CHECK (is_recall IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), applies_from TEXT, applies_to TEXT,
 gearbox_id INTEGER REFERENCES gearboxes(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL) = 1)
);
INSERT INTO reliability_items_new SELECT *, NULL FROM reliability_items;
DROP TABLE reliability_items;
ALTER TABLE reliability_items_new RENAME TO reliability_items;
CREATE INDEX idx_reliability_scope ON reliability_items (vehicle_id, engine_id, generation_id);

CREATE TABLE research_checks_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 task TEXT NOT NULL,
 source_id INTEGER NOT NULL REFERENCES sources(id),
 result TEXT NOT NULL CHECK (result IN ('FOUND', 'NONE FOUND', 'N/A')),
 contract_version INTEGER NOT NULL,
 checked_date TEXT,
 notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0,
 owner_id INTEGER REFERENCES users(id),
 gearbox_id INTEGER REFERENCES gearboxes(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL) = 1)
);
INSERT INTO research_checks_new SELECT *, NULL FROM research_checks;
DROP TABLE research_checks;
ALTER TABLE research_checks_new RENAME TO research_checks;
CREATE INDEX idx_research_checks_task ON research_checks (task);

CREATE TABLE sources_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 title TEXT NOT NULL, url TEXT, source_type TEXT, quality TEXT,
 accessed_date TEXT, supports TEXT, limitations TEXT, owner_id INTEGER REFERENCES users(id),
 gearbox_id INTEGER REFERENCES gearboxes(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL) <= 1)
);
INSERT INTO sources_new SELECT *, NULL FROM sources;
DROP TABLE sources;
ALTER TABLE sources_new RENAME TO sources;

CREATE INDEX idx_gearbox_knowledge ON reliability_items (gearbox_id);
