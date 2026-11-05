# API

All endpoints are under http://127.0.0.1:8000 (behind the proxy, the same paths). Authentication: a session cookie (`carlos_session`, set by the login) or `Authorization: Bearer <agent token>`. Every request sees only the rows of its account. Errors are JSON `{"error": "..."}` with 400 (validation, constraint), 401 (login required or wrong token), 404, 405, 415, 429 (login locked), 507 (storage quota).

## Pages
`GET /` the app, `GET /login` and `GET /invite/<token>` the sign-in page, `GET /static/...` assets, `GET /media/<listing>/<sha256>.<ext>` an archived photo (owner only).

## Sign-in and accounts
| Method and path | Body | Result |
|---|---|---|
| `POST /api/auth/login` | `{username, password}` | the account (`id`, `username`, `role`, `has_password`, `has_token`) and the session cookie; 429 after 10 wrong passwords (5 minutes) |
| `POST /api/auth/logout` | | ends the session |
| `GET /api/auth/me` | | the account, or 401 |
| `GET /api/auth/invite/<token>` | | `{username}` of a valid, unused invite |
| `POST /api/auth/invite/<token>` | `{password}` (8+ characters) | sets the password, burns the invite, signs in |
| `POST /api/account/password` | `{old, new}` | changes the password |
| `POST /api/account/token` | | `{token}`: a new agent token, shown once; the previous one stops working |
| `GET /api/admin/users` | | all accounts (admin) |
| `POST /api/admin/users` | `{username, role?}` | creates the account with its parameters and returns `{id, username, invite}` (the invite URL) |
| `POST /api/admin/users/<id>/invite` | | a new invite link (password reset) |
| `PATCH /api/admin/users/<id>` | `{is_active?, role?}` | deactivating ends the sessions and the token; you cannot deactivate yourself |

## Reading
| Path | Result |
|---|---|
| `GET /api/parameters` | the account's parameters |
| `GET /api/preferences` | the account's `project_preferences` rows (keys written by the setup wizard: see `data-model.md`) |
| `GET /api/tco` (alias `/api/listings`) | everything the Compare page needs: `parameters`, `components` (the eight keys), `listings` (every car with `components`, `known_cost_subtotal`, `known_cost_per_month`, `tco_complete`, `missing_components`, `metrics`, `score`, `rank`, `coverage`, `score_parts`, `explain`, `evidence`, `reliability_detail`, `breakeven`, `budget_status`, `price_history`, `price_change`, `stale`, `cover`, `photo_count`, `inspection_counts`, `delta_vs_reference`, `initial_outlay`, `cost_detail`), `budget`, `ranking` (`answers`, `answered`, `weights`, `derived_weights`, `manual`, `criteria`, `questions`, `candidates`), `fuel_price_stale`. Query parameters among `annual_km`, `ownership_years`, `fuel_price_eur_l`, `diesel_price_eur_l`, `budget_ideal_eur`, `budget_max_eur` preview other assumptions without saving (`preview: true`). |
| `GET /api/listings/<id>` | one car with everything above plus `valuations`, `unit_costs`, `maintenance_resets`, `inspection`, `events`, `snapshots`, `media`, the resolved knowledge rows with their `level` (`maintenance`, `repair_risks` with the expected cost per risk, `maintenance_plan` with occurrences and cost per job, `reliability`, `insurance`, `tax`, `observations`, `tyres`), `engine_row`, `generation_row`, `sources` |
| `GET /api/models` | the tree `makes[] → models[] → generations[] → engines[] → variants[]` with each variant's `listings` and the count of knowledge rows per table |
| `GET /api/vehicles` | flat list of variants with make, model, generation and engine basics |
| `GET /api/vehicles/<id>` | one variant: its fields, `engine_row`, `generation_row`, every knowledge table resolved with `level`, `siblings` (variants sharing the engine or the generation), `listings`, `sources` |
| `GET /api/generations`, `GET /api/engines`, `GET /api/sources` | the account's rows |
| `GET /api/ranking` | the questionnaire state (`answers`, `weights`, `derived_weights`, `manual`, `criteria`, `questions`) |
| `GET /api/todo` (alias `/api/agent/todo`) | what is still missing: `account` (setup, ranking choices, fuel price age, the insurance profile a quote needs), per listing and per variant (English texts, see `AGENTS.md`) |
| `GET /api/storage`, `GET /api/health` | disk use; integrity, schema version, number of listings, storage ratio |
| `GET /api/agent/schema` | the writable tables with their columns and types, which need `source_id`, the code formats, the fixed codes, the scoped tables and the rules |

## Writing
| Method and path | Body | Notes |
|---|---|---|
| `POST /api/preferences` | object `preference_key → value` (keys snake_case, at most 50 per call, values ≤ 1000 characters; `null` or empty removes the key) | upsert per account; returns all rows |
| `POST /api/parameters` | any subset of the parameters; `ranking_answers` (object question → answer id), `ranking_weights` (object criterion → 0–5, or `null` to go back to the answers) | validated: `annual_km`, `ownership_years`, `fuel_price_eur_l` > 0; dates ISO; `budget_ideal_eur ≤ budget_max_eur` |
| `POST /api/agent/<table>` | a row (JSON object) | inserts; `owner_id` is set by the server; referenced parent ids must belong to the account; knowledge tables need exactly one of `vehicle_id`, `engine_id`, `generation_id`; tables in `source_required_on_insert` need `source_id` |
| `PATCH /api/agent/<table>/<id>` | the changed columns | updates; `source_id` cannot be removed; there is no DELETE |
| `POST /api/agent/media/<listing id>?url=<original>&snapshot_id=<id>` | image bytes, `Content-Type: image/jpeg|png|webp`, max 1.5 MB | archives a photo; duplicates (same hash) return `created: false` |
| `POST /api/agent/export-md` | | regenerates the account's Markdown dossiers |
| `PATCH /api/ui/inspection_items/<id>`, `POST /api/ui/inspection_items`, `POST /api/ui/listing_events`, `POST /api/ui/media/<listing id>` | `{status, notes}`, `{listing_id, item}`, `{listing_id, text}` (kind `viewing`), image bytes | the viewing mode of the phone UI; same rules as the agent API |
| `POST /api/ui/decision/<listing id>` | `{decision: shortlist|viewing|reject|reset, reason?}` | the owner's decision from the dossier: sets `verdict` ("Shortlisted by the owner", "Viewing planned by the owner", "Rejected by the owner: <reason>") and a `decision` log entry; `reject` archives the car (`WITHDRAWN`, out of the ranking), `reset` brings it back under review; not for the reference car |

Every write is recorded in `change_log` and regenerates the account's dossiers in `data/dossiers/<account id>/`.
