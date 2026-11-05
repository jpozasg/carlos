-- Electric cars (issue #121): the battery and charging facts of an electric engine (shared catalogue), the seller's
-- battery state-of-health claim on a listing, and the account's charging situation for the energy cost. Fuel types are
-- a controlled code enforced by the API (fixed_codes): Petrol, Diesel, Hybrid, Plug-in hybrid, Electric.
ALTER TABLE engines ADD COLUMN battery_usable_kwh REAL CHECK (battery_usable_kwh IS NULL OR battery_usable_kwh > 0);
ALTER TABLE engines ADD COLUMN ac_charge_kw REAL CHECK (ac_charge_kw IS NULL OR ac_charge_kw > 0);
ALTER TABLE engines ADD COLUMN dc_charge_kw REAL CHECK (dc_charge_kw IS NULL OR dc_charge_kw > 0);
ALTER TABLE listings ADD COLUMN battery_soh_claim REAL CHECK (battery_soh_claim IS NULL OR (battery_soh_claim > 0 AND battery_soh_claim <= 100));
ALTER TABLE project_parameters ADD COLUMN home_charging TEXT
  CHECK (home_charging IS NULL OR home_charging IN ('none', 'socket', 'wallbox', 'wallbox_planned'));
ALTER TABLE project_parameters ADD COLUMN home_charging_pct INTEGER CHECK (home_charging_pct IS NULL OR home_charging_pct BETWEEN 0 AND 100);
ALTER TABLE project_parameters ADD COLUMN electricity_home_eur_kwh REAL CHECK (electricity_home_eur_kwh IS NULL OR electricity_home_eur_kwh > 0);
ALTER TABLE project_parameters ADD COLUMN electricity_home_date TEXT;
ALTER TABLE project_parameters ADD COLUMN electricity_public_eur_kwh REAL CHECK (electricity_public_eur_kwh IS NULL OR electricity_public_eur_kwh > 0);
ALTER TABLE project_parameters ADD COLUMN electricity_public_date TEXT;
ALTER TABLE project_parameters ADD COLUMN wallbox_cost_eur REAL CHECK (wallbox_cost_eur IS NULL OR wallbox_cost_eur >= 0);
