-- Issue #194: a listing can exist without a variant until the worker (re-)researches its model. The research reset of
-- #167 empties the catalogue but keeps the owner's listings. Rebuild of listings with vehicle_id nullable; same columns
-- and checks otherwise. Foreign keys pointing at listings keep working (the table keeps its name).
CREATE TABLE listings_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 source_id INTEGER,
 listing_id TEXT, platform TEXT, url TEXT,
 price_eur REAL, mileage_km INTEGER, seller TEXT, location TEXT,
 seller_address TEXT, accident_free_claim INTEGER, owners_claim INTEGER,
 hu_claim TEXT, service_history_claim TEXT, equipment TEXT,
 listing_date TEXT, last_checked TEXT, listing_status TEXT, notes TEXT
, is_reference INTEGER NOT NULL DEFAULT 0 CHECK (is_reference IN (0, 1)), first_registration TEXT, verdict TEXT, owner_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id), battery_soh_claim REAL CHECK (battery_soh_claim IS NULL OR (battery_soh_claim > 0 AND battery_soh_claim <= 100)), lease_kind TEXT CHECK (lease_kind IS NULL OR lease_kind IN ('km', 'residual', 'abo')), lease_monthly_eur REAL CHECK (lease_monthly_eur IS NULL OR lease_monthly_eur > 0), lease_term_months INTEGER CHECK (lease_term_months IS NULL OR lease_term_months > 0), lease_km_per_year INTEGER CHECK (lease_km_per_year IS NULL OR lease_km_per_year > 0), lease_down_payment_eur REAL CHECK (lease_down_payment_eur IS NULL OR lease_down_payment_eur >= 0), lease_fees_eur REAL CHECK (lease_fees_eur IS NULL OR lease_fees_eur >= 0), lease_extra_km_eur REAL CHECK (lease_extra_km_eur IS NULL OR lease_extra_km_eur >= 0), lease_fewer_km_eur REAL CHECK (lease_fewer_km_eur IS NULL OR lease_fewer_km_eur >= 0), lease_includes TEXT, build_date TEXT, engine_code_seen TEXT, hsn TEXT, tsn TEXT, trim TEXT, distance_km REAL CHECK (distance_km IS NULL OR distance_km >= 0));
INSERT INTO listings_new SELECT * FROM listings;
DROP TABLE listings;
ALTER TABLE listings_new RENAME TO listings;
CREATE INDEX idx_listings_vehicle ON listings (vehicle_id);
