-- Registered research workers (issue #141): each worker has its own token (only heartbeat, claim, finish) and reports
-- its state; a claimed request carries a per-request token (hash) that the headless research run uses instead of any
-- long-lived credential: catalogue writes plus the requester's account only, valid while the request is RUNNING.
CREATE TABLE workers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 token_hash TEXT UNIQUE,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 last_seen TEXT,
 state TEXT CHECK (state IS NULL OR state IN ('idle', 'working', 'error')),
 request_id INTEGER REFERENCES research_requests(id),
 last_error TEXT,
 last_error_at TEXT
);
ALTER TABLE research_requests ADD COLUMN request_token_hash TEXT;
CREATE INDEX research_requests_token ON research_requests (request_token_hash);
