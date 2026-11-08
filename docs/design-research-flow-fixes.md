# Design: research flow fixes after the pilot (2026-11-09)

Design only; nothing here is implemented yet. Evidence: `~/pilot-archive/compare-round3-dual.md` (`pilot_compare.py`): maintenance
jobs on the same level agreed on the interval in 44 % (14/32; round 1: 53 %), research checks in 72 %, faults matched 24 of
36/40 with 8 of 24 on different levels (5 of them engine family vs engine), recalls 0 codes in common (15 vs 14), 20 open
`SOURCES_DISAGREE` flags. Constraints: Python stdlib only, no data deleted (outdated rows are archived), schema changes only as
`migrations/NNN_*.sql`, contract changes in `carlos/research.py` and the protocol table in the same PR.

Prompts that change: `docs/prompts/units/research.md` (the worker's research unit) and `docs/prompts/research-car.md` (in-session
stop-gap); rules live in `docs/cost-research-protocol.md` and the prompts point to them, so the two prompts cannot drift.

---

## 1. Maintenance intervals: fixed source order and a conservative tie-break

**Cause.** The protocol (step 4) lists sources "best first" but says nothing when two sources of the same tier disagree, nor
which service regime to take when the maker offers two (VW LongLife 30,000 km/24 months vs fixed 15,000 km/12 months; BMW CBS).
Runs picked different sources and different regimes, and some wrote km only or months only.

**Rule (protocol step 4, replaces the "Interval sources, best first" sentences):**
1. Source order, stop at the first tier that gives the job for this engine code: A manufacturer service plan / owner's manual /
   service booklet → B ADAC, authorised dealer, Haynes/Bucheli → C aggregators (autodoc club, carwiki, repareo) → D forums.
2. Two regimes from the maker (flexible/long-life vs fixed): take the **fixed** regime (a used car's oil and driving history is
   unknown); say so in `notes`.
3. Sources of the **same tier** disagree: take the **shorter km and the shorter months, each on its own** (component-wise
   minimum), and write `Interval: shorter of <source A km/months> and <source B km/months> (tie-break).` in `notes`.
4. A preventive interval shorter than the manufacturer's only from a **B-or-better** source naming this engine (or two C sources);
   `notes` begin `Preventive interval:` with the reason, the source and the maker's figure (unchanged rule, now with a minimum).
5. Write **both** km and months whenever any source in the chosen tier gives both; NULL only when no source gives that dimension.
6. Never invent: no source at all for the job → the job stays missing in the to-do (unchanged).

**Data structure / contract:** none. The rule is deterministic given the same sources; we measure first and add a structured
`interval_basis` column only if agreement stays low (that would be an Opus data-structure decision).

**Files:** `docs/cost-research-protocol.md` (step 4), `docs/prompts/units/research.md` (item 2: replace the interval sentence by
"intervals by the protocol's source order and tie-break, step 4"), `docs/prompts/research-car.md` (step 4, same pointer),
`pilot_compare.py` (report km and months agreement separately, and how many disagreeing pairs carry the tie-break note).

**Migration:** none. **Test:** `tests/test_worker_prompts.py`: the research unit prompt names the tie-break ("shorter km and the
shorter months") and the fixed-regime rule; a `pilot_compare` unit test on two tiny in-memory databases for the km/months split.

## 2. Fault coverage: every fault named by two or more sources is recorded

**Cause.** A run records the checks (`rel.<PART>.<source>` FOUND) but the contract never asks *which* faults a source named,
so one run filed a fault two sources mention and the other skipped it ("Only in A/B" lists; TÜV age-class defects such as
brake hoses, springs, lighting were filed by one run only).

**Data structure (migration):** `research_checks.named_codes TEXT CHECK (named_codes IS NULL OR json_type(named_codes) = 'array')`:
the `component_code`s (from `fault_components` of the check's part) that this source names as a weak point. For the `tuev`
source: every defect the TÜV-Report marks above average in **any age class** it reports for the generation (car-independent,
so the shared research stays the same whichever listing triggered it). Generic wear the TÜV marks above average counts (the
protocol already allows it when a source flags it for the model).

**Contract:** new item `rel.coverage` (level `variant`, `since` = the new `CONTRACT_VERSION`): for each part, every component
code named by **≥ 2 distinct sources** (`adac`, `tuev`, `guide`, `engine_specific`/`gearbox_specific`) across the variant's
levels must have a fault with that `part` and `component_code` on one of the variant's levels; a FOUND check without
`named_codes` makes the item MISSING (the run must say what it found). `OTHER` never counts toward the threshold.
Implementation: `Contract.level('variant')` already passes the generation as an extra level; extend `extra` to the engine, its
family and the gearbox so the item's candidate function sees all their checks and faults (`rows('faults', 'generation',
'engine', 'engine_family', 'gearbox')`). The to-do line names the missing codes per part.

**Files:** `migrations/0NN_research_check_codes.sql` (+ `python migrate.py --schema`), `carlos/research.py` (item, helper,
version), `carlos/agent.py` (validate `named_codes` codes against `fault_components` of the part encoded in the task),
`carlos/staging.py` (carry the field through `research_findings` payload and compare it as a set for `check` findings),
`agent_tools.py` (`check(..., codes=None)`), protocol (contract table + step 2), both prompts (item 3 / step 2: "list the codes
each source names in `codes=`; file every code two sources name"), `docs/data-model.md`, `pilot_compare.py` (per part: codes
named by ≥ 2 sources in both runs vs filed in both).

**Test:** `tests/test_app.py`: two FOUND checks naming `OIL_LEAK` for ENGINE and no such fault → `rel.coverage` MISSING with the
code in the to-do; add the fault on the engine family → not missing; a FOUND check without codes → MISSING; invalid code → 400.
`tests/test_staging_merge.py`: `named_codes` survives a merge.

## 3. Recalls: aggregator fallback when the KBA site is unreachable, recorded as checks

**Findings in the code.** `gen.recalls` already accepts quality C (`research.py`, #303) while the protocol table still says B.
And `gen.recalls` accepts `N/A` (`FOUND_OR_NONE`): an "unreachable" check citing the KBA source (quality A) grades the item
**VERIFIED** without any recall search — a loophole. Recall codes are free text, so the two runs shared none.

**Rule (protocol step 2, recalls; both prompts):**
1. Order: KBA Rückrufdatenbank (A) → manufacturer recall page (A) → ADAC recall list (B) → one aggregator (C, e.g. CarWiki).
2. Each source tried gets a check: unreachable/blocked → `check('generation', G, 'gen.recalls', kba_source, 'N/A', 'unreachable: <reason>')`,
   then continue down the list; the first reachable source gives `FOUND` or `NONE FOUND`. Stop after the first reachable A/B
   source; with only C reachable, the item is ACCEPTED (not VERIFIED), as today.
3. Recall `code` format: the KBA reference when any source gives it (`KBA-14729R`); otherwise `<MAKE>-<YYYY-MM>-<COMPONENT_CODE>`
   (month of the recall announcement, component code from `fault_components`), never `UNKNOWN-…` or prose. Only recalls that can
   apply to the car's engine, gearbox and build window (unchanged).

**Contract:** `gen.recalls` accepts `('FOUND', 'NONE FOUND')` only (N/A records the attempt but does not satisfy it). No `since`
bump (existing FOUND/NONE FOUND checks keep counting); bump `CONTRACT_VERSION` with a comment.

**Files:** `carlos/research.py`, `docs/cost-research-protocol.md` (table row: min quality C; the fallback text), both prompts,
`carlos/agent.py` `code_formats` (publish the recall code pattern; reject `UNKNOWN-` prefixes for `recalls.code`).
**Migration:** none. **Test:** `tests/test_app.py`: an `N/A` gen.recalls check from an A source leaves the item MISSING; N/A + a
C `NONE FOUND` → ACCEPTED; a recall with code `UNKNOWN-X` → 400; `KBA-14729R` and `VW-2019-08-CAM_ADJUSTER` accepted.

## 4. Engine family: grading asymmetry and `fault(level='engine_family')`

**What the code does.**
- `agent_tools.scope(v, 'engine_family')` reads `engine_family_id` from `GET /api/vehicles/<v>` (`db.VARIANT_SQL`, `e.family_id`).
  When the engine has no family it returns `{'engine_family_id': None}`; `agent.validate` then counts zero levels and answers
  400 "faults must attach to exactly one level". **This is a bug** in the helper: no guard, a misleading error, and the same for
  `level='gearbox'`/`'gearbox_family'`/`'body_style'` and for `check('engine_family', None, …)`. The server is right to refuse.
  (Not verified: whether a staged family, `-10`, patched onto a staged engine shows in `variant()` during a research run; the
  PR's test covers it.)
- Grading (`Contract.resolved`): without a family, `fam.risks` and `rel.ENGINE.engine_specific` are graded on the **engine's**
  rows, so one set of engine faults satisfies `eng.risks` and `fam.risks`, plus a hint "no engine family yet: graded on the
  level below" per item. With a family, they are graded on the family only (`lower` has no `engine_family` entry), so engine
  faults no longer count for `fam.risks` and family faults never count for `eng.risks`. **Asymmetric:** a run that creates a
  family must evidence two items separately; one that does not, once. This is why the runs split the same fault between
  family and engine (pilot: 5 of 8 level mismatches) — the cost is identical either way (the listing inherits both levels).

**Change (contract):** treat the engine and its family as one evidence pool for engine faults.
- `eng.risks` and `fam.risks` are graded on the union of the engine's and its family's rows (each a full grade, no "move it"
  hint); `rel.ENGINE.engine_specific` on the family, else the engine, and an engine-level check counts fully.
  Implementation: in `resolved()`, the `engine` and `engine_family` plan entries pass keys `[('engine_id', e), ('engine_family_id', f)]`.
- Drop the "no engine family yet" hint (the family is optional; the gearbox hint stays because `var.gearbox_level` requires it).
- Placement rule (protocol "Data levels"): a fault goes on the engine family when the source names the family or several
  engine codes of it (`N45/N46`, "all EA211"), else on the engine code; never on both.
- Helper: `scope()` raises `ValueError('variant V has no <level> yet: create it (step 1) or use level=…')` when the level id is
  None. No silent fallback (it would put shared research on the wrong level).
- `pilot_compare.py`: `LEVELS` gives `engine_families` the key `('name',)` (today it prints "engine_familie "), and faults
  match "same level" when one is on the engine and the other on that engine's family (reported separately).

**Migration:** none. **Test:** `tests/test_app.py`: `fault(level='engine_family')` on an engine without a family → clear
`ValueError` before any request (unit test on `scope` with a stub `get`); a variant with a family and faults only on the engine
→ `fam.risks` not MISSING and no hint; faults only on the family → `eng.risks` not MISSING; the todo for a variant without a
family has no "no engine family yet" line. Update `test_research_contract` expectations if they assert the hint.

## 5. Noisy flags

**Sources of noise** (pilot round 3: 11 + 9 open `SOURCES_DISAGREE`, up to 4 on one engine; merge-time flags for single runs
are already gone, #319):
- The research prompt (item 6, and item 4 for TÜV/ADAC tables) says to raise `SOURCES_DISAGREE` whenever two sources disagree,
  even when a fixed rule (less favourable figure, the tie-break of §1) already settles it.
- Nothing stops a second OPEN flag of the same kind on the same level.
- To-do hints repeat per item ("no engine family yet …", §4).

**Change:**
- Prompt + protocol ("Review flags"): raise `SOURCES_DISAGREE` **only when no rule settles the disagreement** (identity facts
  such as two engine codes or timing drives, a fault one source says was fixed and another says was not). When the
  less-favourable or shorter-interval rule applies, quote the other figure in `notes` and raise nothing. The TÜV/ADAC
  table rule (#223) keeps its flag only when the two figures differ by more than 1.5× (`config.STATS_MISMATCH_RATIO`).
- Server (`carlos/agent.py`, insert of `review_flags`): one OPEN flag per (level, kind). A second POST appends its `what`/`why`
  to the open flag (`; ` separated, capped) and answers 200 with the existing id and `merged: true`. No migration (a check in
  code, not a unique index, because CLEARED flags may repeat).
- Remove the per-item family hint (§4).

**Files:** `carlos/agent.py`, `docs/cost-research-protocol.md`, both prompts, `docs/api.md` (merge behaviour).
**Migration:** none. **Test:** two POSTs of `SOURCES_DISAGREE` on one engine → one OPEN row whose `what` holds both; a different
kind or a CLEARED flag → a new row; `test_worker_prompts.py`: the prompt no longer says to flag every disagreement.

---

## Split and order (one issue + PR each; Sonnet for code, Opus only for the §2 migration design)

| # | Issue / PR | Size | Contract version | Depends on |
|---|---|---|---|---|
| 1 | `scope()` guard for a missing level (§4 bug) | XS | – | – |
| 2 | Engine and family as one evidence pool; drop the family hint; placement rule; `pilot_compare` level key and family matching (§4) | S | +1 | 1 |
| 3 | Recalls: N/A no longer satisfies `gen.recalls`, fallback order, code format, protocol table B→C (§3) | S | +1 | – |
| 4 | Flags: raise only when no rule settles it; one OPEN flag per level and kind (§5) | S | – | – |
| 5 | Maintenance source order and tie-break; `pilot_compare` km/months split (§1) | S (docs + prompt + compare) | – | – |
| 6 | `named_codes` migration, `rel.coverage`, `check(codes=)`, staging carry-through, compare (§2) | M | +1 | 2 (union levels), 3 |

Order: 1 → 2 → 3 → 4 → 5 → 6, then one pilot round (two runs per car, `pilot_compare.py`) to measure; 3, 4 and 5 are independent
and can go in parallel worktrees. Each PR: `python -m unittest`, the integrity check, merge when green (AGENTS.md). Contract
bumps mark affected levels incomplete at once; no data is deleted or rewritten — rows already filed stay, and the next research
run (queued by the server's re-grading, #218) adds the missing checks, codes or faults.

**Success measure for the next pilot:** maintenance interval agreement ≥ 80 % (km and months each), fault level agreement
≥ 90 % (engine/family counted as one), faults named by ≥ 2 sources filed by both runs ≥ 90 %, recalls with a shared code ≥ 70 %,
open `SOURCES_DISAGREE` flags ≤ 1 per level.
