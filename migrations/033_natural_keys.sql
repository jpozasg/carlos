-- Issue #194 (target design #172): natural keys of the shared catalogue, so a car type is never stored twice:
-- a generation by make + model + name, an engine by code + power, a variant by HSN/TSN + engine. Only catalogue rows
-- (owner_id NULL) are unique; a private row may repeat one. The catalogue had no duplicates when this was written
-- (part 6, #144), so it applies before and after the research reset of #167.
CREATE UNIQUE INDEX ux_generations_key ON generations (make, model, name) WHERE owner_id IS NULL;
CREATE UNIQUE INDEX ux_engines_key ON engines (code, power_kw) WHERE owner_id IS NULL;
CREATE UNIQUE INDEX ux_vehicles_key ON vehicles (hsn, tsn, engine_id) WHERE owner_id IS NULL AND hsn IS NOT NULL;
