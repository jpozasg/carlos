-- Security review H2: every change_log row records the research request whose token wrote it (NULL for the
-- owner's own writes and for rows written before this migration). Nothing is dropped; the column is nullable.
ALTER TABLE change_log ADD COLUMN request_id INTEGER REFERENCES research_requests(id);
CREATE INDEX IF NOT EXISTS change_log_request ON change_log(request_id);
