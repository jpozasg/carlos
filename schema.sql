-- Reference schema generated from the database (PRAGMA user_version=21). Changes: add migrations/NNN_*.sql.
CREATE TABLE listings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
 source_id INTEGER,
 listing_id TEXT, platform TEXT, url TEXT,
 price_eur REAL, mileage_km INTEGER, seller TEXT, location TEXT,
 seller_address TEXT, accident_free_claim INTEGER, owners_claim INTEGER,
 hu_claim TEXT, service_history_claim TEXT, equipment TEXT,
 listing_date TEXT, last_checked TEXT, listing_status TEXT, notes TEXT
, is_reference INTEGER NOT NULL DEFAULT 0 CHECK (is_reference IN (0, 1)), first_registration TEXT, verdict TEXT, owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id));
CREATE TABLE listing_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 event_date TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
 source_id INTEGER REFERENCES sources(id)
);
CREATE TABLE change_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 changed_at TEXT NOT NULL DEFAULT (datetime('now')),
 table_name TEXT NOT NULL, row_id INTEGER NOT NULL, action TEXT NOT NULL,
 old_json TEXT, new_json TEXT NOT NULL
, user_id INTEGER REFERENCES users(id));
CREATE TABLE listing_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 captured_at TEXT NOT NULL,
 source_id INTEGER NOT NULL REFERENCES sources(id),
 title TEXT, price_eur REAL, mileage_km INTEGER,
 description TEXT,
 attributes_json TEXT CHECK (attributes_json IS NULL OR json_type(attributes_json) = 'object'),
 notes TEXT
);
CREATE TABLE listing_media (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 snapshot_id INTEGER REFERENCES listing_snapshots(id),
 captured_at TEXT NOT NULL DEFAULT (datetime('now')),
 original_url TEXT,
 file_path TEXT NOT NULL UNIQUE,
 mime TEXT NOT NULL,
 bytes INTEGER NOT NULL,
 sha256 TEXT NOT NULL,
 UNIQUE (listing_id, sha256)
);
CREATE TABLE "valuations" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 kind TEXT NOT NULL CHECK (kind IN ('sale_today', 'resale_end')),
 horizon_years INTEGER,
 low_eur REAL, expected_eur REAL NOT NULL, high_eur REAL,
 status TEXT NOT NULL, valued_date TEXT,
 source_id INTEGER NOT NULL REFERENCES sources(id),
 notes TEXT
, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)));
CREATE TABLE "inspection_items" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 item TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'OK', 'PROBLEM', 'N/A')),
 checked_date TEXT, notes TEXT
, reliability_item_id INTEGER REFERENCES reliability_items(id), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)));
CREATE TABLE maintenance_resets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 maintenance_item_id INTEGER NOT NULL REFERENCES maintenance_items(id),
 basis TEXT NOT NULL CHECK (basis IN ('CERTAIN REPAIR', 'SELLER CLAIM', 'DOCUMENTED')),
 unit_cost_id INTEGER REFERENCES unit_costs(id),
 source_id INTEGER REFERENCES sources(id),
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 UNIQUE (listing_id, maintenance_item_id)
);
CREATE TABLE "observations" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 category TEXT NOT NULL, metric TEXT NOT NULL, value_num REAL,
 value_text TEXT, unit TEXT, sample_count INTEGER, min_value REAL, max_value REAL,
 status TEXT NOT NULL, evidence_quality TEXT, observed_date TEXT,
 source_id INTEGER, notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "insurance_data" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 hsn TEXT, tsn TEXT, year INTEGER, liability_typklasse INTEGER,
 partial_typklasse INTEGER, comprehensive_typklasse INTEGER,
 annual_premium_eur REAL, premium_status TEXT, source_id INTEGER, notes TEXT,
 premium_min_eur REAL CHECK (premium_min_eur IS NULL OR premium_min_eur > 0), insurer TEXT, tariff TEXT,
 quote_date TEXT CHECK (quote_date IS NULL OR quote_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
 quote_profile TEXT CHECK (quote_profile IS NULL OR json_type(quote_profile) = 'object'), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "tax_data" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 annual_tax_eur REAL, status TEXT, basis TEXT, source_id INTEGER, notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "maintenance_items" (
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
 active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "reliability_items" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 component TEXT NOT NULL, issue TEXT, evidence TEXT, severity TEXT,
 frequency_status TEXT, source_id INTEGER, inspection_action TEXT, part TEXT CHECK (part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')), is_recall INTEGER NOT NULL DEFAULT 0 CHECK (is_recall IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "repair_risks" (
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
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK (km_to > km_from),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "tyre_data" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 tyre_type TEXT NOT NULL DEFAULT 'ALL-SEASON',
 size TEXT,
 price_per_tyre_eur REAL CHECK (price_per_tyre_eur IS NULL OR price_per_tyre_eur > 0),
 tyres_per_set INTEGER NOT NULL DEFAULT 4 CHECK (tyres_per_set > 0),
 life_km INTEGER CHECK (life_km IS NULL OR life_km > 0),
 fitting_per_set_eur REAL CHECK (fitting_per_set_eur IS NULL OR fitting_per_set_eur >= 0),
 status TEXT,
 source_id INTEGER REFERENCES sources(id),
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT NOT NULL UNIQUE CHECK (length(username) BETWEEN 2 AND 40),
 password_hash TEXT,
 role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
 api_token_hash TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE sessions (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 expires_at TEXT NOT NULL
);
CREATE TABLE invites (
 id TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id),
 created_by INTEGER REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 expires_at TEXT NOT NULL,
 used_at TEXT
);
CREATE TABLE "project_parameters" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
 annual_km INTEGER NOT NULL DEFAULT 15000,
 ownership_years INTEGER NOT NULL DEFAULT 4,
 fuel_price_eur_l REAL NOT NULL DEFAULT 1.8,
 fuel_price_date TEXT,
 diesel_price_eur_l REAL CHECK (diesel_price_eur_l IS NULL OR diesel_price_eur_l > 0),
 diesel_price_date TEXT,
 budget_ideal_eur REAL CHECK (budget_ideal_eur IS NULL OR budget_ideal_eur > 0),
 budget_max_eur REAL CHECK (budget_max_eur IS NULL OR budget_max_eur > 0),
 postal_code TEXT,
 drivers_count INTEGER,
 driver_age INTEGER,
 sf_class TEXT,
 insurance_cover TEXT,
 insurance_deductible_eur REAL,
 purchase_mode TEXT,
 currency TEXT DEFAULT 'EUR',
 ranking_weights TEXT CHECK (ranking_weights IS NULL OR json_type(ranking_weights) = 'object')
, ranking_answers TEXT
  CHECK (ranking_answers IS NULL OR json_type(ranking_answers) = 'object'));
CREATE TABLE "project_preferences" (
 owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
 preference_key TEXT NOT NULL,
 preference_value TEXT,
 unit TEXT,
 status TEXT,
 notes TEXT,
 PRIMARY KEY (owner_id, preference_key)
);
CREATE TABLE "unit_costs" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 category TEXT NOT NULL CHECK (category IN ('repairs', 'maintenance', 'tyres', 'purchase_sale')),
 item TEXT NOT NULL,
 parts_eur REAL, labor_eur REAL, diy_hours REAL,
 status TEXT NOT NULL,
 source_id INTEGER REFERENCES sources(id),
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
 CHECK (parts_eur IS NOT NULL OR labor_eur IS NOT NULL)
);
CREATE TABLE "generations" (
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
CREATE TABLE "engines" (
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
CREATE TABLE "vehicles" (
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
CREATE TABLE "sources" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 title TEXT NOT NULL, url TEXT, source_type TEXT, quality TEXT,
 accessed_date TEXT, supports TEXT, limitations TEXT, owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) <= 1)
);
CREATE TABLE catalogue_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE research_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 url TEXT NOT NULL,
 note TEXT,
 status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED')),
 requested_at TEXT NOT NULL DEFAULT (datetime('now')),
 claimed_at TEXT,
 finished_at TEXT,
 worker TEXT,
 listing_id INTEGER REFERENCES listings(id),
 result TEXT
);
CREATE TABLE research_checks (
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
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE INDEX idx_observations_scope ON observations (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_maintenance_scope ON maintenance_items (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_risks_scope ON repair_risks (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_reliability_scope ON reliability_items (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_listings_vehicle ON listings (vehicle_id);
CREATE INDEX idx_catalogue_links_owner ON catalogue_links (owner_id);
CREATE INDEX idx_vehicles_hsn_tsn ON vehicles (hsn, tsn);
CREATE INDEX research_requests_owner ON research_requests (owner_id, status);
CREATE INDEX research_requests_queue ON research_requests (status, id);
CREATE INDEX idx_research_checks_task ON research_checks (task);
