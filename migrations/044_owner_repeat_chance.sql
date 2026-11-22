-- #379 (owner decision 2026-11-22): the owner's own chance that a fault, fixed on this car (a DONE history row), fails again
-- within the owner's period. It is evidence about one car, so it lives on that car's history row; the shared fault row and
-- every other car keep their figures. NULL = no owner figure (the cost keeps today's treatment), never 0 by default.
ALTER TABLE listing_history ADD COLUMN owner_probability REAL
 CHECK (owner_probability IS NULL OR (owner_probability BETWEEN 0 AND 1 AND fault_id IS NOT NULL AND status = 'DONE'));
ALTER TABLE listing_history ADD COLUMN owner_reason TEXT
 CHECK (owner_reason IS NULL OR owner_probability IS NOT NULL);
