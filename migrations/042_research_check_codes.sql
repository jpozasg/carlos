-- #343: the fault component codes a source names as weak points of a part (JSON array of fault_components codes), so the
-- contract can require every fault two sources name (rel.coverage). NULL = the check does not say.
ALTER TABLE research_checks ADD COLUMN named_codes TEXT CHECK (named_codes IS NULL OR json_type(named_codes) = 'array');
