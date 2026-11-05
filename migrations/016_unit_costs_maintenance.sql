-- A job from the maintenance schedule that is due at purchase (timing belt by age, overdue coolant or brake fluid)
-- is maintenance, not a repair: unit_costs gets the category 'maintenance', counted in the maintenance component.
CREATE TABLE unit_costs_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL REFERENCES listings(id),
 category TEXT NOT NULL CHECK (category IN ('repairs', 'maintenance', 'tyres', 'purchase_sale')),
 item TEXT NOT NULL,
 parts_eur REAL, labor_eur REAL, diy_hours REAL,
 status TEXT NOT NULL,
 source_id INTEGER REFERENCES sources(id),
 notes TEXT,
 CHECK (parts_eur IS NOT NULL OR labor_eur IS NOT NULL)
);
INSERT INTO unit_costs_new (id, listing_id, category, item, parts_eur, labor_eur, diy_hours, status, source_id, notes)
  SELECT id, listing_id, category, item, parts_eur, labor_eur, diy_hours, status, source_id, notes FROM unit_costs;
DROP TABLE unit_costs;
ALTER TABLE unit_costs_new RENAME TO unit_costs;
-- Certain costs that restart a scheduled job were always scheduled maintenance done at purchase.
UPDATE unit_costs SET category = 'maintenance'
 WHERE category = 'repairs' AND id IN (SELECT unit_cost_id FROM maintenance_resets WHERE basis = 'CERTAIN REPAIR' AND unit_cost_id IS NOT NULL);
