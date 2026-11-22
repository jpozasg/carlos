-- Owner decision 2026-11-22: the automated insurance comparison is removed (legacy branch
-- legacy/insurance-automation keeps the old schema). These four columns are used by nothing in the
-- app and hold no values in the owner's database. quote_profile is NOT dropped: the manual quote form writes it.
ALTER TABLE insurance_data DROP COLUMN liability_typklasse;
ALTER TABLE insurance_data DROP COLUMN partial_typklasse;
ALTER TABLE insurance_data DROP COLUMN comprehensive_typklasse;
ALTER TABLE insurance_data DROP COLUMN premium_min_eur;
