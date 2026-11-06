-- Reference schema generated from the database (PRAGMA user_version=34). Changes: add migrations/NNN_*.sql.
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
 annual_tax_eur REAL, status TEXT, basis TEXT, source_id INTEGER, notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), registered_from TEXT, registered_to TEXT,
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE TABLE "reliability_items" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 component TEXT NOT NULL, issue TEXT, evidence TEXT, severity TEXT,
 frequency_status TEXT, source_id INTEGER, inspection_action TEXT, part TEXT CHECK (part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')), is_recall INTEGER NOT NULL DEFAULT 0 CHECK (is_recall IN (0, 1)), archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), applies_from TEXT, applies_to TEXT,
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
 notes TEXT, archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), job TEXT, applies_from TEXT, applies_to TEXT,
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
  CHECK (ranking_answers IS NULL OR json_type(ranking_answers) = 'object'), home_charging TEXT
  CHECK (home_charging IS NULL OR home_charging IN ('none', 'socket', 'wallbox', 'wallbox_planned')), home_charging_pct INTEGER CHECK (home_charging_pct IS NULL OR home_charging_pct BETWEEN 0 AND 100), electricity_home_eur_kwh REAL CHECK (electricity_home_eur_kwh IS NULL OR electricity_home_eur_kwh > 0), electricity_home_date TEXT, electricity_public_eur_kwh REAL CHECK (electricity_public_eur_kwh IS NULL OR electricity_public_eur_kwh > 0), electricity_public_date TEXT, wallbox_cost_eur REAL CHECK (wallbox_cost_eur IS NULL OR wallbox_cost_eur >= 0), acquisition_mode TEXT
  CHECK (acquisition_mode IS NULL OR acquisition_mode IN ('buy', 'lease', 'both')), lease_rate_max_eur REAL CHECK (lease_rate_max_eur IS NULL OR lease_rate_max_eur > 0), exclude_over_max INTEGER CHECK (exclude_over_max IS NULL OR exclude_over_max IN (0, 1)));
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
, ncap_stars INTEGER CHECK (ncap_stars IS NULL OR ncap_stars BETWEEN 0 AND 5), ncap_year INTEGER CHECK (ncap_year IS NULL OR ncap_year BETWEEN 1997 AND 2100));
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
, battery_usable_kwh REAL CHECK (battery_usable_kwh IS NULL OR battery_usable_kwh > 0), ac_charge_kw REAL CHECK (ac_charge_kw IS NULL OR ac_charge_kw > 0), dc_charge_kw REAL CHECK (dc_charge_kw IS NULL OR dc_charge_kw > 0), family_id INTEGER REFERENCES engine_families(id));
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
, gearbox_id INTEGER REFERENCES gearboxes(id), body_style_id INTEGER REFERENCES body_styles(id), esp INTEGER CHECK (esp IS NULL OR esp IN (0, 1)));
CREATE TABLE "sources" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 title TEXT NOT NULL, url TEXT, source_type TEXT, quality TEXT,
 accessed_date TEXT, supports TEXT, limitations TEXT, owner_id INTEGER REFERENCES users(id), gearbox_id INTEGER REFERENCES gearboxes(id), engine_family_id INTEGER REFERENCES engine_families(id), gearbox_family_id INTEGER REFERENCES gearbox_families(id), body_style_id INTEGER REFERENCES body_styles(id), option_id INTEGER REFERENCES options(id),
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
, requested_by INTEGER REFERENCES users(id), request_token_hash TEXT, kind TEXT NOT NULL DEFAULT 'LISTING' CHECK (kind IN ('LISTING', 'FOLLOW_UP')), flag_id INTEGER REFERENCES review_flags(id));
CREATE TABLE workers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 token_hash TEXT UNIQUE,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 last_seen TEXT,
 state TEXT CHECK (state IS NULL OR state IN ('idle', 'working', 'error')),
 request_id INTEGER REFERENCES research_requests(id),
 last_error TEXT,
 last_error_at TEXT
);
CREATE TABLE engine_families (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, maker TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE TABLE gearbox_families (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, maker TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE TABLE gearboxes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, family_id INTEGER REFERENCES gearbox_families(id),
 type TEXT CHECK (type IS NULL OR type IN ('MANUAL', 'DCT', 'AT', 'CVT', 'SINGLE-SPEED')),
 gears INTEGER CHECK (gears IS NULL OR gears > 0), description TEXT, status TEXT, notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE TABLE body_styles (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id), name TEXT NOT NULL,
 notes TEXT, owner_id INTEGER REFERENCES users(id));
CREATE TABLE options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, generation_id INTEGER REFERENCES generations(id), notes TEXT,
 owner_id INTEGER REFERENCES users(id));
CREATE TABLE listing_options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id),
 option_id INTEGER NOT NULL REFERENCES options(id), source_id INTEGER REFERENCES sources(id), notes TEXT,
 UNIQUE (listing_id, option_id));
CREATE TABLE listing_quotes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL REFERENCES listings(id),
 annual_premium_eur REAL NOT NULL CHECK (annual_premium_eur > 0),
 premium_min_eur REAL CHECK (premium_min_eur IS NULL OR premium_min_eur > 0),
 premium_status TEXT NOT NULL, insurer TEXT, tariff TEXT,
 quote_date TEXT CHECK (quote_date IS NULL OR quote_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
 quote_profile TEXT CHECK (quote_profile IS NULL OR json_type(quote_profile) = 'object'),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)));
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
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), frequency_band TEXT CHECK (frequency_band IS NULL OR frequency_band IN ('systemic', 'widespread', 'common', 'occasional', 'rare')), share_low REAL CHECK (share_low IS NULL OR (share_low >= 0 AND share_low <= 1)), share_high REAL CHECK (share_high IS NULL OR (share_high >= 0 AND share_high <= 1)), shape TEXT CHECK (shape IS NULL OR shape IN ('WEAR_KM', 'AGE', 'WINDOW', 'RANDOM')), window_km INTEGER CHECK (window_km IS NULL OR window_km > 0), onset_km INTEGER CHECK (onset_km IS NULL OR onset_km >= 0), manufacturer_trace TEXT, fixed_fault_id INTEGER REFERENCES faults(id), warranty_km INTEGER CHECK (warranty_km IS NULL OR warranty_km > 0), warranty_years REAL CHECK (warranty_years IS NULL OR warranty_years > 0), warranty_share REAL CHECK (warranty_share IS NULL OR (warranty_share > 0 AND warranty_share <= 1)), quote TEXT,
 CHECK (usage_multiplier IS NULL OR usage_source_id IS NOT NULL),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) + (gearbox_id IS NOT NULL)
      + (engine_family_id IS NOT NULL) + (gearbox_family_id IS NOT NULL) + (body_style_id IS NOT NULL) + (option_id IS NOT NULL) = 1));
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
CREATE TABLE reliability_stats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id),
 kind TEXT NOT NULL CHECK (kind IN ('TUEV', 'ADAC')), age_from INTEGER NOT NULL, age_to INTEGER NOT NULL,
 value REAL NOT NULL, unit TEXT NOT NULL, sample_count INTEGER, report_year INTEGER,
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id), class_average REAL CHECK (class_average IS NULL OR class_average > 0),
 CHECK (age_to >= age_from));
CREATE TABLE market_models (
 id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id INTEGER NOT NULL REFERENCES generations(id),
 engine_id INTEGER NOT NULL REFERENCES engines(id), gearbox_id INTEGER REFERENCES gearboxes(id),
 value_ref_eur REAL NOT NULL CHECK (value_ref_eur > 0), ref_age_years REAL NOT NULL, ref_km INTEGER NOT NULL,
 rate_year REAL NOT NULL CHECK (rate_year >= 0 AND rate_year < 1), rate_10k_km REAL NOT NULL CHECK (rate_10k_km >= 0 AND rate_10k_km < 1),
 band_counts TEXT NOT NULL CHECK (json_type(band_counts) = 'array'), sample_date TEXT NOT NULL,
 filters TEXT, sample_json TEXT CHECK (sample_json IS NULL OR json_type(sample_json) = 'array'),
 source_id INTEGER NOT NULL REFERENCES sources(id), notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)), owner_id INTEGER REFERENCES users(id));
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
CREATE TABLE "maintenance_items" (
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
CREATE TABLE "research_checks" (
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
CREATE TABLE "listings" (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 source_id INTEGER,
 listing_id TEXT, platform TEXT, url TEXT,
 price_eur REAL, mileage_km INTEGER, seller TEXT, location TEXT,
 seller_address TEXT, accident_free_claim INTEGER, owners_claim INTEGER,
 hu_claim TEXT, service_history_claim TEXT, equipment TEXT,
 listing_date TEXT, last_checked TEXT, listing_status TEXT, notes TEXT
, is_reference INTEGER NOT NULL DEFAULT 0 CHECK (is_reference IN (0, 1)), first_registration TEXT, verdict TEXT, owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id), battery_soh_claim REAL CHECK (battery_soh_claim IS NULL OR (battery_soh_claim > 0 AND battery_soh_claim <= 100)), lease_kind TEXT CHECK (lease_kind IS NULL OR lease_kind IN ('km', 'residual', 'abo')), lease_monthly_eur REAL CHECK (lease_monthly_eur IS NULL OR lease_monthly_eur > 0), lease_term_months INTEGER CHECK (lease_term_months IS NULL OR lease_term_months > 0), lease_km_per_year INTEGER CHECK (lease_km_per_year IS NULL OR lease_km_per_year > 0), lease_down_payment_eur REAL CHECK (lease_down_payment_eur IS NULL OR lease_down_payment_eur >= 0), lease_fees_eur REAL CHECK (lease_fees_eur IS NULL OR lease_fees_eur >= 0), lease_extra_km_eur REAL CHECK (lease_extra_km_eur IS NULL OR lease_extra_km_eur >= 0), lease_fewer_km_eur REAL CHECK (lease_fewer_km_eur IS NULL OR lease_fewer_km_eur >= 0), lease_includes TEXT, build_date TEXT, engine_code_seen TEXT, hsn TEXT, tsn TEXT, trim TEXT, distance_km REAL CHECK (distance_km IS NULL OR distance_km >= 0), seller_type TEXT CHECK (seller_type IS NULL OR seller_type IN ('DEALER', 'PRIVATE')), warranty INTEGER CHECK (warranty IS NULL OR warranty IN (0, 1)), hu_until TEXT CHECK (hu_until IS NULL OR hu_until GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'), service_history TEXT CHECK (service_history IS NULL OR service_history IN ('YES', 'NO', 'CLAIMED')), accident_free TEXT CHECK (accident_free IS NULL OR accident_free IN ('YES', 'NO', 'CLAIMED')), seller_rating REAL CHECK (seller_rating IS NULL OR seller_rating BETWEEN 0 AND 5), seller_reviews INTEGER CHECK (seller_reviews IS NULL OR seller_reviews >= 0), postal_code TEXT CHECK (postal_code IS NULL OR postal_code GLOB '[0-9][0-9][0-9][0-9][0-9]'));
CREATE INDEX idx_observations_scope ON observations (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_risks_scope ON repair_risks (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_reliability_scope ON reliability_items (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_catalogue_links_owner ON catalogue_links (owner_id);
CREATE INDEX idx_vehicles_hsn_tsn ON vehicles (hsn, tsn);
CREATE INDEX research_requests_owner ON research_requests (owner_id, status);
CREATE INDEX research_requests_queue ON research_requests (status, id);
CREATE INDEX research_requests_token ON research_requests (request_token_hash);
CREATE UNIQUE INDEX ux_engine_families_name ON engine_families (upper(name));
CREATE UNIQUE INDEX ux_gearbox_families_name ON gearbox_families (upper(name));
CREATE UNIQUE INDEX ux_gearboxes_code ON gearboxes (upper(code));
CREATE UNIQUE INDEX ux_body_styles ON body_styles (generation_id, upper(name));
CREATE UNIQUE INDEX ux_options ON options (upper(name), coalesce(generation_id, 0));
CREATE INDEX idx_maintenance_scope ON maintenance_items (vehicle_id, engine_id, generation_id);
CREATE INDEX idx_research_checks_task ON research_checks (task);
CREATE INDEX idx_faults_scope ON faults (vehicle_id, engine_id, generation_id, gearbox_id, engine_family_id);
CREATE INDEX idx_listing_history ON listing_history (listing_id);
CREATE INDEX idx_listing_quotes ON listing_quotes (listing_id);
CREATE INDEX idx_listings_vehicle ON listings (vehicle_id);
CREATE UNIQUE INDEX ux_generations_key ON generations (make, model, name) WHERE owner_id IS NULL;
CREATE UNIQUE INDEX ux_engines_key ON engines (code, power_kw) WHERE owner_id IS NULL;
CREATE UNIQUE INDEX ux_vehicles_key ON vehicles (hsn, tsn, engine_id) WHERE owner_id IS NULL AND hsn IS NOT NULL;
