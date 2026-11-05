-- Research contract (issue #114, part of #106; numbered 021 after 020_research_requests): one row per research task done at one level, including the negative
-- result ("consulted, nothing found") and N/A, so a clean part or a car without a facelift can count as researched.
-- task = a contract item id (carlos/research.py); contract_version = the contract the check was made against.
CREATE TABLE research_checks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vehicle_id INTEGER REFERENCES vehicles(id),
 engine_id INTEGER REFERENCES engines(id),
 generation_id INTEGER REFERENCES generations(id),
 task TEXT NOT NULL,
 source_id INTEGER NOT NULL REFERENCES sources(id),
 result TEXT NOT NULL CHECK (result IN ('FOUND', 'NONE FOUND', 'N/A')),
 contract_version INTEGER NOT NULL,
 checked_date TEXT,
 notes TEXT,
 archived INTEGER NOT NULL DEFAULT 0,
 owner_id INTEGER REFERENCES users(id),
 CHECK ((vehicle_id IS NOT NULL) + (engine_id IS NOT NULL) + (generation_id IS NOT NULL) = 1)
);
CREATE INDEX idx_research_checks_task ON research_checks (task);
