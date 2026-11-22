# Data dictionary: knowledge, accounts, research queue and change log

Scope: the 26 tables of `schema.sql` (user_version 49) that are not part of the catalogue or the listings group. The other 20 tables (catalogue: `generations`, `engines`, `vehicles`, `engine_families`, `gearboxes`, `gearbox_families`, `body_styles`, `options`, `catalogue_links`; listings: `listings`, `listing_snapshots`, `listing_media`, `valuations`, `unit_costs`, `maintenance_resets`, `listing_history`, `listing_quotes`, `listing_options`, `inspection_items`, `listing_events`) are documented elsewhere. Tables covered here: the knowledge tables (16), accounts and settings (7), the two research parts (2) and `change_log`.

Sources of truth: `schema.sql` and `migrations/` (columns, types, CHECK constraints), `carlos/config.py` (controlled codes, bands, jobs, rating sources), `carlos/agent.py` (`CODE_FORMATS`, `FIXED_CODES`, `AGENT_TABLES`, `RETIRED_TABLES`, validation), `carlos/auth.py` (view scoping), `carlos/server.py` (routes), `agent_tools.py` (writer helpers). Every column was checked against a schema built in memory from `schema.sql`; no database or data file was read.

## How to read the tables

- **Column tables.** Each table lists its columns with the SQL type, the allowed values or unit, the meaning, and what NULL means. "NULL = unknown" is the rule for every figure (AGENTS.md: unknown is never 0). Where NULL means "none" (a flag or an optional link) the table says so.
- **Read by / written by** are stated once per table and apply to every column, unless the column's meaning cell names a different reader or writer. Names used:
  - `calc`: the cost and ranking calculation (`carlos/costs.py`, `carlos/ranking.py`), reached through `GET /api/tco`, `GET /api/listings/<id>`, `GET /api/ranking`.
  - `variant`: `GET /api/vehicles/<id>` (`carlos/models.py: variant_detail`); `models`: `GET /api/models` (row counts per variant).
  - `contract`: the research contract (`carlos/research.py`), read by `GET /api/todo`, `GET /api/agent/todo` and on every worker finish.
  - `dossier`: the Markdown dossiers (`markdown_export.py`, written to `data/dossiers/<account>/`).
  - `raw`: `GET /api/admin/data/<table>` (admin token; every account's rows).
  - `agent API`: `POST` / `PATCH /api/agent/<table>` with an admin token (the shared research worker or an admin agent). It validates codes, `source_id` and the level columns, and writes a `change_log` row.
  - `helper`: a function in `agent_tools.py`, named in the table.
  - `staging`: research runs RESEARCH_A, RESEARCH_B and ARBITER write to `research_findings` (`carlos/staging.py`); the MERGE unit writes the agreed findings through the same validation.
- **Owner scope.** `owner_id` NULL on a knowledge row means the shared catalogue, when its level is catalogue (shared by every account and reached through `catalogue_links`). A value means a private row of that account (insurance premiums, `USER DATA`). Views filter by account (`carlos/auth.py: VIEWS`); `<table>_all` also shows archived rows.
- **Level rule (knowledge tables).** A knowledge row attaches to exactly one level: `vehicle_id` (variant), `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id` or `option_id`. The SQL CHECK constraint enforces "exactly one" on `faults`, `recalls` and `research_checks`; `maintenance_items` allows at most one (none = a global default); `observations`, `insurance_data`, `tax_data`, `tyre_data`, `repair_risks` and `reliability_items` allow exactly one of `vehicle_id`, `engine_id`, `generation_id`. A listing inherits the rows of its variant and of every level above it (`carlos/db.py: for_variant`). The API returns the level of every row (`level`).
- **Archive, do not delete.** Tables with `archived` (0/1) hide archived rows from every read and calculation; `archived=0` restores one. Deletion through the API is owner-confirmed only (AGENTS.md).
- **Retired tables** (`reliability_items`, `repair_risks`, `review_flags`, `flag_reviews`) take no new rows and no edits except `archived` (`carlos/agent.py: RETIRED_TABLES`). They are documented under their own headings.

## Knowledge tables

### faults

**Purpose:** one fault of a part of a car (what fails, when, how often, what it costs to fix), priced per level; the calculation's expected repair cost is built from it.
**Owner scope:** shared when `owner_id` is NULL on a catalogue level; private otherwise. The server refuses a second similar fault on one variant with 409 (#221).
**Read by:** `calc` (fault plan, repair cost, severity, checklist), `variant`, `models` (count), `contract`, `dossier`, `raw`.
**Written by:** `agent API` (admin token) and `helper` `fault()`; `staging` (kind `fault`) for research runs.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | row id | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | exactly one non-NULL | the level the fault applies to | (the other seven are NULL) |
| `component` | TEXT NOT NULL | free text, English | readable component name, e.g. "Timing chain" | required |
| `part` | TEXT NOT NULL | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` (`config.RELIABILITY_PARTS`) | the part of the car the fault belongs to; `component_code` must be a code of this part | required |
| `issue` | TEXT | free text, English | the fault as described by the source | not stated |
| `mechanism` | TEXT | free text, English | how the part fails | not stated (read by no calculation) |
| `inspection_action` | TEXT | free text, English | what to check at a viewing; a fault gets a checklist item only when this is set (`contract`, `calc` checklist) | no checklist item |
| `consequence` | TEXT NOT NULL | `ENGINE_DAMAGE`, `STRANDS`, `SAFETY`, `UNUSABLE`, `COST`, `COSMETIC` | what the fault does when it happens; drives the severity (see Status and quality codes) | required |
| `parts_eur` | REAL ≥ 0 | EUR, workshop parts price | parts of the workshop repair | unknown (never 0); the fault's cost is then unknown |
| `labor_eur` | REAL ≥ 0 | EUR, workshop labour | labour of the workshop repair | unknown |
| `diy_parts_eur` | REAL ≥ 0 | EUR | parts for an owner who does the job (used when the account's DIY choice covers `job`) | unknown; the workshop price applies |
| `diy_hours` | REAL ≥ 0 | hours | the owner's time; shown, never priced | unknown |
| `existence` | TEXT NOT NULL | `CONFIRMED`, `REPORTED` | confirmed by a source that documents it, or only reported | required |
| `curve_km` | TEXT (JSON) | `[[km, share], …]`, km rising, share 0–1 never falling | cumulative share of cars failed by that mileage; the stated curve replaces the shape (`calc`) | no stated curve: `shape` and the band give one |
| `curve_age` | TEXT (JSON) | `[[years, share], …]` | same, by age | no stated age curve |
| `probability_basis` | TEXT | `STATISTIC`, `EXPERT`, `ESTIMATE` | how the share was obtained | not stated |
| `usage_flags` | TEXT | comma list of upper-case codes, e.g. `SHORT_TRIPS` | usage that changes the share | none |
| `usage_multiplier` | REAL > 0 | factor on the share | applied when `SHORT_TRIPS` (heavy use, `driving_mix` = "Mostly town") (`calc`); needs `usage_source_id` | no multiplier |
| `usage_source_id` | INTEGER FK sources | | the source of the multiplier (required with `usage_multiplier`) | |
| `applies_from`, `applies_to` | TEXT | `YYYY` or `YYYY-MM`, first registration | build window; a listing inherits the row only when its first registration falls inside (`in_window`) | NULL = any car; an unknown registration keeps the row |
| `window_uncertain` | INTEGER 0/1, default 0 | | set to 1 by the server when a window is given from a source that is not A or B | 0 = not uncertain |
| `source_id` | INTEGER NOT NULL FK sources | | the source the fault cites | required on write |
| `notes` | TEXT | English | free notes | none |
| `archived` | INTEGER 0/1, default 0 | | archived rows are hidden from every read | |
| `owner_id` | INTEGER FK users | | NULL = shared catalogue row; set = private row of that account | shared |
| `frequency_band` | TEXT | `systemic`, `widespread`, `common`, `occasional`, `rare` (`config.FREQUENCY_BANDS`) | the share band of the fault (central value used when no curve is stated) | no band: no share, the fault cannot be priced |
| `share_low`, `share_high` | REAL 0–1 | share of cars affected | the band's range, filled from the band by the server (`fault_checks`) | unknown |
| `shape` | TEXT | `WEAR_KM`, `AGE`, `WINDOW`, `RANDOM` (`config.FAULT_SHAPES`) | the curve form used when no curve is stated (see Status and quality codes) | no shape: no curve from the band |
| `window_km` | INTEGER > 0 | km | `WINDOW` shape: the km by which the share is reached | 100,000 km is used by the calculation |
| `onset_km` | INTEGER ≥ 0 | km | **DEPRECATED / unused:** the protocol describes it for `WINDOW`, but no calculation reads it (`WINDOW` uses `window_km` only) | |
| `manufacturer_trace` | TEXT | free text, English | evidence of a manufacturer response (extended warranty, Kulanz, TPI, class action); required for band `systemic` (`fault_checks`) | no trace: the band cannot be `systemic` |
| `fixed_fault_id` | INTEGER FK faults | | the fault whose curve follows the replacement part once this one is fixed (`calc`) | no replacement link |
| `warranty_km` | INTEGER > 0 | km | extended warranty: km limit | no warranty cover |
| `warranty_years` | REAL > 0 | years | extended warranty: time limit | |
| `warranty_share` | REAL (0, 1] | share of the price paid by the manufacturer | applies while the warranty covers the car (`calc`) | |
| `quote` | TEXT | verbatim wording of the source | evidence for the band; kept for the audit | not stated; no calculation reads it |
| `component_code` | TEXT | one of `config.FAULT_COMPONENTS[part]` (51 codes: ENGINE 16, GEARBOX 11, CHASSIS 13, ELECTRICS 11; each part ends with `OTHER`, which needs `notes`) | controlled component; the reliability and checklist grouping; the server suggests a code from the name | NULL only on rows not yet back-filled (#221): the API requires it on insert |
| `job` | TEXT | one of `config.JOBS` | the maintenance job the fault is done as: priced at `diy_parts_eur` for an owner whose DIY choice covers the job, else at the workshop price (`calc`) | no job: the fault is never a DIY job |

### recalls

**Purpose:** a manufacturer recall (campaign) that applies to a level; the car's status comes from the listing history, and the VIN check is a fixed checklist item.
**Owner scope:** as `faults`.
**Read by:** `calc` (recall weak points in the listing's reliability and checklist), `variant`, `models`, `contract` (`gen.recalls`), `dossier`, `raw`.
**Written by:** `agent API` (admin token); `staging` (kind `recall`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | exactly one non-NULL | the level | |
| `code` | TEXT NOT NULL | KBA reference (`KBA-14729R`) or `<MAKE>-<YYYY-MM>-<COMPONENT_CODE>`; never prose or "UNKNOWN" (`CODE_FORMATS`) | the campaign reference | required |
| `defect` | TEXT NOT NULL | free text, English | the defect the recall addresses | required |
| `remedy` | TEXT | free text, English | what the manufacturer does | not stated (read by no calculation) |
| `part` | TEXT | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` | the part | not stated |
| `safety` | INTEGER 0/1, default 0 | 1 = safety recall | recorded for the owner; **unused by the calculation**, which shows every recall as severity `HIGH IF APPLICABLE` (`calc`) | 0 |
| `applies_from`, `applies_to` | TEXT | `YYYY` or `YYYY-MM` | build window of the affected cars | NULL = any car |
| `window_known` | INTEGER 0/1, default 0 | | 1 = the build window is stated by the source; 0 = unknown | 0 |
| `source_id` | INTEGER NOT NULL FK sources | | the source (KBA or manufacturer) | required on write |
| `notes` | TEXT | English | | |
| `archived` | INTEGER 0/1, default 0 | | | |
| `owner_id` | INTEGER FK users | | NULL = shared; set = private | shared |

### maintenance_items

**Purpose:** a scheduled job or a wear part with its interval and price, at global, variant, engine, generation or family level. A job due at purchase is a certain maintenance cost of the listing (`unit_costs`), not a repair.
**Owner scope:** shared when `owner_id` NULL on a catalogue level. A row with no level is a **global default** (HU, brake fluid, labour rate) that a level row with the same `job` overrides (`carlos/costs.py: Knowledge.of`).
**Read by:** `calc` (maintenance plan, restart after a DONE job, DIY choice), `variant`, `models`, `contract` (matched by `job`), `dossier`, `raw`.
**Written by:** `agent API` (admin token); `helper` `item()` and `hu()`; `staging` (kind `job`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | at most one non-NULL (none = global default) | the level | global default |
| `item` | TEXT NOT NULL | free text, English | the job's name, e.g. "Timing belt kit with water pump" | required |
| `interval_km` | INTEGER | km | interval in km of the normal use | no km interval |
| `interval_months` | INTEGER | months | interval in months of the normal use | no time interval |
| `reference_cost_eur` | REAL | EUR, workshop price of the whole job (parts and labour) | the workshop price | unknown: an account that uses the workshop has no price (the item becomes a to-do, never 0) |
| `diy_parts_cost_eur` | REAL | EUR, parts only | the price when the owner does the job (used when the job is in the account's DIY choice) | unknown |
| `labor_included` | INTEGER | 0/1 | written by `item()` (0 for a DIY job, 1 otherwise) | **DEPRECATED / unused:** no calculation reads it; `reference_cost_eur` is the workshop price by definition |
| `status` | TEXT | e.g. `OFFICIAL FEE LEVEL`, `VERIFIED`, `ESTIMATED`, `PENDING` (see Status and quality codes) | how certain the interval and price are | not stated |
| `source_id` | INTEGER FK sources | | the source of the interval and price | required on write |
| `notes` | TEXT | English | derivation (e.g. the reason for a shortened preventive interval) | |
| `schedule` | TEXT NOT NULL, default `PACKAGE` | `PACKAGE`, `ITEM` | **DEPRECATED (legacy):** the calculation prices only `ITEM` rows (`costs.py` skips `PACKAGE`); `item()` always writes `ITEM` | |
| `diy` | INTEGER 0/1, default 0 | | default DIY flag for rows **without** a `job`; rows with a `job` take the account's DIY choice (`config.DIY_JOBS`) | 0 |
| `diy_hours` | REAL ≥ 0 | hours | the owner's time for the job; shown, never priced | unknown |
| `active` | INTEGER 0/1, default 1 | | 0 = the job is not planned (the calculation skips it) | |
| `archived` | INTEGER 0/1, default 0 | | | |
| `owner_id` | INTEGER FK users | | NULL = shared; set = private | shared |
| `job` | TEXT | one of `config.JOBS`: `OIL_SERVICE`, `AIR_FILTER`, `CABIN_FILTER`, `SPARK_PLUGS`, `TIMING_DRIVE`, `COOLANT`, `BRAKE_FLUID`, `BRAKES_FRONT`, `BRAKES_REAR`, `BATTERY`, `BULBS`, `WIPERS`, `HU`, `FUEL_FILTER`, `DRIVE_BELT`, `CLUTCH`, `DRIVE_COOLANT`, `REDUCTION_GEAR_OIL`, `GEARBOX_OIL` | the job code: the research matches jobs by it and the DIY choice decides the price per job (`contract` and `calc`) | a job without a code is priced by its `diy` flag only |
| `applies_from`, `applies_to` | TEXT | `YYYY` or `YYYY-MM` | build window | any car |
| `kind` | TEXT NOT NULL, default `JOB` | `JOB`, `WEAR` | `WEAR` = a generic wear part (clutch, brakes, battery, bulbs, wipers) whose life is its interval | `JOB` |
| `interval_km_heavy` | INTEGER > 0 | km | heavy-use interval (short trips, `driving_mix` = "Mostly town"); replaces `interval_km` in that case (`calc`) | no heavy-use interval: the normal one applies |
| `interval_months_heavy` | INTEGER > 0 | months | heavy-use interval in months (same rule) | as above |

Notes: the calculation reads a maintenance row's `interval_*` only for `schedule='ITEM'` and `active=1`. Read by: `calc` for everything above.

### repair_risks (RETIRED, #397)

**Purpose (old):** a failure rate in a km window with a repair price. Replaced by `faults`, which carry a curve and a price. No cost code reads these rows any more.
**Status:** retired. The agent API refuses new rows and edits (only `PATCH {"archived": 0|1}` and an owner-confirmed `DELETE`).
**Read by:** `raw`; `research_reset.py` (the reset tool lists them). Nothing else.
**Written by:** nothing since #397.

| Column | Type | Meaning / status |
|---|---|---|
| `id`, `vehicle_id`, `engine_id`, `generation_id` | INTEGER | the level (exactly one) |
| `component` | TEXT NOT NULL | the component |
| `km_from`, `km_to` | INTEGER NOT NULL, `km_to > km_from`, `km_from ≥ 0` | km window of the risk |
| `probability` | REAL NOT NULL, 0–1 | probability within the window |
| `parts_eur`, `labor_eur` | REAL ≥ 0 | workshop price parts and labour (NULL = unknown) |
| `diy` | INTEGER 0/1, default 0 | DIY flag |
| `diy_hours` | REAL ≥ 0 | owner's hours |
| `status`, `evidence` | TEXT | status and evidence as in the other knowledge tables (not read) |
| `source_id` | INTEGER FK sources | source |
| `notes` | TEXT | |
| `archived`, `owner_id`, `job`, `applies_from`, `applies_to` | as in `faults` | `job` is the job code (not read by the calculation) |

### reliability_items (RETIRED, #351)

**Purpose (old):** a weak point of a car per part, with severity and a checklist action. Replaced by the priced `faults` and `recalls` and by the fixed reliability sources (`source_keys`, `source_ratings`).
**Status:** retired; `inspection_items.reliability_item_id` still points here, so the table is kept. Old rows are still read: the listing's reliability and checklist use them, and `is_recall` rows decide whether an open recall's check counts.
**Read by:** `calc` (listing reliability and checklist, legacy rows), `variant`, `dossier`, `raw`.
**Written by:** nothing (403 on the agent API since #397; archive and owner-confirmed delete still work).

| Column | Type | Meaning / status |
|---|---|---|
| `id`, `vehicle_id`, `engine_id`, `generation_id` | INTEGER | the level (exactly one) |
| `component` | TEXT NOT NULL | component |
| `issue`, `evidence` | TEXT | description and evidence (English) |
| `severity` | TEXT | legacy severity code (`HIGH`, `HIGH IF APPLICABLE`, `MEDIUM`, `LOW-MEDIUM`, `LOW`); the calculation now derives severity for faults |
| `frequency_status` | TEXT | legacy frequency wording; replaced by `faults.frequency_band` |
| `source_id` | INTEGER FK sources | source |
| `inspection_action` | TEXT | checklist action (the one a viewing checks) |
| `part` | TEXT | `ENGINE`, `GEARBOX`, `CHASSIS`, `ELECTRICS` |
| `is_recall` | INTEGER 0/1, default 0 | 1 = a recall row (the calculation still counts it for the listing's checklist) |
| `archived`, `owner_id`, `applies_from`, `applies_to` | as in `faults` | |

### review_flags (RETIRED, #351, #397)

**Purpose (old):** a problem to review on a level (a statistic that did not match, sources that disagree). Retired: the MERGE unit now reports an unsettled disagreement in its result instead of filing a flag.
**Status:** retired; the rows are kept because `research_requests.flag_id` and `research_matches.flag_id` point here. No new rows. The table has no `archived` column, so the only removal is an owner-confirmed delete.
**Owner scope:** as `faults`.
**Read by:** `variant` (`review_flags` of a variant, with their reviews), `calc` (the problems a listing's levels carry, in the dossier), `dossier`, `raw`.
**Written by:** nothing since #397.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | exactly one non-NULL | the level the flag is on | |
| `kind` | TEXT NOT NULL | `STATS_MISMATCH`, `SOURCES_DISAGREE`, `FIX_UNCERTAIN`, `OTHER` (CHECK) | the kind of problem | required |
| `what`, `why` | TEXT NOT NULL | English | the problem and why it matters | required |
| `status` | TEXT NOT NULL, default `OPEN` | `OPEN`, `CLEARED` (CHECK) | open until cleared | required |
| `created_at` | TEXT NOT NULL | datetime, default `datetime('now')` | when it was filed | |
| `created_by` | TEXT | the worker or agent name | who filed it | not stated |
| `cleared_at` | TEXT | datetime | when it was cleared | not cleared |
| `owner_id` | INTEGER FK users | | NULL = shared; set = private | shared |

### flag_reviews (RETIRED, #351, #397)

**Purpose (old):** the reviews recorded against a review flag (who, when, the outcome, the finding and its source).
**Status:** retired; kept (it references `review_flags` and is not dropped with the retired tables). No new rows.
**Owner scope:** through its flag (the view shows rows whose flag is visible).
**Read by:** `variant` and `dossier` (with the flag), `raw`.
**Written by:** nothing since #397.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `flag_id` | INTEGER NOT NULL FK review_flags | | the flag reviewed | required |
| `worker` | TEXT NOT NULL | the reviewer's name | who reviewed | required |
| `review_date` | TEXT NOT NULL, default `date('now')` | `YYYY-MM-DD` | when | |
| `outcome` | TEXT NOT NULL | `CONFIRMED`, `RESOLVED` (CHECK) | the verdict of the review | required |
| `conclusion`, `finding` | TEXT NOT NULL | English | the conclusion and what was found | required |
| `source_id` | INTEGER FK sources | | the source of the finding | not stated |

UNIQUE (`flag_id`, `worker`, `conclusion`): one review per reviewer and conclusion.

### observations

**Purpose:** a measured figure of a car. The primary consumption (one real-world source per drivetrain) is the only figure the calculation reads.
**Owner scope:** shared when `owner_id` NULL on a catalogue level; private otherwise.
**Read by:** `calc` (fuel cost, primary consumption only), `variant`, `dossier` (section "Model observations"), `contract` (`var.consumption`), `raw`.
**Written by:** `agent API` (admin token); `helper` `consumption()`; `staging` (kind `observation`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | exactly one non-NULL | the level | |
| `category` | TEXT NOT NULL | free text; the helper writes `consumption` | the kind of figure | required |
| `metric` | TEXT NOT NULL | `Autokostencheck average` (`config.PRIMARY_CONSUMPTION`, petrol, diesel, hybrid), `EVDB real consumption` (`config.PRIMARY_CONSUMPTION_EV`, electric, kWh/100 km), `Owner measured average` (a cross-check; no code reads it) | which figure | required |
| `value_num` | REAL | the figure: l/100 km or kWh/100 km | the value | unknown: fuel cost is unknown (never 0) |
| `value_text` | TEXT | free text | the figure as printed when it is not a number | not stated |
| `unit` | TEXT | e.g. `l/100 km`, `kWh/100 km` | unit of `value_num` | not stated |
| `sample_count` | INTEGER | cars in the source's sample | sample size | not stated |
| `min_value`, `max_value` | REAL | unit of `value_num` | range of the sample, carried with the figure | not stated |
| `status` | TEXT NOT NULL | `PRIMARY` (ICE), `ESTIMATED` (electric, with the derivation in `notes`) | how certain | required |
| `evidence_quality` | TEXT | `A`–`D` by convention (not checked in SQL) | quality grade of the source (see Status and quality codes) | not stated |
| `observed_date` | TEXT | `YYYY-MM-DD` | date of the reading | not stated |
| `source_id` | INTEGER | FK sources | the source | required on write |
| `notes` | TEXT | English | | |
| `archived` | INTEGER 0/1, default 0 | | | |
| `owner_id` | INTEGER FK users | | NULL = shared; set = private | shared |

Read by `calc` only through the row with `metric` equal to the primary metric of the car's fuel type (`costs.py: consumption`).

### tax_data

**Purpose:** the annual road tax (Kfz-Steuer) of a car, from the official calculator (BMF Kfz-Steuer-Rechner) or an estimate, with the inputs it was computed from.
**Owner scope:** shared on a catalogue level; private otherwise.
**Read by:** `calc` (tax component; the row with a registration window that covers the car is chosen, verified before estimated, then the newest), `variant`, `contract` (`var.tax`), `dossier`, `raw`.
**Written by:** `agent API` (admin token) and the TAX research unit (`carlos/research_units.py`, which writes its rows through the agent API; not a staged finding kind).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | exactly one non-NULL | the level | |
| `annual_tax_eur` | REAL | EUR per year | the tax | unknown: the tax component is unknown; a row with NULL is not chosen |
| `status` | TEXT | `VERIFIED` (official calculator), `ESTIMATED` (with the derivation in `basis`) | how certain | not stated |
| `basis` | TEXT | English | every input the figure was computed from, as AGENTS.md requires for an official calculator | not stated |
| `source_id` | INTEGER FK sources | | the source (source type `tax_official_calculator` for the BMF calculator) | required on write |
| `notes` | TEXT | English | | |
| `archived`, `owner_id` | as in `faults` | | | |
| `registered_from`, `registered_to` | TEXT | `YYYY-MM` | first-registration window the row applies to; a car is covered when its first registration falls inside (`costs.py: Knowledge.tax`) | NULL = any car |

Electric cars: the exempt months are computed by the calculation from `config.EV_TAX_EXEMPT_REGISTERED_BY` / `EV_TAX_EXEMPT_UNTIL` (`ev_tax_months`); a stored zero is not needed.

### tyre_data

**Purpose:** one set of all-season tyres per variant: size, price, life and fitting. The wear cost is km ÷ life × (set price + fitting).
**Owner scope:** as `observations`.
**Read by:** `calc` (tyres component), `contract` (`var.tyres`), `dossier`, `raw`.
**Written by:** `agent API` (admin token); `helper` `tyres()` (status `ESTIMATED`); `staging` (kind `tyres`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | exactly one non-NULL | the level | |
| `tyre_type` | TEXT NOT NULL, default `ALL-SEASON` | upper-case code | the tyre class | |
| `size` | TEXT | e.g. `205/55 R16` | tyre size of the variant when it differs | not stated |
| `price_per_tyre_eur` | REAL > 0 | EUR per tyre | median mid-range price | unknown: the tyres component is unknown |
| `tyres_per_set` | INTEGER > 0, default 4 | count | tyres per set | 4 (default) |
| `life_km` | INTEGER > 0 | km | tread life | unknown: the tyres component is unknown |
| `fitting_per_set_eur` | REAL ≥ 0 | EUR per set | fitting | unknown: counted as 0 by the calculation |
| `status` | TEXT | `ESTIMATED` (what the helper writes) | how certain | not stated |
| `source_id` | INTEGER FK sources | | the source | required on write |
| `notes` | TEXT | English | the derivation | |
| `archived`, `owner_id` | as in `faults` | | | |

### insurance_data

**Purpose:** a premium of a car: the premium the owner pays for the reference car (`USER DATA`) or a quote at variant level. Since migration 046 the automated comparison is gone; a listing's own premium is kept in `listing_quotes` (listing group), and this table is the fallback when a listing has none.
**Owner scope:** the premium the owner pays is private (`owner_id` set). Quotes entered by an account are kept in `listing_quotes`, not here.
**Read by:** `calc` (fallback premium when a listing has no quote; the reference car uses its own premium first), `variant`, `dossier`, `contract` (`lst.insurance`), `raw`.
**Written by:** `agent API` (admin token) only. The worker's insurance unit was removed on 2026-11-22.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id` | INTEGER FK | exactly one non-NULL | the level | |
| `hsn`, `tsn` | TEXT | the vehicle's type codes | the codes the premium belongs to | not stated |
| `year` | INTEGER | the insurance year | the year of the quote | not stated |
| `annual_premium_eur` | REAL | EUR per year | the quoted premium, or the premium paid (`USER DATA`) | unknown: no premium; the insurance component is unknown |
| `premium_status` | TEXT | `QUOTE`, `USER DATA`, `PENDING` | what the premium is | not stated |
| `insurer`, `tariff` | TEXT | the insurer and tariff of the cheapest offer | | not stated |
| `quote_date` | TEXT | `YYYY-MM-DD` (CHECK GLOB) | date of the quote; quotes expire after `config.QUOTE_MAX_AGE_DAYS` (60) days (the calculation still uses an expired one and marks the listing item MISSING) | not stated |
| `quote_profile` | TEXT (JSON object) | keys of `agent.QUOTE_PROFILE_KEYS` only: `cover`, `deductible_eur`, `excess_eur`, `sf_class`, `entered_period`, `annual_km`, `usage`, `parking`, `purchase_mode`, `workshop_binding`, `start_date`, `extra_drivers`, `hsn`, `tsn`, `first_registration` | the terms the quote was made for; other keys (names, birth dates, postcode, contact data) are dropped on write | not stated |
| `source_id` | INTEGER FK sources | | the source | required on write |
| `notes` | TEXT | English | | |
| `archived`, `owner_id` | as in `faults` | | | |

### research_checks

**Purpose:** the record that a research task of the contract was done on a level, with the source consulted and its result. A clean part counts as researched only with a check (`NONE FOUND` or `N/A`).
**Owner scope:** as `faults`.
**Read by:** `contract` (grades every level; `FOUND`/`NONE FOUND`/`N/A` from an A or B source count), `variant`, `dossier`, `raw`, `GET /api/todo` (missing items).
**Written by:** `agent API` (admin token); `helper` `check()`; `staging` (kind `check`, the MERGE unit).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | exactly one non-NULL | the level the task was done on | |
| `task` | TEXT NOT NULL | one of `research.TASKS`: `bdy.risks`, `eng.coolant`, `eng.drive_coolant`, `eng.hv_battery`, `eng.identity`, `eng.identity_ev`, `eng.oil`, `eng.reduction_gear_oil`, `eng.risks`, `eng.spark_plugs`, `eng.timing_belt`, `eng.timing_chain`, `fam.risks`, `gbx.clutch`, `gbx.identity`, `gbx.risks`, `gbx.service`, `gen.brake_fluid`, `gen.brakes`, `gen.facelift`, `gen.hu`, `gen.identity`, `gen.recalls`, `gen.risks`, `gen.safety`, `rel.adac`, `rel.adac_gwinfo`, `rel.autoscore`, `rel.enginescope`, `rel.tuev`, `var.consumption`, `var.gearbox_level`, `var.identity`, `var.tax`, `var.tyres` | the contract item the check answers | required |
| `source_id` | INTEGER NOT NULL FK sources | | the source consulted | required |
| `result` | TEXT NOT NULL | `FOUND`, `NONE FOUND` (consulted, nothing to report), `N/A` (does not apply, or the source does not cover the level) | the outcome | required |
| `contract_version` | INTEGER NOT NULL | the contract version (`research.CONTRACT_VERSION`, currently 10) | a check older than an item's `since` stops counting | set by the server on insert |
| `checked_date` | TEXT | `YYYY-MM-DD` | when the source was consulted | not stated |
| `notes` | TEXT | English | the reason for `N/A`, what was found | |
| `archived` | INTEGER, default 0 | 0/1 by convention (no CHECK in SQL) | archived checks are ignored by the contract | |
| `owner_id` | INTEGER FK users | | NULL = shared; set = private | shared |
| `named_codes` | TEXT (JSON array) | `config.FAULT_COMPONENTS` codes of the part | **DEPRECATED:** retired with contract v10 (`docs/cost-research-protocol.md`). The API still validates it and `agent_tools.check(codes=)` still writes it; no calculation reads it and no prompt passes it | not stated |

### source_keys

**Purpose:** links one level (engine or generation) to the page of a fixed external reliability source (Autoscore, EngineScope, TÜV-Report, ADAC Pannenstatistik, ADAC Gebrauchtwagen-Info). Written by hand from the owner's browser; nothing is scraped.
**Owner scope:** always shared (`owner_id` CHECK IS NULL).
**Read by:** `calc` (reliability slots of a listing), `contract` (`rel.*`), `GET /api/todo` (missing slots), `variant`, `dossier`, `raw`.
**Written by:** `agent API` (admin token); `helper` `source_key()`.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `source_key` | TEXT NOT NULL | `AUTOSCORE`, `ENGINESCOPE` (engine); `TUEV_REPORT`, `ADAC_PANNENSTATISTIK`, `ADAC_GWINFO` (generation) (`config.RATING_SOURCES`, checked by the API, not in SQL) | the source | required |
| `engine_id`, `generation_id` | INTEGER FK | exactly one non-NULL | the level | |
| `fuel_type` | TEXT | `Petrol`, `Diesel`, `Hybrid`, `Plug-in hybrid`, `Electric` (`ADAC_GWINFO` only) | the fuel of the GW-Info PDF | NULL = every fuel (the key applies to all) |
| `external_key` | TEXT NOT NULL | verbatim: a slug, a series name as printed, or a file name | the page's identifier at the source | required |
| `url` | TEXT NOT NULL | `https://…` (CHECK) | the page | required |
| `source_id` | INTEGER NOT NULL FK sources | | the source (quality per `config.RATING_SOURCES`: C for Autoscore and EngineScope, B for TÜV and ADAC) | required |
| `checked_date` | TEXT NOT NULL | `YYYY-MM-DD` | when the page was read | required |
| `notes` | TEXT | English | | |
| `archived` | INTEGER 0/1, default 0 | | a live key is unique per source, level and fuel (`ux_source_keys`) | |
| `owner_id` | INTEGER | always NULL (CHECK) | | shared |

### source_ratings

**Purpose:** what a fixed reliability source publishes for an `external_key`, verbatim: a risk score, a verdict, a band, a defect share. Engines that share one page store the rating once (the key is matched case-insensitively).
**Owner scope:** always shared (`owner_id` CHECK IS NULL).
**Read by:** `calc` (reliability score: mean of the slots with a figure; a missing source lowers coverage, it is never 0), `contract` (`rel.*`), `GET /api/todo`, `dossier`, `raw`.
**Written by:** `agent API` (admin token); `helper` `rating()`. A new edition inserts new rows and archives the old ones.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `source_key` | TEXT NOT NULL | as `source_keys.source_key` | the source | required |
| `external_key` | TEXT NOT NULL | as the key | the page the rating belongs to | required |
| `edition` | TEXT NOT NULL | report year, or the reading date for undated sources | which edition | required |
| `age_from`, `age_to` | INTEGER | years | TÜV age class (`age_to ≥ age_from`) | not an age class |
| `reg_year` | INTEGER | year | ADAC first-registration year (not with an age class, CHECK) | not a registration year |
| `value_num` | REAL ≥ 0 | Autoscore risk 0–10; EngineScope score 0–100 (only with permission); TÜV defect share in %; ADAC PKZ | the figure | unknown: the slot is missing, never 0 |
| `value_text` | TEXT | verdict or band as printed (Autoscore verdict verbatim) | the printed wording | not stated |
| `band` | INTEGER 1–5 | ADAC: 1 best, 5 worst | ADAC band | not an ADAC rating |
| `class_average` | REAL > 0 | % | TÜV average of the age class | not a TÜV rating |
| `cost_min_eur`, `cost_max_eur` | REAL ≥ 0 | EUR | EngineScope repair costs, only with `config.ENGINESCOPE_PERMISSION = SCORE_AND_COSTS` | always NULL until the owner holds EngineScope's written permission (the API refuses the figures before that) |
| `sample_count` | INTEGER > 0 | cars | sample size of the source | not stated |
| `url` | TEXT NOT NULL | `https://…` (CHECK) | the page | required |
| `source_id` | INTEGER NOT NULL FK sources | | the source | required |
| `checked_date` | TEXT NOT NULL | `YYYY-MM-DD` | when read | required |
| `notes` | TEXT | English | | |
| `archived` | INTEGER 0/1, default 0 | | one live row per source, key, edition and class or year (`ux_source_ratings`) | |
| `owner_id` | INTEGER | always NULL (CHECK) | | shared |

The slot each source feeds: `AUTOSCORE` and `ENGINESCOPE` → `ENGINE`; `TUEV_REPORT` → `HU`; `ADAC_PANNENSTATISTIK` → `BREAKDOWNS`; `ADAC_GWINFO` has no slot (keys only). The reliability score is computed at calculation time and never stored.

### market_models

**Purpose:** the resale value of a model (generation + engine, optionally gearbox) from a sample of cars for sale: the value at a reference age and mileage and the share lost per year and per 10,000 km. It replaces a listing's own resale valuation when the sample is usable (≥ 5 cars in each of three bands, sampled within 183 days).
**Owner scope:** shared (`owner_id` NULL) or private to an account.
**Read by:** `calc` (resale value at the end of the ownership period, less the private-sale discount), `raw`. Shown only through the calculation.
**Written by:** `agent API` (admin token); no helper in `agent_tools.py`.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `generation_id` | INTEGER NOT NULL FK | | generation of the sample | required |
| `engine_id` | INTEGER NOT NULL FK | | engine of the sample | required |
| `gearbox_id` | INTEGER FK | | gearbox of the sample | NULL = any gearbox |
| `value_ref_eur` | REAL NOT NULL > 0 | EUR | value at the reference age and km | required |
| `ref_age_years` | REAL NOT NULL | years | age of the reference value | required |
| `ref_km` | INTEGER NOT NULL | km | mileage of the reference value | required |
| `rate_year` | REAL NOT NULL, 0 ≤ x < 1 | share per year | share of value lost per year | required |
| `rate_10k_km` | REAL NOT NULL, 0 ≤ x < 1 | share per 10,000 km | share of value lost per 10,000 km | required |
| `band_counts` | TEXT NOT NULL (JSON array) | three counts | cars in each of the three age/km bands | required |
| `sample_date` | TEXT NOT NULL | `YYYY-MM-DD` | date of the sample (usable for 183 days) | required |
| `filters` | TEXT | English | search filters of the source | not stated |
| `sample_json` | TEXT (JSON array) | | the sampled cars as the source lists them | not stored |
| `source_id` | INTEGER NOT NULL FK sources | | the source | required |
| `notes` | TEXT | English | | |
| `archived`, `owner_id` | as in `faults` | | | |

### sources

**Purpose:** every external data point cites one source row: URL, access date, quality A–D, what it supports and its limitations. A source attaches to at most one level, or to none (shared sources such as the HU fee table, global when `owner_id` is NULL).
**Owner scope:** shared (`owner_id` NULL) or private (user data, a listing's own page, which the listing-group tables reference).
**Read by:** every table through `source_id`; `calc` (grades in the research contract); `variant` (`sources` of the variant); `GET /api/sources` (visible sources); `dossier` (the sources list); `raw`.
**Written by:** `agent API`: an admin token for level sources and shared sources; a non-admin account token may write level-free sources of its own (`agent.check_writable`). `helper` `src()`.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `vehicle_id`, `engine_id`, `generation_id`, `gearbox_id`, `engine_family_id`, `gearbox_family_id`, `body_style_id`, `option_id` | INTEGER FK | at most one non-NULL (the SQL CHECK covers the first three; the agent API checks all eight) | the level the source belongs to | none = shared or account-level |
| `title` | TEXT NOT NULL | free text | the source's name | required |
| `url` | TEXT | URL | the page | not stated |
| `source_type` | TEXT | free text; codes in use: `tax_official_calculator`, `fees_official`, `fees_secondary`, `depreciation_reference`, `parts_prices`, `tyres_reference`, `user_data` (quality D, the owner's own entries), `user_reported` | the kind of source | not stated |
| `quality` | TEXT | `A`, `B`, `C`, `D` (CHECK in the agent API) | the grade (see Status and quality codes) | not graded: a row from it can be ACCEPTED at most, never VERIFIED |
| `accessed_date` | TEXT | `YYYY-MM-DD` | when the page was read | not stated |
| `supports` | TEXT | English | what the source supports | not stated |
| `limitations` | TEXT | English | what the source does not establish | not stated |
| `owner_id` | INTEGER FK users | | NULL = shared or global; set = the account's own | shared |

## Accounts and settings

### users

**Purpose:** the accounts. Every account owns its data (`owner_id`); admins also hold the agent token of the shared research worker and of admin agents.
**Owner scope:** global table (no owner column). Hashes are never returned by the API.
**Read by:** the login check (`auth`), `GET /api/auth/me`, `GET /api/admin/users` (public fields only: id, username, role, is_active, has_password, has_token, created_at), `GET /api/admin/data/users` (id, username, role, is_active, created_at).
**Written by:** `POST /api/admin/users` (create, with an invite link), `PATCH /api/admin/users/<id>` (`is_active`, `role`; deactivation deletes the account's sessions), `DELETE /api/admin/users/<id>` (erasure after an export, typed username), `POST /api/auth/invite/<token>` (password set), `POST /api/account/password`, `POST /api/account/token` (new agent token), and the start-up bootstrap (the first admin's token from `.env`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `username` | TEXT NOT NULL, UNIQUE | 2–40 characters | login name | required |
| `password_hash` | TEXT | `scrypt$<salt>$<hash>` | password, hashed with scrypt | NULL = no password yet: the account must use its invite link |
| `role` | TEXT NOT NULL, default `user` | `admin`, `user` | admins may use agent tokens and see every account | |
| `is_active` | INTEGER 0/1, default 1 | | 0 = cannot log in, no session works | |
| `api_token_hash` | TEXT | SHA-256 hex of the agent token | the account's agent token (admins only) | NULL = no agent token |
| `created_at` | TEXT NOT NULL | `YYYY-MM-DD HH:MM:SS` (UTC, `datetime('now')`) | account creation | |

### sessions

**Purpose:** a login session of one account (cookie `carlos_session`); the cookie value itself is never stored.
**Owner scope:** per user (`user_id`).
**Read by:** every authenticated request (`auth`: the session must be unexpired and the user active).
**Written by:** login (`POST /api/auth/login`), logout (`POST /api/auth/logout` deletes the row), the password change (other sessions deleted; the current one kept), deactivation and invite use (all sessions of the user deleted). Expired rows are removed at the next login.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | TEXT PK | SHA-256 hex of the cookie value | the session | |
| `user_id` | INTEGER NOT NULL FK users | | the account | required |
| `created_at` | TEXT NOT NULL | UTC datetime | when the session started | |
| `expires_at` | TEXT NOT NULL | UTC datetime; 30 days after login (`auth.SESSION_DAYS`) | end of the session | required |

### invites

**Purpose:** one-time links for an account to set its password (a new account, or a reset). The link is valid for 72 hours (`auth.INVITE_HOURS`).
**Owner scope:** per user (`user_id`); `created_by` is the admin who issued it.
**Read by:** `GET /api/auth/invite/<token>` (the set-password page) and the password POST that uses it.
**Written by:** `POST /api/admin/users` and `POST /api/admin/users/<id>/invite` (a new link deletes the account's unused ones); the start-up bootstrap for users without a password.

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | TEXT PK | SHA-256 hex of the token | the invite | |
| `user_id` | INTEGER NOT NULL FK users | | the account the password is set for | required |
| `created_by` | INTEGER FK users | | the admin who issued it | NULL = issued at start-up (bootstrap) |
| `created_at` | TEXT NOT NULL | UTC datetime | | |
| `expires_at` | TEXT NOT NULL | UTC datetime, 72 h after creation | end of validity | required |
| `used_at` | TEXT | UTC datetime | when the password was set (a used link is refused) | NULL = not yet used |

### project_parameters

**Purpose:** the owner's calculation parameters of one account: period, km, fuel and electricity prices, budget, origin of the distance, the ranking answers and weights, and the charging situation of an electric car.
**Owner scope:** one row per account (`owner_id` UNIQUE). Created with the account (`auth.create_user`).
**Read by:** `calc` (every cost and the ranking), `GET /api/parameters`, `GET /api/tco?<param>=` (preview, not saved), `dossier`, `GET /api/todo` (setup items), `raw`.
**Written by:** `POST /api/parameters` (the Setup wizard and Settings; validated by `server.clean_params`), and the account creation (`fuel_price_date` set to today).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `owner_id` | INTEGER NOT NULL UNIQUE FK users | | the account | required |
| `annual_km` | INTEGER NOT NULL, default 15000 | km per year | distance per year | required (the default applies) |
| `ownership_years` | INTEGER NOT NULL, default 4 | years | the period of the total cost of ownership | required (the default applies) |
| `fuel_price_eur_l` | REAL NOT NULL, default 1.8 | EUR per litre, petrol | the price used for petrol cars; the to-do flags it when undated or older than 30 days (`config.STALE_FUEL_PRICE_DAYS`) | required (the default applies) |
| `fuel_price_date` | TEXT | `YYYY-MM-DD` | when the petrol price was set | not stated (the price is then not dated) |
| `diesel_price_eur_l` | REAL > 0 | EUR per litre | diesel price | unknown: a diesel car's fuel cost is unknown |
| `diesel_price_date` | TEXT | `YYYY-MM-DD` | when the diesel price was set | not stated |
| `budget_ideal_eur` | REAL > 0 | EUR | the ideal price (budget criterion) | no budget criterion |
| `budget_max_eur` | REAL > 0 | EUR | the maximum price; above it a listing is excluded when `exclude_over_max` is not 0 | no maximum |
| `postal_code` | TEXT | five digits | origin of the distance to a listing | the distance is unknown |
| `purchase_mode` | TEXT | `cash`, `financing` (the Setup choice) | how the car is bought | stored only: no calculation reads it |
| `currency` | TEXT, default `EUR` | | **DEPRECATED / unused:** no code reads or writes it; every amount is EUR | |
| `ranking_weights` | TEXT (JSON object) | criterion → integer 0–5 | the owner's weights; NULL = derived from the answers (`ranking.py`) | derived from `ranking_answers` |
| `ranking_answers` | TEXT (JSON object) | the best–worst questionnaire answers | the answers the weights are derived from | not answered |
| `home_charging` | TEXT | `none`, `socket`, `wallbox`, `wallbox_planned` | electric cars: the home charging situation | not stated |
| `home_charging_pct` | INTEGER 0–100 | % | share of the energy charged at home | not stated |
| `electricity_home_eur_kwh` | REAL > 0 | EUR per kWh | home electricity price | unknown: the energy cost of electric cars is unknown |
| `electricity_home_date` | TEXT | `YYYY-MM-DD` | when it was set | not stated |
| `electricity_public_eur_kwh` | REAL > 0 | EUR per kWh | public charging price | unknown |
| `electricity_public_date` | TEXT | `YYYY-MM-DD` | when it was set | not stated |
| `wallbox_cost_eur` | REAL ≥ 0 | EUR | the planned wallbox | not stated |
| `acquisition_mode` | TEXT | `buy`, `lease`, `both` (CHECK) | **DEPRECATED:** from migration 024 (leasing), removed with leasing (#165); no code reads or writes it | |
| `lease_rate_max_eur` | REAL > 0 | EUR per month | **DEPRECATED:** the leasing rate limit (#165); no code reads or writes it | |
| `exclude_over_max` | INTEGER 0/1 | 1 = cars over the maximum budget are not ranked | the ranking excludes them unless the value is 0 (`ranking.py`: `!= 0`) | NULL = excluded (the default) |
| `drivers_count`, `driver_age`, `sf_class`, `insurance_cover`, `insurance_deductible_eur` | | | removed by migration 046 (2026-11-22, the insurance comparison was removed) | |

### project_preferences

**Purpose:** free settings of an account as key–value pairs: the setup answers (search area, preferred fuel, DIY jobs, driving mix, current car, onboarding state) that agents read before they ask again.
**Owner scope:** per account (`owner_id`, default 1 in SQL; the API always sets the account).
**Read by:** `calc` (`diy_jobs` for the DIY choice of each job, `driving_mix` for heavy use), `GET /api/todo` (setup items), `GET /api/preferences`, `dossier`, `raw`.
**Written by:** `POST /api/preferences` (upsert of `{key: value}`; `null` or empty removes the key), by the Setup wizard and Settings, and by agents for the owner. The API refuses `insurance_worker_quotes` (2026-11-22).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `owner_id` | INTEGER NOT NULL DEFAULT 1 FK users | | the account | |
| `preference_key` | TEXT NOT NULL | snake_case, `[a-z][a-z0-9_]{0,49}` | the setting's name; PRIMARY KEY with `owner_id` | required |
| `preference_value` | TEXT | English or plain text, up to 1000 characters | the value. Keys read by code: `diy_jobs` (comma list of DIY choices or `none`; `config.DIY_JOBS`) and `driving_mix` (`Mostly town` = heavy use) by `calc`; `onboarding_done` (date, or `skipped`) by `GET /api/todo` | removed (the API deletes the row on null) |
| `unit` | TEXT | | **DEPRECATED / unused:** no writer, no reader | |
| `status` | TEXT | | **DEPRECATED / unused:** no writer, no reader | |
| `notes` | TEXT | | **DEPRECATED / unused:** no writer, no reader | |

Other keys (`search_center`, `search_radius`, `preferred_fuel`, `preferred_transmission`, `current_car`, older free-text keys) are read by people and agents, not by a calculation. The insurance profile keys written before 2026-11-22 were deleted by migration 046.

### workers

**Purpose:** the registered research workers (`worker.py` on the owner's desktop): a worker has its own token, claims one request at a time and reports its state.
**Owner scope:** global; created and switched off by an admin.
**Read by:** `GET /api/admin/workers` (without the token hash), `GET /api/admin/data/workers`, the queue's worker-down check (no heartbeat for 180 s).
**Written by:** `POST /api/admin/workers` (create; the token is shown once), `POST /api/admin/workers/<id>/token` (new token; the old one stops working), `PATCH /api/admin/workers/<id>` (`is_active`), `POST /api/worker/heartbeat` (`last_seen`, `state`, `last_error`), `POST /api/worker/claim` (`state`, `request_id`), and the finish of a request (`state` back to `idle`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `name` | TEXT NOT NULL, UNIQUE | 2–40 characters | the worker's name | required |
| `token_hash` | TEXT UNIQUE | SHA-256 hex of the worker token | the worker's token (heartbeat, claim and finish only) | NULL = no token |
| `is_active` | INTEGER 0/1, default 1 | | 0 = the worker cannot claim | |
| `created_at` | TEXT NOT NULL | UTC datetime | | |
| `last_seen` | TEXT | UTC datetime | last heartbeat or claim | never seen |
| `state` | TEXT | `idle`, `working`, `error` (CHECK) | the worker's state | not reported |
| `request_id` | INTEGER FK research_requests | | the request it works on | NULL = none |
| `last_error` | TEXT | English | the last error reported | none |
| `last_error_at` | TEXT | UTC datetime | when | none |

### research_requests

**Purpose:** the research queue. An account (or an admin for it) queues a listing URL; the shared worker claims it, researches it, writes the car to the requester's account and finishes it. A listing request is split into units (`parent_id`, `unit`) that run in stages.
**Owner scope:** `owner_id` = the account whose car it is; `requested_by` = the admin who queued it for that account (NULL = the account itself). Units share their parent's owner.
**Read by:** `GET /api/requests` (the account's parents with their units), `GET /api/admin/requests` (everything), `POST /api/worker/claim`, `GET /api/agent/stage` and `disputes` (the research runs), the requests panel of the UI (`static/js/requests.js`, through `GET /api/requests`), `raw`.
**Written by:** `POST /api/requests` (create), `PATCH /api/requests/<id>` (an account may cancel only), the worker's claim and finish (`POST /api/worker/requests/<id>`), and the internal stage advance (`carlos/research_requests.py`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `owner_id` | INTEGER NOT NULL FK users | | the account the car belongs to | required |
| `url` | TEXT NOT NULL | https listing URL, cleaned by `urlcheck` | the listing to research | required |
| `note` | TEXT | free text (the requester's words) | a note for the worker | none |
| `status` | TEXT NOT NULL, default `QUEUED` | `QUEUED` (waiting), `RUNNING` (claimed), `WAITING` (a listing request whose capture is done, or a unit waiting for a shared unit), `DONE`, `SKIPPED` (a unit that no longer runs, e.g. the removed insurance unit), `FAILED` (no complete result after `MAX_ATTEMPTS` = 3 reports, or a unit that failed), `CANCELLED` | the state | required |
| `requested_at` | TEXT NOT NULL | UTC datetime | when it was queued | |
| `claimed_at` | TEXT | UTC datetime | when a worker claimed it | not claimed |
| `finished_at` | TEXT | UTC datetime | when it ended | not ended |
| `worker` | TEXT | the worker's name | who runs or ran it | not claimed |
| `listing_id` | INTEGER FK listings | | the listing created or updated | not yet created |
| `result` | TEXT | English summary | the outcome or the reason it failed or was refused | none yet |
| `requested_by` | INTEGER FK users | | the admin who queued it for the account (`X-Carlos-Account`) | NULL = the account itself |
| `request_token_hash` | TEXT | SHA-256 hex | the per-request token of a `RUNNING` request; cleared when it ends | not running |
| `kind` | TEXT NOT NULL, default `LISTING` | `LISTING`, `FOLLOW_UP` (CHECK) | **DEPRECATED:** `FOLLOW_UP` belonged to the retired review flags; no new rows | |
| `flag_id` | INTEGER FK review_flags | | **DEPRECATED:** the review flag a follow-up answers (retired #397) | |
| `attempts` | INTEGER NOT NULL, default 0 | count | DONE reports so far; after 3 (`MAX_ATTEMPTS`) the request is FAILED with its missing items | 0 |
| `missing` | TEXT | JSON list of contract item ids, `[]` = none | the items still missing (a DONE report re-queues the request for them) | not yet graded |
| `parent_id` | INTEGER FK research_requests | | the listing request a unit belongs to | NULL = a listing request |
| `unit` | TEXT | `CAPTURE`, `TAX`, `LISTING`, `RESEARCH_A`, `RESEARCH_B`, `ARBITER`, `MERGE`; the retired `VARIANT`, `GENERATION`, `GEN_MAINTENANCE`, `ENGINE`, `GEARBOX` and `INSURANCE` (2026-11-22: refused or skipped at the claim; still allowed by SQL) (CHECK) | the stage this row is (the parent request is `CAPTURE`) | NULL = the request is not split into units |
| `level_id` | INTEGER | the id of the catalogue level the unit researches | the unit's level | not a level unit |
| `shared_id` | INTEGER FK research_requests | | a `WAITING` unit waits for this unit of another request, which researches the same shared level | not waiting |
| `scope` | TEXT (JSON) | the levels a run researches | the scope of a two-run research | not stated |
| `usage` | TEXT (JSON) | tokens, cost, time of the Claude run, summed over the attempts | usage of the run (#291) | not reported |

### research_findings

**Purpose:** the staging area of a two-run research (RESEARCH_A, RESEARCH_B, arbiter): every write a run wants to make, held until the server compares the two runs and the MERGE unit writes the agreed findings (`docs/design-two-agent-research.md`).
**Owner scope:** through its request (`request_id`).
**Read by:** `GET /api/agent/stage` (the run's own findings), `GET /api/agent/disputes` (ARBITER), the comparison (`research_matches`), `raw` (through its request).
**Written by:** `staging.write()` for each staged write of RESEARCH_A, RESEARCH_B or ARBITER (`POST` to the agent API while a staged run is active).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | a negative number in the API | |
| `request_id` | INTEGER NOT NULL FK research_requests | | the unit that staged it | required |
| `parent_id` | INTEGER NOT NULL FK research_requests | | the listing request | required |
| `run` | TEXT NOT NULL | `A`, `B`, `C` (arbiter) | which run wrote it | required |
| `kind` | TEXT NOT NULL | `source`, `level`, `patch`, `fault`, `recall`, `job`, `check`, `observation`, `tyres`; `stats`, `flag` (retired, CHECK only) | what the finding is | required |
| `op` | TEXT NOT NULL | `insert`, `patch` | insert a row or change a real row | required |
| `target_table` | TEXT NOT NULL | the table it will write | | required |
| `target_id` | INTEGER | the row a patch changes | | NULL on insert (required on patch, CHECK) |
| `key` | TEXT NOT NULL | the finding key (the natural key of the row) | the same key in A and B is compared | required |
| `level`, `level_id` | TEXT, INTEGER | the level of the row | | not a level row |
| `part`, `component_code` | TEXT | as in `faults` | the part and component of a fault or recall | not a fault or recall |
| `payload` | TEXT NOT NULL (JSON) | the row's fields | what the write contains | required |
| `status` | TEXT NOT NULL, default `STAGED` | `STAGED`, `MERGED`, `SKIPPED`, `ARCHIVED` | the finding's state | required |
| `merged_id` | INTEGER | the row id it became | | not merged |
| `created_at`, `updated_at` | TEXT NOT NULL | UTC datetime | | |

### research_matches

**Purpose:** the comparison of run A and run B for one finding key: agreed, disputed (with the differences) or only one run found it. The arbiter's verdict settles a disputed match; the MERGE unit then writes the chosen rows.
**Owner scope:** through its request (`parent_id`).
**Read by:** `GET /api/agent/disputes` (the arbiter), the MERGE unit (`staging.merge`), `raw` (through its request).
**Written by:** `staging.compare()` (automatic when both runs have staged) and the arbiter's verdict (`staging`, verdict fields).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `parent_id` | INTEGER NOT NULL FK research_requests | | the listing request | required |
| `kind`, `key` | TEXT NOT NULL | as `research_findings` | what is compared | required |
| `a_id`, `b_id` | INTEGER FK research_findings | | the finding of run A and of run B | the run did not find it (at least one is required, CHECK) |
| `outcome` | TEXT NOT NULL | `AGREED`, `DISPUTED`, `ONLY_A`, `ONLY_B` | the comparison's result (`DISPUTED` when a field differs beyond `config.STAGE_TOLERANCE`) | required |
| `diffs` | TEXT (JSON) | the differing fields | | no difference |
| `material` | INTEGER 0/1, default 0 | 1 = the difference matters: for a fault, a band in the three highest, a price of at least `config.STAGE_MATERIAL_EUR` (500 EUR) or a consequence of `ENGINE_DAMAGE`, `STRANDS` or `SAFETY`; for a patch or level, any difference (`staging._material`) | decides whether the arbiter must settle it | 0 |
| `verdict` | TEXT | `A`, `B`, `BOTH`, `NEITHER`, `OWN` (CHECK) | the arbiter's choice (`OWN` = its own finding, `verdict_id` required) | not yet settled |
| `verdict_id` | INTEGER FK research_findings | | the finding chosen by `OWN` | |
| `verdict_reason` | TEXT | English | why | |
| `verdict_source_id` | INTEGER FK sources | | the source the verdict rests on | |
| `merged` | TEXT (JSON) | the fields written | what the MERGE unit wrote | not merged |
| `flag_id` | INTEGER FK review_flags | | **DEPRECATED:** a review flag (retired) | |

## Research parts and the change log

### change_log

**Purpose:** the audit trail: one row for every write through the API (agent, UI, research and merge), with the old and new values, the writer and the research request that made it.
**Owner scope:** no owner column; the account is read from the row's `owner_id` or its listing (`GET /api/admin/changes`).
**Read by:** `GET /api/admin/changes` (newest first, paged by `before`), `GET /api/admin/data/change_log`, `raw`.
**Written by:** `agent.log_change()` for every write (the caller's transaction), the listing-media changes, and the research queue's note `action='flag'` when one run writes more than 50 listing-level rows (`LISTING_WRITE_ALERT`).

| Column | Type | Values / unit | Meaning | NULL means |
|---|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | | | |
| `changed_at` | TEXT NOT NULL, default `datetime('now')` | UTC datetime | when the write happened | |
| `table_name` | TEXT NOT NULL | the table written (or `research_requests` for a flag) | | required |
| `row_id` | INTEGER NOT NULL | the row's id | | required |
| `action` | TEXT NOT NULL | `insert`, `update` (also archive and restore, which are updates of `archived`), `delete`, `flag` (research note) | what was done | required |
| `old_json` | TEXT | JSON object of the old values | the row before the write | NULL on insert |
| `new_json` | TEXT NOT NULL | JSON object of the new values (or the note) | the row after the write | required |
| `user_id` | INTEGER FK users | | the account that made the write (the writer; an admin token writes as its user) | NULL = a write without a logged-in user |
| `request_id` | INTEGER FK research_requests | | the research request that made the write | not a research write |

## Status and quality codes

These are the codes the knowledge tables carry. Statuses are free text in SQL; the agent API checks the format (`CODE_FORMATS`: upper case words) on `generations.status`, `engines.status`, `tyre_data.status`, `insurance_data.premium_status` and `vehicles.technical_status`. The calculation reads a status only through `ranking.STATUS_POINTS` and the research grades below.

### Status (`status`, `premium_status`, `evidence`)

| Status | Meaning | Points (`ranking.STATUS_POINTS`) | Research grade |
|---|---|---|---|
| `VERIFIED` | official or primary source for this engine or variant | 1 | VERIFIED when the source is A or B; otherwise ACCEPTED |
| `PRIMARY` | the primary consumption figure of a combustion car (`agent_tools.consumption`) | 1 | as VERIFIED |
| `OFFICIAL FEE LEVEL` | an official fee table (the HU/AU fee, `agent_tools.hu`) | 1 | as VERIFIED |
| `USER DATA` | a figure the owner typed in (the reference car's premium, `user_data` entries) | 1 | as VERIFIED (the source is `user_data`, quality D: ACCEPTED at most) |
| `QUOTE` | a quote for a premium (`insurance_data.premium_status`, `listing_quotes`) | 1 | as VERIFIED |
| `ESTIMATED` | derived; the derivation is in `notes` (tyres, electric consumption) | 0.5 | ACCEPTED |
| `PENDING` | unknown, not yet known; never with a number (checklist items use it too) | 0 | ACCEPTED at most; never counts as a figure |
| `OBSERVED` | a figure seen on a car (no status points; `listing_history.evidence` uses the same word for a viewing observation) | 0 | ACCEPTED at most |
| `PARTIAL` | **not used:** a label in the interface (`static/i18n`) only; no code writes or grades it | 0 | none |

Rule (`research.grade_rows`): a row is VERIFIED only when its status (or a check's result) earns the verified points and its source is grade A or B; any other present row is ACCEPTED; no row is MISSING. A source below the item's minimum quality does not count at all.

### Severity (derived for faults, `costs.fault_severity`; `ranking.SEVERITY_POINTS`)

Severity is never stored. It is derived from the fault's `consequence` and its price (`parts_eur + labor_eur`; a fault with neither price has price 0 for this purpose):

| Severity | When | Points |
|---|---|---|
| `HIGH` | `consequence` = `ENGINE_DAMAGE`, or the price ≥ 1,500 EUR (`config.SEVERITY_HIGH_EUR`), or `STRANDS` / `SAFETY` with a price ≥ 500 EUR (`config.SEVERITY_MEDIUM_EUR`) | 3 |
| `LOW-MEDIUM` | `STRANDS` / `SAFETY` with a price below 500 EUR | 1 |
| `MEDIUM` | `UNUSABLE`, or a price ≥ 500 EUR otherwise | 2 |
| `LOW` | everything else (the car still drives) | 0.5 |
| `HIGH IF APPLICABLE` | a recall (`recalls`), shown in the checklist and reliability (`costs.py`) | 1.5 |

### Source quality (`sources.quality`, `source_keys.source_id`, `research_checks.source_id`)

| Grade | Rule (AGENTS.md) | Examples in use |
|---|---|---|
| A | official: manufacturer schedule, official calculator, authority, fee table | BMF Kfz-Steuer-Rechner, manufacturer service schedule, fee tables |
| B | ADAC, TÜV, Haynes, dealer tool, comparison quote | ADAC Pannenstatistik and GW-Info, TÜV-Report |
| C | aggregators, encyclopedias, consumption databases | Autoscore, EngineScope, autokostencheck, ev-database.org |
| D | forums, search snippets, single retailers; the owner's own entries | forum threads, `user_data` sources (`quotes.py` grades a user-entered quote D) |

Code rules that follow from the grade: `VERIFIED` needs A or B (`research.grade_rows`); a fault whose only source is a forum (D) can be at most band `common` (`config.FORUM_MAX_BAND`); a fault window taken from a source that is not A or B is marked `window_uncertain=1` (`agent.fault_checks`); the `quality` column is required to be A–D on write.

### Fault frequency bands (`config.FREQUENCY_BANDS`: central share, low, high)

The share is the part of cars affected by the reference point (`config.BAND_REFERENCE_KM` = 200,000 km or `BAND_REFERENCE_YEARS` = 15 years). The central value is used when a fault has no stated curve; low and high give the range stored in `share_low` and `share_high` (the calculation uses only the central value).

| Band | Central share | Range | Needs |
|---|---|---|---|
| `systemic` | 50 % | 40–70 % | a `manufacturer_trace` (extended warranty, Kulanz, TPI or class action) |
| `widespread` | 25 % | 20–40 % | |
| `common` | 12 % | 8–20 % | the highest band a forum-only (D) fault can take |
| `occasional` | 5 % | 3–8 % | |
| `rare` | 1.5 % | 0.5–3 % | |

Curve shapes (`faults.shape`, used when there is no stated curve; every curve runs to 300,000 km or 20 years, `config.CURVE_END_KM` / `CURVE_END_YEARS`):

| Shape | Share at km (or years) x |
|---|---|
| `WEAR_KM` | central × (x / 200,000 km)² |
| `AGE` | central × (years / 15)² |
| `WINDOW` | central reached at `window_km`, then central × 1.1 at 300,000 km |
| `RANDOM` | 1 − (1 − central)^(km / 200,000) |

## Conventions that apply to every table here

- **NULL is unknown, never 0.** A missing price, interval or share stays NULL, and the calculation reports the component as unknown. A flag column uses 0 for "no" and NULL only where the table says so.
- **Every external figure cites a source** through `source_id`; the write is refused without one on the knowledge tables (`agent.SOURCE_REQUIRED`).
- **Free text is English**; verbatim third-party wording (a source's verdict, a listing's text) keeps its original language.
- **Duplicates.** A knowledge row is kept on one level only. For faults the server refuses a second similar fault on the same variant (409, #221).
- **Writes.** Knowledge tables are written by admin tokens only (the shared research worker and admin agents), through the agent API or the staged research path; an account's own token cannot write them (`agent.ADMIN_TABLES`). Every write is logged in `change_log`.

## Deprecated and unused columns (summary)

| Table.column | Status | Reason |
|---|---|---|
| `maintenance_items.labor_included` | unused | written by the helper; no calculation reads it |
| `maintenance_items.schedule` = `PACKAGE` | legacy | the calculation skips `PACKAGE` rows |
| `faults.onset_km` | unused | the protocol describes it for `WINDOW`; no calculation reads it |
| `faults.quote` | unused | kept for the audit; no reader |
| `recalls.safety` | unused | every recall is shown as `HIGH IF APPLICABLE` |
| `recalls.window_known`, `recalls.remedy` | unused | kept for the audit; no reader |
| `research_checks.named_codes` | deprecated | retired with contract v10; still validated and written only when `check(codes=)` is passed |
| `observations` with `metric` = `Owner measured average` | cross-check only | no code reads it |
| `project_parameters.currency` | unused | every amount is EUR |
| `project_parameters.acquisition_mode`, `lease_rate_max_eur` | deprecated | leasing removed (#165) |
| `project_parameters.purchase_mode` | stored only | no calculation reads it |
| `project_parameters.drivers_count`, `driver_age`, `sf_class`, `insurance_cover`, `insurance_deductible_eur` | removed | migration 046 (2026-11-22) |
| `project_preferences.unit`, `status`, `notes` | unused | never written by the API |
| `research_requests.kind` = `FOLLOW_UP`, `flag_id` | deprecated | review flags retired (#397) |
| `research_matches.flag_id`, `research_findings.kind` `stats`/`flag` | deprecated | review flags and statistics retired |
| `repair_risks` (table) | retired (#397) | replaced by `faults` |
| `reliability_items` (table) | retired (#351) | replaced by `faults`, `recalls` and the fixed sources; legacy rows still read |
| `review_flags`, `flag_reviews` (tables) | retired (#351, #397) | the MERGE unit reports an unsettled disagreement instead |
