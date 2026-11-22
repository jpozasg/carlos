-- #420 (security finding L7): an insurance premium, quote or profile belongs to one account. listing_quotes gets the owner of
-- its listing. insurance_data rows that carry a premium, quote or profile but no owner (written before the owner rule) go to
-- the first admin, the account that owned the install before accounts existed. Shared rows keep only facts that are not an
-- account's (typklasses, tax, research).
ALTER TABLE listing_quotes ADD COLUMN owner_id INTEGER REFERENCES users(id);
UPDATE listing_quotes SET owner_id = (SELECT l.owner_id FROM listings l WHERE l.id = listing_quotes.listing_id);
UPDATE insurance_data SET owner_id = (SELECT min(id) FROM users WHERE role = 'admin')
 WHERE owner_id IS NULL AND (annual_premium_eur IS NOT NULL OR premium_min_eur IS NOT NULL OR premium_status IS NOT NULL
   OR insurer IS NOT NULL OR tariff IS NOT NULL OR quote_date IS NOT NULL OR quote_profile IS NOT NULL);
