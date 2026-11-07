# Prompt: research and cost one car

Reusable prompt for a research agent (an agent with web access and shell access to this repository). Research requests from the accounts are run by the shared worker with `docs/prompts/research-request.md`, which uses this prompt for the research step. Replace the `{…}` placeholders. One agent per car; several can run in parallel because each writes only its own variant, engine, generation and listing. The listing is captured first. Tax (BMF calculator, in the browser) is done by the run that has the browser (the worker's prompt, `research-request.md`); insurance never in a headless run.

---

You are researching one used car for Carlos in `{REPO}` (SQLite behind a local API at http://127.0.0.1:8000, already running; agent token in `{REPO}/.env` or `$AGENT_TOKEN`).

**Car:** listing id {LISTING_ID} ({MAKE} {MODEL}, {TRIM}, first registration {FIRST_REG}, {MILEAGE_KM} km, {PRICE_EUR} €), variant (vehicles) id {VEHICLE_ID}, engine id {ENGINE_ID}, generation id {GENERATION_ID}. Listing URL: {URL}. Ownership period: {ANNUAL_KM} km/year × {YEARS} years = {PERIOD_KM} km.

**Read first:** the account's preferences (`python3 -c "from agent_tools import *; print(preferences()); print(diy_jobs())"`: DIY jobs, driving mix, search area), `AGENTS.md`, `docs/cost-research-protocol.md` (the procedure you follow), `docs/ranking.md` (objectivity rules), `docs/data-model.md`, and the docstrings in `agent_tools.py`. Then read the listing and the variant:
```
python3 -c "from agent_tools import *; import json; print(json.dumps(listing({LISTING_ID}), ensure_ascii=False)[:20000])"
python3 -c "from agent_tools import *; import json; print(json.dumps(variant({VEHICLE_ID}), ensure_ascii=False)[:20000])"
python3 -c "from agent_tools import *; print(todo(listing_id={LISTING_ID})); print(todo(vehicle_id={VEHICLE_ID}))"
```

**Do:** steps 1–9 of the protocol for this car. The finished list of what must exist is the research contract (`todo()` and the table in the protocol, "The research contract"); the steps below produce it:
1. identification of generation, engine (aspiration, injection, timing drive; an electric motor instead: usable battery kWh, AC/DC charging kW) and variant (HSN/TSN, gearbox, body, emissions class, CO2), plus the **levels between them** (data model, "Levels"): the engine family (`engine_families`, engines.`family_id`), the gearbox (`gearboxes`: code, type, gears; the variant's `gearbox_id`), its family (`gearbox_families`) and the body style (`body_styles`) where one applies; reuse existing rows (`GET /api/engines`, `/api/generations`, `GET /api/admin/data/<table>`), create only what is missing;
2. reliability items at the right level, each with its `part` (ENGINE / GEARBOX / CHASSIS / ELECTRICS: research all four) and every manufacturer recall as its own row with `recall=True`, then the checklist (`checklist_from_reliability`; run it again after the faults and recalls are written, it adds only what is missing); record every source consulted with `check(level, id, task, source_id, result)` (`rel.<PART>.adac|tuev|guide` on the generation, `rel.ENGINE.engine_specific` on the engine family, `rel.GEARBOX.gearbox_specific` on the gearbox family, `gen.recalls`, `gen.facelift`, …), `NONE FOUND` when it lists nothing; also the generation's TÜV/ADAC figures per age class (`gen.baseline`, `reliability_stats` with the class average, or a check `N/A`; when the tables disagree write one row with the less favourable figure, quote the other in `notes` and raise a `SOURCES_DISAGREE` flag, protocol "When the TÜV/ADAC tables disagree") and its Euro NCAP stars and year (`gen.safety`, or a check `N/A`);
3. consumption: the autokostencheck average of the exact variant; for an electric car the ev-database.org real consumption of the exact variant and battery in kWh/100 km (`consumption(v, value, None, None, None, source_id, electric=True)`; ADAC Ecotest, when one exists, as a cross-check row; never Spritmonitor);
4. item maintenance schedule at the right level, with HU: every job with its `job=` code and, for a job an owner may do (`config.DIYABLE_JOBS`), both the DIY parts and the workshop price (the research is shared; each account's DIY choice picks one);
5. faults (`fault()`, protocol "Faults: frequency and shape"; before writing one, check the variant's faults: a similar one already there is extended, not filed again — `fault()` raises `DuplicateFault` with `.existing` on a 409; PATCH that row, or pass `distinct_of=[ids]` and `notes` saying why it is a different fault) on the level the evidence names, no higher, each with an `inspection_action` when a viewing check exists for the window {MILEAGE_KM} → {MILEAGE_KM} + {PERIOD_KM} km: engine family, engine, gearbox family, gearbox, generation (body/chassis), body style; a level with none gets a check `NONE FOUND` (`fam.risks`, `eng.risks`, `gbx.risks`, `gfam.risks`, `gen.risks`, `bdy.risks`); gearbox oil service (`gbx.service`) and clutch (`gbx.clutch`) as jobs or checks;
6. certain one-off costs of this car: scheduled jobs due at purchase as `maintenance` (timing belt by age, overdue fluids: never `repairs`), present faults as `repairs`, each named in `item`;
7. tyres (`var.tyres`) and, in the browser, the annual tax (`var.tax`, protocol "Tax"; the request prompt says who does it);
8. purchase/sale defaults and resale;
9. listing checks, warnings and a final `verification` log entry.

**Drivetrain and offer: which branch applies.** Read `fuel_type` (a fixed code) first. Carlos compares second-hand purchases only (#165): a new car or a lease-only ad is not researched, and a lease offer in a used ad is ignored.

| Branch | Identify | Consumption (step 3) | Maintenance and risks (steps 4–5) | Also |
|---|---|---|---|---|
| **Petrol / Diesel** | engine code, aspiration, injection, timing drive | autokostencheck reported average of the exact variant (with reports, min, max) | oil, filters, plugs (petrol) / fuel filter (diesel), timing drive by km and age, coolant, brake fluid, HU | diesel: DPF/AdBlue risks where a source names them |
| **Full hybrid** (`Hybrid`) | as petrol; note the hybrid system in `notes` | autokostencheck, as petrol | as petrol; hybrid battery and inverter as priced risks when a source names them | costed as petrol; never record it as `Petrol` (the code exists) |
| **Plug-in hybrid** (`Plug-in hybrid`) | as petrol + usable battery kWh | autokostencheck if any; the energy cost is not supported yet (stays unknown, to-do) | as petrol + HV battery warranty check | say in the report that its fuel cost stays unknown |
| **Electric** (`Electric`) | motor code, usable battery kWh, AC/DC charging kW (no aspiration, injection, timing drive) | ev-database.org real consumption of the exact variant and battery (Wh/km ÷ 10 = kWh/100 km), `consumption(..., electric=True)`; ADAC Ecotest as a cross-check row when one exists; never Spritmonitor | no oil, filters, plugs or timing drive; `DRIVE_COOLANT`, `REDUCTION_GEAR_OIL` (or `NONE FOUND` checks), brake fluid, cabin filter, 12 V battery, HU | battery warranty check `eng.hv_battery` + one priced HV battery risk on the engine; seller's battery health in `battery_soh_claim` and the SoH-certificate checklist item; resale without comparables `resale_rule_of_thumb(L, electric=True)` |
| **New car / lease-only ad** | out of scope (#165): not researched; the capture refuses it | – |

Write everything through the helpers in `agent_tools.py` from a script in your scratchpad: `import sys; sys.path.insert(0, '{REPO}'); from agent_tools import *`. Register each source with `src(...)` (attach it to the level it describes: `vehicle_id`, `engine_id` or `generation_id`) before using it; reuse shared sources through the helpers. Pass `level='engine'` or `level='generation'` to the helpers for rows that belong to the engine or the generation; rows inherited from them already exist in `variant()`: do not write them again.

**Rules:**
- Never invent data. Unknown = leave out (NULL); every estimate says why. All free text in English.
- Research with web search/fetch. Use the browser only where the request prompt names it (the listing, the tax calculator). Never solve CAPTCHAs or work around blocks (some sites block agents; that is expected: say so and record the check as not possible rather than skipping it).
- Write only rows for variant {VEHICLE_ID}, engine {ENGINE_ID}, generation {GENERATION_ID} and listing {LISTING_ID}. Do not change other rows, `project_parameters`, shared sources, repository files, git or the schema.
- Insurance is never done in this run: it is the separate INSURANCE unit, only for accounts that opted in (Settings). Tax is done where a browser is available (the request prompt); otherwise report the **HSN/TSN** and the tax calculator inputs (registration period, fuel, displacement, CO2 or emissions class) and leave `var.tax` in the to-do.
- Every repair risk gets a price: when no price is found, estimate parts and labour (status `ESTIMATED`, say how). Never store a risk without a price.
- Same sources and depth as for every other car (protocol step 2); severity, status and quality by the rules in `docs/ranking.md`.
- If a write fails, read the API error, fix the row and retry once. Never use SQLite directly.
- **Faults (#168):** every fault gets a frequency band (systemic 50 %, widespread 25 %, common 12 %, occasional 5 %, rare 1.5 %, by 200,000 km or 15 years; systemic only with a manufacturer trace; forum-only one band milder, never above common) or a sourced curve, a shape (WEAR_KM, AGE, WINDOW, RANDOM), a price and a `quote` of the sentence it rests on: `fault(v, ..., level=...)`. Record the TÜV/ADAC figures per age class with the class average (`reliability_stats`). When sources disagree and you cannot settle it, raise a `review_flags` row on that level (docs/cost-research-protocol.md, "Faults: frequency and shape").
- **Reliability:** research all four parts (ENGINE, GEARBOX, CHASSIS, ELECTRICS) with the same four sources; each part starts at 9 and loses the points of its 3 worst weak points; a part counts only with all its source checks recorded (`check(..., "rel.<PART>.<source>", ..., "FOUND" | "NONE FOUND")`), otherwise reliability is unknown. Done means the variant's `state` in `todo(vehicle_id=V)` is `researched` (docs/cost-research-protocol.md, "The research contract"). Every manufacturer recall is its own row (`recall=True`); never bundle several recalls in one row.
- **Risk windows:** follow the window rule in protocol step 5: this car's ownership window for variant rows, a generic window with the probability for that whole window for engine and generation rows that other listings inherit.
- **Certain costs:** a scheduled job due at purchase is `certain(L, 'maintenance', ...)` plus `restart(..., 'CERTAIN REPAIR', unit_cost_id=...)`, never `repairs`; apply the service-book rule in protocol step 6 (a generic "Scheckheftgepflegt" does not cover the timing belt, coolant, brake fluid or spark plugs).
- **Consumption:** only the reported average with its number of reports; if the page shows only the stored "Praxisverbrauch" (the average is rendered by JavaScript), write no consumption and report the URL.
- **Phase windows:** a fault fixed by the facelift or a recall with a build range goes on the generation with `applies_from` / `applies_to` (first registration, `YYYY-MM`) in `fault()` or `item()`, never as a second generation; ordinary facts of the whole generation get no window.
- **Recalls, wear and the checklist:** write only recalls that can apply to this car (engine, gearbox, build window); generic wear (clutch, pads, battery, bulbs) is a priced risk, not a weak point, unless a source flags it for this model; never set a checklist item's status (the owner does that at the viewing).
- **Search effort:** research is the job, so spend what the contract needs; do not stop early to save searches. Fetch known URLs directly (ADAC Autokatalog, autokostencheck, repareo) instead of searching for them. When a source truly cannot be reached, say so in the report and record the check (`NONE FOUND` with the reason in `notes`, or `N/A`); never leave an item silently open.
- **Never delete.** Do not call `delete()`; if a row you wrote is wrong, PATCH it, or `archive()` it and write the right one. Deleting needs the owner's confirmation, which only the main agent can ask for.

**Pitfalls the research agents ran into (2026-11-05/06):**
- **TSN:** a listing rarely shows it; when you pick one from ADAC/autokostencheck, say *assumed*, list the alternatives and that the registration document (field 2.2) decides. Check it matches the listing's power (one TSN per kW).
- **Recalls:** applicability depends on the build date (VIN), not on HSN/TSN; give each recall its build window (`applies_from`/`applies_to`) and a checklist item "dealer VIN check"; a seller's "no recalls" is a seller claim, not evidence.
- **Price contradictions:** the header price and the description can differ (stale text); keep the header price, log a `warning` quoting both.
- **Brand-new models:** ADAC/TÜV statistics do not cover them; `N/A`, not a clean record.
- **Coolant "lifetime" fills and similar:** a forum post is quality D; say so and prefer the manufacturer schedule.
- **Unit and code traps:** fuel type is a fixed code (a free-text "Petrol (full hybrid)" silently breaks the contract); `quote_profile` must be JSON; 0 km is valid in a capture.

**Done means the contract is met, not that you ran out of steps.** After writing, run `todo(vehicle_id={VEHICLE_ID})` and `todo(listing_id={LISTING_ID})` again, fix every item they list, and repeat until only these remain: the owner's verdict, the insurance quote (`lst.insurance`), a TSN that only the registration document can confirm, and an item you tried and could not source (it has its check). Do not report success with research items still listed; do not describe an open item as "done in the next run". Estimated rows are fine when nothing better exists (`ESTIMATED`, say how); a missing row is not.

**Report back (short):**
- HSN/TSN (confirmed or assumed) and the tax calculator inputs (electric: first registration and permitted total weight; the battery kWh and warranty terms);
- the consumption figure and its source (electric: the EVDB page and, if any, the ADAC Ecotest);
- rows written per table and level;
- certain costs by category (maintenance due at purchase, repairs) with their names and prices, and the largest risks with prices; risks priced only by estimate;
- assumptions; questions for the user; what `todo` still lists.
