# Evenness yardstick: metrics and defect codes

Cars = listings that are not WITHDRAWN (`--all` adds them). A listing without a variant (`vehicle_id` NULL) is reported as `NO_VARIANT` and left out of the table. Each car inherits rows from its vehicle, gearbox, engine, engine family, generation and body style (archived rows ignored; private rows of other accounts ignored; a row whose `applies_from/to` build window excludes the car's first registration ignored, as `carlos.costs.in_window` does). Not evaluated: option-level rows (`option_id`) and the retired gearbox family level.

## Table columns
| Column | Meaning | Why it matters |
|---|---|---|
| faults | active `faults` rows on the stack | research depth |
| engine_faults | of those, engine or engine-family level | a car with 0 is unresearched |
| exp_fault_eur | sum (parts + labour) x (share_low + share_high)/2; curve-only faults count 0 | the repairs component of the TCO; spread above 2x signals depth, not cars |
| fault_prob_null | faults with `probability_basis` NULL | method not stated |
| jobs | distinct maintenance `job` codes (active rows) | schedule completeness |
| estimated_pct / verified_pct | share of maintenance, tyre and tax rows by status | evidence level (ESTIMATED vs VERIFIED, OFFICIAL FEE LEVEL, PRIMARY, QUOTE, DOCUMENTED) |
| rel_slots_of_3 | slots with a key and a rating: AUTOSCORE (engine), TUEV_REPORT (HU), ADAC_PANNENSTATISTIK (breakdowns) | reliability score coverage |
| rel_checks | `rel.*` research checks on the stack | N/A is evidence only with notes |
| recalls / recall_items_unlinked | recall rows; checklist items about recalls without `recall_id` | recall coverage |

## Defect codes (table, row id)
- `NO_VARIANT`: listing without a variant: not researched.
- `FAULT_NO_BASIS`, `FAULT_NO_QUOTE`, `FAULT_UNPRICED`: fault without `probability_basis` (an audit convention, not a contract requirement; `ESTIMATE` is accepted), `quote` (the sentence it rests on; protocol "Faults: frequency and shape"), or any price (the contract grades such a fault MISSING).
- `ZERO_NOT_NULL`: 0 in a price or hours column. Unknown is NULL; a real zero needs a note (the script does not read the note: check it).
- `DIY_PAIR`: a DIY-able job with only one of workshop price and DIY parts price (contract grades it MISSING).
- `ESTIMATED_NO_NOTE`, `VERIFIED_LOW_QUALITY`: on maintenance, tyre and tax rows, `ESTIMATED` without a derivation in `notes` (tax: `notes` or `basis`), or `VERIFIED` / `OFFICIAL FEE LEVEL` on a source that is not A or B.
- `STALE_QUOTE`: insurance `QUOTE` (`insurance_data` or `listing_quotes`) older than 60 days (`config.QUOTE_MAX_AGE_DAYS`).
- `CHECK_NO_EVIDENCE`: a `NONE FOUND`, or an `N/A` for `rel.*`, `gen.recalls` or `gen.safety`, whose notes hold neither a URL nor a search (`site:`, "search", "searched"); or any other `N/A` without a reason (10+ characters). The word "research" is not a search.
- `NONE_FOUND_CONTRADICTED`: a `NONE FOUND` on `eng.risks`, `fam.risks`, `gen.risks`, `gbx.risks` or `bdy.risks` while faults exist on that level (engine and family count as one pool).
- `DUPLICATE_LEVELS`: same job or same fault code on several levels of one stack (re-scope with one PATCH). A fault whose notes start "Distinct from fault" (the API's `distinct_of` marker) is skipped.
- `CERTAIN_NO_RESTART`: certain `maintenance` cost without a `maintenance_resets` row (a job restarted through `listing_history` instead is a false positive: read it).
- `DOUBLE_COUNT`: certain cost whose text shares 2+ content words with an active fault (a hint: read both rows).
- `RECALL_UNLINKED`: free-text recall checklist item without `recall_id`.
- Catalogue-wide: `JOB_UNEVEN` (job on some cars only, lists any `NONE FOUND` check that stands in for it), `GRADE_MISMATCH` (one domain, several quality grades among the shared sources; account-private sources are left out; legitimate for a site with PDFs and press pages, so review).

The script finds candidates; a human or the owner decides. It does not check magnitude, units, naming consistency (`item` wording), the `since` of a check against the contract version or stale ADAC editions beyond `rel_slots_of_3`; read the rows for those.
