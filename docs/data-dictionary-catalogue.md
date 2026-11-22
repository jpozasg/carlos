# Data dictionary: catalogue, knowledge and listings

Column-by-column reference for the shared catalogue (models, levels, sources, reliability sources), the knowledge rows
that attach to a catalogue level, the per-listing tables, the research queue and the audit log. Companion to
`docs/data-model.md` (the concepts) and `schema.sql` (the executable definition, `PRAGMA user_version` 49, migrations
001 to 049). Accounts, sessions, invites and the account's parameters and preferences are out of scope here.

Checked against the code at the time of writing: readers and writers were found by searching `carlos/*.py`,
`agent_tools.py`, `capture_listing.py`, `markdown_export.py`, `worker.py` and `static/js`. Where a column has no
reader in the code, the row says so (`none`). Where it is written only by a helper and no code reads it, it is marked
`NO READER`.

## How to read the tables

**Owner scope** (per table, in its heading): `shared` = the catalogue, `owner_id` NULL, shared by every account and
written by admins (the curator and the shared research worker); `shared or private` = `owner_id` NULL is shared, a
row with an owner is private to that account; `per account` = every row belongs to `owner_id` or, through its parent,
to a listing's account. The view each account gets is defined in `carlos/auth.py` (`VIEWS`, `_BASE`).

**Read by** codes (a column lists every code that applies):

| Code | Reader |
|---|---|
| `tco` | `GET /api/tco` (alias `GET /api/listings`): cost and ranking rows, `carlos/costs.py`, `carlos/server.py` |
| `detail` | `GET /api/listings/<id>`: one car with its costs, snapshots, media, log, checklist, quotes |
| `variant` | `GET /api/vehicles`, `GET /api/vehicles/<id>` (`carlos/models.py: variant_detail`, `carlos/db.py`) |
| `models` | `GET /api/models` and the Models page (`carlos/models.py`, `static/js/pages/models.js`) |
| `dossier` | the Dossier page (`static/js/pages/dossier.js`) and the Markdown dossiers (`markdown_export.py`) |
| `compare` | the Compare page (`static/js/pages/compare.js`) |
| `todo` | `GET /api/todo` and `GET /api/agent/todo` (`carlos/todo.py`) |
| `research` | the research contract (`carlos/research.py`), used by the worker and the todo |
| `sources` | `GET /api/sources` and the Sources page |
| `queue` | `GET /api/requests` (the account's own), `GET /api/admin/requests`, the worker's `POST /api/worker/claim` |
| `admin` | `GET /api/admin/data/<table>` (every account's rows, admin token), `GET /api/admin/changes` |
| `export` | `GET /api/account/export` (the logged-in account's own rows) |
| `none` | no reader found in the code |

**Written by** codes:

| Code | Writer |
|---|---|
| `agent` | `POST` / `PATCH /api/agent/<table>`: an admin agent token, or the account's own token where `check_writable` allows it (its own listing rows and level-free sources). `archived` is set this way. |
| `agent (admin)` | the same route, but the table is in `ADMIN_TABLES` (`carlos/agent.py`): the shared catalogue, research and listings. Only an admin token passes. |
| `capture` | `capture_listing.py`, through the agent API (source, listing, snapshot, photos, checklist, `found` log entry) |
| `UI` | a `/api/ui/...` route the Dossier calls with the login session (`server.ui_write`) |
| `stage` | a research run's per-request token: `POST /api/agent/<table>` writes a `research_findings` row (`carlos/staging.py`); `staging.merge` copies the agreed rows into the catalogue |
| `server` | the server itself (`owner_id`, `change_log`, `catalogue_links`, `research_matches`) |
| `worker` | the shared research worker (`worker.py`) through `/api/worker/*` (claim, heartbeat, finish) |

**Status** column: blank = in use. `DEPRECATED` = retired by a decision or with no reader and no writer in the code;
the column stays in the schema until a separate migration drops it. `LEGACY` = superseded by another column but still
read. `NO READER` = written (by the API or a helper) but read by no code; kept as data, a candidate for `DEPRECATED`
that needs the owner's decision.

**NULL means** states what NULL stands for. The convention (`docs/data-model.md`, AGENTS.md) is that NULL is
"unknown", never zero, and the calculation then reports the component as unknown. Where a column has another reading
(for example "not applicable" or "none"), the row says so.

**Controlled codes** are enforced in two places: the API (`carlos/agent.py: FIXED_CODES`, `CODE_FORMATS`,
`clean_row`) and, where the schema has it, a `CHECK` constraint. The lists come from `carlos/config.py` (for example
`FUEL_TYPES`, `JOBS`, `FAULT_COMPONENTS`, `FREQUENCY_BANDS`, `RATING_SOURCES`). `GET /api/agent/schema` returns them.

**Units**: money is EUR (`_eur` suffix, or `EUR` in the meaning), distances km, power kW or PS as the column says,
capacity cm³ or kWh, consumption in the unit of its `observations.unit`. Dates are `YYYY-MM-DD` text unless the
column says `YYYY` or `YYYY-MM`.

**Level columns** (knowledge tables and `sources`, `catalogue_links`, `research_checks`, `faults`, `recalls`,
`maintenance_items`): `vehicle_id` (variant), `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`,
`gearbox_family_id`, `body_style_id`, `option_id`. A knowledge row attaches to exactly one of them (CHECK constraint),
except `maintenance_items` (none = a global default) and `sources` (none = shared). The row in `schema.sql` states
which CHECK applies. They are described once, in the table of each section, not repeated per column.

## Index

| # | Table | Group | Owner scope | Status |
|---|---|---|---|---|
| 1 | `generations` | Catalogue | shared or private | |
| 2 | `engines` | Catalogue | shared or private | |
| 3 | `gearboxes` | Catalogue | shared or private | |
| 4 | `gearbox_families` | Catalogue | shared or private | |
| 5 | `engine_families` | Catalogue | shared or private | |
| 6 | `body_styles` | Catalogue | shared or private | |
| 7 | `options` | Catalogue | shared or private | |
| 8 | `vehicles` | Catalogue | shared or private | |
| 9 | `catalogue_links` | Catalogue | per account | |
| 10 | `sources` | Catalogue | shared or private | |
| 11 | `source_keys` | Catalogue (reliability sources) | shared | |
| 12 | `source_ratings` | Catalogue (reliability sources) | shared | |
| 13 | `faults` | Knowledge | shared or private | |
| 14 | `recalls` | Knowledge | shared or private | |
| 15 | `market_models` | Knowledge | shared or private | |
| 16 | `maintenance_items` | Knowledge | shared or private | |
| 17 | `observations` | Knowledge | shared or private | |
| 18 | `insurance_data` | Knowledge | shared or private | |
| 19 | `tax_data` | Knowledge | shared or private | |
| 20 | `tyre_data` | Knowledge | shared or private | |
| 21 | `research_checks` | Knowledge | shared or private | |
| 22 | `reliability_items` | Knowledge (retired) | shared or private | DEPRECATED |
| 23 | `repair_risks` | Knowledge (retired) | shared or private | DEPRECATED |
| 24 | `listings` | Listing | per account | |
| 25 | `listing_snapshots` | Listing | per account | |
| 26 | `listing_media` | Listing | per account | |
| 27 | `listing_events` | Listing | per account | |
| 28 | `listing_history` | Listing | per account | |
| 29 | `listing_options` | Listing | per account | |
| 30 | `listing_quotes` | Listing | per account | |
| 31 | `valuations` | Listing | per account | |
| 32 | `unit_costs` | Listing | per account | |
| 33 | `maintenance_resets` | Listing | per account | |
| 34 | `inspection_items` | Listing | per account | |
| 35 | `research_requests` | Queue | per account | |
| 36 | `workers` | Queue | admin only | |
| 37 | `research_findings` | Queue (staging) | per request | |
| 38 | `research_matches` | Queue (staging) | per request | |
| 39 | `review_flags` | Queue (retired) | shared or private | DEPRECATED |
| 40 | `flag_reviews` | Queue (retired) | per flag | DEPRECATED |
| 41 | `change_log` | Audit | not owned: writer in `user_id`, admin view | |

Tables 22, 23, 39 and 40 are retired: no code writes them any more (the agent API refuses inserts and edits, see
`carlos/agent.py: RETIRED_TABLES`), and they are kept because rows still reference them.

## Catalogue

### 1. `generations`

**Purpose:** one production run of a model (make, model, generation name), with its years of sale, facelift and safety rating.
**Owner scope:** shared or private. `owner_id` NULL is the shared catalogue (natural key make + model + name, `ux_generations_key`); an owner id makes the row private. Written by admins for the catalogue.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never NULL | all readers | `server` (autoincrement) | |
| `make` | TEXT NN | free text, manufacturer name | Manufacturer, as the catalogue spells it. | never NULL | `models`, `variant`, `tco` (labels) | `agent (admin)`, `stage` | |
| `model` | TEXT NN | free text | Model name. | never NULL | `models`, `variant`, `tco` | `agent (admin)`, `stage` | |
| `name` | TEXT NN | free text, generation code or name | Generation (production run) as the market names it. | never NULL | `models`, `variant` | `agent (admin)`, `stage` | |
| `start_year` | INTEGER | year (YYYY) | First year of sale. | unknown | `research` (`gen.identity`), `models`, `tco` (build windows) | `agent (admin)`, `stage` | |
| `end_year` | INTEGER | year (YYYY) | Last year of sale. | unknown (the convention requires it to be recorded) | `research`, `models` | `agent (admin)`, `stage` | |
| `facelift_year` | INTEGER | year (YYYY) | Year of the facelift that splits the generation; phases are windows on rows, not generations (`docs/data-model.md`). | unknown or no facelift recorded | `research` (`gen.facelift`), `models` | `agent (admin)`, `stage` | |
| `status` | TEXT | status code (`VERIFIED`, `PENDING`, ...) by convention, English upper case | Verification status of the generation row. No CHECK in the schema; `CODE_FORMATS` accepts `[A-Z][A-Z /-]*`. | unknown | `models` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes on the generation. | none | `models`, `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared catalogue; set = private to that account. | NULL = shared | auth scope (`carlos/auth.py`), `admin` | `server` | |
| `ncap_stars` | INTEGER 0 to 5 | Euro NCAP stars | Overall Euro NCAP rating of the generation. Read by the safety criterion (`costs.safety_stars`, one star less for a rating before the 2009 regime and for a car without ESP). | unknown, or the car was never tested (research check `gen.safety` = `N/A`) | `tco` (ranking criterion `safety`), `models`, `research` | `agent (admin)`, `stage` | |
| `ncap_year` | INTEGER 1997 to 2100 | year (YYYY) | Year of the Euro NCAP test behind `ncap_stars`. | unknown | `tco` (with `ncap_stars`), `research` | `agent (admin)`, `stage` | |

### 2. `engines`

**Purpose:** one engine (manufacturer code, power, fuel, induction, timing drive, electric charging figures) that several variants can share.
**Owner scope:** shared or private (natural key `code` + `power_kw`, `ux_engines_key`, catalogue only).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `code` | TEXT NN | manufacturer engine code | Engine code as the manufacturer prints it. Natural key with `power_kw`. | never | `variant`, `models`, `tco` | `agent (admin)`, `stage` | |
| `family` | TEXT | free text | Old text name of the engine family, before `family_id` existed (migration 028). | unknown | `variant` and `models` (returned as `family`, shown only when there is no family row) | `agent (admin)` only; no helper sets it (`agent_tools.engine`) | LEGACY (superseded by `family_id`) |
| `description` | TEXT | English free text | Engine description, for example its layout. | none | `variant`, `models`, `dossier` | `agent (admin)` | |
| `fuel_type` | TEXT | `Petrol`, `Diesel`, `Hybrid`, `Plug-in hybrid`, `Electric` (`config.FUEL_TYPES`, `FIXED_CODES`) | Drivetrain the cost model uses. A full hybrid is costed as petrol; `Plug-in hybrid` has no energy cost yet (AGENTS.md). | unknown: the fuel and consumption choice cannot be made | `tco` (fuel and consumption), `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `displacement_cc` | INTEGER | cm³ | Displacement. | unknown or not applicable (electric) | `variant`, `models`, `tco` (labels) | `agent (admin)`, `stage` | |
| `cylinders` | INTEGER | count | Number of cylinders. | unknown or not applicable | `tco`, `variant` | `agent (admin)`, `stage` | |
| `power_kw` | REAL | kW | Maximum power. Natural key with `code`. | unknown | `variant`, `models`, `tco` | `agent (admin)`, `stage` | |
| `power_ps` | REAL | PS (metric horsepower) | Maximum power in PS. | unknown | `variant`, `models`, `tco` | `agent (admin)`, `stage` | |
| `aspiration` | TEXT | `NATURALLY ASPIRATED`, `TURBO`, `SUPERCHARGED` | Air intake type. | unknown or not applicable (electric) | `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `injection` | TEXT | `PORT`, `DIRECT`, `DUAL`, `CARBURETTOR` | Fuel injection type. | unknown or not applicable | `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `timing_drive` | TEXT | `CHAIN`, `BELT`, `WET BELT`, `GEAR` | How the camshaft is driven. Decides which timing job the maintenance items use (`TIMING_DRIVE`). | unknown | `research` (timing item), `tco` (maintenance) | `agent (admin)`, `stage` | |
| `status` | TEXT | status code by convention | Verification status of the engine row. No CHECK. | unknown | `models` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes. | none | `models`, `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared catalogue. | NULL = shared | auth scope, `admin` | `server` | |
| `battery_usable_kwh` | REAL > 0 | kWh | Usable battery capacity of an electric engine. The consumption and charging costs use it with the EVDB figure. | not electric, or unknown | `tco` (electric cost), `research` | `agent (admin)`, `stage` | |
| `ac_charge_kw` | REAL > 0 | kW | Maximum AC charging power. | not electric, or unknown | `tco` (charging time and losses), `research` | `agent (admin)`, `stage` | |
| `dc_charge_kw` | REAL > 0 | kW | Maximum DC (fast) charging power. | not electric, or unknown | `tco` (charging), `research` | `agent (admin)`, `stage` | |
| `family_id` | INTEGER FK engine_families | id | Engine family (shared catalogue, migration 028). Its name is shown as `engine_family_name`. | no family recorded | `variant`, `models`, `tco` (family level of the research) | `agent (admin)`, `stage` | |

### 3. `gearboxes`

**Purpose:** one gearbox (code, type, number of gears) that variants and reliability rows can attach to.
**Owner scope:** shared or private (natural key `upper(code)`, `ux_gearboxes_code`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `code` | TEXT NN | manufacturer gearbox code | Gearbox code as printed. Unique (upper case). | never | `variant` (`gearbox_code`), `models` | `agent (admin)`, `stage` | |
| `family_id` | INTEGER FK gearbox_families | id | Gearbox family. | no family recorded | `variant`, `research` | `agent (admin)`, `stage` | |
| `type` | TEXT | `MANUAL`, `DCT`, `AT`, `CVT`, `SINGLE-SPEED` (`FIXED_CODES`) | Transmission type. | unknown | `variant` (`gearbox_type`), `research` | `agent (admin)`, `stage` | |
| `gears` | INTEGER > 0 | count | Number of forward gears. | unknown | `variant`, `models` | `agent (admin)`, `stage` | |
| `description` | TEXT | English free text | Description. | none | `variant`, `dossier` | `agent (admin)` | |
| `status` | TEXT | status code by convention | Verification status. | unknown | `models` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |

### 4. `gearbox_families`

**Purpose:** a family of gearboxes from one maker (for example one dual-clutch design) that gearboxes and levels share.
**Owner scope:** shared or private (natural key `upper(name)`, `ux_gearbox_families_name`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `name` | TEXT NN | free text | Family name. Unique (upper case). | never | `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `maker` | TEXT | free text | Maker of the family. | unknown | `models`, `dossier` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |

### 5. `engine_families`

**Purpose:** a family of engines from one maker (the level above `engines`, which point to it with `family_id`).
**Owner scope:** shared or private (natural key `upper(name)`, `ux_engine_families_name`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `name` | TEXT NN | free text | Family name. Unique (upper case). | never | `variant` (`engine_family_name`), `models`, `research` | `agent (admin)`, `stage` | |
| `maker` | TEXT | free text | Maker of the family. | unknown | `models`, `dossier` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |

### 6. `body_styles`

**Purpose:** a body style of one generation (saloon, estate, convertible, ...) that variants and body-style knowledge attach to.
**Owner scope:** shared or private (unique per generation and name, `ux_body_styles`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `generation_id` | INTEGER NN FK generations | id | Generation the body style belongs to. | never (required) | `models`, `variant` | `agent (admin)`, `stage` | |
| `name` | TEXT NN | free text | Body style name, unique per generation (upper case). | never | `variant` (`body_style_name`), `models`, `research` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |

### 7. `options`

**Purpose:** an equipment option of a generation (convertible roof, sunroof, four-wheel drive, ...). A listing records its options in `listing_options`.
**Owner scope:** shared or private (unique by name and generation, `ux_options`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `detail` (through `listing_options`), `models` | `agent (admin)`, `stage` | |
| `name` | TEXT NN | free text | Option name. Unique per generation (upper case). | never | `detail`, `dossier` | `agent (admin)`, `stage` | |
| `generation_id` | INTEGER FK generations | id | Generation the option exists for. | NULL = any generation (visible to every account, `auth._BASE`) | auth scope, `models` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |

### 8. `vehicles`

**Purpose:** the variant: one generation with one engine and one trim, gearbox, body and registration codes (HSN/TSN). Listings point to a variant.
**Owner scope:** shared or private. Natural key `hsn` + `tsn` + `engine_id` where `owner_id` is NULL and `hsn` is set (`ux_vehicles_key`). Visible to an account through `catalogue_links` (`auth._LINKED`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all | `server` | |
| `generation_id` | INTEGER NN FK generations | id | Generation of the variant. | never (required) | `variant`, `models`, `tco` | `agent (admin)`, `stage` | |
| `engine_id` | INTEGER NN FK engines | id | Engine of the variant. | never (required) | `variant`, `models`, `tco` | `agent (admin)`, `stage` | |
| `trim` | TEXT | free text | Trim or equipment line as the market names it. | unknown | `models`, `dossier`, `variant` | `agent (admin)`, `stage` | |
| `transmission` | TEXT | free text, for example "manual" or "automatic" | Gearbox as text, beside `gearbox_id`. | unknown | `research` (the automatic check uses it), `models` (filter), `dossier` | `agent (admin)`, `stage` | LEGACY (superseded by `gearbox_id`) |
| `body_style` | TEXT | free text | Body style as text, beside `body_style_id`. | unknown | `models` (shown when there is no body style row) | `agent (admin)`, `stage` | LEGACY (superseded by `body_style_id`) |
| `model_year` | INTEGER | year (YYYY) | Model year of the variant. | unknown | `variant`, `tco` (selected with the variant) | `agent (admin)`, `stage` | |
| `emissions_standard` | TEXT | free text, emission class as printed | Emission standard (for example the Euro class). | unknown | `variant`, `models`, `dossier`, `research` | `agent (admin)`, `stage` | |
| `co2_g_km` | REAL | g/km | Official CO2 figure of the variant. | unknown | `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `hsn` | TEXT | registry manufacturer key (HSN) | Manufacturer key from the registration document (not personal data). Natural key with `tsn`, `engine_id`. | unknown | `variant`, `models` (`hsn`/`tsn` shown), `research` (the consumption source is matched on it) | `agent (admin)`, `stage` | |
| `tsn` | TEXT | registry type key (TSN) | Type key from the registration document. | unknown | as `hsn` | `agent (admin)`, `stage` | |
| `technical_status` | TEXT | status code by convention, uppercase | Status of the technical facts of the variant. | unknown | `models`, `research`, `dossier` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared. | NULL = shared | auth scope, `admin` | `server` | |
| `gearbox_id` | INTEGER FK gearboxes | id | Gearbox of the variant. | unknown | `variant`, `research` | `agent (admin)`, `stage` | |
| `body_style_id` | INTEGER FK body_styles | id | Body style of the variant. | unknown | `variant`, `models`, `research` | `agent (admin)`, `stage` | |
| `esp` | INTEGER 0 or 1 | 1 = fitted, 0 = not fitted | Electronic stability programme fitted. A car without ESP loses one safety star in the ranking (`costs.py`). | unknown (no penalty) | `tco` (safety criterion) | `agent (admin)`, `stage` | |

### 9. `catalogue_links`

**Purpose:** which catalogue variant (or its engine or generation) an account may see, because it has a listing of that car.
**Owner scope:** per account (`owner_id` is always set). Created when a listing is created for its variant (`carlos/agent.py: link`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `admin` | `server` (`agent.link`) | |
| `owner_id` | INTEGER NN FK users | account id | The account that sees the catalogue row. | never | auth scope (`_LINKED`) | `server` | |
| `vehicle_id` | INTEGER FK vehicles | id | The variant that is visible. | not this kind of link | auth scope | `server` | |
| `engine_id` | INTEGER FK engines | id | The engine that is visible (exactly one of the three ids is set, CHECK). | not this kind of link | auth scope | `server` | |
| `generation_id` | INTEGER FK generations | id | The generation that is visible. | not this kind of link | auth scope | `server` | |
| `created_at` | TEXT | datetime | When the link was created. | never (default now) | `admin` | `server` | |

### 10. `sources`

**Purpose:** every external data point cites a source: its URL, access date, quality A to D, what it supports and its limitations. A listing is also a source of its own rows.
**Owner scope:** shared or private. Level-free sources with `owner_id` NULL are global (fee tables); sources on a level follow that level (`auth._BASE['sources']`). Listing and user sources keep their owner.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key; referenced as `source_id` by almost every knowledge and listing table. | never | `sources`, `dossier`, `tco` (source of each figure) | `server` | |
| `vehicle_id` | INTEGER FK vehicles | id | Variant the source supports (level-attached). | not this level | `sources`, `variant`, `models` | `agent`, `agent (admin)`, `stage` | |
| `engine_id` | INTEGER FK engines | id | Engine the source supports. | not this level | as above | as above | |
| `generation_id` | INTEGER FK generations | id | Generation the source supports. | not this level | as above | as above | |
| `title` | TEXT NN | free text | Title of the page or document. | never | `sources`, `dossier` | `agent`, `capture`, `stage` | |
| `url` | TEXT | URL | Address the data was taken from. | no URL (for example a user entry) | `sources`, `dossier` | `agent`, `capture`, `stage` | |
| `source_type` | TEXT | free text; codes read by the code: `tax_official_calculator` (BMF calculator), `user_data` (a quote typed by the account) | Kind of source. | unknown | `research` (tax check), `quotes` (manual quote source) | `agent`, `stage`, `server` (`user_data`) | |
| `quality` | TEXT | `A`, `B`, `C`, `D` (one letter, checked by the API) | Quality grade by the rules of AGENTS.md: A official, B ADAC/TÜV/Haynes/dealer tool, C aggregators, D forums. | unknown (should not happen for a cited source) | `sources`, `dossier` | `agent`, `stage` | |
| `accessed_date` | TEXT | `YYYY-MM-DD` | Date the source was read. | unknown | `sources`, `dossier` | `agent`, `stage` | |
| `supports` | TEXT | English free text | What the source supports. | none | `sources`, `dossier` | `agent`, `stage` | |
| `limitations` | TEXT | English free text | What the source does not cover. | none | `sources`, `dossier` | `agent`, `stage` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = shared (catalogue or global). | NULL = shared | auth scope, `admin` | `server` | |
| `gearbox_id` | INTEGER FK gearboxes | id | Source for a gearbox. | not this level | `sources` | `agent (admin)`, `stage` | |
| `engine_family_id` | INTEGER FK engine_families | id | Source for an engine family. | not this level | `sources` | `agent (admin)`, `stage` | |
| `gearbox_family_id` | INTEGER FK gearbox_families | id | Source for a gearbox family. | not this level | `sources` | `agent (admin)`, `stage` | |
| `body_style_id` | INTEGER FK body_styles | id | Source for a body style. | not this level | `sources` | `agent (admin)`, `stage` | |
| `option_id` | INTEGER FK options | id | Source for an option. | not this level | `sources` | `agent (admin)`, `stage` | |

Note: a source attaches to at most one level (CHECK), and the API also refuses a second level (`clean_row`, "sources attach to at most one level").

### 11. `source_keys`

**Purpose:** maps one engine or generation to its page on one reliability source (Autoscore, EngineScope, TÜV-Report, ADAC Pannenstatistik, ADAC GW-Info). Links only; no score is stored here.
**Owner scope:** shared only (`owner_id` must be NULL, CHECK). Written by admins (`ADMIN_TABLES`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `models`, `todo`, `research` | `server` | |
| `source_key` | TEXT NN | `AUTOSCORE`, `ENGINESCOPE` (engine); `TUEV_REPORT`, `ADAC_PANNENSTATISTIK`, `ADAC_GWINFO` (generation) (`config.RATING_SOURCES`, checked by the API, not by SQL) | Which fixed source the page belongs to. | never | `models`, `research`, `tco` (reliability slots) | `agent (admin)` | |
| `engine_id` | INTEGER FK engines | id | Engine level (exactly one of `engine_id` and `generation_id`). | not this level | `models`, `research` | `agent (admin)` | |
| `generation_id` | INTEGER FK generations | id | Generation level. | not this level | `models`, `research` | `agent (admin)` | |
| `fuel_type` | TEXT | `Petrol`, `Diesel`, `Hybrid`, `Plug-in hybrid`, `Electric` | Only for `ADAC_GWINFO`, which has one PDF per fuel. | every fuel (the key covers all fuels) | `models`, `research` | `agent (admin)` | |
| `external_key` | TEXT NN | verbatim slug, series name or file name | The source's own identifier for the page, copied as printed. Unique per live key and level. | never | `research`, `tco` (matched case-insensitively against `source_ratings`) | `agent (admin)` | |
| `url` | TEXT NN | `https://` URL (CHECK) | Address of the page. | never | `models` (link), `dossier` | `agent (admin)` | |
| `source_id` | INTEGER NN FK sources | id | The `sources` row that records the citation. | never | `sources` | `agent (admin)` | |
| `checked_date` | TEXT NN | `YYYY-MM-DD` | Date the page was read. | never | `models` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes. | none | `models` | `agent (admin)` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = retired row, hidden from every read; `source_keys_all` still shows it. | never | `admin` (through `source_keys_all`) | `agent (admin)` (PATCH archived) | |
| `owner_id` | INTEGER | must be NULL (CHECK) | Always NULL: a reliability source is catalogue only. | NULL (required) | auth scope | `server` | |

### 12. `source_ratings`

**Purpose:** what a reliability source publishes for one page (an Autoscore risk, a TÜV defect share, an ADAC band), verbatim, per edition. The ranking's reliability slots are computed from these rows at calculation time; no rating enters a TCO component.
**Owner scope:** shared only (CHECK). Written by admins. A new edition inserts new rows and archives the old ones (`agent_tools.rating`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `models`, `tco` (reliability slots) | `server` | |
| `source_key` | TEXT NN | as `source_keys.source_key` | Source the rating comes from. | never | `tco`, `models` | `agent (admin)` | |
| `external_key` | TEXT NN | verbatim | Page identifier, matched case-insensitively with `source_keys.external_key`. | never | `tco`, `models` | `agent (admin)` | |
| `edition` | TEXT NN | report year, or reading date for an undated source | Which edition of the source this rating is. | never | `models` | `agent (admin)` | |
| `age_from` | INTEGER | years | Lower age class (TÜV-Report) in years. | not a TÜV rating | `tco` (HU slot), `models` | `agent (admin)` | |
| `age_to` | INTEGER | years; >= `age_from` (CHECK) | Upper age class (TÜV). | not a TÜV rating | as `age_from` | `agent (admin)` | |
| `reg_year` | INTEGER | year (YYYY) | First-registration year of the ADAC breakdown class. Cannot be set together with `age_from` (CHECK). | not an ADAC rating | `tco` (BREAKDOWNS slot), `models` | `agent (admin)` | |
| `value_num` | REAL >= 0 | Autoscore 0 to 10 (risk); EngineScope 0 to 100 (only with written permission); TÜV defect share in %; ADAC PKZ figure | The published figure. | not published | `tco` (ENGINE, HU, BREAKDOWNS slots), `models` | `agent (admin)` | |
| `value_text` | TEXT | verdict or band as printed | Verdict or band as the source words it (Autoscore verdict verbatim). | not published | `models`, `dossier` | `agent (admin)` | |
| `band` | INTEGER 1 to 5 | ADAC band: 1 best, 5 worst | ADAC Pannenstatistik band. | not an ADAC rating | `tco` (BREAKDOWNS slot), `models` | `agent (admin)` | |
| `class_average` | REAL > 0 | % | TÜV class average (the figure a defect share is compared with). | not a TÜV rating | `tco` (HU slot), `models` | `agent (admin)` | |
| `cost_min_eur` | REAL >= 0 | EUR | EngineScope repair cost range, lower bound. Stored only with `SCORE_AND_COSTS` permission (`config.ENGINESCOPE_PERMISSION` is `NONE`). | not stored | `models` only; never a TCO component | `agent (admin)` | |
| `cost_max_eur` | REAL | EUR; >= `cost_min_eur` (CHECK) | EngineScope repair cost range, upper bound. | not stored | as `cost_min_eur` | `agent (admin)` | |
| `sample_count` | INTEGER > 0 | count | Number of cars the figure is based on. | not published | `models` | `agent (admin)` | |
| `url` | TEXT NN | `https://` URL (CHECK) | Address of the rating. | never | `models`, `dossier` | `agent (admin)` | |
| `source_id` | INTEGER NN FK sources | id | Citation of the rating. | never | `sources` | `agent (admin)` | |
| `checked_date` | TEXT NN | `YYYY-MM-DD` | Date the figure was read. | never | `models` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes. | none | `models` | `agent (admin)` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = superseded or retired; hidden from reads. | never | `admin` | `agent (admin)` (PATCH archived) | |
| `owner_id` | INTEGER | must be NULL (CHECK) | Always NULL. | NULL (required) | auth scope | `server` | |

## Knowledge rows on catalogue levels

Every table in this group attaches to one catalogue level through the level columns (see "Level columns" above). A
listing inherits the rows of its variant, its engine, its generation and the other levels it carries (`carlos/db.py:
for_variant`). The per-column "Read by" shows the readers of the calculation (`tco`), the research contract
(`research`), the to-do (`todo`) and the Models page. A row's `archived` = 1 hides it from every read; `<table>_all`
still shows it so that `archived` can be set back to 0.

Shared rows: `owner_id` NULL = catalogue. A row with `owner_id` set is private to that account (for example an
insurance premium or a `USER DATA` figure).

### 13. `faults`

**Purpose:** one weak point of a level (a failure mode with its consequence, its price and its probability curve over km and age). Replaces the retired `repair_risks` and `reliability_items` for costs.
**Owner scope:** shared or private (on a catalogue level). Duplicate-guarded by the API (409 for a second similar fault on one car, `agent.DUPLICATE_GUARDED`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `models`, `variant`, `dossier`, `research` | `server` | |
| `vehicle_id` / `engine_id` / `generation_id` / `gearbox_id` / `engine_family_id` / `gearbox_family_id` / `body_style_id` / `option_id` | INTEGER FK | ids of the level | The level the fault attaches to. Exactly one is set (CHECK). | not this level | `tco`, `models`, `variant` | `agent (admin)`, `stage` | |
| `component` | TEXT NN | free text | Readable name of the component. The controlled code is `component_code`. | never | `dossier`, `models` | `agent (admin)`, `stage` | |
| `part` | TEXT NN | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` (`config.RELIABILITY_PARTS`) | Part of the car the weak point belongs to. Severity and the ranking are read per part. | never | `tco` (severity), `research` | `agent (admin)`, `stage` | |
| `issue` | TEXT | English free text | What fails, as the car shows it. | unknown | `dossier`, `tco` (checklist text) | `agent (admin)`, `stage` | |
| `mechanism` | TEXT | English free text | How it fails (cause). | unknown | NO READER (no code reads the field by name) | `agent (admin)`, `stage` | NO READER |
| `inspection_action` | TEXT | English free text | What the buyer checks on the car. A fault gets a checklist item only when this is set (`checklist_from_reliability`). | no checklist item | `tco` (checklist), `dossier`, `todo` | `agent (admin)`, `stage` | |
| `consequence` | TEXT NN | `ENGINE_DAMAGE`, `STRANDS`, `SAFETY`, `UNUSABLE`, `COST`, `COSMETIC` (`FAULT_CONSEQUENCES`) | What the fault does to the owner. With the cost it derives the severity (HIGH, MEDIUM, LOW-MEDIUM, LOW): `config.SEVERITY_HIGH_EUR` and `SEVERITY_MEDIUM_EUR`. | never | `tco` (severity), `dossier` | `agent (admin)`, `stage` | |
| `parts_eur` | REAL >= 0 | EUR | Workshop parts price of the fix. | unknown | `tco` (repairs cost) | `agent (admin)`, `stage` | |
| `labor_eur` | REAL >= 0 | EUR | Workshop labour price of the fix. | unknown | `tco` (repairs cost) | `agent (admin)`, `stage` | |
| `diy_parts_eur` | REAL >= 0 | EUR | Parts price when the owner does the fix. | unknown | `tco` (only when the account does this job itself) | `agent (admin)`, `stage` | |
| `diy_hours` | REAL >= 0 | hours | Owner's hours for the fix. Shown, never priced. | unknown | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `existence` | TEXT NN | `CONFIRMED`, `REPORTED` | Whether the fault is confirmed by a source or only reported. | never | `dossier`, `research` | `agent (admin)`, `stage` | |
| `curve_km` | TEXT (JSON array) | array of `[km, share]`, share 0 to 1, cumulative | Share of cars affected by a given mileage. Continues to 300,000 km (`CURVE_END_KM`). | not set (the shape or the band is used) | `tco` (probability by km) | `agent (admin)`, `stage` | |
| `curve_age` | TEXT (JSON array) | array of `[years, share]`, cumulative | Share of cars affected by a given age. Continues to 20 years (`CURVE_END_YEARS`). | not set | `tco` (probability by age) | `agent (admin)`, `stage` | |
| `probability_basis` | TEXT | `STATISTIC`, `EXPERT`, `ESTIMATE` | Where the probability comes from. | unknown | `dossier`, `research` | `agent (admin)`, `stage` | |
| `usage_flags` | TEXT | comma list of usage codes, for example `SHORT_TRIPS` | Driving patterns that change the probability. | none | `tco` (heavy use from the setup's driving mix) | `agent (admin)`, `stage` | |
| `usage_multiplier` | REAL > 0 | factor | Factor applied when the usage flags match. Needs `usage_source_id` (CHECK). | no usage effect | `tco` | `agent (admin)`, `stage` | |
| `usage_source_id` | INTEGER FK sources | id | Source of the usage factor. | no usage effect | NO READER (citation; required by the CHECK) | `agent (admin)`, `stage` | NO READER |
| `applies_from` | TEXT | `YYYY` or `YYYY-MM` (first registration) | Start of the first-registration window the fault applies to. | any registration (no window) | `tco` (listing inherits only inside the window), `research` | `agent (admin)`, `stage` | |
| `applies_to` | TEXT | `YYYY` or `YYYY-MM` | End of that window. | any registration | `tco`, `research` | `agent (admin)`, `stage` | |
| `window_uncertain` | INTEGER 0 or 1 | 0, 1 | 1 = the window is an estimate, the dossier says so. | 0 (certain) | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER NN FK sources | id | Citation of the fault. | never (required) | `dossier`, `sources` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` (`faults_all`) | `agent (admin)` (PATCH archived) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope, `admin` | `server` | |
| `frequency_band` | TEXT | `systemic`, `widespread`, `common`, `occasional`, `rare` (`FREQUENCY_BANDS`) | Band of the share of cars affected, central value 0.50, 0.25, 0.12, 0.05, 0.015 (low and high bounds in `config.FREQUENCY_BANDS`). `systemic` needs `manufacturer_trace`. | unknown (no band; the curves decide) | `tco` (probability), `research` | `agent (admin)`, `stage` | |
| `share_low` | REAL 0 to 1 | share | Lower bound of the share of cars affected. | unknown | NO READER (the band's own bounds are used) | `agent (admin)`, `stage` | NO READER |
| `share_high` | REAL 0 to 1 | share | Upper bound. | unknown | NO READER | `agent (admin)`, `stage` | NO READER |
| `shape` | TEXT | `WEAR_KM`, `AGE`, `WINDOW`, `RANDOM` (`FAULT_SHAPES`) | Shape of the probability curve over km and age. | unknown | `tco` (probability), `research` | `agent (admin)`, `stage` | |
| `window_km` | INTEGER > 0 | km | Mileage at which a `WINDOW` shape ends. | not a window shape | `tco`, `research` | `agent (admin)`, `stage` | |
| `onset_km` | INTEGER >= 0 | km | Mileage at which the fault starts. | unknown | NO READER | `agent (admin)`, `stage` | NO READER |
| `manufacturer_trace` | TEXT | free text | Evidence of a manufacturer trace (extended warranty, goodwill, TPI, class action). Required for `systemic`. | no trace | `research`, `dossier` | `agent (admin)`, `stage` | |
| `fixed_fault_id` | INTEGER FK faults | id | The fault that replaces this one after the fix; its curve then applies (`tco`). | not fixed by a later part | `tco`, `consistency`, `staging` | `agent (admin)`, `stage` | |
| `warranty_km` | INTEGER > 0 | km | Warranty mileage limit of the fix. | no warranty | `tco` (warranty share) | `agent (admin)`, `stage` | |
| `warranty_years` | REAL > 0 | years | Warranty time limit. | no warranty | `tco` | `agent (admin)`, `stage` | |
| `warranty_share` | REAL > 0 and <= 1 | share | Share of cost the warranty covers. | no warranty share | `tco` | `agent (admin)`, `stage` | |
| `quote` | TEXT | free text | A short quotation the research wrote for the fault. | none | NO READER (no code reads the field by name) | `agent (admin)`, `stage` | NO READER |
| `component_code` | TEXT | controlled codes per part (`config.FAULT_COMPONENTS`, for example `TIMING_BELT` for ENGINE) | Controlled component; the duplicate check and the back-fill use it. | NULL on rows before migration 039, not back-filled yet | `consistency`, `staging`, `research` | `agent (admin)`, `stage` | |
| `job` | TEXT | `config.JOBS` (for example `TIMING_DRIVE`, `CLUTCH`) | Maintenance job the fault is done as (migration 047). When the account does that job itself the fault is priced at `diy_parts_eur` and `diy_hours` is shown; otherwise at parts and labour. | not done as a job | `tco`, `research` | `agent (admin)`, `stage` | |

### 14. `recalls`

**Purpose:** a manufacturer recall campaign for a level (safety or not), with its remedy and the build window it covers. Recalls stay read-only history plus new recall rows (`recall=True`); the VIN check is a checklist item on every listing.
**Owner scope:** shared or private (on a catalogue level).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `models`, `dossier` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | ids | Exactly one level (CHECK). | not this level | `tco`, `models` | `agent (admin)`, `stage` | |
| `code` | TEXT NN | a KBA reference such as `KBA-14729R`, or `<MAKE>-<YYYY-MM>-<COMPONENT_CODE>`; never starting with `UNKNOWN` (`CODE_FORMATS`) | Campaign reference. | never | `dossier`, `tco` (checklist) | `agent (admin)`, `stage` | |
| `defect` | TEXT NN | English free text | What is wrong. | never | `dossier`, `tco` | `agent (admin)`, `stage` | |
| `remedy` | TEXT | English free text | What the dealer does. | unknown | `dossier` | `agent (admin)`, `stage` | |
| `part` | TEXT | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` (CHECK, nullable) | Part of the car. | unknown | `tco`, `research` | `agent (admin)`, `stage` | |
| `safety` | INTEGER 0 or 1 | 0, 1 | 1 = safety recall. | 0 (not stated as safety) | `dossier` | `agent (admin)`, `stage` | |
| `applies_from` | TEXT | `YYYY` or `YYYY-MM` | Start of the build window. | any build (no window) | `tco` (listing inherits only inside the window), `research` | `agent (admin)`, `stage` | |
| `applies_to` | TEXT | `YYYY` or `YYYY-MM` | End of the build window. | any build | `tco`, `research` | `agent (admin)`, `stage` | |
| `window_known` | INTEGER 0 or 1 | 0, 1 | Whether the build window is known. | 0 (not known) | NO READER (no code names the column) | none found in code | DEPRECATED (no reader and no writer in code) |
| `source_id` | INTEGER NN FK sources | id | Citation. | never | `dossier`, `sources` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |

### 15. `market_models`

**Purpose:** the resale market of a generation and engine: the value of a reference car at a reference age and mileage, and how fast it loses value per year and per 10,000 km, from a dated sample.
**Owner scope:** shared or private (per generation and engine; a private row carries `owner_id`). Not in the admin-only set (`agent.ADMIN_TABLES`), so the API does not reserve it for admins.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` | `server` | |
| `generation_id` | INTEGER NN FK generations | id | Generation of the sample. | never | `tco` | `agent` | |
| `engine_id` | INTEGER NN FK engines | id | Engine of the sample. | never | `tco` | `agent` | |
| `gearbox_id` | INTEGER FK gearboxes | id | Gearbox of the sample, when the sample is split by it. | not split | `tco` | `agent` | |
| `value_ref_eur` | REAL NN > 0 | EUR | Value of the reference car at `ref_age_years` and `ref_km`. | never | `tco` (resale estimate) | `agent` | |
| `ref_age_years` | REAL NN | years | Age of the reference car. | never | `tco` | `agent` | |
| `ref_km` | INTEGER NN | km | Mileage of the reference car. | never | `tco` | `agent` | |
| `rate_year` | REAL NN, 0 <= x < 1 | share per year | Share of value lost per year. | never | `tco` | `agent` | |
| `rate_10k_km` | REAL NN, 0 <= x < 1 | share per 10,000 km | Share of value lost per 10,000 km. | never | `tco` | `agent` | |
| `band_counts` | TEXT NN (JSON array) | counts per km band, three bands | Number of cars in each km band of the sample (at least 5 per band, `MARKET_MIN_PER_BAND`). | never | `tco` | `agent` | |
| `sample_date` | TEXT NN | `YYYY-MM-DD` | Date of the sample. The calculation uses the row only while its age is at most `MARKET_MAX_AGE_DAYS` (183) and each band has at least `MARKET_MIN_PER_BAND` (5) cars. | never | `tco` (resale estimate, `costs.py`) | `agent` | |
| `filters` | TEXT | free text | Filters used on the market site. | unknown | NO READER (no code names the column) | `agent` | NO READER |
| `sample_json` | TEXT (JSON array) | array of sample cars | Verbatim sample. | not stored | NO READER (validated on write only) | `agent` | NO READER |
| `source_id` | INTEGER NN FK sources | id | Citation of the sample. | never | `sources` | `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |

### 16. `maintenance_items`

**Purpose:** a scheduled job or a wear part of a level (oil service, timing drive, brake fluid, HU, ...) with its interval and its price. A row with no level is a global default (HU, brake fluid, the labour rate). The research shares one row per job; each account's DIY choice picks the price at calculation time.
**Owner scope:** shared or private. A level-less row is global.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `todo` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | ids | At most one level (CHECK); none = global default. | none = global default | `tco`, `models` | `agent (admin)`, `stage` | |
| `item` | TEXT NN | English free text | Name of the job. | never | `tco` (cost lines), `dossier` | `agent (admin)`, `stage` | |
| `interval_km` | INTEGER | km | Normal-use interval in km. | no km interval | `tco` (schedule), `research` | `agent (admin)`, `stage` | |
| `interval_months` | INTEGER | months | Normal-use interval in months. | no time interval | `tco`, `research` | `agent (admin)`, `stage` | |
| `reference_cost_eur` | REAL | EUR | Workshop price of the whole job (parts and labour), used when the account does not do the job itself. | unknown (the cost is unknown) | `tco` (maintenance) | `agent (admin)`, `stage` | |
| `diy_parts_cost_eur` | REAL | EUR | Parts price when the account does the job itself. Labour is not priced. | unknown | `tco` (only for DIY jobs), `research` | `agent (admin)`, `stage` | |
| `labor_included` | INTEGER | 0 or 1 | 1 = the workshop price includes labour (`agent_tools.job`). | unknown | NO READER | `agent (admin)`, `stage` (`agent_tools.job`) | NO READER |
| `status` | TEXT | status code by convention | Verification status of the job. | unknown | `dossier` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER (no foreign key in the schema) | id | Citation. | never for shared rows (required on insert) | `dossier`, `sources` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes (for example why a preventive interval is shorter). | none | `dossier` | `agent (admin)`, `stage` | |
| `schedule` | TEXT NN | `PACKAGE`, `ITEM` (CHECK, default `PACKAGE`) | `ITEM` = the row is priced and scheduled on its own (`tco` reads `schedule = 'ITEM'`); `PACKAGE` = part of a package. | never | `tco` | `agent (admin)`, `stage` | |
| `diy` | INTEGER NN | 0 or 1 | Default DIY flag for rows without a `job` (ignored when a `job` is set). | 0 | `tco` | `agent (admin)`, `stage` | |
| `diy_hours` | REAL >= 0 | hours | The owner's hours for the job. Shown, never priced. | unknown | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `active` | INTEGER NN | 0 or 1 | 0 = not part of the schedule. | never (default 1) | `tco`, `research` (only active rows count) | `agent (admin)`, `stage` | |
| `archived` | INTEGER NN | 0 or 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |
| `job` | TEXT | `config.JOBS` (`OIL_SERVICE`, `AIR_FILTER`, `CABIN_FILTER`, `SPARK_PLUGS`, `TIMING_DRIVE`, `COOLANT`, `BRAKE_FLUID`, `BRAKES_FRONT`, `BRAKES_REAR`, `BATTERY`, `BULBS`, `WIPERS`, `HU`, `FUEL_FILTER`, `DRIVE_BELT`, `CLUTCH`, `DRIVE_COOLANT`, `REDUCTION_GEAR_OIL`, `GEARBOX_OIL`) | Controlled job code. The research matches rows by it; the account's DIY choice (`diy_jobs`) decides per job which price counts. | a job without a code (for example a yearly service) | `tco`, `research` | `agent (admin)`, `stage` | |
| `applies_from` | TEXT | `YYYY` or `YYYY-MM` | Start of the first-registration window. | any registration | `tco`, `research` | `agent (admin)`, `stage` | |
| `applies_to` | TEXT | `YYYY` or `YYYY-MM` | End of the window. | any registration | `tco`, `research` | `agent (admin)`, `stage` | |
| `kind` | TEXT NN | `JOB`, `WEAR` (CHECK, default `JOB`) | `WEAR` = a wear part with its typical life as the interval. | never | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `interval_km_heavy` | INTEGER > 0 | km | Shorter interval for heavy use (short trips, `HEAVY_USE_MIX`). | no heavy interval | `tco` | `agent (admin)`, `stage` | |
| `interval_months_heavy` | INTEGER > 0 | months | Shorter time interval for heavy use. | no heavy interval | `tco` | `agent (admin)`, `stage` | |

### 17. `observations`

**Purpose:** a measured or published figure of a level, above all fuel consumption (the primary source of the fuel cost: `Autokostencheck average`, or `EVDB real consumption` for electric cars).
**Owner scope:** shared or private (the owner's own consumption is a private row, a cross-check only).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `models` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | ids | Exactly one of `vehicle_id`, `engine_id`, `generation_id` (CHECK). | not this level | `tco`, `models` | `agent (admin)`, `stage` | |
| `category` | TEXT NN | free text; `consumption` for fuel figures | Kind of figure. | never | `tco` (consumption), `dossier` | `agent (admin)`, `stage` | |
| `metric` | TEXT NN | free text; `Autokostencheck average` (primary, petrol, diesel, hybrid), `EVDB real consumption` (primary, electric), `Owner measured average` (cross-check) | Name of the measured quantity and of its source method (`config.PRIMARY_CONSUMPTION`). | never | `tco` (picks the primary figure), `dossier` | `agent (admin)`, `stage` | |
| `value_num` | REAL | unit in `unit` (for consumption, l/100 km or kWh/100 km) | The figure. | not published (the figure is unknown; never 0) | `tco`, `models`, `compare` | `agent (admin)`, `stage` | |
| `value_text` | TEXT | free text | The figure as printed, when it is not a number. | none | `dossier` | `agent (admin)`, `stage` | |
| `unit` | TEXT | for example `l/100 km`, `kWh/100 km` | Unit of `value_num`. | unknown (must be set with a value) | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `sample_count` | INTEGER | count | Number of cars in the sample. | unknown | `dossier` | `agent (admin)`, `stage` | |
| `min_value` | REAL | unit of `unit` | Lowest figure in the sample. | unknown | `dossier`, `models` | `agent (admin)`, `stage` | |
| `max_value` | REAL | unit of `unit` | Highest figure in the sample. | unknown | `dossier`, `models` | `agent (admin)`, `stage` | |
| `status` | TEXT NN | status code (`VERIFIED`, `OBSERVED`, `USER DATA`, `ESTIMATED`, `PENDING`, ...) | Status of the figure. `USER DATA` for the owner's own measurement. | never | `dossier`, `tco` | `agent (admin)`, `stage` | |
| `evidence_quality` | TEXT | `A` to `D` | Quality of the evidence (rules of AGENTS.md). | unknown | `dossier` | `agent (admin)`, `stage` | |
| `observed_date` | TEXT | `YYYY-MM-DD` | Date of the observation. | unknown | `dossier` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER (no foreign key in the schema) | id | Citation. Required on insert by the API (`SOURCE_REQUIRED`), the column itself is nullable. | not allowed on insert | `dossier`, `sources` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue; an account id = the owner's own figure. | NULL = shared | auth scope | `server` | |

### 18. `insurance_data`

**Purpose:** an insurance premium at a level. Since migration 046 the automated insurance comparison is gone and the rows it stored were deleted; the cost uses a listing's quote first and falls back to a level row (`carlos/costs.py: know.insurance`).
**Owner scope:** shared or private. The premium paid for the own car is private (`USER DATA`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | ids | Exactly one level (CHECK). | not this level | `tco` | `agent (admin)` | |
| `hsn` | TEXT | registry key | Manufacturer key the premium applies to. | unknown | `tco` (matching), `dossier` | `agent (admin)` | |
| `tsn` | TEXT | registry key | Type key. | unknown | as `hsn` | `agent (admin)` | |
| `year` | INTEGER | year (YYYY) | Model or registration year the premium applies to. | unknown | `dossier` | `agent (admin)` | |
| `annual_premium_eur` | REAL | EUR per year | The premium. | unknown (never 0) | `tco` (fallback insurance cost) | `agent (admin)` | |
| `premium_status` | TEXT | `QUOTE`, `USER DATA`, `PENDING` | `USER DATA` = the premium the owner pays for the own car; `QUOTE` = a quote. | unknown | `tco`, `dossier` | `agent (admin)` | |
| `source_id` | INTEGER (no foreign key in the schema) | id | Citation. | not allowed on insert (`SOURCE_REQUIRED`) | `dossier` | `agent (admin)` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)` | |
| `insurer` | TEXT | free text | Insurer named in the quote. | unknown | `dossier` | `agent (admin)` | |
| `tariff` | TEXT | free text | Tariff of the quote. | unknown | `dossier` | `agent (admin)` | |
| `quote_date` | TEXT | `YYYY-MM-DD` (GLOB CHECK) | Date of the quote. A quote expires after 60 days (`QUOTE_MAX_AGE_DAYS`). | unknown | `tco`, `dossier` | `agent (admin)` | |
| `quote_profile` | TEXT (JSON object) | keys from `QUOTE_PROFILE_KEYS` only (cover, deductible, annual km, dates of the policy, HSN/TSN, first registration) | The terms and the car, never names, birth dates, postcode or contact data. | not recorded | `dossier` | `agent (admin)` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | Private premium rows carry the owner. | NULL = catalogue | auth scope | `server` | |

Dropped by migration 046 and no longer in the schema: `premium_min_eur` and the three Typklasse columns. `docs/data-model.md`
still lists them; that text is out of date.

### 19. `tax_data`

**Purpose:** annual road tax (Kfz-Steuer) of a level, with the calculator's inputs (`basis`) and the first-registration window it applies to.
**Owner scope:** shared or private.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | ids | Exactly one level (CHECK). | not this level | `tco`, `models` | `agent (admin)`, `stage` | |
| `annual_tax_eur` | REAL | EUR per year | Road tax per year. | unknown (never 0 by default) | `tco` (tax component) | `agent (admin)`, `stage` | |
| `status` | TEXT | `VERIFIED` (official calculator), `ESTIMATED`, `PENDING` | Status of the figure. | unknown | `tco`, `dossier` | `agent (admin)`, `stage` | |
| `basis` | TEXT | English free text | Every input of the calculator (engine, CO2, emission class, registration date, electric exemption). | unknown | `dossier` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER (no foreign key in the schema) | id | Citation; for `VERIFIED` the source type is `tax_official_calculator`. | not allowed on insert | `tco` (checks the official source), `research` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |
| `registered_from` | TEXT | `YYYY-MM` | Start of the first-registration window the row applies to. | any registration | `tco` (listing uses the row whose window covers its first registration) | `agent (admin)`, `stage` | |
| `registered_to` | TEXT | `YYYY-MM` | End of that window. | any registration | `tco` | `agent (admin)`, `stage` | |

### 20. `tyre_data`

**Purpose:** the tyre set of a level (one set of all-season tyres per variant: size, price, tread life, fitting). The tyre cost is the km of the period over the tread life times the set price plus fitting.
**Owner scope:** shared or private.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | ids | Exactly one level (CHECK). | not this level | `tco`, `models` | `agent (admin)`, `stage` | |
| `tyre_type` | TEXT NN | `ALL-SEASON` (default) | Tyre type of the set. | never | `dossier` | `agent (admin)`, `stage` | |
| `size` | TEXT | tyre size as printed | Tyre size of the variant. | unknown: no tyre cost | `tco` (needed for the set), `research`, `dossier` | `agent (admin)`, `stage` | |
| `price_per_tyre_eur` | REAL > 0 | EUR | Median mid-range price of one tyre. | unknown: no tyre cost | `tco` (tyres component) | `agent (admin)`, `stage` | |
| `tyres_per_set` | INTEGER NN > 0 | count, default 4 | Tyres in a set. | never | `tco` | `agent (admin)`, `stage` | |
| `life_km` | INTEGER > 0 | km | Tread life. | unknown: no tyre cost | `tco` (tyres component) | `agent (admin)`, `stage` | |
| `fitting_per_set_eur` | REAL >= 0 | EUR per set | Fitting price for a set. | unknown, but the cost formula counts NULL as 0 (`costs.tyre_cost: ... or 0`), which breaks the NULL = unknown rule; see the findings at the end | `tco` | `agent (admin)`, `stage` | |
| `status` | TEXT | status code by convention | Status of the figures. | unknown | `dossier` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER FK sources | id | Citation. | not allowed on insert | `dossier`, `sources` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent (admin)` (PATCH) | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |

### 21. `research_checks`

**Purpose:** a record that one task of the research contract was done on a level, with its result. A clean part counts as researched when it is `NONE FOUND` or `N/A`; a missing check is missing (`docs/cost-research-protocol.md`).
**Owner scope:** shared or private.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `research`, `todo`, `models` | `server` | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | ids | Exactly one level (CHECK). | not this level | `research`, `models` | `agent (admin)`, `stage` | |
| `task` | TEXT NN | a contract item id, for example `gen.safety`, `rel.autoscore`, `eng.timing_chain` (`research.TASKS`) | Which task of the contract the check covers. | never | `research`, `todo` | `agent (admin)`, `stage` | |
| `source_id` | INTEGER NN FK sources | id | Source consulted. | never (required) | `research`, `sources` | `agent (admin)`, `stage` | |
| `result` | TEXT NN | `FOUND`, `NONE FOUND`, `N/A` (CHECK) | FOUND = something to record; NONE FOUND = consulted, nothing to report; N/A = not applicable (for example never tested). | never | `research` (grades the item MISSING, ACCEPTED or VERIFIED) | `agent (admin)`, `stage` | |
| `contract_version` | INTEGER NN | research contract version (currently 10, `research.CONTRACT_VERSION`) | Version of the contract the check was made under. | never (set by the API on insert) | `research` | `server` | |
| `checked_date` | TEXT | `YYYY-MM-DD` | Date of the check. | unknown | `dossier`, `research` | `agent (admin)`, `stage` | |
| `notes` | TEXT | English free text | Notes; the reason for an N/A or NONE FOUND. | none | `dossier` | `agent (admin)`, `stage` | |
| `archived` | INTEGER | 0 or 1 | 1 = hidden. (No CHECK in the schema; the API keeps it 0 or 1.) | never | `admin` | `agent (admin)` | |
| `owner_id` | INTEGER FK users | NULL or an account id | NULL = catalogue. | NULL = shared | auth scope | `server` | |
| `named_codes` | TEXT (JSON array) | `config.FAULT_COMPONENTS` codes of the task's part | The weak points a reliability source names. Still accepted by the API and by `agent_tools.check(codes=...)`, but the contract no longer needs it (#351, `docs/data-model.md`). | not set | `research` (only for old rows) | `agent (admin)` (only when `check()` is called with codes) | DEPRECATED (not written by the contract since #351; still validated) |

### 22. `reliability_items` (retired, #351)

**Purpose:** the old weak-point table. Retired: no new rows and no edits (the agent API answers 403 since #397), kept because `inspection_items.reliability_item_id` references it and some old rows are still read by the cost code (`carlos/costs.py`, recall ids and the old reliability rows). Its job is now done by `faults` (priced), `recalls` and `source_keys` / `source_ratings`.
**Owner scope:** shared or private. Archive and an owner-confirmed delete still work.

All columns below are **DEPRECATED** (retired table; reason as above). Their meaning is unchanged from the original design, for reading old rows.

| Column | Type | Meaning (old rows) | Read by | Written by | Status |
|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | `tco` (old rows), `admin` | none | DEPRECATED |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | the level the old weak point attaches to | `tco` | none | DEPRECATED |
| `component` | TEXT NN | component name | `dossier` | none | DEPRECATED |
| `issue` | TEXT | what fails | `dossier` | none | DEPRECATED |
| `evidence` | TEXT | evidence for the issue | `dossier` | none | DEPRECATED |
| `severity` | TEXT | `HIGH`, `HIGH IF APPLICABLE`, `MEDIUM`, `LOW-MEDIUM`, `LOW` | `dossier`, `tco` (old rows) | none | DEPRECATED |
| `frequency_status` | TEXT | how often it occurs, as a status | `dossier` (markdown) | none | DEPRECATED |
| `source_id` | INTEGER (no foreign key in the schema) | citation | `dossier` | none | DEPRECATED |
| `inspection_action` | TEXT | checklist action | `tco`, `dossier` | none | DEPRECATED |
| `part` | TEXT | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` | `tco` | none | DEPRECATED |
| `is_recall` | INTEGER 0 or 1 | 1 = a recall (read by the cost code for the recall check) | `tco` | none | DEPRECATED |
| `archived` | INTEGER 0 or 1 | hidden when 1 | `admin` | `agent (admin)` (PATCH archive only) | DEPRECATED |
| `owner_id` | INTEGER FK users | owner | auth scope | none | DEPRECATED |
| `applies_from` / `applies_to` | TEXT | build window | `tco` (old rows) | none | DEPRECATED |

### 23. `repair_risks` (retired, #397)

**Purpose:** the old km-window failure risks. Retired: the API refuses inserts and edits (403); no cost code reads the table (`carlos/costs.py` does not reference it). Its job is done by `faults`.
**Owner scope:** shared or private.

All columns are **DEPRECATED** (no reader in the cost code; no writer through the API). Meaning kept for reading old rows.

| Column | Type | Meaning (old rows) | Read by | Written by | Status |
|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | `admin` | none | DEPRECATED |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | level (exactly one, CHECK) | none | none | DEPRECATED |
| `component` | TEXT NN | component | none | none | DEPRECATED |
| `km_from` / `km_to` | INTEGER | km window; `km_to > km_from` (CHECK) | none | none | DEPRECATED |
| `probability` | REAL | 0 to 1 chance in the window | none | none | DEPRECATED |
| `parts_eur` / `labor_eur` | REAL >= 0 | EUR | none | none | DEPRECATED |
| `diy` | INTEGER | 0 or 1 | none | none | DEPRECATED |
| `diy_hours` | REAL >= 0 | hours | none | none | DEPRECATED |
| `status` / `evidence` | TEXT | status and evidence | none | none | DEPRECATED |
| `source_id` | INTEGER FK sources | citation | none | none | DEPRECATED |
| `notes` | TEXT | notes | none | none | DEPRECATED |
| `archived` | INTEGER 0 or 1 | hidden when 1 | `admin` | `agent (admin)` (PATCH archive only) | DEPRECATED |
| `owner_id` | INTEGER FK users | owner | auth scope | none | DEPRECATED |
| `job` | TEXT | `config.JOBS` code | none | none | DEPRECATED |
| `applies_from` / `applies_to` | TEXT | build window | none | none | DEPRECATED |

## Listings (one specific car)

### 24. `listings`

**Purpose:** one car for sale (or the owner's own car, `is_reference = 1`): the ad's facts as published, the seller's claims, the status and the owner's verdict. Its costs, checklist, photos and log hang off it.
**Owner scope:** per account (`owner_id`, NOT NULL, default 1). Written by the capture script, the agent API and the Dossier decision route.
**Write rules:** `listing_status` = `WITHDRAWN` when the car is no longer for sale (a reject sets it, `server.py`). A listing is never deleted by an agent.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | all listing readers | `server` | |
| `vehicle_id` | INTEGER FK vehicles | id | The variant (catalogue). NULL after a research reset until the worker re-researches the car (`research_reset.py`). | not yet matched to a variant | `tco`, `detail`, `models`, `compare` | `capture`, `agent`, `stage` | |
| `source_id` | INTEGER | id of a `sources` row (no foreign key in the schema) | The listing itself, as a source of its facts. | not recorded | `dossier`, `sources` | `capture`, `agent` | |
| `listing_id` | TEXT | the platform's own id | Identifier of the ad on its platform. | unknown | `dossier`, `capture` (duplicate check) | `capture`, `agent` | |
| `platform` | TEXT | free text, for example the site's name | Where the ad is. | unknown | `compare`, `dossier`, `models` | `capture`, `agent` | |
| `url` | TEXT | URL | Address of the ad. | unknown | `dossier`, `compare`, `admin` | `capture`, `agent`, `UI` (request) | |
| `price_eur` | REAL | EUR | Asking price as published. It is an asking price, not a transaction price (AGENTS.md). | not stated (the cost is unknown) | `tco` (purchase price, `purchase_sale`), `compare`, `dossier` | `capture`, `agent` | |
| `mileage_km` | INTEGER | km | Mileage as published. | unknown | `tco` (depreciation, km), `compare`, `todo` | `capture`, `agent` | |
| `seller` | TEXT | free text, only what the ad publishes | Seller's name or shop as published. No personal data beyond the ad (AGENTS.md privacy). | not published | `dossier`, `markdown` | `capture`, `agent` | |
| `location` | TEXT | free text | Town or place as published. | not published | `compare`, `dossier` | `capture`, `agent` | |
| `seller_address` | TEXT | free text | Seller's address, only as the ad publishes it. | not published | NO READER (no code reads the column) | `capture` | NO READER |
| `accident_free_claim` | INTEGER | 0 or 1 | The seller's claim of no accident damage (1 = claimed). A claim, not a fact. | not stated | `dossier`, `markdown` | `capture`, `agent` | |
| `owners_claim` | INTEGER | count >= 0 | Number of previous owners the seller states. | not stated | `dossier`, `markdown` | `capture`, `agent` | |
| `hu_claim` | TEXT | free text | The seller's statement on the inspection (HU) as written. | not stated | `dossier`, `markdown` | `capture`, `agent` | |
| `service_history_claim` | TEXT | free text | The seller's statement on the service history as written. | not stated | `dossier`, `markdown` | `capture`, `agent` | |
| `equipment` | TEXT | free text (listing's wording) | Equipment as the ad lists it. Verbatim third-party content, original language. | not stated | `dossier`, `markdown` | `capture`, `agent` | |
| `listing_date` | TEXT | date as the ad shows it | Date the ad was posted. | not shown | NO READER (written by the capture script only) | `capture` | NO READER |
| `last_checked` | TEXT | `YYYY-MM-DD` | Last time the ad was read. Older than `STALE_LISTING_DAYS` (14) the car is stale in the to-do. | never checked | `tco` (stale check), `models`, `dossier` | `capture`, `agent` | |
| `listing_status` | TEXT | `UNDER REVIEW`, `OWNED`, `WITHDRAWN` (`CODE_FORMATS`, controlled by convention) | Status of the car for the owner. `WITHDRAWN` = no longer for sale (a reject sets it; a shortlist or viewing sets `UNDER REVIEW`); `OWNED` = the owner bought it (set through the agent API; no route sets it). | never (the capture script sets `UNDER REVIEW` for a new listing) | `tco` (withdrawn cars leave the ranking), `compare`, `dossier`, `todo` | `capture`, `agent`, `UI` (decision) | |
| `notes` | TEXT | English free text | Notes. | none | `dossier`, `compare` | `capture`, `agent`, `UI` | |
| `is_reference` | INTEGER | 0 or 1 | 1 = the owner's own car (the reference): its premium is the one paid (`USER DATA`), its distance is 0. | 0 (not the reference) | `tco` (reference rules), `compare`, `dossier` | `agent` | |
| `first_registration` | TEXT | `YYYY-MM` (capture format) | First registration of the car. Decides the tax, insurance, fault and recall windows. | unknown (windows fall back to `build_date`, then "any registration") | `tco` (windows), `models`, `dossier`, `todo` | `capture`, `agent` | |
| `verdict` | TEXT | free text, English. Set by the owner's decision: "Shortlisted by the owner", "Viewing planned by the owner", "Rejected by the owner: <reason>"; otherwise an agent's verdict | Short conclusion on the car. | no verdict yet (`todo` asks for one) | `compare`, `dossier`, `todo` | `agent`, `UI` (decision) | |
| `owner_id` | INTEGER NOT NULL FK users | account id, default 1 | The account the listing belongs to. | never | auth scope | `server` | |
| `battery_soh_claim` | REAL | % in (0, 100] (CHECK) | Battery state of health the seller states, for an electric car. A claim. | not stated | `todo` (asks for a check), `dossier` | `capture`, `agent` | |
| `lease_kind` | TEXT | `km`, `residual`, `abo` (`LEASE_KINDS`) | Kind of lease offer. | not a lease | NO READER (leasing is out of scope, #165) | `capture`, `agent` | DEPRECATED (lease out of scope since #165; the codes are kept) |
| `lease_monthly_eur` | REAL > 0 | EUR per month | Lease rate. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_term_months` | INTEGER > 0 | months | Lease term. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_km_per_year` | INTEGER > 0 | km per year | Lease mileage allowance. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_down_payment_eur` | REAL >= 0 | EUR | Down payment. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_fees_eur` | REAL >= 0 | EUR | One-off fees. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_extra_km_eur` | REAL >= 0 | EUR per km | Charge per extra km. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_fewer_km_eur` | REAL >= 0 | EUR per km | Refund per km not driven. | not a lease | NO READER | `capture` | DEPRECATED (#165) |
| `lease_includes` | TEXT | comma list of `insurance`, `tax`, `maintenance`, `repairs`, `tyres`, `gap` (no spaces) | What the lease rate includes. | not stated | NO READER | `capture`, `agent` | DEPRECATED (#165) |
| `build_date` | TEXT | `YYYY` or `YYYY-MM` (`CODE_FORMATS`) | Build date when the ad shows it. The build windows use it before the first registration. | not shown (the flag `build_date_unknown` is set) | `tco` (windows) | `agent` | |
| `engine_code_seen` | TEXT | free text | Engine code the ad shows. | not shown | none (the research reset comment says it is kept) | `agent` | DEPRECATED (no reader and no writer in the capture script) |
| `hsn` | TEXT | registry key | Manufacturer key stated by the ad or the owner; matches the variant. | not stated | `tco` (variant match), `dossier`, `models` | `capture`, `agent` | |
| `tsn` | TEXT | registry key | Type key, as `hsn`. | not stated | as `hsn` | `capture`, `agent` | |
| `trim` | TEXT | free text | Trim as the ad names it (copied to the variant when it matches). | not stated | `models`, `dossier`, `tco` (labels) | `capture`, `agent` | |
| `distance_km` | REAL >= 0 | km | Distance from the owner's postcode. When set it replaces the computed distance (`costs.py`). | the distance is computed from `postal_code` (or unknown) | `tco` (distance criterion) | `agent` | |
| `seller_type` | TEXT | `DEALER`, `PRIVATE` (CHECK) | Kind of seller. | not stated | `tco` (ranking filter), `dossier` | `capture`, `agent` | |
| `warranty` | INTEGER | 0 or 1 | 1 = a warranty is offered. | not stated | `tco` (ranking filter `filter_warranty`), `dossier` | `capture`, `agent` | |
| `hu_until` | TEXT | `YYYY-MM` | Month the inspection (HU) expires. | not stated | `tco` (ranking filter `filter_hu_months`), `dossier` | `capture`, `agent` | |
| `service_history` | TEXT | `YES`, `NO`, `CLAIMED` (CHECK) | Service history as the ad states it (`CLAIMED` = a seller claim). | not stated | `tco` (ranking filter), `dossier` | `capture`, `agent` | |
| `accident_free` | TEXT | `YES`, `NO`, `CLAIMED` (CHECK) | Accident-free status as the ad states it. Used by the ranking filter. | not stated | `tco` (ranking filter), `dossier` | `capture`, `agent` | |
| `seller_rating` | REAL 0 to 5 | stars | Seller's rating as the platform shows it. | not shown | `dossier` | `capture`, `agent` | |
| `seller_reviews` | INTEGER >= 0 | count | Number of reviews of the seller. | not shown | `dossier` | `capture`, `agent` | |
| `postal_code` | TEXT | 5 digits (CHECK, GLOB) | Postcode of the car's location, for the distance. | unknown (distance unknown unless `distance_km` is set) | `tco` (distance), `dossier` | `capture`, `agent` | |

### 25. `listing_snapshots`

**Purpose:** every capture of the ad as published at one visit: price, mileage, title, verbatim description and every feature the ad shows. Never overwritten; the price history comes from here.
**Owner scope:** per account (through `listing_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `detail` (history), `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `detail` | `capture`, `agent` | |
| `captured_at` | TEXT NN | datetime | When the ad was read. | never | `dossier`, `markdown` | `capture`, `agent` | |
| `source_id` | INTEGER NN FK sources | id | The page the capture came from. | never | `dossier` | `capture`, `agent` | |
| `title` | TEXT | ad's title, verbatim | Title of the ad. | not shown | `dossier`, `compare` | `capture`, `agent` | |
| `price_eur` | REAL | EUR | Asking price at the capture. | not shown | `detail` (price history), `dossier` | `capture`, `agent` | |
| `mileage_km` | INTEGER | km | Mileage at the capture. | not shown | `detail`, `dossier` | `capture`, `agent` | |
| `description` | TEXT | verbatim, original language | The ad's description as written. Third-party content: keep the language. | not shown | `dossier` | `capture`, `agent` | |
| `attributes_json` | TEXT (JSON object) | object of feature name to value, verbatim | Every feature the ad shows. | not shown | `dossier`, `markdown` | `capture`, `agent` | |
| `notes` | TEXT | English free text | Notes on the capture (for example a photo the script could not fetch). | none | `dossier` | `capture`, `agent` | |

### 26. `listing_media`

**Purpose:** an archived photo of a listing, stored in the data directory (`media/<listing id>/<sha256>.<ext>`, at most 1.5 MB, deduplicated by hash).
**Owner scope:** per account (through `listing_id`). Quota: the whole installation stays under 1 GB (`config.STORAGE_LIMIT`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `detail`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `detail` | `capture`, `UI` (`/api/ui/media`), `agent` | |
| `snapshot_id` | INTEGER FK listing_snapshots | id | The capture the photo was taken with. | not linked | `detail` | `capture`, `agent` | |
| `captured_at` | TEXT NN | datetime (default now) | When the photo was archived. | never | `dossier` | `server` | |
| `original_url` | TEXT | URL | Address the photo was downloaded from. | not recorded | NO READER (written by the agent API only) | `agent` | NO READER |
| `file_path` | TEXT NN UNIQUE | `media/<listing>/<sha256>.<ext>` (relative to the data directory) | Where the file is. | never | `detail` (served through `/media/...`), `dossier` | `capture`, `UI`, `agent` | |
| `mime` | TEXT NN | `image/jpeg`, `image/png`, `image/webp` (`IMAGE_TYPES`) | Media type, from the file's magic bytes. | never | `detail` | `capture`, `UI` | |
| `bytes` | INTEGER NN | bytes | File size (limit 1.5 MB per image). | never | NO READER (the storage quota sums the files on disk, `agent.storage_usage`) | `capture`, `UI`, `agent` | NO READER |
| `sha256` | TEXT NN | hex digest | Hash of the file; with `listing_id` unique (no duplicate photo). | never | `agent` (duplicate check when a photo is saved, `save_media`) | `capture`, `UI`, `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = not shown (a removed photo). | never | `detail`, `dossier` | `UI` (`PATCH /api/ui/photo`), `agent` | |

### 27. `listing_events`

**Purpose:** the log of a listing, the agent's memory: what was found, verified, corrected, priced, decided, measured by the owner, photographed or viewed. Written in English.
**Owner scope:** per account (through `listing_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `detail`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `detail` | `capture`, `agent`, `UI` | |
| `event_date` | TEXT NN | `YYYY-MM-DD` | Date of the entry. | never | `dossier` | `capture`, `agent`, `UI` | |
| `kind` | TEXT NN | `found`, `verification`, `correction`, `price`, `decision`, `user_data`, `warning`, `archive`, `photos`, `viewing` (new kinds: lower case, snake_case, `CODE_FORMATS`) | What the entry is. `decision` = the owner's shortlist, viewing or reject; `user_data` = a figure the owner gave; `viewing` = the owner's observation at a viewing. | never | `detail`, `dossier`, `todo` | `capture`, `agent`, `UI` (decision, viewing) | |
| `text` | TEXT NN | English free text | The entry. Non-English owner notes get an English `user_data` entry as well. | never | `dossier`, `detail` | `capture`, `agent`, `UI`, `server` (quotes: `user_data`) | |
| `source_id` | INTEGER FK sources | id | Citation of the entry. | not cited | `dossier` | `capture`, `agent`, `UI` | |

### 28. `listing_history`

**Purpose:** the history of the car against the research's jobs, faults and recalls: whether a job was done (and when), a fault is present, a recall is open or does not apply. Also the owner's own chance that a DONE fault fails again.
**Owner scope:** per account (through `listing_id`). At least one of `maintenance_item_id`, `fault_id`, `recall_id`, `job` (CHECK).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `tco` | `agent`, `capture` | |
| `maintenance_item_id` | INTEGER FK maintenance_items | id | The job the entry is about. | not a job | `tco` (`maintenance_resets`) | `agent`, `stage` | |
| `fault_id` | INTEGER FK faults | id | The fault the entry is about. | not a fault | `tco` (repairs, owner's chance), `dossier` | `agent`, `stage` | |
| `recall_id` | INTEGER FK recalls | id | The recall the entry is about. | not a recall | `tco`, `dossier` | `agent`, `stage` | |
| `job` | TEXT | `config.JOBS` | A job without a maintenance row. | not a job | `tco` | `agent`, `stage` | |
| `item` | TEXT NN | English free text | Name of the entry. | never | `dossier`, `tco` (checklist) | `agent`, `capture` | |
| `status` | TEXT NN | `DONE`, `PRESENT` (a certain cost), `OPEN`, `NOT AFFECTED` (CHECK) | State of the job, fault or recall for this car. | never | `tco` (certain costs, restarts), `dossier` | `agent`, `capture` | |
| `km` | INTEGER >= 0 | km | Mileage when it was done or seen. | unknown | `tco` (restart km), `dossier` | `agent`, `capture` | |
| `event_date` | TEXT | `YYYY-MM-DD` | Date when it was done or seen. | unknown (the window then uses the km curve alone) | `tco` (age of the fault), `dossier` | `agent`, `capture` | |
| `evidence` | TEXT NN | `DOCUMENTED`, `SELLER CLAIM`, `OBSERVED`, `VIN CHECK` (CHECK) | What the status rests on. | never | `tco`, `dossier` | `agent`, `capture` | |
| `category` | TEXT | `maintenance`, `repairs` | Where a certain cost goes. Required when `status` is `PRESENT`. | not a cost | `tco` | `agent`, `capture` | |
| `parts_eur` | REAL >= 0 | EUR | Parts price of a certain cost. | unknown | `tco` | `agent` | |
| `labor_eur` | REAL >= 0 | EUR | Labour price of a certain cost. | unknown | `tco` | `agent` | |
| `diy_hours` | REAL >= 0 | hours | Hours of the owner's work. Shown, never priced. | unknown | `dossier` | `agent` | |
| `source_id` | INTEGER FK sources | id | Citation of the entry. | not cited | `dossier` | `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent`, `capture` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |
| `owner_probability` | REAL | 0 to 1 (CHECK), only on a `DONE` row with `fault_id` | The owner's own chance that this fault fails again within the owner's period, for this car only. The shared `faults` row is not changed. | no owner figure (the curve applies) | `tco` (`costs.py` uses it in place of the fault's curve), `dossier` (shown as `owner_chance`) | `UI` (`PATCH /api/ui/listing_history/<id>`, `chance.py`) | |
| `owner_reason` | TEXT | English free text | Why the owner expects it (required with `owner_probability`). | none | `dossier` | `UI` | |

### 29. `listing_options`

**Purpose:** the equipment options of a listing (from the catalogue's `options`).
**Owner scope:** per account (through `listing_id`). Unique per listing and option.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` (the options' costs and ranking), `detail` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `detail` | `capture`, `agent` | |
| `option_id` | INTEGER NN FK options | id | The option the car has. | never | `detail`, `tco` | `agent`, `stage` | |
| `source_id` | INTEGER FK sources | id | Citation (for example the ad). | not cited | `dossier` | `capture`, `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent` | |

### 30. `listing_quotes`

**Purpose:** insurance quotes for a listing: the premium and the terms the quote was made on. The cost uses the newest quote by `quote_date` (then the highest id); a quote older than 60 days is still used in the cost and flagged in the to-do. For the reference car the `USER DATA` premium is used.
**Owner scope:** per account (through `listing_id`). Only the account types a quote by hand (`POST /api/ui/listing_quotes`, `carlos/quotes.py`); the comparison-site robot was removed on 2026-11-22.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `tco`, `dossier` | `UI`, `agent` | |
| `annual_premium_eur` | REAL NN > 0 | EUR per year | The premium the quote states; a manual entry given per month is multiplied by 12 (`quotes.py`). | never (a quote needs a premium) | `tco` (insurance component) | `UI`, `agent` | |
| `premium_min_eur` | REAL > 0 | EUR per year | Lower end of a premium range. | not stated | NO READER (no code names the column) | none found in code | DEPRECATED (no reader and no writer in code) |
| `premium_status` | TEXT NN | `QUOTE` (a manual quote), `USER DATA` (the owner's own premium, for the reference car) | Kind of premium. | never | `tco` (the reference car uses `USER DATA`), `dossier`, `todo` | `UI` (`QUOTE`), `agent` | |
| `insurer` | TEXT | free text | Insurer named in the quote. | not stated | `dossier` | `UI`, `agent` | |
| `tariff` | TEXT | free text | Tariff named in the quote. | not stated | `dossier` | `UI`, `agent` | |
| `quote_date` | TEXT | `YYYY-MM-DD` (GLOB CHECK) | Date of the quote. The manual form refuses a date older than 60 days or more than a day ahead. | unknown | `tco` (newest quote wins), `todo` (expired), `dossier` | `UI`, `agent` | |
| `quote_profile` | TEXT (JSON object) | keys from `QUOTE_PROFILE_KEYS` only | The policy's terms and the car (cover, deductible, annual km, dates, HSN/TSN, first registration). Never names, birth dates, postcode or contact data. | not recorded | `dossier` | `UI`, `agent` | |
| `source_id` | INTEGER NOT NULL FK sources | id | Citation: a manual quote uses a `user_data` source of the account (quality D, `quotes.py`). | never | `dossier` | `server` (`quotes.py`), `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `UI`, `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |

### 31. `valuations`

**Purpose:** what the car is worth: today (reference only, `sale_today`) and at the end of the owner's ownership (`resale_end`, the figure the depreciation uses).
**Owner scope:** per account (through `listing_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `tco` | `agent` | |
| `kind` | TEXT NN | `sale_today` (reference only), `resale_end` (used by depreciation) (CHECK) | What the value is. | never | `tco` (depreciation, the reference car's sale value), `dossier` | `agent` | |
| `horizon_years` | INTEGER | years | Ownership period the value is for. The cost moves a `resale_end` along the resale rule when the account's period differs (`RESALE_YEARLY_LOSS`). | unknown | `tco`, `dossier` | `agent` | |
| `low_eur` | REAL | EUR | Lower bound of the value. | unknown | `dossier` | `agent` | |
| `expected_eur` | REAL NN | EUR | The expected value. | never | `tco` (depreciation), `dossier` | `agent` | |
| `high_eur` | REAL | EUR | Upper bound. | unknown | `dossier` | `agent` | |
| `status` | TEXT NN | status code (`ESTIMATED`, `OBSERVED`, `PRIMARY`, ...) | Status of the value. | never | `dossier` | `agent` | |
| `valued_date` | TEXT | `YYYY-MM-DD` | Date of the valuation. | unknown | NO READER (written by the agent helper only) | `agent` | NO READER |
| `source_id` | INTEGER NN FK sources | id | Citation (the market sample or rule of thumb). | never | `dossier` | `agent` | |
| `notes` | TEXT | English free text | Derivation of an estimate. | none | `dossier` | `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |

### 32. `unit_costs`

**Purpose:** certain one-off costs of this car: a scheduled job due at purchase (`maintenance`), a fault the car has now (`repairs`), a tyre cost (`tyres`) and purchase costs (`purchase_sale`). They are certain, not expected: a fault linked by `fault_id` adds no expected cost for this car.
**Owner scope:** per account (through `listing_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco`, `dossier`, `research` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `tco` | `agent` | |
| `category` | TEXT NN | `repairs`, `maintenance`, `tyres`, `purchase_sale` (`UNIT_COST_CATEGORIES`, CHECK) | Which cost component it goes to. | never | `tco` (component), `research` (purchase costs item) | `agent` | |
| `item` | TEXT NN | English free text | Names the job or fault (for example "Timing belt kit with water pump (due by age: 10 years)"). | never | `dossier`, `tco` | `agent` | |
| `parts_eur` | REAL | EUR | Parts price. At least one of the two prices is set (CHECK). | unknown | `tco` | `agent` | |
| `labor_eur` | REAL | EUR | Labour price. | unknown | `tco` | `agent` | |
| `diy_hours` | REAL | hours | The owner's hours. Shown, never priced. | unknown | `dossier` | `agent` | |
| `status` | TEXT NN | status code (`VERIFIED`, `ESTIMATED`, `QUOTE`, ...) | Status of the prices. | never | `dossier`, `tco` (a certain cost without a price makes its component unknown) | `agent` | |
| `source_id` | INTEGER FK sources | id | Citation. | not cited | `dossier` | `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |
| `fault_id` | INTEGER FK faults | id | The fault this repair fixes; the fault adds no expected cost for this car. | not a repair of a fault | `tco` | `agent` | |

### 33. `maintenance_resets`

**Purpose:** a scheduled job done at the start of the owner's ownership: the schedule restarts for this car, so its next due date is counted from here. The basis says how the reset is known.
**Owner scope:** per account (through `listing_id`). Unique per listing and job.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `tco` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `tco` | `agent` | |
| `maintenance_item_id` | INTEGER NN FK maintenance_items | id | The job that restarts. | never | `tco` | `agent` | |
| `basis` | TEXT NN | `CERTAIN REPAIR`, `SELLER CLAIM`, `DOCUMENTED` (CHECK) | How the reset is known. A seller claim gets a checklist item asking for the invoice. | never | `tco` (restart), `dossier` | `agent` | |
| `unit_cost_id` | INTEGER FK unit_costs | id | The certain cost that paid for the job (when the job is a certain repair). | not linked | `tco` | `agent` | |
| `source_id` | INTEGER FK sources | id | Citation. | not cited | `dossier` | `agent` | |
| `notes` | TEXT | English free text | Notes. | none | `dossier` | `agent` | |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |

### 34. `inspection_items`

**Purpose:** the checklist of a listing: what the buyer checks, with its status and notes. Each item comes from one weak point (a fault, a recall or, for old rows, a retired reliability item) or from the fixed checks of every listing (for example the VIN recall check).
**Owner scope:** per account (through `listing_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `detail`, `dossier` | `server` | |
| `listing_id` | INTEGER NN FK listings | id | The car. | never | `detail` | `capture`, `agent` | |
| `item` | TEXT NN | English free text | What to check. | never | `detail`, `dossier` | `capture`, `agent`, `server` (`checklist_from_reliability`) | |
| `status` | TEXT NN | `PENDING`, `OK`, `PROBLEM`, `N/A` (CHECK, default `PENDING`) | Result of the check. For a recall item, `PROBLEM` or `OK` decides whether the recall counts. | never | `tco` (weak points checked), `dossier`, `todo` | `UI` (`/api/ui/inspection_items`), `agent` | |
| `checked_date` | TEXT | `YYYY-MM-DD` | When it was checked. | not checked | `dossier` | `UI`, `agent` | |
| `notes` | TEXT | free text (the owner's words in the viewing) | Notes on the check. | none | `dossier` | `UI`, `agent` | |
| `reliability_item_id` | INTEGER FK reliability_items | id | The retired reliability item the check comes from (old rows). | not linked | none in the cost code for new rows; `tco` (old rows) | `agent` only for old rows (no new links) | DEPRECATED (the referenced table is retired, #351) |
| `archived` | INTEGER 0 or 1 | 0, 1 | 1 = hidden from every read. | never | `admin` | `agent` (PATCH) | |
| `fault_id` | INTEGER FK faults | id | The fault the check comes from. A fault gets an item only when it has an `inspection_action`. | not from a fault | `tco` (weak points checked), `dossier` | `agent`, `server` | |
| `recall_id` | INTEGER FK recalls | id | The recall the check comes from; its result decides whether the recall counts. | not from a recall | `tco`, `dossier` | `agent`, `server` | |

## Research queue, staging and audit

### 35. `research_requests`

**Purpose:** the research queue. An account asks for a car by its URL (`POST /api/requests`); a registered worker claims the request, and the server splits a listing request into unit rows (`parent_id`, `unit`, `level_id`, `shared_id`) that run stage by stage.
**Owner scope:** per account (`owner_id` = the account the car is for). `requested_by` names the admin who queued it for another account.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `queue`, `change_log` | `server` | |
| `owner_id` | INTEGER NN FK users | account id | The account the request is for. | never | `queue` (scoped to the account) | `server` (from the request) | |
| `url` | TEXT NN | URL of the ad | The ad to research. | never | `queue`, `admin` | `UI` (`POST /api/requests`) | |
| `note` | TEXT | free text | The account's note. | none | `queue` | `UI` | |
| `status` | TEXT NN | `QUEUED`, `RUNNING`, `WAITING`, `DONE`, `SKIPPED`, `FAILED`, `CANCELLED` (CHECK, default `QUEUED`) | State of the request. `WAITING` = a unit waits for its stage (the data-model text omits it; the code uses it). `SKIPPED` also covers a retired unit such as `INSURANCE`. | never | `queue`, `admin` | `server`, `worker` (claim/finish), `UI` (cancel: `CANCELLED` only) | |
| `requested_at` | TEXT NN | datetime | When it was queued. | never | `queue` | `server` | |
| `claimed_at` | TEXT | datetime | When a worker claimed it. | not claimed yet | `queue`, `admin` | `worker` | |
| `finished_at` | TEXT | datetime | When it ended. | not finished | `queue`, `admin` | `worker`, `server` | |
| `worker` | TEXT | worker name | The worker that claimed it. | not claimed | `queue`, `admin` | `worker` | |
| `listing_id` | INTEGER FK listings | id | The car the request produced or updated. | not yet | `queue` | `worker`, `server` | |
| `result` | TEXT | free text | What the run reported. | not finished | `queue`, `admin` | `worker`, `server` | |
| `requested_by` | INTEGER FK users | admin account id | The admin who queued the request for another account (recorded, never a worker). | the account asked itself | `admin` | `server` | |
| `request_token_hash` | TEXT | SHA-256 hex | Hash of the per-request token of a running request (cleared when it ends). The token is never stored in clear. | no run is active | `server` (auth of the run) | `worker`, `server` | |
| `kind` | TEXT NN | `LISTING`, `FOLLOW_UP` (CHECK, default `LISTING`) | Listing request, or a follow-up. No follow-up is created any more (`docs/data-model.md`); the branch that reads it is still in `research_requests.py`. | never | `queue`, `worker` | `server` | LEGACY (`FOLLOW_UP` no longer created) |
| `flag_id` | INTEGER FK review_flags | id | The review flag a follow-up answered. | not linked | `queue` (returned in the row) | `server` (no longer created) | DEPRECATED (review flags retired, #397) |
| `attempts` | INTEGER NN | count, default 0 | How many runs the request has had (3 max, #218). | never | `queue`, `admin` | `server`, `worker` | |
| `missing` | TEXT | comma list of contract items | Contract items still missing after a run. | none missing or not graded | `queue`, `admin`, `todo` | `server`, `worker` | |
| `parent_id` | INTEGER FK research_requests | id | The listing request a unit row belongs to. Unique per parent and unit. | a parent (listing) request | `queue`, `server` | `server` | |
| `unit` | TEXT | `CAPTURE`, `VARIANT`, `GENERATION`, `GEN_MAINTENANCE`, `ENGINE`, `GEARBOX`, `TAX`, `LISTING`, `INSURANCE` (retired 2026-11-22: skipped), `RESEARCH_A`, `RESEARCH_B`, `ARBITER`, `MERGE` (CHECK) | The stage this row runs. | a request without units (the old single run) | `queue`, `worker` | `server` | |
| `level_id` | INTEGER | id of the level the unit researches | The variant, generation, engine or gearbox of the unit. | not a level unit | `queue`, `server` | `server` | |
| `shared_id` | INTEGER FK research_requests | id | The other request's identical open unit this one waits for (the same catalogue level is already being researched). Released when that unit ends (`research_requests.release_shared`). | not waiting for another unit | `queue`, `server` | `server` | |
| `scope` | TEXT (JSON) | JSON | The levels a two-run research unit covers. | not set | `worker`, `server` | `server` | |
| `usage` | TEXT (JSON) | JSON object of numbers: tokens, cost and time of the Claude run, summed over the attempts (#291) | Usage of the run. | not reported | `admin` | `worker` (`/api/worker/requests/<id>`) | |

### 36. `workers`

**Purpose:** the registered research workers (the desktop worker that runs `worker.py`). Created and switched off by an admin; each has its own token (stored as a hash).
**Owner scope:** admin only (not exported to accounts, `account.EXCLUDED`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `admin` | `server` | |
| `name` | TEXT NN UNIQUE | free text | The worker's name. | never | `admin`, `queue` | `admin` (`POST /api/admin/workers`) | |
| `token_hash` | TEXT UNIQUE | SHA-256 hex | Hash of the worker token. Heartbeat, claim and finish only. | never issued | `server` (auth) | `admin` (new token) | |
| `is_active` | INTEGER NN | 0 or 1 | 0 = switched off by the admin. | never (default 1) | `server` (auth), `admin` | `admin` | |
| `created_at` | TEXT NN | datetime | When it was registered. | never | `admin` | `server` | |
| `last_seen` | TEXT | datetime | Last heartbeat. The admin view shows `down` after 180 s without one. | never seen | `admin` | `worker` (heartbeat, claim) | |
| `state` | TEXT | `idle`, `working`, `error` (CHECK) | What the worker is doing. | never reported | `admin` | `worker`, `server` | |
| `request_id` | INTEGER FK research_requests | id | The request the worker is on. | idle | `admin` | `worker`, `server` | |
| `last_error` | TEXT | free text | Last error reported. | none | `admin` | `worker` | |
| `last_error_at` | TEXT | datetime | When the last error happened. | none | `admin` | `worker` | |

### 37. `research_findings`

**Purpose:** the staging area of a two-run research (`RESEARCH_A`, `RESEARCH_B`): every write a run makes is staged here, not in the catalogue, until the arbiter and the MERGE unit copy the agreed rows (`carlos/staging.py`).
**Owner scope:** per request (`parent_id`). Catalogue research only, no listing or personal data. The API shows the id as a negative number.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key (shown as a negative number to the run). | never | `stage`, `disputes` | `stage` | |
| `request_id` | INTEGER NN FK research_requests | id | The run's unit request. | never | `stage`, `merge` | `stage` | |
| `parent_id` | INTEGER NN FK research_requests | id | The listing request. | never | `stage`, `merge`, `disputes` | `stage` | |
| `run` | TEXT NN | `A`, `B` (CHECK also allows `C`) | Which of the two runs wrote it. | never | `disputes`, `merge` | `stage` | |
| `kind` | TEXT NN | `source`, `level`, `patch`, `fault`, `recall`, `job`, `check`, `observation`, `tyres`, `stats`, `flag` (CHECK) | What the row is. `stats` and `flag` belong to retired features (`reliability_stats`, review flags). | never | `disputes`, `merge` | `stage` | `stats`, `flag`: DEPRECATED (features retired) |
| `op` | TEXT NN | `insert`, `patch` (CHECK) | Insert a new row, or patch an existing one (`target_id` required). | never | `merge` | `stage` | |
| `target_table` | TEXT NN | a table name | The table the write goes to. | never | `merge` | `stage` | |
| `target_id` | INTEGER | id | The row a patch changes. | NULL for an insert | `merge` | `stage` | |
| `key` | TEXT NN | key | Natural key of the finding; unique per request while staged (`research_findings_key`). | never | `disputes`, `merge` | `stage` | |
| `level` | TEXT | level name (`variant`, `engine`, `generation`, ...) | Level the finding attaches to. | not a level finding | `merge` | `stage` | |
| `level_id` | INTEGER | id | Id of that level. | not a level finding | `merge` | `stage` | |
| `part` | TEXT | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` | Part of a fault or recall. | not a fault or recall | `disputes` | `stage` | |
| `component_code` | TEXT | `config.FAULT_COMPONENTS` code | Controlled component of a fault. | not a fault | `disputes` | `stage` | |
| `payload` | TEXT NN (JSON) | JSON object | The row as the run wrote it. | never | `disputes`, `merge` | `stage` | |
| `status` | TEXT NN | `STAGED`, `MERGED`, `SKIPPED`, `ARCHIVED` (CHECK, default `STAGED`) | State of the finding. | never | `merge`, `stage` | `stage`, `merge` (sets `MERGED`, `merged_id`) | |
| `merged_id` | INTEGER | id | The catalogue row the finding became. | not merged | `merge` | `merge` | |
| `created_at` / `updated_at` | TEXT NN | datetime | Times of the write and of the last status change. | never | `admin` | `stage`, `merge` | |

### 38. `research_matches`

**Purpose:** the comparison of run A and run B per finding key: whether they agree, and the arbiter's verdict on a dispute. Reads the findings; writes nothing to the catalogue itself.
**Owner scope:** per request (`parent_id`).

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key. | never | `disputes`, `merge` | `server` | |
| `parent_id` | INTEGER NN FK research_requests | id | The listing request. | never | `disputes`, `merge` | `server` | |
| `kind` | TEXT NN | as `research_findings.kind` | Kind of the finding compared. | never | `disputes` | `server` | |
| `key` | TEXT NN | key | Finding key compared. | never | `disputes`, `merge` | `server` | |
| `a_id` / `b_id` | INTEGER FK research_findings | ids | The run A and run B findings (at least one is set, CHECK). | the run did not write it | `disputes`, `merge` | `server` | |
| `outcome` | TEXT NN | `AGREED`, `DISPUTED`, `ONLY_A`, `ONLY_B` (CHECK) | Result of the comparison (tolerances in `config.STAGE_TOLERANCE`). | never | `disputes`, `merge` | `server` | |
| `diffs` | TEXT (JSON) | JSON | The fields that differ. | not set | `disputes` | `server` | |
| `material` | INTEGER 0 or 1 | 0, 1 | 1 = a difference that matters, by the rules of `staging._material` (design section 3.3; a price difference counts against `STAGE_MATERIAL_EUR`, 500 EUR). | 0 | `disputes`, `merge` | `server` | |
| `verdict` | TEXT | `A`, `B`, `BOTH`, `NEITHER`, `OWN` (CHECK) | The arbiter's verdict. `OWN` needs `verdict_id`. | not decided | `merge` | `disputes` (`PATCH /api/agent/disputes/<id>`, ARBITER token) | |
| `verdict_id` | INTEGER FK research_findings | id | The finding the verdict takes (or the own one). | not decided | `merge` | `disputes` | |
| `verdict_reason` | TEXT | English free text | Why. | none | `disputes`, `merge` | `disputes` | |
| `verdict_source_id` | INTEGER | id of a `sources` row | Source the arbiter used. | none | `merge` | `disputes` | |
| `merged` | TEXT (JSON) | JSON | The value the merge wrote. | not merged | `merge` | `server` | |
| `flag_id` | INTEGER FK review_flags | id | A review flag raised for the dispute. Flags are retired; the MERGE unit reports an unsettled dispute in its result instead. | not linked | none | none | DEPRECATED (review flags retired) |

### 39. `review_flags` (retired, #397 and #351)

**Purpose:** a problem a level needed a person or a worker to review (for example a statistic that disagrees with the faults). Retired: no new flags, no edits (403 on the agent API); kept because `research_requests.flag_id` and `research_matches.flag_id` refer to it.
**Owner scope:** shared or private (on a catalogue level).

All columns are **DEPRECATED**. Reason as above; read only by the Models page and the Dossier for old rows.

| Column | Type | Meaning (old rows) | Read by | Written by | Status |
|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | `models` | none | DEPRECATED |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | the level (exactly one, CHECK) | `models` | none | DEPRECATED |
| `kind` | TEXT NN | `STATS_MISMATCH`, `SOURCES_DISAGREE`, `FIX_UNCERTAIN`, `OTHER` | `models` | none | DEPRECATED |
| `what` | TEXT NN | what the problem is | `models` | none | DEPRECATED |
| `why` | TEXT NN | why it is a problem | `models` | none | DEPRECATED |
| `status` | TEXT NN | `OPEN`, `CLEARED` | `models` | none | DEPRECATED |
| `created_at` / `created_by` / `cleared_at` | TEXT | when and by whom it was raised and cleared | `models` | none | DEPRECATED |
| `owner_id` | INTEGER FK users | owner | auth scope | none | DEPRECATED |

### 40. `flag_reviews` (retired)

**Purpose:** a worker's review of a flag (confirmed or resolved). Retired with `review_flags`.
**Owner scope:** per flag (the view follows `review_flags`).

| Column | Type | Meaning (old rows) | Read by | Written by | Status |
|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | `models` | none | DEPRECATED |
| `flag_id` | INTEGER NN FK review_flags | the flag reviewed | `models` | none | DEPRECATED |
| `worker` | TEXT NN | the worker that reviewed | `models` | none | DEPRECATED |
| `review_date` | TEXT NN | `YYYY-MM-DD` (default today) | `models` | none | DEPRECATED |
| `outcome` | TEXT NN | `CONFIRMED`, `RESOLVED` | `models` | none | DEPRECATED |
| `conclusion` | TEXT NN | the conclusion | `models` | none | DEPRECATED |
| `finding` | TEXT NN | what was found | `models` | none | DEPRECATED |
| `source_id` | INTEGER FK sources | citation | `models` | none | DEPRECATED |

### 41. `change_log`

**Purpose:** the audit trail: one row per write through the API (who, what table, which row, the old and new values as JSON). A research run that writes too much in one run is flagged once in this log.
**Owner scope:** not owned by an account. The writer is in `user_id`; admins read it (`GET /api/admin/changes`). Excluded from the account export.

| Column | Type | Allowed values / unit | Meaning | NULL means | Read by | Written by | Status |
|---|---|---|---|---|---|---|---|
| `id` | INTEGER PK | row id | Primary key; the admin view pages by it. | never | `admin` | `server` | |
| `changed_at` | TEXT NN | datetime (default now) | When the write happened. | never | `admin` | `server` | |
| `table_name` | TEXT NN | a table name | The table written. | never | `admin` | `server` | |
| `row_id` | INTEGER NN | id | The row written. | never | `admin` | `server` | |
| `action` | TEXT NN | `insert`, `update`, `delete` (lower case, `agent.log_change`) | What was done. | never | `admin` | `server` | |
| `old_json` | TEXT | JSON object | The row before (update, delete). | NULL for an insert | `admin` | `server` | |
| `new_json` | TEXT NN | JSON object | The row after (or the data sent). | never | `admin` | `server` | |
| `user_id` | INTEGER FK users | account id | Who made the write (the account, or the admin that acted for it). | a write without a user (for example a worker's request) | `admin` (writer name) | `server` | |
| `request_id` | INTEGER FK research_requests | id | The research request whose token made the write. | not a research write | `admin`, `staging` (listing request check) | `server` | |

## Columns not used by the app

Marked in the tables above. Dropping a column is a migration with a backup (`migrate.py`), so none is dropped here; each
needs the owner's decision. The `DEPRECATED` list is the candidates for a later migration; `NO READER` columns are
written and kept as data.

**Retired tables** (all columns DEPRECATED): `reliability_items` (still read by old rows in `carlos/costs.py`),
`repair_risks`, `review_flags`, `flag_reviews`.

**DEPRECATED columns in live tables:**

| Table.column | Reason |
|---|---|
| `listings.lease_kind`, `lease_monthly_eur`, `lease_term_months`, `lease_km_per_year`, `lease_down_payment_eur`, `lease_fees_eur`, `lease_extra_km_eur`, `lease_fewer_km_eur`, `lease_includes` | Leasing is out of scope (#165); no reader. |
| `listings.engine_code_seen` | No reader and no writer in the capture script; the research reset comment says it is kept. |
| `listing_quotes.premium_min_eur` | Referenced nowhere in the code. |
| `recalls.window_known` | Referenced nowhere in the code. |
| `research_checks.named_codes` | Not written by the contract since #351 (`docs/data-model.md`). |
| `inspection_items.reliability_item_id` | Links to the retired `reliability_items`. |
| `research_requests.flag_id`, `research_matches.flag_id` | Link to the retired `review_flags`. |
| `research_findings.kind IN ('stats', 'flag')` | Features retired (`reliability_stats`, review flags). |
| `research_requests.kind = 'FOLLOW_UP'` (LEGACY) | No follow-up is created any more; the branch that reads it is still in the code. |
| `research_requests.unit = 'INSURANCE'` | Worker insurance quotes removed 2026-11-22; such rows are skipped. |

**NO READER columns** (written, read by no code): `listings.seller_address`, `listings.listing_date`, `listing_media.original_url`,
`listing_media.bytes`, `valuations.valued_date`, `faults.mechanism`, `faults.quote`, `faults.onset_km`, `faults.usage_source_id`,
`faults.share_low`, `faults.share_high`, `maintenance_items.labor_included`, `market_models.filters`,
`market_models.sample_json`. "No reader" means no
code names the column; the dossier and the API return whole rows, so a field can still reach a page without a name in
the code. Check that before dropping anything.

## Findings (not changed here)

Found while writing; this task changes only the documentation.

1. **NULL is counted as zero in the tyre cost.** `carlos/costs.py: tyre_cost` adds `fitting_per_set_eur or 0`, so an
   unknown fitting price is priced at 0, against the rule "unknown = NULL, never zero".
2. **`market_models` is not in `agent.ADMIN_TABLES`.** `check_writable` reserves the catalogue tables for admins; this
   one is not in that set, so `check_writable` does not refuse an account token for it. What owner the row gets from an
   account token was not traced here. Confirm the intent (the sample is per generation and engine, so it may be meant
   to be shared).
3. **`docs/data-model.md` is out of date** for `insurance_data` (it lists `premium_min_eur` and the Typklassen, dropped by
   migration 046), for `research_requests.status` (it omits `WAITING` and `SKIPPED`), and for the `engines` family
   columns (it does not mention `family` as legacy).
4. **Schema versus convention:** `source_id` has no foreign key in `observations`, `insurance_data`, `tax_data`,
   `reliability_items`, `maintenance_items` and `listings` (the other tables have one); `research_checks.archived` has no
   CHECK (the API keeps it 0 or 1); `observations.source_id` is nullable in the schema but required by the API.
5. **Legacy text beside a level id:** `vehicles.transmission` and `vehicles.body_style` are read by the research
   check and the Models page. They are kept on purpose; the table marks them LEGACY, not DEPRECATED.

## How this was checked

- Columns, types, CHECKs and defaults: `schema.sql` loaded into an in-memory SQLite database (`PRAGMA table_info`). No
  database file was opened; `data/` was not touched.
- Allowed values: `carlos/config.py` (`FUEL_TYPES`, `JOBS`, `FAULT_COMPONENTS`, `FREQUENCY_BANDS`, `RATING_SOURCES`,
  `QUOTE_PROFILE_KEYS`, ...) and `carlos/agent.py` (`FIXED_CODES`, `CODE_FORMATS`, `ADMIN_TABLES`, `RETIRED_TABLES`).
- Readers: `carlos/auth.py` (per-owner views), `carlos/server.py` (routes), `carlos/costs.py`, `carlos/models.py`,
  `carlos/todo.py`, `carlos/research.py`, `carlos/staging.py`, `carlos/research_requests.py`, `carlos/chance.py`,
  `carlos/quotes.py`, `markdown_export.py`, and `static/js/pages/*.js`, matched by table and column name.
- Writers: `carlos/agent.py` (`clean_row`, `agent_write`, `check_writable`), `agent_tools.py`, `capture_listing.py`,
  `carlos/server.py` (`ui_write`), `carlos/chance.py`, `carlos/quotes.py`, `carlos/research_requests.py`.
- Column coverage: every column of every table in the 41 sections is named (the level columns are named in full in
  each knowledge table).
