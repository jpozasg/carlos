# Cost research protocol (one car → complete TCO)

How every car is researched and costed, so all totals are built the same way and stay comparable. `AGENTS.md` always applies (NULL = unknown; every data point cites a source with quality A–D; English free text; writes only through the API). The reusable agent prompt is `prompts/research-car.md`; the write helpers are `agent_tools.py`.

## Who does what
| Step | Who | Why |
|---|---|---|
| 0. Capture the listing | main agent, in the user's browser | bot-protected sites; see `browser-tasks.md` |
| 1–9. Model research and costs | one research agent per car (several in parallel) | web research and API writes for its own variant, engine, generation and listing only |
| 10. Tax (official calculator) | main agent, browser | official source |
| 11. Insurance (comparison site) | main agent, browser, with the user's OK | personal data of the account holder |
| 12. Review, tests, commit | main agent | one place checks totals and consistency |

Research agents never use a browser, never touch another listing or another account's data, never change `project_parameters`, shared sources, repository files, git or the schema.

## Data levels: where a row goes
Every knowledge row is written to exactly one level and inherited by every car below it:
- **engine** (`level='engine'`): oil and filters, spark plugs, timing drive, coolant, drive belt, engine faults (chain rattle, oil consumption, turbo, injectors, wet belt), engine-related repair risks, engine-level consumption only when no variant page exists.
- **generation**: HU/AU, brakes, wipers, bulbs, battery, suspension, body rust, electrics, interior; chassis repair risks; tyre size when every engine shares it.
- **variant** (default): the exact HSN/TSN data: consumption (the autokostencheck page of the variant), tax, insurance, tyre size when it differs per engine.
Before writing, read `variant(V)`: rows already inherited must not be written again. If a car shares an engine code or a generation with an existing row, reuse it (`GET /api/engines`, `GET /api/generations`) instead of creating a second one.

## Period and shared conventions
- Window: `km_now` (listing) to `km_now + annual_km × ownership_years` (the account's parameters). Time-based items use the same number of years.
- **DIY** = the jobs the owner does, from `project_preferences.diy_jobs` (the setup wizard's list; `diy_skills` is an older free-text note; default: engine oil and filters, spark plugs, yearly service, brake pads/discs, battery, bulbs, wipers). Everything else is **workshop** (timing drive, coolant, brake fluid, clutch, engine internals). DIY items carry parts price + hours; workshop items carry the total job price. Hours are shown separately and never priced.
- **HU/AU** every 24 months at the regional fee (`agent_tools.HU_FEE_EUR`; adjust from the local inspection organisation's fee table and cite it).
- **Tyres:** one set of all-season tyres; standard size of the variant; price = median of 4–5 mid-range all-season tyres in that size; tread life and fitting from `agent_tools` defaults (ADAC tests, tyre shops), cited.
- **Purchase/sale:** the same items for every car for sale (`purchase_sale_defaults`): re-registration, plates, pre-purchase check, with the regional fees from an official fee table cited as a shared source. Deregistration for the reference car.
- **Resale at the end:** `resale_rule_of_thumb` from the asking price unless comparable listings give a better figure (then record those as the source).
- **Fuel:** the primary consumption is the autokostencheck.de real-world average of the exact HSN/TSN variant (`consumption()`), the same source for every car including the reference. Other databases are cross-checks only.
- **Listing contradictions:** mileage → the higher figure (PATCH `listings.mileage_km`, log a `correction`); CO2 → the catalogue value of the assumed HSN/TSN until the registration document is seen (the listing value for the tax if the registration period uses CO2); anything else → the less favourable value, the alternative in `notes`; always a `warning` log entry.
- **Seller claims** ("timing belt new", "service done") are trusted at no cost, get a `restart(..., 'SELLER CLAIM')` and a checklist item asking for the invoice; if none is shown at the viewing, the cost is added then.
- **Tyres that come with the car:** a new set is a certain cost only when the existing tyres are unusable (age ≥ 8–10 years or worn). Usable summer-only tyres add nothing.
- **Statuses:** `ESTIMATED` for anything derived (say how in `notes`), `VERIFIED` only for official/primary figures for this engine or variant, `PENDING` while unknown (never with a number).

## Steps for one car
Start with `todo(listing_id=L)` and `todo(vehicle_id=V)`, read the listing (`listing(L)`: description, attributes, claims, photo count) and the variant (`variant(V)`: engine, generation, inherited rows).

1. **Identify the car**: PATCH `generations/<id>` (name and code, start/end of sale, facelift year), `engines/<id>` (code, description, fuel, displacement, power, aspiration, injection, timing drive) and `vehicles/V` (trim, gearbox, body, emissions, CO2, HSN/TSN). Sources: ADAC Autokatalog (HSN/TSN, tyres, engine), Wikipedia, manufacturer data, dieversicherer.de for HSN/TSN candidates. A TSN not on the listing is recorded as the best candidate with "assumed" in `notes`; the user confirms it from the registration document (field 2.2). Set `status`/`technical_status` to `VERIFIED` (two agreeing sources) or `PARTIAL`.
2. **Reliability** (`reliability()` per weak point at its level, then `checklist_from_reliability(L)`): the same four sources for every car: ADAC Pannenstatistik or Gebrauchtwagen-Info, the TÜV-Report, one buying guide, one engine-specific source. Severity by the rule in `ranking.md`; `inspection_action` is a concrete check for a viewing ("cold start: listen for chain rattle for 5 s"). One row per distinct failure.
3. **Consumption** (`consumption()`): the autokostencheck page of the exact variant with average, number of reports, min, max. If the exact variant has no page, the nearest one (same engine and power) and say so.
4. **Maintenance schedule** (`item()` per job at its level, `hu(v)`, `deactivate_packages()` if old package rows exist): manufacturer intervals (km and months) from service plans or manuals; DIY parts prices from shops; workshop prices for brake fluid, coolant, timing drive, gearbox oil if scheduled. Note the source of every price (quality D for search snippets). Interval sources, best first: A the manufacturer's service plan, owner's manual or service booklet for this engine; B ADAC, an authorised dealer page, Haynes/Bucheli; C aggregators (autodoc club, carwiki, repareo); D forums. Use the manufacturer's **normal-use** interval; when a reliable source says it is too optimistic for this engine (long-life oil services, "lifetime" fluids, wet belts, direct-injection or turbo engines), use the shorter preventive interval and begin `notes` with "Preventive interval:" plus the reason, the source and the manufacturer's figure. Never shorten without a stated reason. `VERIFIED` only with an A or B source for this engine; otherwise `ESTIMATED` saying what was not found. If a better source changes the interval of a job that is also a certain repair or a restart, check that the certain repair is still due.
5. **Repair risks** (`risk()` at its level) for the km window of this car: each known failure with a km window, a probability over that window **with the reason** (statistics, "typical life ~160k km", "age"), and a price (parts + labour, or DIY parts + hours). Age-driven items (battery, rust) use the ownership window. **Every risk gets a price**; when none is found, estimate parts and labour from similar jobs (labour ≈ 100 €/h), status `ESTIMATED`, the derivation in `notes`. Engine damage, body rust and similar large risks are priced too, with a realistic probability.
6. **Certain one-off costs of this car** (`certain(L, 'repairs', ...)`): items due by age or km now or within the period and not documented as done (timing belt by age, coolant overdue, brake fluid). When the job is also a scheduled item, `restart(L, item_id, 'CERTAIN REPAIR', source_id, unit_cost_id)` so it is not counted again.
7. **Tyres** (`tyres()` at the variant or generation): standard size and median price; the size on the listing photos overrides when visible.
8. **Purchase/sale and resale** (`purchase_sale_defaults(L)`, `resale_rule_of_thumb(L)`).
9. **Listing checks and log**: checklist items for every seller claim to verify (HU, service book, new parts, owners); `warning` entries for red flags (price far below market, contradictions); a final `verification` entry summarising what was researched.

## Browser steps (main agent)
10. **Tax**: the official calculator with registration period, fuel, displacement and CO2 or emissions class; record as in `AGENTS.md`.
11. **Insurance**: the comparison site with the confirmed profile and HSN/TSN; median of the 5 cheapest reasonable offers; record as in `AGENTS.md` and `browser-tasks.md`.

## Definition of done
- `todo(vehicle_id=V)` and `todo(listing_id=L)` are empty except owner decisions (verdict) and items that need the user (TSN confirmation).
- `GET /api/listings/L` shows every TCO component not NULL and `tco_complete` true.
- Every risk has a price (estimated when necessary); every engine has aspiration, injection and timing drive.
- The agent's report lists: what was written (rows per table and level), every assumption (TSN, sizes, intervals), risks priced only by estimate, questions for the user.
- Main agent: `python -m unittest`, integrity check, commit of the data repository, push.
