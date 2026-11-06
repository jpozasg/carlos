-- Issue #153 (owner chose "A", 2026-11-06): a generation stays the whole production run; a maintenance item, repair
-- risk or reliability item that only concerns part of it (a fault fixed by the facelift, a recall's build range) carries
-- the months of first registration it applies to ('YYYY-MM' or 'YYYY'; NULL = open end). A listing outside the window
-- does not inherit the row; a listing without a known first registration inherits it (never silently dropped).
ALTER TABLE maintenance_items ADD COLUMN applies_from TEXT;
ALTER TABLE maintenance_items ADD COLUMN applies_to TEXT;
ALTER TABLE repair_risks ADD COLUMN applies_from TEXT;
ALTER TABLE repair_risks ADD COLUMN applies_to TEXT;
ALTER TABLE reliability_items ADD COLUMN applies_from TEXT;
ALTER TABLE reliability_items ADD COLUMN applies_to TEXT;
