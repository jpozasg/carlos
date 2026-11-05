-- Reliability by part (issue #54): every weak point belongs to one part (ENGINE, GEARBOX, CHASSIS, ELECTRICS) and each
-- part counts its three worst points. Recalls are flagged and linked to their own checklist item per listing; a recall
-- stops counting when that check is OK or N/A. Existing rows keep part NULL until they are classified.
ALTER TABLE reliability_items ADD COLUMN part TEXT CHECK (part IN ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS'));
ALTER TABLE reliability_items ADD COLUMN is_recall INTEGER NOT NULL DEFAULT 0 CHECK (is_recall IN (0, 1));
ALTER TABLE inspection_items ADD COLUMN reliability_item_id INTEGER REFERENCES reliability_items(id);
-- Link the checklist items created from a weak point (same text, a row that applies to the listing's variant,
-- engine or generation of the same account) to that row.
UPDATE inspection_items SET reliability_item_id = (
  SELECT min(r.id) FROM reliability_items r, listings l, vehicles v
   WHERE l.id = inspection_items.listing_id AND v.id = l.vehicle_id
     AND trim(r.inspection_action) = trim(inspection_items.item)
     AND (r.vehicle_id = v.id OR r.engine_id = v.engine_id OR r.generation_id = v.generation_id))
 WHERE reliability_item_id IS NULL;
