# API

Every route the server serves, one row each. Base URL `http://127.0.0.1:8000` (behind the reverse proxy, the same paths). The index below has 72 endpoints (method + path); each appears once. Route sources: `carlos/server.py` (`handle_request`, `api`, `auth_api`, `admin_api`, `worker_api`, `ui_write`), `carlos/auth.py`, `carlos/agent.py`, `carlos/research_requests.py`. "Called by" was checked against `static/js` (grep); `none` means no UI page calls it (agents, the desktop worker or the admin tooling do).

## Conventions
- Bodies are JSON objects sent with `Content-Type: application/json` (otherwise 415), at most 1,000,000 bytes (413). Image uploads send the bytes with `Content-Type: image/jpeg`, `image/png` or `image/webp`, at most 1,500,000 bytes.
- "no body" means the handler reads none; a request body is ignored.
- Types: `int`, `number` (finite, never a boolean), `text` (a string; an empty string is NULL for table columns), `date` (ISO `YYYY-MM-DD`), `0|1` (flag).
- Null means unknown, never zero.
- The agent write rules and the controlled codes are in `GET /api/agent/schema` (`writable_tables`, `code_formats`, `fixed_codes`, `fault_components`, `research_contract`) and in `AGENTS.md`.
- Every response carries `Content-Security-Policy` (scripts only from `/static/`, no framing), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin` and, behind HTTPS, `Strict-Transport-Security`. A client that stalls for 30 seconds is dropped.

## Auth model

Each request is checked in this order: the `Host` header (must be one of `CARLOS_HOSTS`, else 400), the credential (cookie or bearer token), then the route's own rule. A route that needs a login answers 401 before routing, so an unknown `/api/` path is 401 for an anonymous caller and 404 for a signed-in one (under `/api/auth/` it is 404 for anyone).

| Caller | Credential | Reaches | Does not reach |
|---|---|---|---|
| **anonymous** | none | the pages, `/static/`, the sign-in, invite and logout routes | everything else (401) |
| **login session** | cookie `carlos_session`, set by `POST /api/auth/login` (HttpOnly, SameSite=Strict, Secure behind HTTPS, 30 days, stored as a SHA-256 digest) | any route for its own account; the catalogue rows linked to its listings (`catalogue_links`) | other accounts' rows (they look missing: 404), admin routes (401 `Admin only`), `/api/storage` and `/api/health` (403) |
| **admin session** | the same cookie, of an admin account | the login session's routes plus `/api/admin/*`, `/api/storage`, `/api/health`; the shared catalogue for research writes | nothing further. With the view cookie `carlos_view=<user id>` (set by the header switcher) it acts as that account: reads, `/api/agent/` and `/api/ui/` writes and research requests only; passwords, tokens and settings are 403; `/api/admin/` ignores the cookie. A non-admin's view cookie is ignored |
| **agent token** (admin account) | `Authorization: Bearer <token>`; issued by `POST /api/account/token` (admin only), stored as a digest, shown once; a new one replaces it; ends when the account is deactivated | the agent write and read routes and the admin routes, as its own account and as curator of the shared catalogue | a non-admin account's token is 403 (`Agent tokens work for admin accounts only`). Never given to a worker |
| **admin agent token** | the agent token of an admin account, used across accounts | with the header `X-Carlos-Account: <user id>`: reads, `/api/agent/` writes and research requests for that account (`requested_by` records the admin); other writes with the header are 403. Without the header a PATCH or DELETE of another account's row by its id is done as that account, and `GET /api/admin/data/<table>` lists every account's rows (issue #143) | `/api/account/password`, `/api/account/token` and settings writes made while acting for an account |
| **request token** | `request_token` returned once by `POST /api/worker/claim` for one RUNNING request; bound to that request; ends when it finishes, is re-queued or fails, and after 3 hours (then 401) | the research list of reads (`/api/agent/todo\|schema\|stage\|disputes`, `/api/todo`, `/api/models`, `/api/vehicles`, `/api/generations`, `/api/engines`, `/api/sources`, `/api/listings`, `/api/tco`, `/api/preferences`); `POST` and `PATCH` under `/api/agent/` for the requester's account (curator: catalogue rows go to the shared catalogue, limited per unit by `carlos/staging.py` and `carlos/research_units.py`); `POST /api/agent/media/<id>` for its own listing | no admin, settings, queue or `/api/ui/` routes, no deletes, no `X-Carlos-Account`. The profile is cut out of the reads: `/api/tco` and `/api/listings` leave out `parameters` postal code, purchase mode, ranking answers and weights; `/api/preferences` lists only the DIY, driving, search radius, preferred engine, current car and onboarding keys |
| **worker token** | `Authorization: Bearer <token>` created by an admin (`POST /api/admin/workers`), shown once, stored as a digest; deactivating the worker or issuing a new token ends it | `POST /api/worker/heartbeat`, `POST /api/worker/claim`, and `POST /api/worker/requests/<id>` for the request it claimed | everything else (403 `A worker token only sends heartbeats, claims and finishes requests`) |

Account isolation: every connection is scoped to one account (`auth.scope`). Reads see the account's rows and the shared catalogue rows linked to its listings; a curator scope (admin or request token) sees the whole catalogue. Shared catalogue rows (`owner_id` NULL) are written by curators only. Insurance premiums and `USER DATA` figures stay private to their account.

Cross-site protection: JSON endpoints require `application/json`, which forces a CORS preflight, and the session cookie is SameSite=Strict.

## Errors

Error bodies are JSON `{"error": "<text>"}`, except where a row says otherwise. Texts are English. A browser (cookie) gets a generic text for database errors (`The request could not be completed`); an agent token gets the exact SQLite text.

| Status | Body | Causes |
|---|---|---|
| 400 | `{"error"}` | validation (`ValueError`): unknown parameter or column, a value off its code list or scale, a missing required field, a body that is not a JSON object, malformed JSON, a negative `Content-Length`, an unknown `Host` header (`Unknown host name`); SQLite CHECK, foreign-key or UNIQUE violation; deleting a row that is still referenced |
| 401 | `{"error"}` | `Login required` (no or ended session); `Invalid token` (unknown, deactivated or stale request token, or an inactive worker); `Admin only` (a non-admin session on `/api/admin/`); `Wrong current password`; a login that failed (the login route answers 401 `Wrong username or password`) |
| 403 | `{"error"}` | the credential is valid but the action is not allowed for it (see Auth model): a non-admin agent token, a worker token outside its routes, a request token outside its scope, writes to research, listing or retired tables, view-as restrictions, `/api/storage` and `/api/health` for a non-admin, a photo removal made with a bearer token, a permission not granted (ENGINESCOPE) |
| 404 | `{"error"}` | `Endpoint not found` (unknown route); `<table> id=<n> does not exist` (also for another account's row); `Listing not found`; `Vehicle not found`; an invalid or expired invite; `No such user`; `No such table`; `No such account`; `Unsupported viewing-mode request`. Static files, photos and the pages answer a plain HTML 404 from the HTTP server |
| 405 | `{"error"}` | the path exists but not for this method, with the form to use (e.g. `PATCH /api/agent/<table>/<id>` for an update, `DELETE /api/agent/<table>/<id>` needs an id) |
| 409 | `{"error", "conflict": [...]}` | the duplicate guard for `faults`, `recalls` and `maintenance_items`: a similar row already applies to this level (`conflict` lists its id, level, part and component); resend with `distinct_of` and a reason in `notes`, or PATCH the row. A staged finding with the same component: 409 `distinct_of`. A photo that was removed from the dossier (`POST /api/ui/media/<id>`) |
| 413 | `{"error"}` | a JSON body over 1,000,000 bytes; an image over 1,500,000 bytes |
| 415 | `{"error"}` | a JSON endpoint without `application/json`; a media endpoint without `image/*`; an image that is not JPEG, PNG or WebP (400 from the parser: see the media rows) |
| 429 | `{"error"}` | login locked: 10 wrong passwords from one client address or 20 for one username, for 5 minutes (the text stays `Wrong username or password`); password change locked after 10 wrong current passwords, for 5 minutes (`Too many wrong passwords; try again in a few minutes`) |
| 501 | HTML | a method the server does not implement (PUT, OPTIONS, HEAD), from the HTTP server |
| 503 | `{"error": "overloaded"}` with `Retry-After: 5` | more than 32 connections served at once |
| 507 | `{"error"}` | the photo storage budget (900 MB of 1024) is exhausted |

## Endpoint index

### Pages and files (anonymous)

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `GET /` | anonymous | none | HTML: the app shell (`index.html`); the page then checks the session with `GET /api/auth/me` | none | browser (app) |
| `GET /index.html` | anonymous | none | the same HTML as `GET /` | none | browser |
| `GET /login` | anonymous | none | HTML: the sign-in page (`auth.html`) | none | browser |
| `GET /invite/<token>` | anonymous | none | HTML: the sign-in page in invite mode; an invalid token shows the page and the API answers 404 | none | browser (invite link) |
| `GET /privacy` | anonymous | none | HTML: the privacy notice (`privacy.html`) | none | browser |
| `GET /impressum` | anonymous | none | HTML: the imprint (from the configuration) | none | browser |
| `GET /static/<path>` | anonymous | none | the file from `static/` (`.html .js .css .json .svg .png .ico .webmanifest .woff2`), `Cache-Control: no-cache`, ETag, 304 when unchanged | 404 (missing file or other suffix) | browser (every page) |
| `GET /media/<listing id>/<sha256>.<jpg\|png\|webp>` | login session or agent token | none | the archived photo, `Cache-Control: private, max-age=31536000, immutable`; only photos of this account that are not removed | 404 (plain HTML): not this account's, removed, or missing; 403 for a request token | dossier (`<img>`) |

### Sign-in and accounts

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `GET /api/auth/me` | login session (anonymous: 401) | none | the account: `id`, `username`, `role` (`admin` or `user`), `is_active`, `has_password`, `has_token`, `created_at` | 401 `Login required` | app.js (shell) |
| `POST /api/auth/login` | anonymous | `username` text, `password` text | the account (as `GET /api/auth/me`) and `Set-Cookie: carlos_session` | 401 wrong username or password; 429 locked (see Errors); 415 | auth.js (`/login`) |
| `POST /api/auth/logout` | anonymous or login session | none | `{ok: true}`; ends the session and clears the cookie | none | app.js (logout) |
| `GET /api/auth/invite/<token>` | anonymous | none | `{username}` of a valid, unused invite (valid 72 hours) | 404 `Invite link invalid or expired` | auth.js (`/invite/<token>`) |
| `POST /api/auth/invite/<token>` | anonymous | `password` text: 8 to 200 characters (12 for an admin account), not a common password | 201: the account and `Set-Cookie`; burns the invite and ends the account's other sessions | 400 password rules; 404 invite invalid or expired (checked after the password); 415 | auth.js (`/invite/<token>`) |
| `POST /api/account/password` | login session | `old` text, `new` text (same rules as above) | `{ok: true}`; ends the account's other sessions, keeps this one | 401 `Wrong current password`; 429 locked; 400 new password rules | settings.js (password) |
| `GET /api/account/export` | login session | none | `{account: {id, username, role, created_at}, exported_at, note, tables: {name: rows}}`: the account's own rows; no hashes, sessions, change log or worker rows; photos by file name only | 403 for a request token | settings.js (Download my data) |
| `POST /api/account/token` | admin session or agent token (admin account) | none | 201 `{token, note}`; the token is shown once and the previous one stops working | 403 for a non-admin account or while acting for another account | settings.js (agent token) |

### Admin (admin session or agent token of an admin account)

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `GET /api/admin/users` | admin session, agent token | none | array of accounts, as `GET /api/auth/me` returns each | 401 `Admin only` (non-admin session); 403 request token | app.js (accounts), admin.js |
| `POST /api/admin/users` | admin | `username` text, 2 to 40 characters of letters, digits, `.`, `-`, `_`; `role` admin or user (default user) | 201 `{id, username, invite}`; `invite` is the one-time sign-up URL (72 hours, host from `X-Forwarded-Host`) | 400 username or role invalid, or taken | admin.js |
| `POST /api/admin/users/<id>/invite` | admin | none | 201 `{invite}`; replaces the account's unused invites (password reset) | 404 `No such user` | admin.js |
| `PATCH /api/admin/users/<id>` | admin | `is_active` 0\|1 and/or `role` admin or user; no other keys | the account | 400 deactivating or demoting your own account; invalid value or key; 404 `No such user` | admin.js |
| `DELETE /api/admin/users/<id>` | admin | `username` text, typed exactly | `{id, username, export, deleted}`: `export` is `exports/account-<id>-<time>.json` (written first, mode 0600), `deleted` the rows removed per table; the rows, sessions, photos and dossiers go in one transaction | 404 `No such account`; 400 your own account, a username that does not match, or another account's row would be left pointing at a deleted row (nothing changed) | admin.js (erase) |
| `GET /api/admin/data/<table>` | admin session, agent token | query `owner_id` (int, filters account-owned tables), `limit` (default 1000, max 5000) | array of rows, newest first. Tables: the agent tables, the retired tables (read only), `users` (no hashes), `catalogue_links`, `research_requests`, `workers` (no token hash), `change_log` | 404 `No such table` | none (admin tooling) |
| `GET /api/admin/workers` | admin | none | array of workers: `id`, `name`, `is_active`, `created_at`, `last_seen`, `state`, `request_id`, `last_error`, `last_error_at`, `url`, `listing_id`, `unit`, `parent_id`, `username` (of the request), `status`: `idle`, `working`, `error`, `down` (no heartbeat for 180 seconds) or `deactivated` | 401 or 403 as for the other admin routes | admin.js |
| `POST /api/admin/workers` | admin | `name` text, 2 to 40 characters of letters, digits, `.`, `-`, `_` | 201 `{id, token, note}`; the token is shown once | 400 name invalid | admin.js |
| `POST /api/admin/workers/<id>/token` | admin | none | `{id, token, note}`; the previous token stops working | 400 `No such worker` | admin.js |
| `PATCH /api/admin/workers/<id>` | admin | `is_active` 0\|1 only | the worker (as in the list above); a deactivated worker's token stops (401) | 400 other keys, or no such worker | admin.js |
| `GET /api/admin/changes` | admin | query `limit` (default 50, max 200), `before` (a change id, for the next page) | array, newest first: `id`, `changed_at`, `table_name`, `row_id`, `action`, `writer` (username), `account` (owner of the row or its listing; empty for the catalogue) | 401 or 403 as for the other admin routes | admin.js |
| `GET /api/admin/requests` | admin | none | the queue, newest first, last 500 parents: the request fields of `GET /api/requests` plus `username` and `children` (the units: `unit`, `status`, `attempts`, `missing`, `shared_id`, `detail`) | 401 or 403 | admin.js |

### Reads (login session, agent token, request token where marked)

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `GET /api/parameters` | login session, agent token (request token: 403) | none | the account's parameters row: `annual_km`, `ownership_years`, `fuel_price_eur_l`, `fuel_price_date`, `diesel_price_eur_l`, `diesel_price_date`, `budget_ideal_eur`, `budget_max_eur`, `electricity_home_eur_kwh`, `electricity_public_eur_kwh`, `electricity_home_date`, `electricity_public_date`, `home_charging`, `home_charging_pct`, `wallbox_cost_eur`, `exclude_over_max`, `purchase_mode`, `postal_code`, and the other columns of `project_parameters` | none | app.js (shell), settings.js, ranking.js, start.js |
| `GET /api/preferences` | login session, agent token, request token (its keys only) | none | array of `{preference_key, preference_value, owner_id}`, sorted by key; the keys the setup wizard writes are listed in `docs/data-model.md` | none | app.js (shell), start.js (wizard) |
| `GET /api/tco` | login session, agent token, request token (profile cut out) | query: any of `annual_km`, `ownership_years`, `fuel_price_eur_l`, `diesel_price_eur_l`, `budget_ideal_eur`, `budget_max_eur`, `electricity_home_eur_kwh`, `electricity_public_eur_kwh`, `home_charging_pct`, `wallbox_cost_eur`: a preview, validated and never saved | `{parameters, preview` (true when a query value was used)`, components` (the eight TCO keys), `listings[]`, `budget`, `ranking` (`answers`, `answered`, `weights`, `derived_weights`, `manual`, `criteria`, `tasks`, `questions`, `candidates`), `fuel_price_stale`}. Each listing: `id`, `components`, `known_cost_subtotal`, `known_cost_per_month`, `period_months`, `tco_complete`, `missing_components`, `metrics`, `score`, `rank`, `coverage`, `score_parts`, `explain`, `research` (contract items with grade), `reliability_sources` (`score`, `coverage`, `present`, `of`, `missing`, `slots` ENGINE, HU, BREAKDOWNS with `points` and their `sources`), `breakeven`, `budget_status`, `price_history`, `price_change`, `stale`, `cover`, `photo_count`, `inspection_counts`, `delta_vs_reference`, `initial_outlay`, `cost_detail` | 400 a preview value invalid | app.js (Compare, Ranking), settings.js (preview) |
| `GET /api/listings` | as `GET /api/tco` | as `GET /api/tco` | as `GET /api/tco` (alias of that route) | as `GET /api/tco` | none |
| `GET /api/listings/<id>` | login session, agent token, request token | none | one listing: everything of `/api/tco` for it plus `valuations`, `unit_costs`, `maintenance_resets`, `inspection`, `events`, `snapshots`, `media`, the resolved knowledge rows with their `level`, `fault_plan` (expected cost per fault), `maintenance_plan` (occurrences and cost per job), `reliability`, `insurance`, `tax`, `observations`, `tyres`, `engine_row`, `generation_row`, `sources`, `research_levels` (per level: `state`, `missing`, `accepted`, `items`) | 404 `Listing not found` (also another account's) | dossier.js |
| `GET /api/models` | login session, agent token, request token | none | the tree `makes[]`, `models[]`, `generations[]`, `engines[]`, `variants[]`; each variant with its `listings`, the count of knowledge rows per table and `research` (per level: `incomplete`, `researched` or `verified`) | none | models.js |
| `GET /api/vehicles` | login session, agent token, request token | none | array of the account's variants: all `vehicles` columns plus `make`, `model`, `generation`, `engine_code`, `fuel_type`, `displacement_cc`, `power_ps` | none | none |
| `GET /api/vehicles/<id>` | login session, agent token, request token | none | one variant: its fields, `engine_row`, `generation_row`, every knowledge table with its `level`, `siblings` (variants sharing the engine or generation), `listings`, `sources`, `research` (per level: `state`, `missing`, `accepted`, graded `items`) | 404 `Vehicle not found` | models.js |
| `GET /api/generations` | login session, agent token, request token | none | array of the account's generations (own and shared), ordered by make, model, start year | none | none |
| `GET /api/engines` | login session, agent token, request token | none | array of the account's engines (own and shared) | none | none |
| `GET /api/sources` | login session, agent token, request token | none | array of `sources` rows the account can see (`quality` A to D, `supports`, `limitations`, `url`, `accessed_date`) | none | app.js (shell, Sources page) |
| `GET /api/ranking` | login session, agent token (request token: 403) | none | `answers`, `answered`, `weights`, `derived_weights`, `manual`, `criteria`, `tasks`, `questions` | none | none (Ranking reads `/api/tco`) |
| `GET /api/todo` | login session, agent token, request token (a staged run gets its own staging's gaps) | none | `account` (setup, ranking choices, fuel price age), `listings[]` (`listing_id`, `todo`), `models[]` (`vehicle_id`, `todo`: missing contract items with engine and generation), `catalogue[]` (each generation, engine and variant: `state`, `missing`, `accepted`); English texts | none | app.js (shell), models.js, dossier.js |
| `GET /api/agent/todo` | as `GET /api/todo` | none | as `GET /api/todo` (alias) | as `GET /api/todo` | none |
| `GET /api/agent/stage` | request token of a staged run (RESEARCH_A, RESEARCH_B, ARBITER); others 403 | none | `request_id`, `run` (A, B or C), `scope`, `findings[]` (negative `id`, `kind`, `op`, `table`, `target_id`), `counts`, `missing` (the contract graded with the findings applied in a rolled-back transaction) | 403 for other callers | none |
| `GET /api/agent/disputes` | request token of an ARBITER run; others 403 | none | the disputes of the parent (at most 25): `question`, `diffs`, both sides' payload and sources | 403 `Only the ARBITER run reads the disputes` | none |
| `GET /api/storage` | admin session, agent token | none | `total_bytes`, `limit_bytes`, `budget_bytes`, `by_item` (bytes per folder or file); cached 60 seconds | 403 `Admin only` for a non-admin or a request token | app.js (shell, admin only; errors ignored) |
| `GET /api/health` | admin session, agent token | none | `integrity` (`PRAGMA quick_check`), `schema_version`, `listings` (count), `storage_ratio` (used / limit) | 403 `Admin only` | none |
| `GET /api/agent/schema` | login session, agent token, request token | none | `writable_tables` (table: column: `[type, not_null]`), `source_required_on_insert`, `code_formats`, `fixed_codes`, `scoped_tables`, `scope_columns`, `rules`, `research_contract` (version, items with level, kind, accepted check results, minimum quality, `since`), `fault_components` (per part: code and what it covers) | none | none (agents) |
| `GET /api/ui/check` | login session, agent token | none | `{ok: true}` | none | none (health probe) |
| `GET /api/requests` | login session, agent token (request token: 403) | none | the account's own parent requests, newest first: `id`, `owner_id`, `url`, `note`, `status` (QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED), `requested_at`, `claimed_at`, `finished_at`, `worker`, `listing_id`, `result`, `requested_by`, `kind`, `flag_id`, `attempts`, `missing`, `parent_id`, `unit`, `level_id`, `shared_id`, `scope`, and `parts[]` (units in stage order: `unit`, `status`, `attempts`, `missing`, `shared_id`, `detail`) | none | requests.js (Compare) |

### Agent writes (`/api/agent/`)

Research runs (RESEARCH_A, RESEARCH_B, ARBITER) write to staging, not to the catalogue: their POST and PATCH answer a negative `id` with `staged: true`, and their JSON bodies only (an image body is 415). The listing and insurance tables are refused for a request token outside its unit (403).

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `POST /api/agent/<table>` | agent token, admin agent token, request token (its unit's tables) | one row of `<table>`, the columns of `writable_tables` in `GET /api/agent/schema`: numbers as numbers, text as text, `''` as NULL; `owner_id` is refused. Required: `source_id` for the tables in `source_required_on_insert`; exactly one level column for the scoped tables; `component_code` for `faults`; `distinct_of` (ids) and `notes` when the duplicate guard fires | 201 `{table, id}`; 200 `{table, id, existing: true}` when the insert reuses a catalogue variant (same HSN/TSN), generation or engine; staged runs: `{id: <negative>, staged: true, ...}` | 400 validation; 403 table not writable for the caller (research tables for non-admin tokens, retired tables, listings and sources of another unit, ENGINESCOPE without permission); 404 unknown table; 409 duplicate guard; 415 | none (agents, worker) |
| `PATCH /api/agent/<table>/<id>` | as `POST /api/agent/<table>` | the changed columns only; `{"archived": 0\|1}` on archivable tables (1 hides the row from every read and calculation; 0 restores it); `source_id` cannot be cleared | `{table, id}` (200) | as `POST`; 404 `<table> id=<n> does not exist`; 405 without an id | none (agents, worker) |
| `DELETE /api/agent/<table>/<id>` | agent token, admin agent token (request token: 403 for research and listing tables) | no body | `{table, id, deleted: true, removed_children: {table: rows}}`; a listing goes with its own rows, photo files and folders | 400 the row is still referenced (the message names the referencing tables; nothing deleted); 404; 405 without an id; 403. Agents call it only after the owner confirmed that exact deletion (`AGENTS.md`) | none |
| `POST /api/agent/merge` | request token of a MERGE unit only | no body | `counts`, `written`, `skipped` (a 409 against a real row: "exists as faults #N"), `disagreements` (unresolved material disputes), `orphans` (a shell engine relinked to the catalogue one); idempotent | 403 for other callers; 400 nothing to merge (the two runs were not compared) | none (worker) |
| `PATCH /api/agent/disputes/<id>` | request token of an ARBITER run | `verdict` A, B, BOTH, NEITHER or OWN; `reason` text (required); `source_id` (a staged source of the run, negative, or an existing one); `finding` (negative id; with OWN only) | the answer of `staging.answer_dispute` | 403 not ARBITER; 404 dispute not of this request; 400 verdict or reason invalid; 405 other methods | none (worker) |
| `POST /api/agent/media/<listing id>` | agent token, admin agent token, request token (its own listing) | the image bytes; query `url` (the original photo URL) and `snapshot_id` (a capture of this listing). Metadata (GPS, device, time, XMP, comments) is removed; JPEG orientation kept | 201 `{table: "listing_media", id, created: true}`; 200 with `created: false` when the same image (SHA-256) is already in the listing | 415 not an image; 413 over 1,500,000 bytes; 400 empty, not JPEG, PNG or WebP, undecodable, or a snapshot of another listing; 404 listing; 403 another listing; 507 storage budget | none (capture_listing.py) |
| `POST /api/agent/export-md` | agent token, admin agent token, request token (not a staged run) | no body | `{written: [file names]}`: the account's dossiers regenerated | 403 for a staged run | none |

### Owner actions and viewing mode (`/api/ui/`, login session)

The phone's viewing mode and the dossier's own writes. Each one goes through the same rules as the agent API and writes its own `change_log` entry.

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `PATCH /api/ui/inspection_items/<id>` | login session, agent token | `status` PENDING, OK, PROBLEM or N/A; `notes` text (other keys are ignored); the check date is set to today, cleared on PENDING | `{table: "inspection_items", id}` | 400 status not in the list; 404 not found | dossier.js (checklist) |
| `POST /api/ui/inspection_items` | login session | `listing_id` int, `item` text | 201 `{table, id}` | 400 (including a car that is not in this account) | dossier.js (checklist, add item) |
| `POST /api/ui/listing_events` | login session | `listing_id` int, `text` text (kept verbatim, kind `viewing`, source: the account's user-provided data) | 201 `{table: "listing_events", id}` | 400 | dossier.js (log note) |
| `POST /api/ui/media/<listing id>` | login session | image bytes (as the agent media route); the photo joins the dossier after a short delay (export later) | 201 `{table: "listing_media", id, created}`; `created: false` when the same image is already in the listing | 409 `This photo was removed from the dossier: restore it under Removed photos first`; 415; 413; 400 not an image | dossier.js (photo upload) |
| `PATCH /api/ui/photo/<id>` | login session only (a bearer token: 403) | `archived` 0\|1 (1 hides the photo from the listing, its cover, its count and `/media/`; the file stays; 0 restores it) | `{table: "listing_media", id, archived}` | 400 other keys; 404 another account's photo; 403 bearer token | dossier.js (Removed photos) |
| `DELETE /api/ui/photo/<id>` | login session only (a bearer token: 403) | `id` (the same id) and `confirm: true`; only an archived photo | `{table: "listing_media", id, deleted: true}`; the row and its file are removed for good | 400 not archived, or no confirmation; 404; 403 bearer token | dossier.js (Removed photos) |
| `PATCH /api/ui/listing_history/<id>` | login session | `owner_probability` number 0 to 1 or null, `owner_reason` text up to 300 characters (required with a probability; kept only with one); null clears both | `{table: "listing_history", id}`; this car only, the shared fault row is unchanged | 400 a value invalid, or the row is not a DONE repair of a fault; 404 not found | none (no control in the UI yet) |
| `POST /api/ui/listing_quotes` | login session | `listing_id` int (a car of this account that is for sale), `premium_eur` number above 0, `period` year or month (default year; a monthly figure is multiplied by 12), optional `insurer` and `tariff` (text up to 80), `quote_date` date (default today; not in the future, at most 60 days old), `cover` Haftpflicht, Teilkasko or Vollkasko, `deductible_eur` 0 to 10000, `sf_class` text up to 8 | 201 `{table: "listing_quotes", id}`; stored as `QUOTE` from the account's user-data source (quality D) with a `user_data` log entry; expires after 60 days | 400 the reference car, another account's car, a value invalid, more than 20000 EUR a year, or 30 quotes already on the car | dossier.js (insurance quote) |
| `POST /api/ui/decision/<listing id>` | login session | `decision` shortlist, viewing, reject or reset; `reason` text up to 300 characters (for reject) | `{table: "decision", id}` (the `decision` log entry); `reject` archives the car (WITHDRAWN, out of the ranking); `reset` brings it back under review | 400 decision not in the list, or the reference car; 404 | dossier.js (decision) |

### Profile

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `POST /api/parameters` | login session, agent token (request token: 403) | any subset of the parameters: numbers `annual_km` (int above 0), `ownership_years` (int above 0), `fuel_price_eur_l` (above 0), `diesel_price_eur_l`, `budget_ideal_eur`, `budget_max_eur`, `electricity_home_eur_kwh`, `electricity_public_eur_kwh`, `home_charging_pct` (int 0 to 100), `wallbox_cost_eur`, `exclude_over_max` (0 or 1); dates `fuel_price_date`, `diesel_price_date`, `electricity_home_date`, `electricity_public_date` (ISO); text `postal_code`, `purchase_mode`, `home_charging` (none, socket, wallbox or wallbox_planned); `ranking_answers` (object: question to answer id); `ranking_weights` (object: criterion to int 0 to 5, or null to use the answers) | the parameters row (as `GET /api/parameters`) | 400 unknown parameter (for example `acquisition_mode`), value or code invalid, `budget_ideal_eur` above `budget_max_eur`; 415 | app.js (ranking), settings.js, ranking.js, start.js (wizard) |
| `POST /api/preferences` | login session, agent token (request token: 403) | an object of `preference_key` to value; keys snake_case, at most 50 per call; values up to 1000 characters; `null` or `''` removes the key | all of the account's preference rows (as `GET /api/preferences`) | 400 keys not snake_case, more than 50 keys, or `insurance_worker_quotes` set (see Removed endpoints) | settings.js, start.js (wizard) |

### Research requests (`/api/requests`)

An account asks for a listing to be researched; the shared worker does it and writes the car into that account (Auth model: request token). A listing request is split into units (CAPTURE, then RESEARCH_A and RESEARCH_B, ARBITER, MERGE, TAX, LISTING, items per unit in `carlos/research_units.py`; the single-run units VARIANT, GENERATION, GEN_MAINTENANCE, ENGINE and GEARBOX, and a request without a unit, are refused at the claim with their reason, owner decision 2026-11-22); a unit is QUEUED, RUNNING, WAITING (`shared_id`: an identical open unit of another request), DONE, SKIPPED (already researched), FAILED or CANCELLED.

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `POST /api/requests` | login session, agent token (admin agent token: queues for an account with `X-Carlos-Account`; `requested_by` records the admin) | `url` text: an `http(s)` link of at most 500 characters, or `carlos://listing/<id>` to re-research one of the account's own cars (no ad, or offline); `note` text up to 1000 characters | 201: the new request (the `GET /api/requests` fields with `parts`), status QUEUED | 400 url invalid or not a public address; the same link already waits; at most 5 requests QUEUED, RUNNING or WAITING per account; unknown listing; 403 request token | requests.js (Compare, request form) |
| `PATCH /api/requests/<id>` | login session, agent token (admin agent token: for an account) | `{"status": "CANCELLED"}` only | `{id, status: "CANCELLED"}` | 400 another body, or not one of the account's own QUEUED requests | requests.js (cancel) |

### Research worker (`/api/worker/`)

The registered desktop worker (`worker.py`, its own worker token) and admin tokens. Other callers: 403.

| Method and path | Auth | Request | Response | Errors | Called by |
|---|---|---|---|---|---|
| `POST /api/worker/heartbeat` | worker token | `state` idle, working or error (default idle); `error` text (the last 2000 characters) | `{ok: true}`; the worker's `last_seen` is updated (down after 180 seconds without one) | 400 state invalid | none (worker.py) |
| `POST /api/worker/claim` | worker token (body `{}`), or admin agent token (body `{"worker": "<name>"}`) | see left | `{request: null}` when the queue is empty, else `{request: {...}}` with the request (now RUNNING), `request_token` (for that run only), `unit`, `level_id`, `parent_id`, `listing_id`, `missing`, `attempts`. A request this worker still holds (interrupted run) goes back to QUEUED first; a RUNNING request older than 3 hours is handed out again | 403 a non-admin token or session; 401 a deactivated worker | none (worker.py) |
| `POST /api/worker/requests/<id>` | worker token (only the request it claimed), or admin agent token | `status` DONE, FAILED or QUEUED (release: unfinished, e.g. a usage limit); `listing_id` int (DONE: a listing of the requester); `result` text (the last 4000 characters); `usage` object of numbers (summed over the attempts) | the finished request row. DONE is re-graded by the server against the research contract: missing items put it back in the queue (`attempts` plus 1, the ids in `missing`); after 3 attempts it is FAILED | 403 not the claimed request; 400 status invalid, `listing_id` missing for DONE, or the request is not RUNNING | none (worker.py) |

## Removed and retired endpoints and parameters

- **Leases.** No route serves a lease and no capture writes lease fields (`capture_listing.py` refuses them). The legacy `lease_*` columns of `listings` remain in the schema and are still accepted by `POST` and `PATCH /api/agent/listings`, within their code lists (`GET /api/agent/schema`). Dropping them is a separate decision (not made here).
- **Acquisition mode.** No route. The `acquisition_mode` and `lease_rate_max_eur` columns of `project_parameters` (schema only) are not accepted: `POST /api/parameters` answers 400 `Unknown parameter`. `purchase_mode` stays a text parameter (the UI offers cash and financing; the server does not validate the value).
- **Insurance worker.** No worker route. `POST /api/preferences` answers 400 for `insurance_worker_quotes` set to a value (`Worker insurance quotes were removed`); clearing it (`null` or `''`) is accepted. Quotes are entered by hand with `POST /api/ui/listing_quotes`.
- **Retired tables** `reliability_items`, `repair_risks`, `review_flags`, `flag_reviews`: no read route (`GET /api/agent/<table>` answers 404), not in `GET /api/agent/schema`; admins still read them in `GET /api/admin/data/<table>` (200). Writes answer 403 except `PATCH` with `{"archived": 0|1}` and the owner-confirmed `DELETE`. Faults, recalls and source ratings replace them.

## Known gap

A research run's `DELETE /api/agent/<table>` without an id is staged as an insert (the staged branch in `carlos/server.py` checks only PATCH), where this document says 405. Not fixed in this change.

## Side effects of writes

Every write is recorded in `change_log` (with the writer's account and, for a research run, `request_id`) and regenerates the dossiers of the account in `data/dossiers/<account id>/`, and those of every account with a listing on a changed catalogue level. Photos and checklist ticks regenerate the dossier about 60 seconds later, once per account. A research run that writes more than 50 listing-level rows gets a `flag` note on its request.
