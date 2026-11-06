# Target design: data model, ranking, resale and research workflow

Status: **for review** (issue #172). Nothing here is built yet. It consolidates the owner's decisions of 2026-11-06 in #164 (PR #170), #165, #166, #167, #168 and #169 and the two independent reviews (data model, ranking). The reset and re-research (#167) is the **last** step.

## 1. Principles

1. **Facts are researched once and stored once** in the shared catalogue, at the level they belong to. Every account with a matching car reuses them.
2. **Settings are applied at calculation time.** Research never depends on an account's km/year, years, budget or postcode. Changing a setting only reruns arithmetic.
3. **Unknown is never 0.** A missing fact stays NULL and is shown as missing.
4. **The same method for every car**, with the same sources, depth and reference tables.
5. **A car is scored only when it is comparable:** every weighted criterion has a value and its research meets the minimum. Otherwise it shows "not scored yet" with what is missing.
6. **Second-hand cars only** (#165). New cars and leasing are out of scope.

## 2. Levels and entities

```
global_defaults (HU, brake fluid, labour rate …)
engine_family ─< engine          gearbox_family ─< gearbox
          \                         /
generation (whole production run; phases = date windows)
          \           |           /
           variant  (UNIQUE hsn+tsn → generation, engine, gearbox)
              |
           listing  (per account) ─< history, checklist, quote, valuation, log, photos, captures
```

| Entity | Holds | Natural key (UNIQUE) |
|---|---|---|
| global_defaults | facts true for all cars unless overridden (HU 24 months, brake fluid 2 years, labour rate) | key |
| engine_family | EA211, PSA EB, Toyota NR … | name |
| engine | code, fuel, cc, kW/PS, aspiration, injection, timing drive, battery kWh (EV) | code + kW |
| gearbox_family | DQ200, MQ200, AL4 … | name |
| gearbox | code (0AM, 0CW), type MANUAL / DCT / AT / CVT / SINGLE-SPEED, gears | code |
| generation | make, model, code, start/end of the whole run, facelift year | make + model + code |
| variant | HSN/TSN, generation, engine, gearbox, body, emissions class, CO2, Typklassen | hsn + tsn |
| listing (private) | price, km, first registration, trim, equipment, seller, location, claims, distance from the account's postcode, assumed-TSN flag | account + platform + listing id |

- Trim, equipment and "TSN assumed" belong to the **listing**, never to the shared variant.
- No "platform" level: chassis behaviour is tuned per model; badge twins (Aygo/C1/108) get a note.
- Duplicates are prevented by the UNIQUE keys; a worker resolves an existing row before creating one.

## 3. Knowledge

### 3.1 Faults (replace weak points + repair risks)

One record per **design fault** (not wear):

| Field | Meaning |
|---|---|
| component, part | ENGINE / GEARBOX / CHASSIS / ELECTRICS (required) |
| issue, mechanism | what fails and why |
| how to notice / inspection_action | feeds the viewing checklist |
| consequence | ENGINE_DAMAGE / STRANDS / SAFETY / COST / COSMETIC |
| price | workshop parts + labour, DIY parts + hours |
| probability curve | 2–4 points: km → cumulative share failed (e.g. 100k: 10 %, 200k: 40 %); optional age points for rust, rubber, batteries |
| probability_basis | STATISTIC / EXPERT / ESTIMATE |
| usage flags | SHORT_TRIPS, TOWING … (shown, no multipliers) |
| window | optional built/registered from–to (facelift fixes, #153) |
| level | exactly one of engine_family, engine, gearbox_family, gearbox, generation, variant |

**Severity is derived, not chosen:** SAFETY or ENGINE_DAMAGE → HIGH; STRANDS or COST ≥ €1,500 → MEDIUM; COST < €1,500 → LOW-MEDIUM; COSMETIC → LOW.

**Placement:** engine faults (incl. engine electrics, EV drive unit/HV) → engine or engine family; gearbox and clutch faults → gearbox or gearbox family; chassis, brakes, rust, suspension → generation (variant for 4×4, sport suspension, body exceptions); body electrics/infotainment → generation with phase windows.

**Expected repair cost for one car:** with F(x) the cumulative curve (linear between points),
`p = (F(km_end) − F(km_now)) / (1 − F(km_now))`, expected cost = p × price. The same with age when an age curve exists; the larger of the two counts, never both. km_end uses the account's km/year at calculation time.

**Reference table for estimates** (so ESTIMATE curves are comparable): "known widespread fault" 30 % by 150k; "common" 15 %; "occasional" 5 %; "rare" 2 %; age faults by 10/15 years with the same scale.

### 3.2 Maintenance (incl. wear parts)

- One row per job: interval km and/or months, **heavy-use interval** where the manufacturer gives one, DIY parts + hours, workshop price.
- **Wear parts** (clutch, dual-mass flywheel, battery, shocks, exhaust, brakes) are maintenance with a **typical life**, not faults: clutch on the gearbox, brakes on the generation.
- **Usage:** the setup's usage profile picks normal or heavy-use intervals. Nothing else is multiplied.
- **Global defaults** cover HU, brake fluid and the labour rate; a level overrides them only when it differs.

### 3.3 Recalls (own record)

Code (KBA / manufacturer), defect, remedy, safety flag, build window or "unknown", source. Every applicable recall creates a **VIN-check** checklist item. It costs no expected repair money (the fix is free); it counts against the car while **open or unverified** (status in §4).

### 3.4 Other knowledge

| Fact | Level | Source |
|---|---|---|
| consumption | variant (engine as fallback) | autokostencheck (combustion), ev-database.org (EV) |
| tax | variant, registration window | BMF calculator |
| Typklassen | variant | GDV |
| tyres (size, price, life) | variant / generation | |
| market sample + resale fit | generation + engine + gearbox | mobile.de comparables (§4.4) |

### 3.5 Sources and research checks

- Every fact cites a source with quality A–D.
- A **research check** records "consulted source X for task T on this level: FOUND / NONE FOUND / N/A", so a clean result counts.
- **ADAC breakdown statistics, TÜV report and a buying guide** are checked on the **generation** for all four parts (they publish per model and year). **Engine- and gearbox-specific sources** are checked on their **families**.
- Models too new for statistics stay unknown, never clean.

## 4. Listing facts (private to the account)

### 4.1 History (replaces resets and certain costs)

One record per fact: target (job, fault or recall), **DONE** / **PRESENT** (needs doing now) / **OPEN**, km, date, evidence (invoice, seller claim, seen at viewing), source.
DONE restarts that job's schedule or that fault's curve; PRESENT becomes a certain cost; a recall's status lives here.

### 4.2 Insurance

Quotes on the **listing** (account profile, median of the 5 cheapest, 60-day validity); Typklassen on the variant.

### 4.3 Checklist

Generated from applicable faults (inspection action), recalls (VIN check) and listing gaps; results feed history.

### 4.4 Resale (decided in #166)

- **Research, once per model** (generation + engine + gearbox): a sample of real listings across ages and mileages; fit `price ≈ a − b·age − c·km`; store a, b (€/year), c (€/km), the sample size, date and filters.
- **Calculation, live:** value now = the line at the car's age and km; end value = the line at end age (age + years) and end km (km + km/year × years); minus the private-sale negotiation discount.
- A sample older than the refresh age, too small or too narrow → "not enough market data" (no score).

## 5. Costs (eight components)

| Component | Reads |
|---|---|
| fuel | consumption × km × fuel/electricity price (setup) |
| insurance | the listing's quote |
| tax | variant tax row whose window covers the registration |
| maintenance | jobs and wear parts due in the period (heavy-use intervals by profile), history restarts, DIY vs workshop by the account's DIY choices |
| repairs | Σ fault p × price (§3.1) + PRESENT history items |
| tyres | tyre row × km |
| purchase/sale | fees, pre-purchase check, registration |
| depreciation | purchase price − end value (§4.4) |

Any missing input makes that component unknown, and the TCO incomplete.

## 6. Ranking

### 6.1 Criteria

| Criterion | Measures | Proposed score curve (100 → 0) |
|---|---|---|
| cost_month | complete TCO / months | ≤ 70 % of the account's reference cost → 100; reference car's cost → 60; ≥ 150 % → 0 |
| budget (replaces cash_now) | purchase price | 100 up to ~55 % of the ideal budget, slowly to ~80 at the ideal, accelerating decline above, 0 at the maximum; above the maximum = excluded (switchable) |
| mileage | odometer | ≤ 50,000 km → 100; 250,000 km → 0 |
| age | years since registration | ≤ 3 → 100; 20 → 0 |
| reliability | fault points per part (out of 36) | 36 → 100; 18 → 0 |
| inspection | checklist problems | 0 → 100; 5 → 0 |
| power | PS vs the owner's preference | 0 at 60 PS; 100 at the setup's "enough power" |
| safety (new) | Euro NCAP stars + test year, else ESP/airbags | 5★ recent → 100; no ESP → 0 |
| distance to view (new) | km from the account's postcode, on the listing | ≤ 25 km → 100; 300 km → 0 |

- Curves are fixed per account (defaults from the setup, adjustable); a car's points never depend on the other cars.
- **Not criteria:** confidence (shown next to the score), seller type and evidence (service history, accident-free claim, HU left, dealer warranty) are **filters**.
- **Scored only when complete:** every weighted criterion has a value and research meets the minimum (§9). The owner's car is scored exactly the same way.

### 6.2 Questionnaire

Shorter than the current eight tasks, finer weights: 5–6 cars per screen, adaptive stop when weights are stable, a final screen to confirm or adjust weights. Simulated before release.

## 7. Research contract and worker workflow

| Level | Mandatory |
|---|---|
| global | HU, brake fluid, labour rate |
| engine family / gearbox family | identity; engine- or gearbox-specific source check; faults with price + curve |
| engine | identity; oil, plugs, timing drive, coolant schedule |
| gearbox | identity; gearbox service (or NONE FOUND); clutch life |
| generation | identity + phases; ADAC + TÜV + buying guide for all four parts; KBA recall search; chassis/body wear |
| variant | HSN/TSN, consumption, tax, tyres, Typklassen |
| market (gen+engine+gearbox) | resale sample + fit |
| listing | capture, history, checklist, quote, distance |

Rules: every fault has a price and a curve; every recall has a window or "unknown"; no shared row carries a window derived from one listing's mileage.

**Worker workflow** (Sonnet, through the queue):
1. Resolve the listing's variant by HSN/TSN; create missing levels.
2. Work **top-down**: global → families → engine/gearbox → generation → variant → market → listing.
3. **Skip** any level already researched; **claim** a level before researching it, so two workers never do EA211 at once.
4. Use the fixed reference tables (§3.1) for estimates.
5. No background agents; fail with a clear reason when blocked.

## 8. Build order (PR-sized)

1. **Schema rebuild** (one fresh migration, since data is wiped): families, gearboxes (supersedes PR #170), variant keys, faults, recalls, maintenance fields, global defaults, history, listing-level quotes, market fits; listings keep hsn/tsn/trim so they survive the wipe.
2. **Costs**: curve-based repairs, wear parts, heavy-use intervals, resale fit, history.
3. **Research contract v6** + to-do.
4. **Ranking**: score curves, budget curve, completeness gate, filters, safety, distance.
5. **Questionnaire** redesign + simulation.
6. **UI**: Models page levels, dossier sections, settings for curves and filters (four languages).
7. **Protocol, prompts, worker** (top-down, level claims, reference tables).
8. **Reset (#167)**: full dump (data commit + backup file) → empty catalogue, knowledge, checks, level sources → keep accounts, tokens, workers, parameters, preferences, listings with captures, photos, decisions, viewing notes, quotes → queue every listing.

**Risks:** the rebuild touches most tables (big PR; mitigate with tests per step); curve estimates are mostly ESTIMATE until better sources exist; the completeness gate will leave many cars "not scored" until research catches up; mobile.de search parameters must be verified in the browser.

## 9. Open questions (recommended values)

1. **Minimum research to be scored:** every mandatory contract item at least ACCEPTED, no MISSING (recommended), or a percentage threshold.
2. **Market sample:** ≥ 15 cars spanning ≥ 6 years of age and ≥ 80,000 km; refresh after 6 months.
3. **Negotiation discount (private sale):** 5 % (range 3–10 %), ESTIMATED — no primary source found.
4. **Curve defaults** in §6.1: confirm or adjust each.
5. **Safety source:** Euro NCAP (older tests are not comparable with newer ones; use stars + test year).
6. **Fault reference table** in §3.1: confirm the four probability levels.
