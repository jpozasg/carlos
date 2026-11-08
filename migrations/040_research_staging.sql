-- #253 phase P2: two research runs per car write to staging; the server compares, an arbiter settles disputes, the merge writes
-- (docs/design-two-agent-research.md, sections 1-3). Rebuild research_requests because the `unit` CHECK lists the units (as 037/038);
-- `scope` is new. Staging holds catalogue research only: no listing data, no personal data.
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
 unit TEXT CHECK (unit IS NULL OR unit IN ('CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING', 'INSURANCE',
                                           'RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')),
 level_id INTEGER,
 shared_id INTEGER REFERENCES research_requests_new(id),
 scope TEXT CHECK (scope IS NULL OR json_valid(scope)));
INSERT INTO research_requests_new (id, owner_id, url, note, status, requested_at, claimed_at, finished_at, worker, listing_id, result, requested_by, request_token_hash, kind, flag_id, attempts, missing, parent_id, unit, level_id, shared_id) SELECT id, owner_id, url, note, status, requested_at, claimed_at, finished_at, worker, listing_id, result, requested_by, request_token_hash, kind, flag_id, attempts, missing, parent_id, unit, level_id, shared_id FROM research_requests;
DROP TABLE research_requests;
ALTER TABLE research_requests_new RENAME TO research_requests;
CREATE INDEX research_requests_owner ON research_requests (owner_id, status);
CREATE INDEX research_requests_queue ON research_requests (status, id);
CREATE INDEX research_requests_token ON research_requests (request_token_hash);
CREATE UNIQUE INDEX research_requests_child ON research_requests (parent_id, unit) WHERE parent_id IS NOT NULL;
CREATE UNIQUE INDEX research_requests_open_unit ON research_requests (unit, level_id)
 WHERE parent_id IS NOT NULL AND level_id IS NOT NULL AND status IN ('QUEUED', 'RUNNING');

-- one row per staged write of a run (the body the run sent to /api/agent/<table>; negative ids in the API are -id)
CREATE TABLE research_findings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES research_requests(id),
 parent_id INTEGER NOT NULL REFERENCES research_requests(id),
 run TEXT NOT NULL CHECK (run IN ('A', 'B', 'C')),
 kind TEXT NOT NULL CHECK (kind IN ('source', 'level', 'patch', 'fault', 'recall', 'job', 'check', 'observation', 'tyres', 'stats', 'flag')),
 op TEXT NOT NULL CHECK (op IN ('insert', 'patch')),
 target_table TEXT NOT NULL,
 target_id INTEGER,
 key TEXT NOT NULL,
 level TEXT, level_id INTEGER,
 part TEXT, component_code TEXT,
 payload TEXT NOT NULL CHECK (json_valid(payload)),
 status TEXT NOT NULL DEFAULT 'STAGED' CHECK (status IN ('STAGED', 'MERGED', 'SKIPPED', 'ARCHIVED')),
 merged_id INTEGER,
 created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
 CHECK ((op = 'patch') = (target_id IS NOT NULL)));
CREATE UNIQUE INDEX research_findings_key ON research_findings (request_id, key)
 WHERE status = 'STAGED' AND kind NOT IN ('fault', 'check', 'flag');
CREATE INDEX research_findings_parent ON research_findings (parent_id, run, kind);

-- the comparison of run A with run B and the arbiter's verdicts (filled by P3)
CREATE TABLE research_matches (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 parent_id INTEGER NOT NULL REFERENCES research_requests(id),
 kind TEXT NOT NULL, key TEXT NOT NULL,
 a_id INTEGER REFERENCES research_findings(id), b_id INTEGER REFERENCES research_findings(id),
 outcome TEXT NOT NULL CHECK (outcome IN ('AGREED', 'DISPUTED', 'ONLY_A', 'ONLY_B')),
 diffs TEXT CHECK (diffs IS NULL OR json_valid(diffs)),
 material INTEGER NOT NULL DEFAULT 0 CHECK (material IN (0, 1)),
 verdict TEXT CHECK (verdict IS NULL OR verdict IN ('A', 'B', 'BOTH', 'NEITHER', 'OWN')),
 verdict_id INTEGER REFERENCES research_findings(id),
 verdict_reason TEXT, verdict_source_id INTEGER,
 merged TEXT CHECK (merged IS NULL OR json_valid(merged)),
 flag_id INTEGER REFERENCES review_flags(id),
 CHECK (a_id IS NOT NULL OR b_id IS NOT NULL),
 CHECK (verdict IS NOT 'OWN' OR verdict_id IS NOT NULL));
CREATE INDEX research_matches_parent ON research_matches (parent_id, outcome);
