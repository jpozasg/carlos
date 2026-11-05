-- Leasing (issue #127): one lease offer per listing, next to the purchase price (a used mobile.de ad can show both).
-- lease_kind: km (kilometre leasing), residual (residual-value leasing, recorded but not costed), abo (car subscription,
-- usually all-inclusive). lease_includes: what the rate covers, a comma list of insurance, tax, maintenance, repairs,
-- tyres, gap (checked by the API); those components are inside the rate, never counted again. NULL = not stated.
ALTER TABLE listings ADD COLUMN lease_kind TEXT CHECK (lease_kind IS NULL OR lease_kind IN ('km', 'residual', 'abo'));
ALTER TABLE listings ADD COLUMN lease_monthly_eur REAL CHECK (lease_monthly_eur IS NULL OR lease_monthly_eur > 0);
ALTER TABLE listings ADD COLUMN lease_term_months INTEGER CHECK (lease_term_months IS NULL OR lease_term_months > 0);
ALTER TABLE listings ADD COLUMN lease_km_per_year INTEGER CHECK (lease_km_per_year IS NULL OR lease_km_per_year > 0);
ALTER TABLE listings ADD COLUMN lease_down_payment_eur REAL CHECK (lease_down_payment_eur IS NULL OR lease_down_payment_eur >= 0);
ALTER TABLE listings ADD COLUMN lease_fees_eur REAL CHECK (lease_fees_eur IS NULL OR lease_fees_eur >= 0);
ALTER TABLE listings ADD COLUMN lease_extra_km_eur REAL CHECK (lease_extra_km_eur IS NULL OR lease_extra_km_eur >= 0);
ALTER TABLE listings ADD COLUMN lease_fewer_km_eur REAL CHECK (lease_fewer_km_eur IS NULL OR lease_fewer_km_eur >= 0);
ALTER TABLE listings ADD COLUMN lease_includes TEXT;
-- the account: buy, lease or compare both (NULL behaves as buy), and the highest monthly lease rate it would pay
ALTER TABLE project_parameters ADD COLUMN acquisition_mode TEXT
  CHECK (acquisition_mode IS NULL OR acquisition_mode IN ('buy', 'lease', 'both'));
ALTER TABLE project_parameters ADD COLUMN lease_rate_max_eur REAL CHECK (lease_rate_max_eur IS NULL OR lease_rate_max_eur > 0);
