-- improve-core C4 and C3 (2026-11-22): a fault may carry the maintenance job it is done as (config.JOBS): the account's DIY
-- choice then picks its DIY parts price and hours, as for maintenance items (NULL = workshop only, the default). A certain
-- repair (unit_costs, category repairs) may name the fault it fixes, so the fault's expected cost is not added on top of it.
-- The job code is checked by the API (FIXED_CODES), as for maintenance_items.job.
ALTER TABLE faults ADD COLUMN job TEXT;
ALTER TABLE unit_costs ADD COLUMN fault_id INTEGER REFERENCES faults(id);
