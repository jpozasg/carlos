-- #223: a checklist item can come from a fault or a recall row (not only a reliability item), so lst.checklist can be met
-- for cars with faults; a recall's item gates it like a legacy recall item. At most one link per item (the helper enforces it).
ALTER TABLE inspection_items ADD COLUMN fault_id INTEGER REFERENCES faults(id);
ALTER TABLE inspection_items ADD COLUMN recall_id INTEGER REFERENCES recalls(id);
