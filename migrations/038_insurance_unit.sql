-- #245: the INSURANCE unit (workers get insurance quotes for accounts that opted in). Rebuild because the `unit` CHECK lists the
-- units; same table as 037 otherwise.
CREATE TABLE research_requests_new (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 url TEXT NOT NULL,
 note TEXT,
 status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'WAITING', 'DONE', 'SKIPPED', 'FAILED', 'CANCELLED')),
 requested_at TEXT NOT NULL DEFAULT (datetime('now')),
 claimed_at TEXT,
 finished_at TEXT,
 worker TEXT,
 listing_id INTEGER REFERENCES listings(id),
 result TEXT,
 requested_by INTEGER REFERENCES users(id), request_token_hash TEXT,
 kind TEXT NOT NULL DEFAULT 'LISTING' CHECK (kind IN ('LISTING', 'FOLLOW_UP')),
 flag_id INTEGER REFERENCES review_flags(id),
 attempts INTEGER NOT NULL DEFAULT 0, missing TEXT,
 parent_id INTEGER REFERENCES research_requests_new(id),
 unit TEXT CHECK (unit IS NULL OR unit IN ('CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING', 'INSURANCE')),
 level_id INTEGER,
 shared_id INTEGER REFERENCES research_requests_new(id));
INSERT INTO research_requests_new SELECT * FROM research_requests;
DROP TABLE research_requests;
ALTER TABLE research_requests_new RENAME TO research_requests;
CREATE INDEX research_requests_owner ON research_requests (owner_id, status);
CREATE INDEX research_requests_queue ON research_requests (status, id);
CREATE INDEX research_requests_token ON research_requests (request_token_hash);
CREATE UNIQUE INDEX research_requests_child ON research_requests (parent_id, unit) WHERE parent_id IS NOT NULL;
CREATE UNIQUE INDEX research_requests_open_unit ON research_requests (unit, level_id)
 WHERE parent_id IS NOT NULL AND level_id IS NOT NULL AND status IN ('QUEUED', 'RUNNING');
