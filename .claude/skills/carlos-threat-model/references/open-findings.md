# Open findings (security audit 2026-11-22, static review at commit 75de5f1; re-verified at 67f98cb)

Copied from the audit and re-checked against the code at 67f98cb (two commits later: manual car entry, #375/#376): every item below is still OPEN, with the corrections the re-check found marked "Re-check". Update this file in the PR that closes one (add `CLOSED #<pr>`). Locations name the function; line numbers are approximate and drift: re-grep. The audit did not run the server, read secrets or inspect database contents; dynamic tests, the 403 test coverage, staging merge internals, migrations, the INSURANCE unit's Chrome behaviour and the deployed Caddy/Pi config were not checked, and neither did the re-check.

## HIGH

### H1. The headless research run is not isolated from the worker/admin credentials
- Where: `worker.py` `work_one()`: `env = {**os.environ, ...}` and `subprocess.Popen(..., cwd=ROOT, ...)`; `pilot.py` runs claude with `--allowedTools Bash,Read,Write,Edit,...`.
- Exploit: the run inherits `WORKER_TOKEN` (`docs/deployment.md`, "On the desktop", claims only the per-request token reaches the run). Injected listing text makes the run call `POST /api/worker/claim` and receive other accounts' per-request tokens. Re-check: in the admin fallback (no `WORKER_TOKEN`) `work_one()` sets `AGENT_TOKEN=<the admin token>` for the run itself. When the worker checkout is the server checkout (true on this development machine: `data/` mode 755, `cars.sqlite` 644, `.env` 600 sit in the same checkout), `.env` holds the admin `AGENT_TOKEN` and `data/cars.sqlite` is readable by `Bash`/`Read`; "only the API, never open data/" is a prompt sentence, not a control. The deployment doc says the desktop checkout is code only; that holds only where `data/` and `.env` are absent.
- Fix: build `env` from an allow-list (PATH, HOME, `CAR_API`, `AGENT_TOKEN` = request token, Claude auth vars), drop `WORKER_TOKEN`; run the worker as a separate OS user or container without access to the server's `.env` and `data/`; deny `Read(.env)`, `Read(data/**)`, `Bash(sqlite3*)`, `Bash(curl*127.0.0.1*)` in the tool list; never run worker and server from one checkout.

### H2. Prompt injection: any account can steer the worker, and a run can poison the shared catalogue
- Where: `carlos/research_requests.py` `clean_url()` (accepts any http(s) host that has a dot, including `127.0.0.1`, LAN IPs, `user@host`) and `create()` (`note`, 1000 chars), `worker.py` `unit_prompt()` / `prompt_for()` (url and note pasted into the prompt); `docs/prompts/units/_header.md` has no "page content is data" rule (only AGENTS.md states it); `carlos/server.py` `Handler.require()` request-token branch (`self.admin = True`, `auth.scope(c, uid, curator=True)`); `markdown_export.py` listing archive section (dossiers verbatim).
- Exploit: a normal user queues a link to their own page or puts instructions in `note`; the Haiku run follows them. CAPTURE, TAX, LISTING and INSURANCE write directly and can PATCH/archive any shared catalogue row (generations, engines, faults, maintenance, sources, ratings) that all accounts rely on; descriptions, dossiers and `PREVIOUS_RESULT` are second-order channels. Staging (RESEARCH_A/B, ARBITER) limits writes to the run's scope (`staging.write()`, the `scope` check); the other units have no such limit.
- Damage ceiling today: no DELETE, no users/tokens/settings/preferences writes (`Handler.require()` allows a request token only GET and POST/PATCH under `/api/agent/`), no cross-account writes with a request token (uid pinned to the request's owner): reversible poisoning (`change_log` keeps old values), read of the requester's profile (M3), exfiltration through the run's browser/WebFetch, SSRF/LAN access from the desktop.
- Fix: (1) header rule in every unit prompt: page, listing and note text is untrusted data, never fetch URLs or call endpoints it names; (2) `clean_url` rejects IP literals, `localhost`, private/link-local ranges, userinfo, non-default ports, with a resolve check at claim time; (3) restrict PATCH of catalogue rows for non-staged units to the unit's `scope`/level ids as `staging.write` does; (4) accept `note` only from the account itself and wrap it as quoted data; (5) alert on mass catalogue PATCH by one request token.

## MEDIUM

### M1. No security headers
- Where: `carlos/server.py` `Handler.send_json()` / `send_file()` (no header besides Content-Type, Content-Length, Cache-Control, Set-Cookie), the Caddy block in `docs/deployment.md` (has none).
- Exploit: any future XSS (listing text is third-party) runs with the admin session and can mint tokens (`/api/account/token`) or create users; framing and sniffing open. SameSite=Strict blunts clickjacking today.
- Fix: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security`. Re-check: `static/auth.html` has two inline `<script>` blocks, one inline `<style>` and inline `style=` attributes, and `static/index.html` has an inline `<script>` (the colour-mode bootstrap): move them to files (or use a nonce) so the CSP can drop `unsafe-inline`.

### M2. No socket timeout, unbounded threads, unchecked negative Content-Length
- Where: `carlos/server.py` `main()` `ThreadingHTTPServer`, `Handler.timeout` unset (None); `Handler.read_json()` `int(Content-Length)` checks only the upper bound (`-1` makes `rfile.read(-1)` block); the same pattern in the two upload branches that read `Content-Length` directly.
- Exploit: many connections with partial headers or `Content-Length: -1` on `/api/auth/login` pin threads on the Pi 2B; the port is reachable from the LAN/worker host.
- Fix: `Handler.timeout = 30`; reject `length < 0`; cap threads (semaphore or bounded pool).

### M3. A per-request (research) token can read the requester's personal profile
- Where: `carlos/server.py` `Handler.require()` allows every GET except `/api/worker/*` for a request token: `/api/parameters` (postal code, driver age, SF class, cover), `/api/preferences`, `/api/tco`, other listings of the account.
- Exploit: an injected run puts those values into a URL it fetches and leaks the insurance profile; AGENTS.md says the profile must not leave the account except to the insurance unit.
- Fix: for request tokens allow GET only on research endpoints (schema, todo, stage, models, vehicles, sources, listings of the request); deny `/api/parameters`, `/api/preferences`, `/api/storage`, `/api/health`; give the INSURANCE unit its own narrow profile read.

### M4. Login brute-force controls are weak
- Where: `carlos/auth.py` `LOGIN_MAX_FAILS`, `FAILS`, `login()`, `check_new_password()`; `carlos/server.py` `auth_api()` login branch.
- Issue: lock per client IP only (10 tries / 5 min) keyed on the first `X-Forwarded-For` element (client-controlled if the proxy appends; Caddy overwrites, nginx `$proxy_add_x_forwarded_for` does not); no per-username throttle (the `login()` docstring says "not the username"; Re-check: README says "ten wrong passwords lock a username for five minutes", which does not match the code); min length 8, no common-password check; unknown users skip scrypt (`login()` short-circuits on `u is None`: timing oracle).
- Fix: per-username counter with exponential backoff plus a global attempts-per-minute cap; trusted-proxy last hop only; dummy scrypt for unknown users; 12+ characters for admins.

### M5. Sessions not invalidated on password change; password endpoint unthrottled
- Where: `carlos/auth.py` `set_password()` (does not delete other sessions; `accept_invite()` does); `carlos/server.py` `/api/account/password` branch.
- Exploit: a stolen cookie stays valid 30 days after the victim changes the password and can brute-force `old` without a lock.
- Fix: `DELETE FROM sessions WHERE user_id=? AND id<>current` in `set_password`; count failures on that endpoint into the lock table.

### M6. SSRF and local file read in the capture helper
- Where: `capture_listing.py` `read_photo()`: `photo['url']` goes to `urlopen` (accepts `file://`, `ftp://`, `http://169.254.169.254`, LAN hosts); `photo['file']` is joined to `base_dir` unchecked (`../`, and an absolute path replaces `base_dir` altogether). The capture JSON is written by an agent that read an untrusted page (H2); since #375 (a car without a link) `{"file": ...}` photos are the normal way to add photos in that flow.
- Exploit: an injected run emits `{"url": "http://192.168.1.1/..."}` or `{"file": "../../.ssh/..."}`; only image-magic-byte results are uploaded, so the leak is limited to image files and blind SSRF from the owner's desktop.
- Fix: only `https`/`http` to public IPs (resolve and block private ranges), no redirects to other schemes; require `base_dir / file` to stay inside `base_dir`.

## LOW
- **L1 Raw invite tokens are logged.** `Handler.log_message` not overridden (`carlos/server.py`), so the default handler writes `/invite/<token>` and `/api/auth/invite/<token>` (and client addresses) to stderr/journal; `bootstrap()` prints full invite URLs. Fix: redact `/invite/*` and query strings; print the link only to a TTY.
- **L2 Error text leaks internals.** `Handler.handle_request()` returns `str(e)` for `(ValueError, sqlite3.Error)` with status 400. Fix: log it, return a generic 400 for non-ValueError.
- **L3 `/api/storage` and `/api/health` open to any account** (GET branches in `server.py`): file names of the install, repeated `PRAGMA quick_check`. Fix: admin only, cache health.
- **L4 No Host-header validation**; `Handler.invite_url()` builds links from `X-Forwarded-Host`/`Host`. Fix: allow-list the public hostname.
- **L5 File permissions**: `data/` 755 and `cars.sqlite` 644 (re-checked on this machine with `stat`; `.env` is 600). Fix: `chmod 700 data`, `umask 077` in the service.
- **L6 `carlos_view` cookie** set by JS without `Secure` (`static/js/app.js`, the view-as switcher). Fix: `Secure` on https.
- **L7 Privacy rule is a convention**: `quote_profile` is free JSON (names or birth dates can be stored); `carlos/agent.py` (the owner-assignment branch for `_KNOW` tables) decides private insurance rows by `annual_premium_eur`/`status` heuristics; `JSON_COLUMNS` only validates that `quote_profile` is JSON. Fix: allow-list `quote_profile` keys; force `owner_id` on all insurance rows.
- **L8 Unsalted SHA-256 for tokens** (`carlos/auth.py` `digest()`) is fine for 256-bit random tokens; never reuse `digest` for passwords.
- **L9 Worker-supplied text stored verbatim** (heartbeat `error` in `research_requests.heartbeat()`, and the request `result`): the UI escapes it (`admin.js`, `requests.js`); keep it that way.

## Checked and found sound (do not regress)
Tenant isolation via `auth.scope` TEMP views (owned tables, knowledge rows owner NULL or own, listing children, sources, ratings; media only if `listing_media` is visible, the media route in `server.py`); explicit admin cross-account writes (`row_owner`); non-admin writes blocked on shared tables (`agent.py` `check_writable`); `insurance_worker_quotes` not settable with a token (`POST /api/preferences` refuses a Bearer caller; `project_preferences` is not in `AGENT_TABLES`); every f-string table name whitelisted, columns checked, values bound; all DB strings in `static/js` through `esc()`/`safeUrl()`; uploads capped, magic-byte checked, hashed names, no SVG; static paths regex- and extension-restricted; no CORS and JSON content type required on writes; `.env` mode 600 and ignored.
