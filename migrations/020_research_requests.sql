-- Research requests (issue #113, part of #106): an account asks for a listing URL to be researched; the shared worker
-- (an admin token on the owner's desktop) claims it, writes the listing into the requester's account and finishes it.
-- The log of who asked for what, when, and what came of it.
CREATE TABLE research_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 url TEXT NOT NULL,
 note TEXT,
 status TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED')),
 requested_at TEXT NOT NULL DEFAULT (datetime('now')),
 claimed_at TEXT,
 finished_at TEXT,
 worker TEXT,
 listing_id INTEGER REFERENCES listings(id),
 result TEXT
);
CREATE INDEX research_requests_owner ON research_requests (owner_id, status);
CREATE INDEX research_requests_queue ON research_requests (status, id);
