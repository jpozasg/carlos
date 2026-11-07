-- Done gate (#218): the server re-grades the listing when the worker says DONE; a request with items still missing goes back
-- to the queue (attempts + 1, up to MAX_ATTEMPTS) with the missing contract item ids (JSON array) for the continuation run.
ALTER TABLE research_requests ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE research_requests ADD COLUMN missing TEXT;
