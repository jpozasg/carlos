-- #291: tokens, cost, time and turns of the worker's Claude runs, summed over a request's attempts (JSON, NULL = not measured).
ALTER TABLE research_requests ADD COLUMN usage TEXT CHECK (usage IS NULL OR json_valid(usage));
