-- Owner decision 2026-11-22 (confirmed in session): the automated insurance comparison is removed, so the
-- insurance data already registered is deleted and its columns dropped. The code and schema are on the
-- legacy branch legacy/insurance-automation; the values are backed up privately by migrate.py (data/backups).
DELETE FROM insurance_data WHERE id = 74;                      -- the BMW's own premium, 927 EUR/year (USER DATA)
DELETE FROM listing_quotes WHERE id IN (49, 50);               -- the Polo (721.10) and Golf (910.69) quotes
DELETE FROM project_preferences WHERE preference_key LIKE 'insurance\_%' ESCAPE '\';  -- 29 insurance profile keys
ALTER TABLE project_parameters DROP COLUMN drivers_count;
ALTER TABLE project_parameters DROP COLUMN driver_age;
ALTER TABLE project_parameters DROP COLUMN sf_class;
ALTER TABLE project_parameters DROP COLUMN insurance_cover;
ALTER TABLE project_parameters DROP COLUMN insurance_deductible_eur;
