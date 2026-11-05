-- Archive (issue #58): an archived row is kept in the database but ignored by every read and calculation
-- (the per-account views filter archived=0); PATCH archived=0 restores it. Deleting is a separate, confirmed step.
ALTER TABLE observations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE insurance_data ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE tax_data ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE maintenance_items ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE reliability_items ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE repair_risks ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE tyre_data ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE unit_costs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE valuations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE maintenance_resets ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
ALTER TABLE inspection_items ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1));
