-- Structured listing facts for the ranking filters and the distance (#169, owner 2026-11-06): read from the ad by
-- capture_listing.py; NULL = not shown in the ad. The seller's rating (stars 0–5, review count) for the dossier facts.
ALTER TABLE listings ADD COLUMN seller_type TEXT CHECK (seller_type IS NULL OR seller_type IN ('DEALER', 'PRIVATE'));
ALTER TABLE listings ADD COLUMN warranty INTEGER CHECK (warranty IS NULL OR warranty IN (0, 1));
ALTER TABLE listings ADD COLUMN hu_until TEXT CHECK (hu_until IS NULL OR hu_until GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]');
ALTER TABLE listings ADD COLUMN service_history TEXT CHECK (service_history IS NULL OR service_history IN ('YES', 'NO', 'CLAIMED'));
ALTER TABLE listings ADD COLUMN accident_free TEXT CHECK (accident_free IS NULL OR accident_free IN ('YES', 'NO', 'CLAIMED'));
ALTER TABLE listings ADD COLUMN seller_rating REAL CHECK (seller_rating IS NULL OR seller_rating BETWEEN 0 AND 5);
ALTER TABLE listings ADD COLUMN seller_reviews INTEGER CHECK (seller_reviews IS NULL OR seller_reviews >= 0);
-- the car's postcode, for the distance from the owning account's postcode (bundled OSM table, carlos/plz_de.csv)
ALTER TABLE listings ADD COLUMN postal_code TEXT CHECK (postal_code IS NULL OR postal_code GLOB '[0-9][0-9][0-9][0-9][0-9]');
