# Prompt: research and cost one car

Reusable prompt for a research agent (an agent with web access and shell access to this repository). Research requests from the accounts are run by the shared worker with `docs/prompts/research-request.md`, which uses this prompt for the research step. Replace the `{…}` placeholders. One agent per car; several can run in parallel because each writes only its own variant, engine, generation and listing. The main agent captures the listing first and runs the browser steps (tax, insurance) afterwards.

---

You are researching one used car for Carlos in `{REPO}` (SQLite behind a local API at http://127.0.0.1:8000, already running; agent token in `{REPO}/.env` or `$AGENT_TOKEN`).

**Car:** listing id {LISTING_ID} ({MAKE} {MODEL}, {TRIM}, first registration {FIRST_REG}, {MILEAGE_KM} km, {PRICE_EUR} €), variant (vehicles) id {VEHICLE_ID}, engine id {ENGINE_ID}, generation id {GENERATION_ID}. Listing URL: {URL}. Ownership period: {ANNUAL_KM} km/year × {YEARS} years = {PERIOD_KM} km.

**Read first:** the account's preferences (`python3 -c "from agent_tools import *; print(preferences()); print(diy_jobs())"`: DIY jobs, driving mix, search area), `AGENTS.md`, `docs/cost-research-protocol.md` (the procedure you follow), `docs/ranking.md` (objectivity rules), `docs/data-model.md`, and the docstrings in `agent_tools.py`. Then read the listing and the variant:
```
python3 -c "from agent_tools import *; import json; print(json.dumps(listing({LISTING_ID}), ensure_ascii=False)[:20000])"
python3 -c "from agent_tools import *; import json; print(json.dumps(variant({VEHICLE_ID}), ensure_ascii=False)[:20000])"
python3 -c "from agent_tools import *; print(todo(listing_id={LISTING_ID})); print(todo(vehicle_id={VEHICLE_ID}))"
```

**Do:** steps 1–9 of the protocol for this car:
1. identification of generation, engine (aspiration, injection, timing drive) and variant (HSN/TSN);
2. reliability items at the right level, each with its `part` (ENGINE / GEARBOX / CHASSIS / ELECTRICS: research all four) and every manufacturer recall as its own row with `recall=True`, then the checklist; record every source consulted with `check(level, id, task, source_id, result)` (`rel.<PART>.<source>`, `gen.recalls`, `gen.facelift`, …), `NONE FOUND` when it lists nothing;
3. autokostencheck consumption of the exact variant;
4. item maintenance schedule at the right level, with HU;
5. repair risks at the right level for the window {MILEAGE_KM} → {MILEAGE_KM} + {PERIOD_KM} km;
6. certain one-off costs of this car: scheduled jobs due at purchase as `maintenance` (timing belt by age, overdue fluids: never `repairs`), present faults as `repairs`, each named in `item`;
7. tyres;
8. purchase/sale defaults and resale;
9. listing checks, warnings and a final `verification` log entry.

Write everything through the helpers in `agent_tools.py` from a script in your scratchpad: `import sys; sys.path.insert(0, '{REPO}'); from agent_tools import *`. Register each source with `src(...)` (attach it to the level it describes: `vehicle_id`, `engine_id` or `generation_id`) before using it; reuse shared sources through the helpers. Pass `level='engine'` or `level='generation'` to the helpers for rows that belong to the engine or the generation; rows inherited from them already exist in `variant()`: do not write them again.

**Rules:**
- Never invent data. Unknown = leave out (NULL); every estimate says why. All free text in English.
- Research with web search/fetch only. Do **not** use a browser, solve CAPTCHAs or work around blocks (some sites block agents; that is expected: say so).
- Write only rows for variant {VEHICLE_ID}, engine {ENGINE_ID}, generation {GENERATION_ID} and listing {LISTING_ID}. Do not change other rows, `project_parameters`, shared sources, repository files, git or the schema.
- Do not do tax or insurance: the main agent does them in the browser. Find the **HSN/TSN** (and the tax calculator inputs: registration period, fuel, displacement, CO2 or emissions class) and report them.
- Every repair risk gets a price: when no price is found, estimate parts and labour (status `ESTIMATED`, say how). Never store a risk without a price.
- Same sources and depth as for every other car (protocol step 2); severity, status and quality by the rules in `docs/ranking.md`.
- If a write fails, read the API error, fix the row and retry once. Never use SQLite directly.
- **Reliability:** research all four parts (ENGINE, GEARBOX, CHASSIS, ELECTRICS) with the same four sources; each part starts at 9 and loses the points of its 3 worst weak points; a part counts only with all its source checks recorded (`check(..., "rel.<PART>.<source>", ..., "FOUND" | "NONE FOUND")`), otherwise reliability is unknown. Done means the variant's `state` in `todo(vehicle_id=V)` is `researched` (docs/cost-research-protocol.md, "The research contract"). Every manufacturer recall is its own row (`recall=True`); never bundle several recalls in one row.
- **Risk windows:** follow the window rule in protocol step 5: this car's ownership window for variant rows, a generic window with the probability for that whole window for engine and generation rows that other listings inherit.
- **Certain costs:** a scheduled job due at purchase is `certain(L, 'maintenance', ...)` plus `restart(..., 'CERTAIN REPAIR', unit_cost_id=...)`, never `repairs`; apply the service-book rule in protocol step 6 (a generic "Scheckheftgepflegt" does not cover the timing belt, coolant, brake fluid or spark plugs).
- **Consumption:** only the reported average with its number of reports; if the page shows only the stored "Praxisverbrauch" (the average is rendered by JavaScript), write no consumption and report the URL.
- **Recalls, wear and the checklist:** write only recalls that can apply to this car (engine, gearbox, build window); generic wear (clutch, pads, battery, bulbs) is a priced risk, not a weak point, unless a source flags it for this model; never set a checklist item's status (the owner does that at the viewing).
- **Search budget:** web searches are limited for the whole session (about 200, shared by all agents running in parallel). Spend them on the four reliability sources, the recalls and the consumption page first; fetch known URLs directly (ADAC Autokatalog, autokostencheck, repareo) instead of searching for them; say in the report which figures you could not source because the budget ran out.
- **Never delete.** Do not call `delete()`; if a row you wrote is wrong, PATCH it, or `archive()` it and write the right one. Deleting needs the owner's confirmation, which only the main agent can ask for.

**Report back (short):**
- HSN/TSN (confirmed or assumed) and the tax calculator inputs;
- the consumption figure;
- rows written per table and level;
- certain costs by category (maintenance due at purchase, repairs) with their names and prices, and the largest risks with prices; risks priced only by estimate;
- assumptions; questions for the user; what `todo` still lists.
