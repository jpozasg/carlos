-- Prices per account (part 4 of #106): a controlled `job` code on maintenance items and repair risks, so each account's
-- DIY choice (preference diy_jobs) picks the DIY parts or the workshop price of a shared row at calculation time; and a
-- registration window on tax rows (a variant's tax depends on the first registration). Codes: config.JOBS; the list is
-- enforced by the API (fixed_codes), not by a CHECK, so new jobs (electric cars) need no table rebuild.
ALTER TABLE maintenance_items ADD COLUMN job TEXT;
ALTER TABLE repair_risks ADD COLUMN job TEXT;
ALTER TABLE tax_data ADD COLUMN registered_from TEXT;
ALTER TABLE tax_data ADD COLUMN registered_to TEXT;

-- back-fill by generic name patterns; order matters (a timing belt kit mentions the water pump and coolant, brake
-- fluid is not a brake job); anything unrecognised stays NULL and keeps its stored diy flag
UPDATE maintenance_items SET job = CASE
  WHEN item LIKE 'HU%' OR item LIKE '%Hauptuntersuchung%' THEN 'HU'
  WHEN item LIKE '%brake fluid%' THEN 'BRAKE_FLUID'
  WHEN item LIKE '%timing belt%' OR item LIKE '%timing chain%' OR item LIKE '%cam belt%' THEN 'TIMING_DRIVE'
  WHEN item LIKE '%drive belt%' OR item LIKE '%accessory belt%' OR item LIKE '%auxiliary%belt%' OR item LIKE '%serpentine%' THEN 'DRIVE_BELT'
  WHEN item LIKE '%coolant%' THEN 'COOLANT'
  WHEN item LIKE '%spark plug%' THEN 'SPARK_PLUGS'
  WHEN item LIKE '%fuel filter%' THEN 'FUEL_FILTER'
  WHEN item LIKE '%air filter%' THEN 'AIR_FILTER'
  WHEN item LIKE '%cabin%' OR item LIKE '%pollen%' THEN 'CABIN_FILTER'
  WHEN (item LIKE '%engine oil%' OR item LIKE 'oil and filter%') AND item NOT LIKE '%gear%' AND item NOT LIKE '%transmission%' THEN 'OIL_SERVICE'
  WHEN item LIKE '%front brake%' THEN 'BRAKES_FRONT'
  WHEN item LIKE '%rear brake%' OR item LIKE '%rear drum%' THEN 'BRAKES_REAR'
  WHEN item LIKE '%battery%' THEN 'BATTERY'
  WHEN item LIKE '%bulb%' THEN 'BULBS'
  WHEN item LIKE '%wiper%' THEN 'WIPERS'
  WHEN item LIKE '%clutch%' THEN 'CLUTCH'
END;
-- risks: only plain replacement jobs (consequential damage such as "engine damage after timing belt failure" is no job)
UPDATE repair_risks SET job = CASE
  WHEN component LIKE '%damage%' OR component LIKE '%failure%' THEN NULL
  WHEN component LIKE '%clutch%' THEN 'CLUTCH'
  WHEN component LIKE '%timing chain%' OR component LIKE '%timing belt%' THEN 'TIMING_DRIVE'
  WHEN component LIKE '%battery%' THEN 'BATTERY'
  WHEN component LIKE '%bulb%' THEN 'BULBS'
END;
