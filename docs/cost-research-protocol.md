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
- **DIY** = the jobs the owner does: call `diy_jobs()` (the account's `diy_jobs` preference from the setup wizard; `diy_skills` is an older free-text note; default when unset: engine oil and filters, spark plugs, yearly service, brake pads/discs, battery, bulbs, wipers). Everything else is **workshop** (timing drive, coolant, brake fluid, clutch, engine internals). DIY items carry parts price + hours; workshop items carry the total job price. Hours are shown separately and never priced.
- **HU/AU** every 24 months at the regional fee (`agent_tools.HU_FEE_EUR`; adjust from the local inspection organisation's fee table and cite it).
- **Tyres:** one set of all-season tyres; standard size of the variant; price = median of 4–5 mid-range all-season tyres in that size; tread life and fitting from `agent_tools` defaults (ADAC tests, tyre shops), cited.
- **Purchase/sale:** the same items for every car for sale (`purchase_sale_defaults`): re-registration, plates, pre-purchase check, with the regional fees from an official fee table cited as a shared source. Deregistration for the reference car.
- **Resale at the end:** `resale_rule_of_thumb` from the asking price unless comparable listings give a better figure (then record those as the source).
- **Fuel:** one real-world source **per drivetrain**, the same for every car of that drivetrain including the reference: for petrol, diesel and hybrid cars the autokostencheck.de real-world average of the exact HSN/TSN variant (`consumption()`); for electric cars the Spritmonitor average in kWh/100 km (`consumption(..., electric=True)`, owner decision 2026-11-05: autokostencheck often has 1–2 reports per electric variant). Use the **reported average with its number of reports** ("Ø … aus N Angaben", with min and max), never the site's stored catalogue or cost-calculator figure shown elsewhere on the page; note the site's report filter (e.g. 60–125 % of the NEDC figure). Other databases are cross-checks only.
- **Listing contradictions:** mileage → the higher figure (PATCH `listings.mileage_km`, log a `correction`); CO2 → the catalogue value of the assumed HSN/TSN until the registration document is seen (the listing value for the tax if the registration period uses CO2); anything else → the less favourable value, the alternative in `notes`; always a `warning` log entry.
- **Seller claims** ("timing belt new", "service done") are trusted at no cost, get a `restart(..., 'SELLER CLAIM')` and a checklist item asking for the invoice; if none is shown at the viewing, the cost is added then.
- **Tyres that come with the car:** a new set is a certain cost only when the existing tyres are unusable (age ≥ 8–10 years or worn). Usable summer-only tyres add nothing.
- **Statuses:** `ESTIMATED` for anything derived (say how in `notes`), `VERIFIED` only for official/primary figures for this engine or variant, `PENDING` while unknown (never with a number).

## Electric cars
The same steps, with these differences (owner decisions 2026-11-05; sources in the EV design of #121):
- **Identify:** `fuel_type='Electric'`; the engine is the motor (code from the manufacturer or the type approval) with `power_ps`, `battery_usable_kwh`, `ac_charge_kw`, `dc_charge_kw`; displacement, aspiration, injection and timing drive stay NULL. Plug-in hybrids: `fuel_type='Plug-in hybrid'` and the combustion engine's fields; their energy cost is not supported yet (fuel stays unknown). Full hybrids: `fuel_type='Hybrid'`, costed as petrol.
- **Consumption:** the Spritmonitor year-round average of the model and battery (`consumption(v, value, n, lo, hi, source_id, electric=True)`, kWh/100 km), with the number of vehicles or reports, min and max. Winter is inside the year-round average; no adjustment. Say in `notes` whether the figure is measured at the wallbox or in the car.
- **Maintenance:** no oil, air filter, spark plugs or timing drive. Keep brake fluid, cabin filter, brakes, 12 V battery and wipers (generation), and the electric jobs on the engine: `DRIVE_COOLANT` (battery/motor coolant loop: interval and workshop price, or a check `NONE FOUND` for a lifetime fill) and `REDUCTION_GEAR_OIL` (or a check `NONE FOUND`). HU without AU (no emissions test) at the regional fee.
- **Battery (`eng.hv_battery`):** record the battery warranty (years / km / minimum % health, e.g. 8 years / 160,000 km / 70 %) with a check `FOUND` citing it (quality A/B), and price the high-voltage battery as one `risk()` on the engine with a generic window and a probability with its reason (replacement typically €6,400–16,500). Never a second battery row per listing.
- **Reliability parts:** `ENGINE` = motor, inverter, high-voltage battery and its management, on-board charger and charge port, thermal management/heat pump; `GEARBOX` = reduction gear and driveshafts.
- **Listing:** the seller's battery health figure goes in `battery_soh_claim` (%); `capture_listing.py` adds the checklist item asking for a SoH certificate (method, date, km; ADAC guide ≥ 88 % at 100,000 km) to every electric listing.
- **Tax:** the BMF calculator with the permitted total weight, recording the annual amount **after** the exemption; the calculation applies the exemption itself (first registered by 2030-12-31: 10 years, until 2035-12-31 at the latest), so a car exempt for the whole period needs no tax row.
- **Resale:** comparable listings first; without them `resale_rule_of_thumb(L, electric=True)` takes the low case as the expected value (DAT: 3-year-old electric cars keep 51.5 % of the list price vs 62.7 % for petrol).
- **THG-Quote:** information only (volatile, broker-dependent); never deducted from the cost.
- **Charging:** the account's answers (setup step Charging) set the electricity price; nothing to research per car.

## Steps for one car
**New account:** run `shared_sources()` once first; it registers the shared reference sources (registration and plate fees, pre-purchase check, depreciation rule of thumb, HU/AU fee, tyre test) that `purchase_sale_defaults`, `hu`, `tyres` and `resale_rule_of_thumb` cite, and does nothing when they exist.

Start with `todo(listing_id=L)` and `todo(vehicle_id=V)`, read the listing (`listing(L)`: description, attributes, claims, photo count) and the variant (`variant(V)`: engine, generation, inherited rows).

1. **Identify the car**: PATCH `generations/<id>` (name and code, start/end of sale, facelift year), `engines/<id>` (code, description, fuel, displacement, power, aspiration, injection, timing drive) and `vehicles/V` (trim, gearbox, body, emissions, CO2, HSN/TSN). Sources: ADAC Autokatalog (HSN/TSN, tyres, engine), Wikipedia, manufacturer data, dieversicherer.de for HSN/TSN candidates. A TSN not on the listing is recorded as the best candidate with "assumed" in `notes`; the user confirms it from the registration document (field 2.2). Set `status`/`technical_status` to `VERIFIED` (two agreeing sources) or `PARTIAL`.
2. **Reliability** (`reliability()` per weak point at its level, then `checklist_from_reliability(L)`): the same four sources for every car: ADAC Pannenstatistik or Gebrauchtwagen-Info, the TÜV-Report, one buying guide, one engine-specific source. Severity by the rule in `ranking.md`; `inspection_action` is a concrete check for a viewing ("cold start: listen for chain rattle for 5 s"). One row per distinct failure. Every row gets a **part** (`part=` in `reliability()`): `ENGINE` (everything that makes it run: block and head, timing drive, oil consumption and leaks, intake, turbo, injection and fuel pump, ignition, cooling incl. water pump and thermostat, EGR/DPF/catalyst, engine mounts and engine sensors), `GEARBOX` (gearbox, clutch and its hydraulics, dual-mass flywheel, driveshafts), `CHASSIS` (suspension, steering, wheel bearings, brakes and brake lines, body, rust, water ingress, exhaust pipes and silencers), `ELECTRICS` (battery, alternator, starter, lighting, locks, windows, A/C electronics and compressor clutch, infotainment, airbag/ABS/ESP electronics, steering lock). Each part starts at 9 and loses the points of its 3 worst weak points, so research all four parts with the same sources and record every source consulted per part with `check(level, id, 'rel.<PART>.<source>', source_id, 'FOUND' | 'NONE FOUND')`, also when it lists nothing: a part without its checks is unknown (see "The research contract"). A **manufacturer recall** is its own row with `recall=True` and an `inspection_action` that names the check ("dealer check by VIN that recall X was done"); `checklist_from_reliability(L)` gives every recall its own checklist item, linked by `reliability_item_id`, and the recall stops counting when that item is OK or N/A.
   - **Only recalls that can apply to this car:** check the engine, gearbox and build window against the car (first registration as the latest possible build date). A recall for another engine is written on that engine or not at all; one whose build window starts after this car's first registration is not written for it. When it cannot be decided, write it and leave its checklist item PENDING for the owner's VIN check.
   - **Generic wear is not a weak point.** Clutch, brake pads and discs, battery, bulbs and wipers wear on every car: their cost is a priced risk or a maintenance item. They become a `reliability_items` row only when a source flags them for this model or engine as above average (e.g. "clutch wears early", a known dual-mass flywheel fault), and the row says which source.
   - **The checklist is the owner's.** Agents create checklist items but never set their status (OK, PROBLEM, N/A): that is the result of the owner's viewing.
3. **Consumption** (`consumption()`): the autokostencheck page of the exact variant with average, number of reports, min, max. If the exact variant has no page, the nearest one (same engine and power) and say so. The "Gemeldeter Durchschnitt: X l/100 km … Grundlage sind N … Meldungen" block is sometimes rendered by JavaScript, so a plain fetch only shows the stored "Praxisverbrauch": never use that figure; read the page in the browser (main agent) or leave consumption empty and report the URL.
4. **Maintenance schedule** (`item(..., job=...)` per job at its level, `hu(v)`, `deactivate_packages()` if old package rows exist): manufacturer intervals (km and months) from service plans or manuals. Every job gets its `job` code (`config.JOBS`; the contract finds jobs by it) and, since the research is shared and each account's DIY choice picks one price at calculation time, **both prices** for a job any owner may do (`config.DIYABLE_JOBS`: oil and filters, plugs, brakes, battery, bulbs, wipers, coolant, timing drive, clutch): DIY parts from shops and the workshop price of the whole job; workshop-only jobs (HU, brake fluid, drive belt) the workshop price. A price the account's choice needs and nobody found stays NULL: the cost is unknown and the to-do names the job, never the other price instead. Note the source of every price (quality D for search snippets). Interval sources, best first: A the manufacturer's service plan, owner's manual or service booklet for this engine; B ADAC, an authorised dealer page, Haynes/Bucheli; C aggregators (autodoc club, carwiki, repareo); D forums. Use the manufacturer's **normal-use** interval; when a reliable source says it is too optimistic for this engine (long-life oil services, "lifetime" fluids, wet belts, direct-injection or turbo engines), use the shorter preventive interval and begin `notes` with "Preventive interval:" plus the reason, the source and the manufacturer's figure. Never shorten without a stated reason. `VERIFIED` only with an A or B source for this engine; otherwise `ESTIMATED` saying what was not found. If a better source changes the interval of a job that is also a certain repair or a restart, check that the certain repair is still due.
5. **Repair risks** (`risk()` at its level) for the km window of this car: each known failure with a km window, a probability over that window **with the reason** (statistics, "typical life ~160k km", "age"), and a price (parts + labour, or DIY parts + hours). Age-driven items (battery, rust) use the ownership window. **Every risk gets a price**; when none is found, estimate parts and labour from similar jobs (labour ≈ 100 €/h), status `ESTIMATED`, the derivation in `notes`. Engine damage, body rust and similar large risks are priced too, with a realistic probability. **Window rule:** `probability` is the chance of the failure anywhere in `[km_from, km_to]`, and the cost model multiplies it by the share of that window this car drives in the period. So a row that only this car uses (variant level) takes this car's ownership window (`km_now` → `km_now + period`) and the probability for those years; a row on the engine or generation, which other listings inherit, takes a generic window covering every plausible car on that level (e.g. 50,000–250,000 km) and the probability for that whole window. Never put a 4-year probability on a wider window: it is diluted for every car.
6. **Certain one-off costs of this car**, each with an `item` that names the job and why it is due ("Timing belt kit with water pump (due by age: 11 years, limit 10)"):
   - **Service book vs. jobs due by age:** a claim naming the job ("Zahnriemen neu", "Bremsflüssigkeit gewechselt") is trusted as `restart(..., 'SELLER CLAIM')` plus a checklist item asking for the invoice; a document showing it is `DOCUMENTED`. A generic "Scheckheftgepflegt" / "service history" covers only the routine yearly service (oil and filters); it does **not** cover jobs due by age or km (timing belt or chain kit, coolant, brake fluid, spark plugs): when one of those is overdue and not documented, it is certain maintenance. The same rule for every car.
   - **Maintenance due at purchase** (`certain(L, 'maintenance', ...)`): a job from the maintenance schedule that is due now or overdue and not documented as done (timing belt or chain kit by interval, coolant, brake fluid, spark plugs, service). It is maintenance, not a repair, even when overdue. Always `restart(L, item_id, 'CERTAIN REPAIR', source_id, unit_cost_id)` so the schedule restarts and the job is not counted twice.
   - **Repairs** (`certain(L, 'repairs', ...)`): a fault this car has now (a stretched chain the owner reports, a leak, worn brakes on the photos, a defect in the HU report).
   - **Tyres** (`certain(L, 'tyres', ...)`): see the tyres rule above.
7. **Tyres** (`tyres()` at the variant or generation): standard size and median price; the size on the listing photos overrides when visible.
8. **Purchase/sale and resale** (`purchase_sale_defaults(L)`, `resale_rule_of_thumb(L)`).
9. **Listing checks and log**: checklist items for every seller claim to verify (HU, service book, new parts, owners); `warning` entries for red flags (price far below market, contradictions); a final `verification` entry summarising what was researched.

## Browser steps (main agent)
10. **Tax**: the official calculator with registration period, fuel, displacement and CO2 or emissions class; record as in `AGENTS.md`.
11. **Insurance**: the comparison site with the confirmed profile and HSN/TSN; median of the 5 cheapest reasonable offers; record as in `AGENTS.md` and `browser-tasks.md`.

## The research contract (what "researched" means)
`carlos/research.py` lists what must be known on each level; `GET /api/agent/schema` → `research_contract` publishes it, and `todo()` reports every missing item (`catalogue` per generation, engine and variant on its own; `models` per variant with its engine and generation). Each item is graded from the rows **on its own level**, so a level counts as researched the same way whichever listing triggered the research:
- **MISSING**: nothing acceptable, a source below the item's minimum quality, or a check recorded against an older contract (`since`).
- **ACCEPTED**: present, but `ESTIMATED` or from a C/D source. A row found one level too low (an engine job on the variant) counts as ACCEPTED at most, and the to-do says to move it.
- **VERIFIED**: a verified, official or primary row from an A/B source; for a check, an A/B source.

A level is **researched** when no item is MISSING and **verified** when every item is VERIFIED. The confidence criterion is the mean grade of the variant's, its engine's, its generation's and its listing's items (VERIFIED 1, ACCEPTED 0.5, MISSING 0).

**Checks** (`check(level, id, task, source_id, result, notes)`, table `research_checks`) record a task done on one level: `FOUND`, `NONE FOUND` ("consulted, nothing to report": a clean part counts as researched) or `N/A` (does not apply, e.g. no facelift). Write one per source consulted, also when the source lists nothing.

| Item | Level | Accepted when | Min. quality |
|---|---|---|---|
| `gen.identity` | generation | start and end year of the whole production run (status VERIFIED to verify) | – |
| `gen.facelift` | generation | `facelift_year`, or a check `N/A` when there was none | – |
| `gen.hu` | generation | the `HU` job with an interval and the workshop fee | – |
| `gen.brake_fluid` | generation | the `BRAKE_FLUID` job with an interval and the workshop price | – |
| `gen.brakes`, `gen.battery`, `gen.wipers`, `gen.cabin_filter` | generation | the job (by `job` code) with an interval, the DIY parts and the workshop price | – |
| `gen.recalls` | generation | check: recall search (KBA or manufacturer), FOUND or NONE FOUND | B |
| `gen.risks` | generation | body/chassis risks, every one priced, or a check `NONE FOUND` | – |
| `eng.identity` | engine (combustion) | code (not "unknown…"), fuel, displacement, power, aspiration, injection, timing drive | – |
| `eng.identity_ev` | engine (electric) | code (not "unknown…"), fuel, power, usable battery kWh, AC charging kW | – |
| `eng.hv_battery` | engine (electric) | check: battery warranty (years / km / % health) and the priced battery risk, FOUND or NONE FOUND | B |
| `eng.drive_coolant`, `eng.reduction_gear_oil` | engine (electric) | the `DRIVE_COOLANT` / `REDUCTION_GEAR_OIL` job with an interval and the workshop price, or a check `NONE FOUND` | – |
| `eng.oil`, `eng.air_filter` | engine (combustion) | the job (by `job` code) with an interval, the DIY parts and the workshop price | – |
| `eng.spark_plugs` (petrol, hybrid, plug-in hybrid), `eng.fuel_filter` (diesel) | engine | the job with an interval, the DIY parts and the workshop price | – |
| `eng.timing_belt` | engine (belt or unknown) | the `TIMING_DRIVE` job with an interval, the DIY parts and the workshop price | – |
| `eng.timing_chain` | engine (chain or gear) | a job, or a check `NONE FOUND` (no scheduled replacement) | – |
| `eng.coolant` | engine (combustion) | the job, or a check `NONE FOUND` citing the lifetime fill | – |
| `eng.risks` | engine | engine risks, every one priced, or a check `NONE FOUND` | – |
| `var.identity` | variant | HSN, TSN, gearbox, body, emissions class, CO2 (`technical_status` VERIFIED to verify) | – |
| `var.consumption` | variant | `Autokostencheck average` (electric: `Spritmonitor average`, kWh/100 km) with sample size, min and max | C |
| `var.tyres` | variant (or its generation) | size, price per tyre, tread life | – |
| `var.tax` | variant | a tax row from the BMF Kfz-Steuer-Rechner (`tax_official_calculator`) | A |
| `var.gearbox` | variant (automatics) | check: weak points of this automatic gearbox | C |
| `rel.<PART>.<source>` | engine (ENGINE) or generation (GEARBOX, CHASSIS, ELECTRICS) | check per part and source: `adac`, `tuev` (B), `guide` (C) and, for ENGINE, `engine_specific` (C). **A part without all its checks is unknown**, and so is the reliability score (it lowers the coverage; it never scores full points or 0) | B/C |
| `lst.insurance` | listing | a quote younger than 60 days (the reference car: the premium the owner pays) | – |
| `lst.tax_covered` | listing | a tax row whose registration window covers the car's first registration (an electric car exempt for the whole period needs none) | – |
| `lst.valuation` | listing | a `resale_end` valuation | – |
| `lst.purchase_sale`, `lst.checklist`, `lst.capture`, `lst.photos` | listing (for sale) | purchase costs; a checklist item for every weak point; a capture; archived photos | – |

Changing the contract: add the item to `research.py` and this table in the same PR (a test checks the ids); a new item makes every level it applies to incomplete at once. When an item's rule gets stricter, raise its `since` to the new `CONTRACT_VERSION`, so checks recorded against the older contract stop counting.

## Definition of done
- `todo(vehicle_id=V)` and `todo(listing_id=L)` are empty except owner decisions (verdict) and items that need the user (TSN confirmation); the variant's `state` is `researched` or `verified`.
- `GET /api/listings/L` shows every TCO component not NULL and `tco_complete` true.
- Every risk has a price (estimated when necessary); every combustion engine has aspiration, injection and timing drive; every electric engine its usable battery kWh and AC charging power.
- The agent's report lists: what was written (rows per table and level), every assumption (TSN, sizes, intervals), risks priced only by estimate, questions for the user.
- Main agent: `python -m unittest`, integrity check, commit of the data repository, push.
