-- Target design, build step 1 (docs/target-design.md §2–§4): the new levels and knowledge tables, and the listing-side
-- facts that must survive the research reset (#167). Additive: the old knowledge tables (reliability_items,
-- repair_risks, insurance_data premiums, maintenance_resets, unit_costs) stay until the reset drops them.
-- Levels: engine family → engine, gearbox family → gearbox, generation, body style, option, variant. Catalogue rows have
-- owner_id NULL (shared), like generations/engines/vehicles.
CREATE TABLE engine_families (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, maker TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE UNIQUE INDEX ux_engine_families_name ON engine_families (upper(name));
CREATE TABLE gearbox_families (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, maker TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE UNIQUE INDEX ux_gearbox_families_name ON gearbox_families (upper(name));
CREATE TABLE gearboxes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, family_id INTEGER REFERENCES gearbox_families(id),
 type TEXT CHECK (type IS NULL OR type IN ('MANUAL', 'DCT', 'AT', 'CVT', 'SINGLE-SPEED')),
 gears INTEGER CHECK (gears IS NULL OR gears > 0), description TEXT, status TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE UNIQUE INDEX ux_gearboxes_code ON gearboxes (upper(code));
CREATE TABLE body_styles (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id), name TEXT NOT NULL,
 notes TEXT, owner_id INTEGER REFERENCES users(id));
CREATE UNIQUE INDEX ux_body_styles ON body_styles (generation_id, upper(name));
-- option: equipment with its own faults or maintenance (convertible roof, sunroof, xenon, air suspension, 4x4);
-- generation_id NULL = a generic option kind
CREATE TABLE options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, generation_id INTEGER REFERENCES generations(id), notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE UNIQUE INDEX ux_options ON options (upper(name), coalesce(generation_id, 0));
ALTER TABLE engines ADD COLUMN family_id INTEGER REFERENCES engine_families(id);
ALTER TABLE vehicles ADD COLUMN gearbox_id INTEGER REFERENCES gearboxes(id);
ALTER TABLE vehicles ADD COLUMN body_style_id INTEGER REFERENCES body_styles(id);
-- Sources may attach to any level (at most one, checked by the API).
ALTER TABLE sources ADD COLUMN gearbox_id INTEGER REFERENCES gearboxes(id);
ALTER TABLE sources ADD COLUMN engine_family_id INTEGER REFERENCES engine_families(id);
ALTER TABLE sources ADD COLUMN gearbox_family_id INTEGER REFERENCES gearbox_families(id);
ALTER TABLE sources ADD COLUMN body_style_id INTEGER REFERENCES body_styles(id);
ALTER TABLE sources ADD COLUMN option_id INTEGER REFERENCES options(id);

-- Listing facts as shown (they survive the wipe and resolve the listing to its re-researched variant): build date,
-- engine code, HSN/TSN, trim. Existing listings take HSN/TSN, trim and the engine code from their current variant.
ALTER TABLE listings ADD COLUMN build_date TEXT;
ALTER TABLE listings ADD COLUMN engine_code_seen TEXT;
ALTER TABLE listings ADD COLUMN hsn TEXT;
ALTER TABLE listings ADD COLUMN tsn TEXT;
ALTER TABLE listings ADD COLUMN trim TEXT;
UPDATE listings SET hsn = (SELECT hsn FROM vehicles v WHERE v.id = listings.vehicle_id),
                    tsn = (SELECT tsn FROM vehicles v WHERE v.id = listings.vehicle_id),
                    trim = (SELECT trim FROM vehicles v WHERE v.id = listings.vehicle_id),
                    engine_code_seen = (SELECT e.code FROM vehicles v JOIN engines e ON e.id = v.engine_id WHERE v.id = listings.vehicle_id);
CREATE TABLE listing_options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id),
 option_id INTEGER NOT NULL REFERENCES options(id), source_id INTEGER REFERENCES sources(id), notes TEXT,
 UNIQUE (listing_id, option_id));

-- Insurance quotes belong to the listing (§4.2); Typklassen stay on the variant. Existing premium rows are copied to
-- every listing of their account on that variant.
CREATE TABLE listing_quotes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id),
 annual_premium_eur REAL NOT NULL CHECK (annual_premium_eur > 0),
 premium_min_eur REAL CHECK (premium_min_eur IS NULL OR premium_min_eur > 0),
 premium_status TEXT NOT NULL, insurer TEXT, tariff TEXT,
 quote_date TEXT CHECK (quote_date IS NULL OR quote_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
 quote_profile TEXT CHECK (quote_profile IS NULL OR json_type(quote_profile) = 'object'),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)));
INSERT INTO listing_quotes (listing_id, annual_premium_eur, premium_min_eur, premium_status, insurer, tariff, quote_date,
                            quote_profile, source_id, notes, archived)
  SELECT l.id, i.annual_premium_eur, i.premium_min_eur, coalesce(i.premium_status, 'QUOTE'), i.insurer, i.tariff, i.quote_date,
         i.quote_profile, i.source_id, i.notes, i.archived
    FROM insurance_data i JOIN listings l ON l.vehicle_id = i.vehicle_id AND l.owner_id = i.owner_id
   WHERE i.annual_premium_eur IS NOT NULL AND i.owner_id IS NOT NULL AND i.source_id IS NOT NULL;

-- Knowledge levels used by the new tables: exactly one of these (maintenance: at most one; none = a global default).
-- Faults (§3.1) replace weak points + repair risks: one design fault, its consequence (severity is derived, never
-- chosen), price, existence grade, a cumulative probability curve by km (and optional age) as JSON points
-- [[km, share], …], the probability basis graded separately, a usage multiplier only with its own source, a
-- build-date window.
CREATE TABLE faults (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id), engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id),
 body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
 component TEXT NOT NULL, part TEXT NOT NULL CHECK (part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')),
 issue TEXT, mechanism TEXT, inspection_action TEXT,
 consequence TEXT NOT NULL CHECK (consequence IN ('ENGINE_DAMAGE', 'STRANDS', 'SAFETY', 'UNUSABLE', 'COST', 'COSMETIC')),
 parts_eur REAL CHECK (parts_eur IS NULL OR parts_eur >= 0), labor_eur REAL CHECK (labor_eur IS NULL OR labor_eur >= 0),
 diy_parts_eur REAL CHECK (diy_parts_eur IS NULL OR diy_parts_eur >= 0), diy_hours REAL CHECK (diy_hours IS NULL OR diy_hours >= 0),
 existence TEXT NOT NULL CHECK (existence IN ('CONFIRMED', 'REPORTED')),
 curve_km TEXT CHECK (curve_km IS NULL OR json_type(curve_km) = 'array'),
 curve_age TEXT CHECK (curve_age IS NULL OR json_type(curve_age) = 'array'),
 probability_basis TEXT CHECK (probability_basis IS NULL OR probability_basis IN ('STATISTIC', 'EXPERT', 'ESTIMATE')),
 usage_flags TEXT, usage_multiplier REAL CHECK (usage_multiplier IS NULL OR usage_multiplier > 0),
 usage_source_id INTEGER REFERENCES sources(id),
 applies_from TEXT, applies_to TEXT, window_uncertain INTEGER NOT NULL DEFAULT 0 CHECK (window_uncertain IN (0, 1)),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK (usage_multiplier IS NULL OR usage_source_id IS NOT NULL),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) = 1));
-- Recalls (§3.3): an official campaign; the per-car status lives in listing_history. Window unknown = applies_from and
-- applies_to NULL with window_known 0.
CREATE TABLE recalls (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id), engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id),
 body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
 code TEXT NOT NULL, defect TEXT NOT NULL, remedy TEXT, part TEXT CHECK (part IS NULL OR part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')),
 safety INTEGER NOT NULL DEFAULT 0 CHECK (safety IN (0, 1)),
 applies_from TEXT, applies_to TEXT, window_known INTEGER NOT NULL DEFAULT 0 CHECK (window_known IN (0, 1)),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) = 1));
-- Reliability baseline (§3.4): TÜV defect rates / ADAC breakdown figures per generation and age class.
CREATE TABLE reliability_stats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id),
 kind TEXT NOT NULL CHECK (kind IN ('TUEV', 'ADAC')), age_from INTEGER NOT NULL, age_to INTEGER NOT NULL,
 value REAL NOT NULL, unit TEXT NOT NULL, sample_count INTEGER, report_year INTEGER,
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK (age_to >= age_from));
-- Market model (§4.4): value of the model at (ref_age_years, ref_km), and the fitted share lost per year of age and per
-- 10,000 km, from three bands of comparable listings (counts in band_counts), sampled on sample_date.
CREATE TABLE market_models (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id),
 engine_id INTEGER NOT NULL REFERENCES engines(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 value_ref_eur REAL NOT NULL CHECK (value_ref_eur > 0), ref_age_years REAL NOT NULL, ref_km INTEGER NOT NULL,
 rate_year REAL NOT NULL CHECK (rate_year >= 0 AND rate_year < 1), rate_10k_km REAL NOT NULL CHECK (rate_10k_km >= 0 AND rate_10k_km < 1),
 band_counts TEXT NOT NULL CHECK (json_type(band_counts) = 'array'), sample_date TEXT NOT NULL,
 filters TEXT, sample_json TEXT CHECK (sample_json IS NULL OR json_type(sample_json) = 'array'),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id));
-- Listing history (§4.1): one fact per row about this car — a scheduled job, a fault or a recall — DONE (restarts the
-- schedule or the fault's curve at km), PRESENT (needs doing now: a certain cost) or OPEN (a recall not done or not
-- verified), NOT AFFECTED (a recall the VIN check excludes); evidence and its source.
CREATE TABLE listing_history (
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id),
 maintenance_item_id INTEGER REFERENCES maintenance_items(id), fault_id INTEGER REFERENCES faults(id),
 recall_id INTEGER REFERENCES recalls(id), job TEXT, item TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('DONE', 'PRESENT', 'OPEN', 'NOT AFFECTED')),
 km INTEGER CHECK (km IS NULL OR km >= 0), event_date TEXT,
 evidence TEXT NOT NULL CHECK (evidence IN ('DOCUMENTED', 'SELLER CLAIM', 'OBSERVED', 'VIN CHECK')),
 category TEXT CHECK (category IS NULL OR category IN ('maintenance', 'repairs')),
 parts_eur REAL CHECK (parts_eur IS NULL OR parts_eur >= 0), labor_eur REAL CHECK (labor_eur IS NULL OR labor_eur >= 0),
 diy_hours REAL CHECK (diy_hours IS NULL OR diy_hours >= 0),
 source_id INTEGER REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 CHECK ((maintenance_item_id IS NOT NULL) + (fault_id IS NOT NULL) + (recall_id IS NOT NULL) + (job IS NOT NULL) >= 1),
 CHECK (status <> 'PRESENT' OR category IS NOT NULL));

-- Maintenance (§3.2): every level, wear parts (kind WEAR, interval = typical life), heavy-use intervals; a row without
-- a level is a global default (HU, brake fluid, labour rate) that a level row with the same job overrides.
CREATE TABLE maintenance_items_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id), engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id),
 body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
 item TEXT NOT NULL, interval_km INTEGER, interval_months INTEGER,
 reference_cost_eur REAL, diy_parts_cost_eur REAL, labor_included INTEGER,
 status TEXT, source_id INTEGER, notes TEXT,
 schedule TEXT NOT NULL DEFAULT 'PACKAGE' CHECK (schedule IN ('PACKAGE', 'ITEM')),
 diy INTEGER NOT NULL DEFAULT 0 CHECK (diy IN (0, 1)),
 diy_hours REAL CHECK (diy_hours IS NULL OR diy_hours >= 0),
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 owner_id INTEGER REFERENCES users(id), job TEXT, applies_from TEXT, applies_to TEXT,
 kind TEXT NOT NULL DEFAULT 'JOB' CHECK (kind IN ('JOB', 'WEAR')),
 interval_km_heavy INTEGER CHECK (interval_km_heavy IS NULL OR interval_km_heavy > 0),
 interval_months_heavy INTEGER CHECK (interval_months_heavy IS NULL OR interval_months_heavy > 0),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) <= 1));
INSERT INTO maintenance_items_new (id, vehicle_id, engine_id, generation_id, item, interval_km, interval_months, reference_cost_eur,
  diy_parts_cost_eur, labor_included, status, source_id, notes, schedule, diy, diy_hours, active, archived, owner_id, job,
  applies_from, applies_to)
  SELECT id, vehicle_id, engine_id, generation_id, item, interval_km, interval_months, reference_cost_eur, diy_parts_cost_eur,
         labor_included, status, source_id, notes, schedule, diy, diy_hours, active, archived, owner_id, job, applies_from, applies_to
    FROM maintenance_items;
DROP TABLE maintenance_items;
ALTER TABLE maintenance_items_new RENAME TO maintenance_items;
CREATE INDEX idx_maintenance_scope ON maintenance_items (vehicle_id, engine_id, generation_id);

-- Research checks on every level (§3.6: ADAC/TÜV/guide on the generation, specific sources on the families).
CREATE TABLE research_checks_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id), engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id),
 body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
 task TEXT NOT NULL, source_id INTEGER NOT NULL REFERENCES sources(id),
 result TEXT NOT NULL CHECK (result IN ('FOUND', 'NONE FOUND', 'N/A')),
 contract_version INTEGER NOT NULL, checked_date TEXT, notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0, owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) = 1));
INSERT INTO research_checks_new (id, vehicle_id, engine_id, generation_id, task, source_id, result, contract_version, checked_date,
  notes, archived, owner_id)
  SELECT id, vehicle_id, engine_id, generation_id, task, source_id, result, contract_version, checked_date, notes, archived, owner_id
    FROM research_checks;
DROP TABLE research_checks;
ALTER TABLE research_checks_new RENAME TO research_checks;
CREATE INDEX idx_research_checks_task ON research_checks (task);
CREATE INDEX idx_faults_scope ON faults (vehicle_id, engine_id, generation_id, gearbox_id, engine_family_id);
CREATE INDEX idx_listing_history ON listing_history (listing_id);
CREATE INDEX idx_listing_quotes ON listing_quotes (listing_id);
