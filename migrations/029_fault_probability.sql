-- Fault probability method (owner, 2026-11-06, #168): a frequency band from the source's wording (central value used,
-- range stored), one of four curve shapes, the fixed part's curve after a documented fix, extended warranty cover,
-- and the manufacturer trace a systemic fault needs.
ALTER TABLE faults ADD COLUMN frequency_band TEXT CHECK (frequency_band IS NULL OR frequency_band IN ('systemic', 'widespread', 'common', 'occasional', 'rare'));
ALTER TABLE faults ADD COLUMN share_low REAL CHECK (share_low IS NULL OR (share_low >= 0 AND share_low <= 1));
ALTER TABLE faults ADD COLUMN share_high REAL CHECK (share_high IS NULL OR (share_high >= 0 AND share_high <= 1));
ALTER TABLE faults ADD COLUMN shape TEXT CHECK (shape IS NULL OR shape IN ('WEAR_KM', 'AGE', 'WINDOW', 'RANDOM'));
ALTER TABLE faults ADD COLUMN window_km INTEGER CHECK (window_km IS NULL OR window_km > 0);
ALTER TABLE faults ADD COLUMN onset_km INTEGER CHECK (onset_km IS NULL OR onset_km >= 0);
ALTER TABLE faults ADD COLUMN manufacturer_trace TEXT;
ALTER TABLE faults ADD COLUMN fixed_fault_id INTEGER REFERENCES faults(id);
ALTER TABLE faults ADD COLUMN warranty_km INTEGER CHECK (warranty_km IS NULL OR warranty_km > 0);
ALTER TABLE faults ADD COLUMN warranty_years REAL CHECK (warranty_years IS NULL OR warranty_years > 0);
ALTER TABLE faults ADD COLUMN warranty_share REAL CHECK (warranty_share IS NULL OR (warranty_share > 0 AND warranty_share <= 1));
ALTER TABLE faults ADD COLUMN quote TEXT;
