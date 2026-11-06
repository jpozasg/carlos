-- Issue #139: an admin (the shared worker's agent) may queue a research request for an account; requested_by records
-- who queued it (NULL = the account itself).
ALTER TABLE research_requests ADD COLUMN requested_by INTEGER REFERENCES users(id);
