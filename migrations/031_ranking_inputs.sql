-- Ranking redesign (#169, target design §6): inputs of the new criteria and the budget switch.
-- safety: Euro NCAP stars of the generation and the year of its test (the regime changed in 2009); ESP standard on the variant.
ALTER TABLE generations ADD COLUMN ncap_stars INTEGER CHECK (ncap_stars IS NULL OR ncap_stars BETWEEN 0 AND 5);
ALTER TABLE generations ADD COLUMN ncap_year INTEGER CHECK (ncap_year IS NULL OR ncap_year BETWEEN 1997 AND 2100);
ALTER TABLE vehicles ADD COLUMN esp INTEGER CHECK (esp IS NULL OR esp IN (0, 1));
-- distance to view: km from the owning account's postcode, stored on the listing (private, per account)
ALTER TABLE listings ADD COLUMN distance_km REAL CHECK (distance_km IS NULL OR distance_km >= 0);
-- the maximum budget excludes cars from the ranking unless switched off (1 = exclude)
ALTER TABLE project_parameters ADD COLUMN exclude_over_max INTEGER CHECK (exclude_over_max IS NULL OR exclude_over_max IN (0, 1));
