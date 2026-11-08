# Design: two independent research runs per car, compare, arbitrate, merge (#253) and fault component codes (#221 phase 3)

Status: design (Opus, 2026-11-08), owner decision 2026-11-08. Not implemented. Build it in the PRs of section 6, in order.
Everything marked **(unverified)** was not checked in code or data and must be confirmed by the PR that touches it.

## 0. Why, and what changes
- Today a car runs as up to 9 cold-started units (CAPTURE, VARIANT, GENERATION, GEN_MAINTENANCE, ENGINE, GEARBOX, TAX, LISTING, INSURANCE). Two pilot runs on the same cars filed about 5 vs 12 faults (round 1: A 5, B 13, 3 matched). One run per item gives no measure of how far a figure can be trusted.
- New flow: **CAPTURE → RESEARCH_A + RESEARCH_B (independent, write to staging) → compare (server) → ARBITER (only on material disputes) → MERGE (server code, through `agent_write`) → TAX → LISTING → INSURANCE.**
- Cold starts for a new car: 6 (7 with a dispute, 8 with insurance) instead of 9. A car whose catalogue levels are already researched skips both research runs, the arbiter and the merge.
- **One deviation from the issue text, for the owner to confirm:** the merge is deterministic server code, not an LLM run. Merging is rule-following (pick the agreed row, apply the arbiter's verdict, write through the API, raise flags); an LLM there adds a cold start and a third source of variance. The MERGE unit stays as a queue row (progress, attempts, a target to wait on) that the worker executes without Claude. If the owner wants an agent, the MERGE prompt would only execute the plan returned by the same code and may edit nothing but free text.

## 1. Request and unit flow

### 1.1 Units and stages (`carlos/research_units.py`)
```python
UNITS = ('CAPTURE', 'RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE', 'TAX', 'LISTING', 'INSURANCE')
LEGACY_UNITS = ('VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX')   # kept so open legacy requests finish
BROWSER_UNITS = ('CAPTURE', 'TAX', 'INSURANCE')
STAGED_UNITS = ('RESEARCH_A', 'RESEARCH_B', 'ARBITER')          # their /api/agent writes go to staging (1.4)
SERVER_UNITS = ('MERGE',)                                       # the worker runs no Claude for these
STAGES = (('RESEARCH_A', 'RESEARCH_B'), ('ARBITER',), ('MERGE',), ('TAX',), ('LISTING',), ('INSURANCE',))
LEGACY_STAGES = (...today's STAGES...)
RESEARCH_ITEMS = [i for u in LEGACY_UNITS for i in UNIT_ITEMS[u]]   # today's item ids of the five units, unchanged
UNIT_ITEMS = {'CAPTURE': [...], 'RESEARCH': RESEARCH_ITEMS, 'TAX': [...], 'LISTING': [...], 'INSURANCE': [...], **legacy}
ITEM_UNIT = {'RESEARCH_A': 'RESEARCH', 'RESEARCH_B': 'RESEARCH'}   # _unit_ids(ids, unit) maps through this
```
- `advance()` picks `LEGACY_STAGES` when the parent already has a legacy child, else `STAGES` (no flag day; open requests finish the old way). A module constant `FLOW = 'dual'` (`'units'` restores the old stages for new requests) is the rollback switch.
- TAX moves after MERGE: it needs the merged identity (HSN/TSN, CO2, emissions class, displacement).
- FOLLOW_UP requests are unchanged (one run, direct writes; a flag review needs two different workers anyway).

### 1.2 Creating the stages (`research_requests.advance`)
- **RESEARCH stage.** `ids = _unit_ids(missing(owner, listing), 'RESEARCH')`. Empty: RESEARCH_A, RESEARCH_B, ARBITER and MERGE are inserted `SKIPPED` ("Already researched") and the flow goes on to TAX. Otherwise both runs are inserted with the same `missing` (the ids) and the same **scope** (new column, JSON list of `[level_column, id]`): for each missing id the level it is graded on in `Contract.resolved` for the listing's variant (a missing family/gearbox counts as its fallback level, e.g. `fam.risks` without a family → `["engine_id", 69]`). Levels without missing items are not in the scope: their rows are read-only context for the runs.
- **Overlap with another request.** A research is *open* from the moment its RESEARCH_A exists until its MERGE is closed. If any open research of another parent has a scope that intersects this scope, both runs are inserted `WAITING` with `shared_id` = that parent's RESEARCH_A id. (The old `research_requests_open_unit` index keyed on one `level_id` does not cover multi-level scopes: RESEARCH rows keep `level_id` NULL and the overlap is checked in Python on `scope`.)
- **Release** (`release_shared`): the other parent's MERGE calls `release_shared(c, <its RESEARCH_A id>)` when it closes (RESEARCH_A's own close does not release). A waiting parent is handled as a pair: recompute `ids` and `scope` for its listing; nothing missing → both runs `DONE` "Researched by request #x" and `advance()`; otherwise both `QUEUED` with the new `missing`/`scope`; other waiters that now overlap re-point their `shared_id` to this pair's RESEARCH_A. The blocker's MERGE FAILED does **not** fail the waiters (unlike legacy units): they recompute and run.
- **ARBITER stage.** Created after both runs closed: the server runs `staging.compare(parent)` first (section 3). Material disputes → ARBITER `QUEUED` (`missing` = the dispute ids, capped at `MAX_DISPUTES = 25`, most material first); none → `SKIPPED` with "No material disagreement (agreement 87 %)".
- **MERGE stage.** Always `QUEUED` when the research ran (also when one run closed with gaps).
- Stage order and the parent's final status are unchanged: the parent is DONE when every unit is DONE or SKIPPED (INSURANCE exempt), else FAILED with the failed units listed.

### 1.3 Statuses, attempts and the done gate
| Unit | Graded on | Attempts | After the last attempt |
|---|---|---|---|
| RESEARCH_A / _B | the run's staged rows applied on top of the real rows (dry grade, 1.5), research items of its scope only | `RESEARCH_MAX_ATTEMPTS = 2` (cost: one continuation) | `DONE` with `missing` kept and result "closed with N items missing" (never FAILED: the other run and the merge may still cover them) |
| ARBITER | every dispute in its `missing` has a verdict | 2 | `DONE`; disputes without a verdict are UNRESOLVED (flags at merge) |
| MERGE | real rows after the merge, research items of the scope | 1 (re-merging writes nothing new) | missing items → `FAILED` "still missing after merge: ids"; the owner re-queues `carlos://listing/<id>` and only the still-missing items are researched (dual again) |
| CAPTURE, TAX, LISTING, INSURANCE | unchanged | unchanged | unchanged |

- Statuses stay `QUEUED / RUNNING / WAITING / DONE / SKIPPED / FAILED / CANCELLED`; no new status.
- A run that ends `failed:` (CARLOS_RESULT) is graded anyway: what it staged counts. A usage-limit release (`status QUEUED`) keeps its staged rows; the continuation run sees them (`GET /api/agent/stage`) and goes on.
- `finish()` for a staged unit uses `staging.missing(c, request_id)` instead of `missing(owner, listing)`; `lst.*` items are never part of the research runs (CAPTURE, TAX, LISTING, INSURANCE keep them).
- `cancel()` cancels QUEUED/WAITING children as today; a running research finishes, its staging is kept, no merge is created.

### 1.4 What each research run covers (writes to staging only)
Each of RESEARCH_A and RESEARCH_B gets the **same prompt** (`docs/prompts/units/research.md`, replaces variant/generation/gen_maintenance/engine/gearbox.md) and does, for every level in its scope, everything the five old units did:
1. **Identity** (staged PATCHes of the level rows the capture created; staged inserts of missing levels): generation years, facelift, Euro NCAP; engine code, fuel, displacement, power, aspiration, injection, timing drive (EV fields); variant HSN/TSN, transmission, body, emissions class, CO2, `gearbox_id`; gearbox (code, type, gears), engine family, gearbox family, body style. If the real engine/generation/gearbox already exists in the catalogue (`GET /api/engines`, …), stage a PATCH of the variant pointing at it and leave that level alone.
2. **Maintenance**: every applicable job of `config.JOBS` on its level with interval and both prices (contract items `gen.*`, `eng.*`, `gbx.service`, `gbx.clutch`), plus WEAR items.
3. **Faults** per part (ENGINE, GEARBOX, CHASSIS, ELECTRICS) with `component_code` (section 4), band, shape, price, `inspection_action`, on the level the evidence names; the four sources per part with a `check()` each (`rel.<PART>.<source>`), `eng.risks`, `fam.risks`, `gbx.risks`, `gfam.risks`, `gen.risks`, `bdy.risks` or their `NONE FOUND` checks.
4. **Recalls** (`recalls` table, one per recall code, on the level it names, with build window) and the `gen.recalls` check. Legacy `reliability_items` are refused in staging.
5. **Consumption** (`var.consumption`), **tyres** (`var.tyres`), **TÜV/ADAC baseline** (`gen.baseline`, `reliability_stats`), `var.gearbox`.
6. Its own `SOURCES_DISAGREE` flags when two sources it read disagree.
7. `todo()` (answers from the dry grade), fix what is sourceable, last line `CARLOS_RESULT done: …`.

Not in a research run: listings, captures, photos, checklist, unit costs, valuations, tax, insurance, log entries (403 in staging: "not part of a research run").

**Independence.** A run can read the real catalogue and its own staged rows only; never the other run's (every staging read filters by the token's request). Both runs are Haiku with the same prompt, so their errors are correlated: agreement is evidence, not proof (the pilot should measure it against the round-2 cars).

### 1.5 Staged writes: how runs write (no new helpers needed)
- The server routes every `POST/PATCH /api/agent/<table>[/<id>]` made with the per-request token of a STAGED unit to `staging.write()` instead of `agent_write()`. `agent_tools` stays as it is (`src`, `fault`, `item`, `check`, `consumption`, `tyres`, `engine`, `patch`, …): a Haiku run cannot bypass staging by mistake.
- The answer is `{"table": t, "id": -<finding id>, "staged": true}`. **A negative id is a staged row of this run**: it may be used as `source_id`, as a level id (`gearbox_id: -12`), as `fixed_fault_id`, and in `PATCH /api/agent/<table>/-12` (updates the staged payload; the key is recomputed).
- A PATCH of a real row (positive id) is staged as one `patch` finding per row (later PATCHes of the same row merge into its payload).
- Validation at staging time, so the merge does not fail later: `clean_row(c, table, payload, insert=...)` (columns, types, fixed codes incl. `component_code`), then `check_parents` with negative ids removed (verified: `check_parents` looks every FK up in the real table, so negatives must be skipped) and each negative checked to be a staged row of this run of the right table; the scope rule (the row's level must be in the run's scope or a staged level of this run; else 403 "level already researched"); the within-run key rule (409 with the staged id, same wording as #221: "PATCH -12, or resend with distinct_of=[-12] and the reason in notes"); `consistency.conflicts()` against the real rows when the level is real (the #221 409, unchanged).
- `GET /api/agent/stage` → the run's findings and `missing` from the dry grade; `GET /api/agent/todo` with a staged token answers from the dry grade too.
- **Dry grade** (`staging.missing(c, request_id)`): open a second connection, `BEGIN`, apply the run's findings with plain INSERT/UPDATE (negative ids mapped in order: sources, levels, patches, knowledge), run the same grading as `server.missing_items` on that connection, `ROLLBACK`. One code path (`staging.apply(conn, findings, write)`) serves the dry grade (raw SQL) and the merge (`agent_write`). The write lock is held for the grading (a few seconds) **(unverified on the Pi 2B; a busy timeout covers concurrent writers)**.

### 1.6 Worker (`worker.py`)
- `unit_prompt`: RESEARCH_A/_B → `_header.md` + `research.md` (`{MISSING}`, `{SCOPE}` listed as "generation 64, engine 69, …"); ARBITER → `_header.md` + `arbiter.md`. `_header.md` gets one paragraph on staging (writes go to a private staging area, ids are negative, `todo()` grades the staging).
- MERGE: no Claude. `POST /api/agent/merge` with the request token, then finish `DONE` with the returned summary (the server grades it).
- Timeout: `WORKER_RESEARCH_TIMEOUT_MIN` (default 150) for RESEARCH units, `WORKER_TIMEOUT_MIN` for the rest. Model stays Haiku for all three LLM units. Worst case per new car: 2 runs × 2 attempts + arbiter × 2 = 6 Haiku runs; typical: 2 research + 0–1 arbiter.

### 1.7 Progress data for the UI
`research_requests.mine()` / `everything()` add per part a `detail`:
- RESEARCH_A/_B: `{"staged": {"fault": 9, "job": 14, "check": 22, "source": 11, …}, "last": "fault ENGINE TIMING_CHAIN", "last_at": "...", "missing": [...]}` from one `GROUP BY kind` over `research_findings` (the "what is it on" line is the most recent finding's key).
- ARBITER: `{"disputes": 7, "answered": 5}`.
- MERGE: `{"agreement": 0.82, "written": 41, "skipped": 3, "flags": 2}` (from `research_matches`).
The Compare page's request list shows unit names (i18n keys `unit.RESEARCH_A` "Research run 1", `unit.RESEARCH_B` "Research run 2", `unit.ARBITER` "Second opinion", `unit.MERGE` "Merge") and the detail line, in all four languages.

## 2. Staging schema (migration `040_research_staging.sql`)
Migration numbers: last applied is `038_insurance_unit.sql`; `039` is the component code (section 4, independent, small), `040` this one. Rename on merge if another migration lands first.

```sql
-- #253: two research runs per car write to staging; the server compares, an arbiter settles disputes, the merge writes.
-- 1) research_requests: new units + scope. Rebuild because the `unit` CHECK lists the units (same pattern as 038).
CREATE TABLE research_requests_new (
 ... every column of 038 unchanged ...,
 unit TEXT CHECK (unit IS NULL OR unit IN ('CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX',
                  'LISTING', 'INSURANCE', 'RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')),
 level_id INTEGER, shared_id INTEGER REFERENCES research_requests_new(id),
 scope TEXT CHECK (scope IS NULL OR json_valid(scope)));          -- [["generation_id", 64], ["engine_id", 69], ...]
INSERT INTO research_requests_new (<038 columns>) SELECT <038 columns> FROM research_requests;
DROP TABLE research_requests; ALTER TABLE research_requests_new RENAME TO research_requests;
-- the five indexes of 038, unchanged

-- 2) one row per staged write of a run
CREATE TABLE research_findings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id INTEGER NOT NULL REFERENCES research_requests(id),   -- the run: a RESEARCH_A, RESEARCH_B or ARBITER unit
 parent_id INTEGER NOT NULL REFERENCES research_requests(id),    -- the listing request
 run TEXT NOT NULL CHECK (run IN ('A', 'B', 'C')),               -- C = the arbiter
 kind TEXT NOT NULL CHECK (kind IN ('source', 'level', 'patch', 'fault', 'recall', 'job', 'check', 'observation',
                                    'tyres', 'stats', 'flag')),
 op TEXT NOT NULL CHECK (op IN ('insert', 'patch')),
 target_table TEXT NOT NULL,                                     -- the real table the payload is written to
 target_id INTEGER,                                              -- op 'patch': the real row id
 key TEXT NOT NULL,                                              -- section 2.2
 level TEXT, level_id INTEGER,                                   -- config.LEVELS name; a negative id = a staged level of this run
 part TEXT, component_code TEXT,
 payload TEXT NOT NULL CHECK (json_valid(payload)),              -- exactly the body the run sent to /api/agent/<table>
 status TEXT NOT NULL DEFAULT 'STAGED' CHECK (status IN ('STAGED', 'MERGED', 'SKIPPED', 'ARCHIVED')),
 merged_id INTEGER,                                              -- the real row it became or was mapped to
 created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
 CHECK ((op = 'patch') = (target_id IS NOT NULL)));
CREATE UNIQUE INDEX research_findings_key ON research_findings (request_id, key)
 WHERE status = 'STAGED' AND kind NOT IN ('fault', 'check', 'flag');
CREATE INDEX research_findings_parent ON research_findings (parent_id, run, kind);

-- 3) the comparison of run A with run B, and the arbiter's verdicts
CREATE TABLE research_matches (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 parent_id INTEGER NOT NULL REFERENCES research_requests(id),
 kind TEXT NOT NULL, key TEXT NOT NULL,
 a_id INTEGER REFERENCES research_findings(id), b_id INTEGER REFERENCES research_findings(id),
 outcome TEXT NOT NULL CHECK (outcome IN ('AGREED', 'DISPUTED', 'ONLY_A', 'ONLY_B')),
 diffs TEXT CHECK (diffs IS NULL OR json_valid(diffs)),          -- [{"field": "frequency_band", "a": "common", "b": "rare", "rule": "one band step"}]
 material INTEGER NOT NULL DEFAULT 0 CHECK (material IN (0, 1)),
 verdict TEXT CHECK (verdict IS NULL OR verdict IN ('A', 'B', 'BOTH', 'NEITHER', 'OWN')),
 verdict_id INTEGER REFERENCES research_findings(id),            -- OWN: the arbiter's staged finding
 verdict_reason TEXT, verdict_source_id INTEGER,                 -- negative: a staged source of run C
 merged TEXT CHECK (merged IS NULL OR json_valid(merged)),       -- {"ids": [...], "skipped": "exists as fault #12"}
 flag_id INTEGER REFERENCES review_flags(id),
 CHECK (a_id IS NOT NULL OR b_id IS NOT NULL),
 CHECK (verdict IS NOT 'OWN' OR verdict_id IS NOT NULL));
CREATE INDEX research_matches_parent ON research_matches (parent_id, outcome);
```
- Staging holds catalogue research only (no personal data: listing tables are refused). Rows are kept after the merge as the audit trail of why a value was chosen; nothing deletes them (size: a few hundred rows per car).
- Expose read-only through `GET /api/admin/data/research_findings|research_matches` (admins) and the staged/arbiter endpoints; they are **not** in `AGENT_TABLES`.

### 2.1 Staged table → kind → real table
| Real table (`target_table`) | kind | Note |
|---|---|---|
| `sources` | source | merge reuses a visible source with the same normalised URL, else inserts the payload |
| `engine_families`, `gearbox_families`, `gearboxes`, `body_styles`, `options` | level | merge = get-or-create by natural key (migration 028 unique indexes) |
| `generations`, `engines`, `vehicles` (PATCH only; inserts refused: the capture creates the shells) | patch | identity fields and links (`gearbox_id`, `engine_id`, `body_style_id`) |
| any knowledge table, PATCH of a real row | patch | e.g. pricing an unpriced real fault |
| `faults` | fault | |
| `recalls` | recall | `reliability_items` refused |
| `maintenance_items` | job | |
| `research_checks` | check | |
| `observations` | observation | |
| `tyre_data` | tyres | |
| `reliability_stats` | stats | |
| `review_flags` | flag | |
Everything else → 403.

### 2.2 Finding keys (normalisation)
`norm(s)` = NFKD fold, upper case, trimmed, inner whitespace collapsed. Level is a **compared field**, not part of the key, wherever the same thing can sit on several levels (faults, recalls, jobs, consumption, tyres), so a level disagreement shows as a dispute instead of two unmatched findings.
| kind | key | unique per run |
|---|---|---|
| source | `src:<url lower-cased, without fragment and trailing slash>` | yes (re-staging returns the existing id) |
| level | `lvl:<table>:<natural key>` (gearboxes `upper(code)`; families `upper(name)`; body_styles `<generation_id>:upper(name)`; options `upper(name):<generation_id or 0>`) | yes |
| patch | `patch:<table>:<target_id>` | yes |
| fault | `fault:<part>:<component_code>` | no (two faults may share a code, see 3.1) |
| recall | `recall:<norm(code)>` | yes |
| job | `job:<job>`, or `item:<consistency._words(item) joined>` without a job | yes |
| check | `check:<task>` | no (one per source consulted) |
| observation | `obs:<metric>` | yes |
| tyres | `tyres:<tyre_type>` | yes |
| stats | `stats:<kind>:<age_from>-<age_to>:<report_year>` | yes |
| flag | `flag:<kind>:<level>:<level_id>` | no |

## 3. Comparison, arbiter, merge (`carlos/staging.py`)

### 3.1 Pairing
Runs on the findings with `status='STAGED'` of run A and run B of one parent, once, when both runs are closed (idempotent: does nothing if `research_matches` rows exist for the parent).
- Unique kinds: pair by equal key.
- faults: group by `(part, component_code)`; inside a group pair greedily by `consistency.same_fault(component)`, then by the best `difflib` ratio (as `pilot_compare.match`); a group with one fault on each side is always paired (a wording difference becomes a `component` diff for the arbiter). `OTHER` faults are paired only by `same_fault`.
- checks: group by task; compare the best result (FOUND > NONE FOUND > N/A); the merge writes the union, one check per distinct source URL.
- flags: never compared; the merge writes the union (one per level and kind).
- sources: never compared; merged when a merged finding cites them.

### 3.2 Diffs and tolerances (`config.STAGE_TOLERANCE`)
| kind | field | agreed when |
|---|---|---|
| fault | level (column + id) | equal |
| fault | `frequency_band` | at most one step apart (`systemic > widespread > common > occasional > rare`) |
| fault | price = `parts_eur + labor_eur` (workshop) | within ±30 % of the larger (the pilot's rule); both NULL agrees |
| fault | `consequence`, `shape` | equal (a shape diff alone is not material) |
| recall | level, `applies_from`, `applies_to`, `part` | equal |
| job | level | equal |
| job | `interval_km`, `interval_months` | each within ±20 % (NULL vs value = diff) |
| job | `reference_cost_eur` ±30 %, `diy_parts_cost_eur` ±40 % | |
| observation | `value_num` | ±3 % (both read the same page) |
| tyres | `size` equal; `price_per_tyre_eur` ±25 %; `life_km` ±20 % | |
| stats | `value`, `class_average` | ±10 % |
| patch / level | every field both payloads set | equal after `norm()`; numbers equal |

Outcome: `AGREED` (paired, no diff), `DISPUTED` (paired, ≥ 1 diff), `ONLY_A` / `ONLY_B`.

**Agreement metric** (stored in the MERGE result, shown in the UI and used by the pilot): `agreement = AGREED / (AGREED + DISPUTED + ONLY_A + ONLY_B)` over faults, recalls, jobs, checks, observations, tyres, stats, patches and levels. Reported per kind as well.

### 3.3 Material disputes (trigger the ARBITER)
A match is `material=1` when it is any of:
- a `patch` or `level` diff (identity: everything hangs on it);
- a fault ONLY in one run with band ≥ `common`, or price ≥ €500, or consequence `ENGINE_DAMAGE`/`STRANDS`/`SAFETY`;
- a paired fault with a level diff, a band diff of more than one step, a `component` diff (paired by code only), or a price diff where the larger price is ≥ €500;
- a recall ONLY in one run;
- a job ONLY in one run when its job code belongs to a contract item, or any interval diff;
- an observation, tyres or stats diff.
Everything else (cheap one-sided faults, WEAR items, check results, price diffs under €500) is resolved by rule in the merge. **The ARBITER runs when at least one material match exists**; at most `MAX_DISPUTES = 25` (ordered: identity, recalls, faults by price, jobs, the rest); the rest are UNRESOLVED.

### 3.4 What the arbiter gets and does (`docs/prompts/units/arbiter.md`)
- `GET /api/agent/disputes` (ARBITER token; only its parent's material matches in its `missing`): per dispute `{id, kind, key, question, diffs, a: {payload, level, sources: [{title, url, quality, supports}]}, b: {...}}` with `question` generated from the diffs ("Is this fault real for this engine?", "Which band?", "Which level does the evidence name?", "Which TSN?").
- It reads the cited sources of both sides first, may consult one more source per dispute, and answers each with `PATCH /api/agent/disputes/<id> {"verdict": "A"|"B"|"BOTH"|"NEITHER"|"OWN", "reason": "...", "source_id": <staged source>}`:
  - `A`/`B`: that side's finding is right (as it stands); `BOTH`: two different things, keep both (the second is written with `distinct_of`); `NEITHER`: neither is supported for this car; `OWN`: stage a corrected finding first (staged write as in 1.5, run C) and pass its id as `"finding": -<id>`.
- It may stage only findings referenced by a verdict (others are ignored by the merge) and only for keys under dispute. It never writes outside staging.

### 3.5 Merge rules (`POST /api/agent/merge`, MERGE token; `staging.merge(c, parent_id, owner_id)`)
Order: sources (on use) → levels (get-or-create by natural key) → patches → knowledge rows → flags; negative ids are mapped as rows are written. Every write is `agent.agent_write(c, table, row_id, payload, user_id=<requester>, admin=True, actor=<request user>)`: the same validation, change log, catalogue ownership, `#221` duplicate guard and `consistency.check()` as any agent write (verified: `agent_write` calls the guard and `consistency.check`). Dossiers are exported once at the end (`export_all` for the linked accounts), not per row.

| Match | Written |
|---|---|
| AGREED | the representative: the side whose best source quality is higher, then A; within tolerance the **less favourable** figure (higher band, higher price, shorter interval; the project's contradiction rule); notes += "Second independent run agreed (sources: …)"; checks: the union |
| DISPUTED / ONLY, verdict A / B | that side |
| verdict OWN | run C's finding |
| verdict BOTH | both; the second with `distinct_of=[first id]` and `notes` = the verdict reason |
| verdict NEITHER | nothing; `merged.skipped` = "rejected by the arbiter: <reason>" |
| non-material, no verdict | paired: the less favourable side; ONLY: written, notes += "Found by one of two independent runs" |
| material, no verdict (UNRESOLVED) | paired: the less favourable side; ONLY fault/recall/job: written (sourced evidence; the cost is not under-estimated); `patch`/`level` (identity): **not written** (the item stays missing); in every case one `SOURCES_DISAGREE` review flag on the finding's level (A's level on a level diff): `what` = "<kind> <key>: run 1 <summary>; run 2 <summary>", `why` = "Two independent research runs disagree and the arbiter did not settle it (request #<parent>)", `created_by` = "merge of request #<parent>" |
- **409 from the guard**: never forced. A conflict with a real row → `merged.skipped` = "exists as <table> #N" (the run should have extended it; the comparison shows it). `distinct_of` only after a BOTH verdict.
- **Natural-key collision on an identity patch** (the shell engine `UNKNOWN-1199-60` turns out to be the catalogue's `EB2` 60 kW): relink the variant (`PATCH vehicles engine_id=<existing>`), map the shell's staged level id to the existing engine for the remaining findings (409s then drop duplicates), and name the orphaned shell in the result for the owner (never deleted).
- **The merge may not**: write a value that is in neither run nor in a verdict; average or round figures; change a source's quality; PATCH or archive real rows except through an agreed or decided `patch` finding; delete anything; touch listing tables, tax or insurance; pass `distinct_of` without a BOTH verdict.
- Then `finish` grades the MERGE unit on the real rows (1.3) and `release_shared` wakes the waiters.

## 4. Component codes (#221 phase 3; migration `039_fault_component_code.sql`)

### 4.1 Vocabulary (`config.FAULT_COMPONENTS`)
Built from the components actually filed: the pilot databases (`~/pilot-archive/*/{a,b}/cars.sqlite`: 28 faults, in `pilot-before-gate/a` and `round2-attempt1/a`; the running pilot `data/backups/pilot/{a,b}` has none yet), the round-1 comparison (`~/pilot-archive/compare-round1.md`, 15 faults) and the pre-reset reliability items with a part (`data/backups/before_part6_20261106.sqlite`, 367 distinct part + component pairs including the pilots). A keyword classifier with the patterns below put **361 of 367 (98 %)** in a code other than `OTHER`; the six left were two placeholders ("ENGINE", "Engine"), "5-speed manual gearbox", an EHPS pump and a steering angle sensor filed under ELECTRICS, and a hybrid DC-DC converter (now `ELECTRIC_DRIVE`).

`config.FAULT_COMPONENTS = {part: [(code, covers, pattern)]}`: `covers` is the English line shown in the schema and the prompt; `pattern` (regex, first match wins, in this order) is used for the back-fill and the suggestion in error messages only, never to set a code silently on insert.

**ENGINE** (16)
| Code | Covers | Real examples (filed) |
|---|---|---|
| `TIMING_BELT` | belt, wet belt, tensioner, belt-driven water pump | "Timing belt in oil bath (wet belt)", "Timing belt and camshaft gear", "Timing belts (two belts, interference engine)" |
| `TIMING_CHAIN` | chain, guides, tensioner, rattle | "Timing chain stretch (tensioner, guide rail)", "Timing chain / tensioner cold-start rattle" |
| `CAM_PHASER` | camshaft adjuster, VANOS, cam gear/pulley | "VANOS solenoid valves", "Camshaft adjuster failure (recall window)", "Recall: camshaft pulley (Ford 16B42)" |
| `OIL_CONSUMPTION` | piston rings, valve stem seals, crankcase ventilation / PCV | "Oil consumption at high mileage", "Oil consumption (piston rings / crankcase ventilation)", "PCV membrane in the valve cover" |
| `OIL_LEAK` | gaskets and seals leaking oil | "Oil loss at valve cover and sump gaskets", "Oil leaks (timing cover, cam bridge seal, rear main seal)" |
| `ENGINE_INTERNALS` | oil pump, lifters, crankshaft, bores, head gasket, oil pressure | "Oil pump", "Crankshaft (early production)", "Cylinder bores (catalyst debris, overheating)" |
| `COOLING` | water pump, thermostat, hoses, expansion tank, radiator, fan | "Coolant module (water pump and thermostat housing)", "Coolant loss from pump, hoses or expansion tank" |
| `IGNITION` | coils, ignition module, plugs (misfire) | "Ignition coils", "Ignition coil failure (misfire)" |
| `FUEL_SYSTEM` | injectors, high-pressure pump/line, in-tank pump, intake-valve deposits | "Injectors and injector seals", "Fuel pump (in tank)", "Intake valves / injectors (direct injection)" |
| `TURBO` | turbocharger, wastegate, boost control | "Turbocharger wear", "Wastegate actuator (boost control) rod breakage" |
| `EMISSIONS` | EGR, DPF, catalyst, lambda sensors, AdBlue/SCR, charcoal canister, tank venting, exhaust manifold | "EGR valve / EGR cooler", "Diesel particulate filter (DPF)", "AdBlue / SCR system" |
| `ENGINE_MANAGEMENT` | throttle body, air-mass meter, intake flaps, engine sensors and ECU, idle/judder control | "Throttle body / idle control", "Twinport intake flaps", "Crankshaft position sensor" |
| `ENGINE_MOUNTS` | engine and gearbox mounts | "Engine mounts", "Rear engine mount" |
| `HV_BATTERY` | high-voltage / hybrid traction battery | "Hybrid battery (NiMH) module or pack replacement" |
| `ELECTRIC_DRIVE` | motor, inverter, DC-DC, on-board charger and port, 48 V starter-generator | "Inverter coolant pump", "On-board charger (AC charging)", "48 V mild-hybrid system" |
| `OTHER` | needs `notes` saying what it is | |

**GEARBOX** (11)
| Code | Covers | Real examples |
|---|---|---|
| `CLUTCH` | clutch disc/pressure plate, dry or wet dual-clutch packs (judder, wear) | "Clutch wear", "DQ200 dry double clutch" |
| `CLUTCH_ACTUATION` | slave/master cylinder, release bearing, clutch actuator, delay valve | "Clutch release bearing or slave cylinder failure", "DSG clutch actuator or slave cylinder" |
| `DUAL_MASS_FLYWHEEL` | dual-mass flywheel | "Dual-mass flywheel and clutch" |
| `MECHATRONICS` | DCT/AT control unit, valve block, accumulator, solenoids | "DQ200 mechatronic unit failure", "Mechatronic unit (valve block, sensors, hydraulic accumulator)" |
| `AT_CVT_INTERNALS` | torque converter, automatic/CVT internals, shift quality | "Automatic gearbox (MB3) … shift quality" |
| `GEARS_SYNCHROS` | synchronisers, gear wheels | "Synchroniser wear (crunching or crackling when shifting)", "3rd/4th gear synchroniser rings" |
| `BEARINGS_DIFFERENTIAL` | shaft bearings, differential, satellite gears (whine) | "Differential bearing wear (whine on overrun)", "Satellite gear or differential damage" |
| `SHIFT_MECHANISM` | linkage, cables, lever bushes | "Shift mechanism wear (linkage, shift lever bushes, lubricant leaks)", "Gear linkage" |
| `GEARBOX_LEAK` | gearbox and output-shaft seals | "Gearbox oil leak (input shaft seal or output seal)" |
| `DRIVESHAFT` | driveshafts, CV joints and boots, propshaft and joint disc | "Drive shafts and CV joints", "Propshaft elastic joint disc (Gelenkscheibe)" |
| `OTHER` | needs `notes` | |

**CHASSIS** (13)
| Code | Covers | Real examples |
|---|---|---|
| `SUSPENSION_ARMS` | control arms, bushes, ball joints, anti-roll bar links, axle mounts and bolts | "Front axle suspension (control arms, bushes, ball joints)", "Suspension arm bushes" |
| `SPRINGS_DAMPERS` | coil springs, spring seats, shock absorbers, strut top mounts | "Coil springs", "Front and rear springs and shock absorbers worn" |
| `STEERING` | tie-rod ends, steering joints and gear, play, power-steering hoses/assist | "Steering joints and tie rod ends worn", "Steering gear bolt corrosion (recall)", "Electric power steering control unit" |
| `WHEEL_BEARINGS` | wheel bearings | "Rear wheel bearings" |
| `BRAKES` | pads, discs, calipers, drums, ABS/ESP hydraulic unit | "Brake pads", "Rear drum brakes seize" |
| `BRAKE_LINES` | brake hoses and lines, servo, pedal | "Brake hoses (cracked)", "Brake lines (rear axle)" |
| `PARKING_BRAKE` | handbrake lever, cable, mechanism | "Parking brake (mechanical)", "Handbrake (parking brake) cable and mechanism" |
| `EXHAUST` | pipes, flex pipe, silencers | "Exhaust silencer and pipe", "Exhaust pipes and silencer rust" |
| `BODY_RUST` | sills, wheel arches, seams, underbody, tailgate rust | "Sill panels", "Sills and load-bearing body parts (rust)" |
| `WATER_INGRESS` | seals, drains, leaks into the cabin or boot | "Water ingress through seals and drains" |
| `BODY_FITTINGS` | dashboard, wiper linkage, door/tailgate mechanics, seat-belt anchors, wheels | "Cracked centre dashboard", "Windscreen wiper arm hinges", "Tailgate wiring harness and lock" (wiring part: see ELECTRICS) |
| `ROOF` | sunroof, panoramic roof, convertible roof (body style / option level) | "Body / panoramic roof" (legacy, no part) |
| `OTHER` | needs `notes` | |

**ELECTRICS** (11)
| Code | Covers | Real examples |
|---|---|---|
| `BATTERY_12V` | starter/start-stop battery, terminals, positive cable | "Battery plus connector (repair cable)", "Start-stop battery" |
| `STARTER_ALTERNATOR` | starter, solenoid, relay, alternator | "Starter motor", "Recall 6/2017: starter relay" |
| `LIGHTING` | headlights, aim, levelling, tail lights, indicators, bulbs | "Lighting faults (bulbs, lamps, switches, indicators)", "Rear light seals (LED tail light)" |
| `AIRBAG` | airbags, gas generators, airbag control unit, occupant sensing, pretensioners | "Driver airbag gas generator (Takata) — recall KBA 15308R", "Airbag control unit" |
| `ABS_ESP` | ABS sensors and ABS/ESP control unit | "ABS wheel speed sensors", "Recall 07/2017: ABS/ESP control unit ground connection" |
| `AIR_CONDITIONING` | compressor, condenser, refrigerant, flap actuators, blower | "A/C flap actuator defect", "A/C compressor failure" |
| `INFOTAINMENT` | display, touchscreen, radio/navigation, instrument cluster, emergency call | "Infotainment touchscreen fault (pre-facelift)", "Instrument cluster sudden failure" |
| `BODY_ELECTRONICS` | window regulators and switches, central locking, immobiliser, ignition lock, seat heating, washer pump, stalks | "Window regulator (front and rear)", "Ignition lock (steering lock)" |
| `WIRING` | harnesses, plugs, fretting corrosion, power distributor, grounds, moisture | "Power distributor plug (fretting corrosion)" |
| `DRIVER_ASSISTANCE` | cameras, radar, tyre pressure monitoring | "Windscreen camera fogging", "Tyre pressure warning" |
| `OTHER` | needs `notes` | |

### 4.2 Migration and validation
```sql
-- 039_fault_component_code.sql (#221 phase 3): a controlled component code per fault; `component` stays readable English.
-- No CHECK: the vocabulary lives in config.FAULT_COMPONENTS and grows without a table rebuild; the API enforces it.
ALTER TABLE faults ADD COLUMN component_code TEXT;
CREATE INDEX faults_component_code ON faults (part, component_code);
```
- `agent.FIXED_CODES['faults.component_code']` = every code of every part (flat), so the generic check rejects unknown codes.
- One rule in `clean_row` (or `guard_duplicate`'s caller): on insert `component_code` is required and must belong to the row's `part`; `OTHER` needs non-empty `notes`; on PATCH a NULL is tolerated, a set code is checked against the (merged) part. The 400 text names the suggested code: `component_code: required; for 'Timing chain stretch' (ENGINE) probably TIMING_CHAIN; codes: …`.
- `GET /api/agent/schema` adds `"fault_components": {"ENGINE": [{"code": "TIMING_BELT", "covers": "…"}, …], …}`.
- `consistency.same_fault(a, b)` takes rows (callers pass `a.get('component')` today; change them to pass the row dicts, with a `component_code` key optional): **different codes (neither `OTHER`) → never the same** (this alone separates "Timing chain" from "Timing belt"); same code → the same when the names share one content word (`_words`) or `difflib` ratio ≥ 0.5 (two different `COOLING` faults like "Water pump" vs "Expansion tank crack" stay distinct); a missing or `OTHER` code → today's wording rules. Tune the 0.5 on the pilot pairs before merging.
- `agent_tools.fault(..., code=...)` → `component_code`; `pilot_compare.py` pairs faults with `staging.pair` once it exists.

### 4.3 Back-fill of existing rows
`python -m carlos.consistency --backfill-codes [--apply]` via the API with an admin token (`GET /api/admin/data/faults`, `PATCH /api/agent/faults/<id> {"component_code": …}`): dry run by default, prints `id, part, component → code` per row and the `OTHER` ones; `--apply` PATCHes only rows whose code is NULL and whose pattern matched (never `OTHER`: those stay NULL and are listed for a person). Run it on `data/` (data commit) and the pilot copies; a fault left NULL keeps the wording-only matching.

### 4.4 Prompt text (`_header.md`, `research.md`, `research-car.md` fault step, `cost-research-protocol.md` "Faults")
"Every fault gets a `component_code` from `fault_components` of `GET /api/agent/schema` for its part (`code=` in `fault()`). Pick the code of the component that fails, not of the symptom (oil loss from a valve cover gasket is `OIL_LEAK`, oil burnt through the piston rings is `OIL_CONSUMPTION`). `OTHER` only when no code fits, with `notes` saying what it is. Two faults with the same code on one car are the same fault unless you say why not (`distinct_of`)."

## 5. Test plan
Unit tests in `tests/` with the existing in-memory fixtures; each phase also runs `python -m unittest` and the README integrity check.
- **P1 component codes:** unknown code 400; code from another part 400; `OTHER` without notes 400; insert without code 400 naming the suggestion; PATCH with NULL accepted; schema lists `fault_components`; `same_fault`: TIMING_BELT vs TIMING_CHAIN never, two `COOLING` with no shared word not, same code + shared word yes, NULL codes fall back to wording; back-fill dry run on a fixture maps the 28 pilot strings as in 4.1 (fixture list in the test) and `--apply` writes only NULL rows; every code in `FAULT_COMPONENTS` is in `FIXED_CODES`.
- **P2 staging:** a RESEARCH token's `POST /api/agent/faults` creates a `research_findings` row and no `faults` row, answers a negative id; a negative `source_id`/`gearbox_id` of the same run accepted, of another run 400; listing tables 403; level outside the scope 403; second staged fault with the same code and a similar name 409 naming the staged id, `distinct_of` accepted; a staged fault similar to a real one 409 (#221 unchanged); PATCH of `-id` updates the payload and key; PATCH of a real row creates one `patch` finding and merges later PATCHes; run B cannot read run A's findings; dry grade: a run that staged every item of a fixture variant grades complete while the real tables stay unchanged (row counts before = after); migration 040 keeps every 038 column and row (copy test like 037/038).
- **P3 compare + arbiter API:** fixtures with one of each outcome per kind; band two steps → material, one step → agreed; price 1,000 vs 1,250 agreed, 1,000 vs 1,500 disputed + material; one-sided cheap rare fault not material; identity diff material; group pairing by code with one per side pairs differently worded faults with a `component` diff; agreement figure on a fixture; compare is idempotent; `GET /api/agent/disputes` only for the ARBITER token and its parent; verdict validation (OWN needs a staged run-C finding; unknown dispute 404); the arbiter's done gate re-queues once with unanswered disputes.
- **P4 merge:** each row of the 3.5 table on a fixture; AGREED picks the less favourable figure and cites both runs' sources; BOTH writes the second with the `Distinct from` prefix; NEITHER writes nothing; UNRESOLVED material writes a `SOURCES_DISAGREE` flag and leaves identity unwritten; a 409 against a real row is skipped with "exists as"; staged level get-or-create reuses an existing gearbox by code; the shell-engine relink; negative ids mapped in `fixed_fault_id`; merge twice writes nothing new; `change_log` rows carry the request user; source reuse by URL.
- **P5 flow:** `advance` creates both runs with identical `missing` and `scope`; a fully researched variant skips RESEARCH/ARBITER/MERGE and goes to TAX; overlap: the second request waits, is released by the first's MERGE (not by its RESEARCH_A) and runs only what is still missing, or is DONE "Researched by request #x"; ARBITER SKIPPED without material disputes; research run closes DONE with gaps after 2 attempts; MERGE FAILED when items remain, the parent FAILED, TAX and LISTING still run; cancel while a run is RUNNING leaves no MERGE; a legacy parent (has a GENERATION child) keeps the legacy stages; `FLOW='units'` restores them for new parents; `worker.prompt_for` for RESEARCH_A/ARBITER includes the staging paragraph; worker handles MERGE without launching Claude (fake `CLAUDE_CMD` that fails if called); `mine()` returns the `detail` lines.
- **P6 pilot (data, no PR of code):** run the dual flow on the round-2 pilot cars in two pilot copies; report agreement per kind, number of arbiter runs, faults per car vs round 2 (5 vs 12), Haiku runs and wall time per car; tune `STAGE_TOLERANCE`, the material rules and the `same_fault` 0.5 from it.

## 6. Phases (one PR each)
| # | PR | Depends on | Parallel with |
|---|---|---|---|
| P1 | Component codes: `config.FAULT_COMPONENTS`, migration 039, `FIXED_CODES`, per-part validation, schema exposure, `same_fault` code gate, `fault(code=)`, back-fill tool, prompt/protocol text | – | P2 |
| P2 | Staging: migration 040 (units, `scope`, `research_findings`, `research_matches`), `carlos/staging.py` (write, keys, validation, apply, dry grade), server routing of staged tokens, `GET /api/agent/stage`, staged `todo` | P1 for the fault key (until then `component_code` NULL keys `fault:<part>:NULL`) | P1 |
| P3 | Compare + arbiter interface: `staging.compare`/`pair`, tolerances, material rules, agreement, disputes endpoints, `arbiter.md` | P2 | P4 |
| P4 | Merge: `staging.merge` through `agent_write`, flags, relink, `POST /api/agent/merge` | P2 (builds its own `research_matches` fixtures) | P3 |
| P5 | Flow: `research_units` stages, `advance`/`finish`/`release_shared` changes, overlap waiting, worker (prompts, MERGE without Claude, timeout), `research.md`, `_header.md`, UI progress + i18n, docs (`data-model.md`, `api.md`, protocol "Who does what") | P2–P4 | – |
| P6 | Pilot run and tuning (data repository; tolerance changes as a small code PR) | P5 | – |
After P6: retire the five legacy unit prompts and `LEGACY_STAGES` once no open request uses them (separate PR).

## 7. Not verified / risks
- (unverified) That `clean_row` accepts a payload whose FK columns hold negative ids once `check_parents` is skipped for them; P2 adds a `staged=True` path if not.
- (unverified) Performance on the Pi 2B: `consistency.conflicts()` scans every catalogue variant per write and `consistency.check()` runs after every fault write; a merge of ~80 rows may take minutes. If so, P4 restricts `conflicts()` to the target's generation/engine first (the #221 risk note) and runs `consistency.check()` once at the end.
- (unverified) That one Haiku run can cover a whole new car (~45 contract items plus the faults) within 150 minutes; staged rows survive a timeout and the continuation run resumes, but the pilot must confirm the timeout and the attempt count.
- (unverified) Whether `POST` of an existing gearbox/family natural key answers 409/400 or reuses the row; the merge does get-or-create itself either way.
- The dry grade holds the write lock while grading; concurrent writers wait on the busy timeout.
- Two Haiku runs with one prompt are not independent experts; agreement overstates certainty. A later option: run B with a different model or a shuffled source order.
- Including cheap one-sided faults keeps some of the "12 vs 5" spread (bounded: under €500, at most `occasional`); the pilot shows whether to drop them instead.
- The component vocabulary was tested on reliability items and pilot faults, not on a large set of `faults` rows (only 28 exist); `ROOF` and `AT_CVT_INTERNALS` have almost no examples yet.

## Summary of the phases
1. P1 component codes: `faults.component_code` (migration 039), 51 codes in four parts from 367 filed components (98 % covered), validation, schema, code-gated `same_fault`, back-fill tool.
2. P2 staging: migration 040 (units RESEARCH_A/B, ARBITER, MERGE, `scope`, `research_findings`, `research_matches`); staged tokens' writes go to staging with negative ids; dry-grade done gate.
3. P3 compare and arbiter: pairing by key and component code, tolerances, material rules, agreement %, disputes API and the arbiter prompt.
4. P4 merge: deterministic server code through `agent_write` with the #221 guard; less-favourable rule; verdicts; `SOURCES_DISAGREE` flags for unresolved disputes.
5. P5 flow: new stages (research pair → arbiter → merge → tax → listing → insurance), skip of researched levels, overlap waiting released by the merge, worker without Claude for MERGE, progress UI.
6. P1 and P2 can start in parallel; P3 and P4 in parallel after P2; P5 after both.
7. P6: pilot on the round-2 cars, tune tolerances and thresholds, then retire the legacy units.
8. Cold starts per new car: 6–8 instead of 9; already-researched cars skip the research entirely.
9. Owner decision needed: merge as server code (recommended) instead of a merge agent.
10. Unverified: negative FK ids in `clean_row`, Pi performance of the guard during the merge, one Haiku run covering a whole car.
