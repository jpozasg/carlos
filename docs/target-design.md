# Target design: data model, ranking, resale and research workflow

Status: **for review** (issue #172). Nothing here is built yet. It consolidates the owner's decisions of 2026-11-06 in #164 (PR #170), #165, #166, #167, #168 (rounds 1–3) and #169, the first independent data-model and ranking reviews, and two further independent designs (web research only), which agreed with the direction. Ideas that came from a review are marked **[review]**; everything else is an owner decision or follows from one. The reset and re-research (#167) is the **last** step, after a validation pilot (§8).

## 1. Principles

1. **Facts are researched once and stored once** in the shared catalogue, at the level they belong to. Every account with a matching car reuses them.
2. **Settings are applied at calculation time.** Research never depends on an account's km/year, years, budget or postcode. Changing a setting only reruns arithmetic.
3. **Unknown is never 0.** A missing fact stays NULL and is shown as missing.
4. **The same method for every car**, with the same sources, depth and reference tables.
5. **A car is scored only when it is comparable:** every weighted criterion has a value and its research meets the minimum. Otherwise it shows "not scored yet" with what is missing.
6. **Second-hand cars only** (#165).

## 2. Levels and entities

```
global_defaults (HU, brake fluid, labour rate …)
engine_family ─< engine        gearbox_family ─< gearbox
generation (whole production run; phases = build-date windows)
body_style (per generation)    option (convertible roof, sunroof, xenon, air suspension, 4×4 …)
          \        |          /
           variant (UNIQUE hsn+tsn+engine code → generation, engine, gearbox, body style)
              |
           listing (per account) ─< history, checklist, quote, log, photos, captures
market (generation + engine [+ gearbox]) ── resale coefficients (§4.4)
```

| Entity | Holds | Natural key (UNIQUE) |
|---|---|---|
| global_defaults | facts true for all cars unless overridden (HU 24 months, brake fluid 2 years, labour rate) | key |
| engine_family **[review]** | EA211, PSA EB (PureTech), Toyota NR … | name |
| engine | code, fuel, cc, kW/PS, aspiration, injection, timing drive, battery kWh (EV) | code + kW |
| gearbox_family **[review]** | DQ200, MQ200, AL4 … | name |
| gearbox | code (0AM, 0CW), type MANUAL / DCT / AT / CVT / SINGLE-SPEED, gears | code |
| generation | make, model, code, whole run, facelift year | make + model + code |
| body_style | hatchback, estate, convertible … of a generation | generation + name |
| option | equipment with its own faults or maintenance (convertible roof, sunroof, xenon, air suspension, 4×4) | name (+ generation) |
| variant | HSN/TSN + engine code (+ gearbox), body style, emissions class, CO2, Typklassen | hsn + tsn + engine |
| listing (private) | price, km, first registration, **build date** and **engine code as shown** (unknown keeps both possibilities, flagged), trim, options present, seller, location, distance from the account's postcode, claims | account + platform + listing id |

- One HSN/TSN can cover more than one engine code; the variant therefore includes the engine code.
- **Platform** is not a level, only a grouping note (badge twins Aygo/C1/108, shared MQB parts).
- Duplicates are prevented by the UNIQUE keys **[review]**; a worker resolves an existing row before creating one.

## 3. Knowledge

### 3.1 Faults (replace weak points + repair risks) [review]

One record per **design fault** (not wear):

| Field | Meaning |
|---|---|
| component, part | ENGINE / GEARBOX / CHASSIS / ELECTRICS (required) |
| issue, mechanism | what fails and why |
| how to notice / inspection_action | feeds the viewing checklist |
| consequence | ENGINE_DAMAGE / STRANDS / SAFETY / COST / COSMETIC |
| price | workshop parts + labour, DIY parts + hours |
| existence | how sure it is that the fault exists for this level: CONFIRMED (A/B source) / REPORTED (C/D) |
| probability curve | 2–4 points: km → cumulative share failed (e.g. 100k: 10 %, 200k: 40 %); optional age points (rust, rubber, batteries) |
| probability_basis | STATISTIC / EXPERT / ESTIMATE — **graded separately from existence** |
| usage | a multiplier only with a cited source; otherwise a usage-sensitive flag (SHORT_TRIPS, TOWING …) |
| window | build date from–to; "fixed from X" needs an A/B source, otherwise the fault stays and is marked uncertain |
| level | exactly one of engine_family, engine, gearbox_family, gearbox, generation, body_style, option, variant |

**Severity is derived, not chosen [review]:** SAFETY or ENGINE_DAMAGE → HIGH; STRANDS or COST ≥ €1,500 → MEDIUM; COST < €1,500 → LOW-MEDIUM; COSMETIC → LOW.

**Placement:** engine faults (incl. engine electrics, EV drive unit/HV) → engine or engine family; gearbox and clutch → gearbox or gearbox family; chassis, brakes, rust, suspension → generation (body style or option for convertible roofs, air suspension, 4×4); body electrics/infotainment → generation with phase windows.

**Windows use the build date** when the listing has it; otherwise the first registration, with the fault applied and the car flagged "build date unknown".

**Expected repair cost for one car [review]:** with F(x) the cumulative curve (linear between points),
`p = (F(km_end) − F(km_now)) / (1 − F(km_now))`, expected cost = p × price. The same with age when an age curve exists; the larger of the two counts, never both. km_end uses the account's km/year at calculation time.

**Reference table for estimates** (so ESTIMATE curves are comparable): "known widespread fault" 30 % by 150k; "common" 15 %; "occasional" 5 %; "rare" 2 %; age faults by 10/15 years on the same scale.

### 3.2 Maintenance (incl. wear parts)

- One row per job: interval km and/or months, **heavy-use interval** where the manufacturer gives one **[review]**, DIY parts + hours, workshop price.
- **Wear parts** (clutch, dual-mass flywheel, battery, shocks, exhaust, brakes) are maintenance with a **typical life** **[review]**: clutch on the gearbox, brakes on the generation.
- The setup's usage profile picks normal or heavy-use intervals.
- **Global defaults** **[review]** cover HU, brake fluid and the labour rate; a level overrides them only when it differs.

### 3.3 Recalls (own record) [review]

Code (KBA / manufacturer), defect, remedy, safety flag, build window or "unknown", source. Every applicable recall creates a **VIN-check** checklist item. No expected repair money (the fix is free); it counts against the car while **open or unverified**.

### 3.4 Reliability baseline (statistics)

**TÜV defect rates and ADAC breakdown figures**, stored **per generation and age class** (e.g. 2–3, 4–5, 6–7, 8–9, 10–11 years). They feed the reliability score as an **independent baseline** next to the faults, and are **never added to the repair cost** (the faults already carry the money).

### 3.5 Other knowledge

| Fact | Level | Source |
|---|---|---|
| consumption | variant (engine as fallback) | autokostencheck (combustion), ev-database.org (EV) |
| tax | variant, registration window | BMF calculator |
| Typklassen | variant | GDV |
| tyres (size, price, life) | variant / generation | |
| resale coefficients | market: generation + engine (+ gearbox) | mobile.de comparables (§4.4) |

### 3.6 Sources and research checks

- Every fact cites a source with quality A–D.
- A **research check** records "consulted source X for task T on this level: FOUND / NONE FOUND / N/A", so a clean result counts.
- **ADAC, TÜV and a buying guide** are checked on the **generation** for all four parts **[review]**. **Engine- and gearbox-specific sources** are checked on their **families**.
- Models too new for statistics stay unknown, never clean.

## 4. Listing facts (private to the account)

### 4.1 History (replaces resets and certain costs) [review]

One record per fact: target (job, fault or recall), **DONE** / **PRESENT** (needs doing now) / **OPEN**, km, date, evidence (invoice, seller claim, seen at viewing), source. DONE restarts that job's schedule or that fault's curve; PRESENT becomes a certain cost; a recall's status lives here.

### 4.2 Insurance

Quotes on the **listing** (account profile, median of the 5 cheapest, 60-day validity); Typklassen on the variant.

### 4.3 Checklist

Generated from applicable faults (inspection action), options present, recalls (VIN check) and listing gaps; results feed history.

### 4.4 Resale (decided in #166, percentage model)

- **Research, once per model** (generation + engine, + gearbox when it matters): comparables of the same model in **three bands** — like the car now; about 5 years older with more km; about 10 years older with about 100,000 km more. From them fit the two percentages: **a = value lost per year of age**, **c = value lost per 10,000 km** (log-linear). Store a, c, the sample size, date and filters on the shared model level; reused by every listing of that model until the sample is old.
- **Calculation, live:** value now (from the comparables like the car now) × (1 − a)^added years × (1 − c)^(added km / 10,000), minus the private-sale negotiation discount.
- A sample older than the refresh age or too thin → "not enough market data" (no score).

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

Any missing input makes that component unknown, and the TCO incomplete. The reliability baseline (§3.4) never enters these.

## 6. Ranking

### 6.1 Criteria

| Criterion | Measures | Proposed score curve (100 → 0) |
|---|---|---|
| cost_month | complete TCO / months | ≤ 70 % of the reference car's cost → 100; reference cost → 60; ≥ 150 % → 0 |
| budget (replaces cash_now) | purchase price | 100 up to ~55 % of the ideal budget, slowly to ~80 at the ideal, accelerating decline above, 0 at the maximum; above the maximum excluded (switchable) |
| mileage | odometer | ≤ 50,000 km → 100; 250,000 km → 0 |
| age | years since registration | ≤ 3 → 100; 20 → 0 |
| reliability | fault points per part (out of 36) blended with the TÜV/ADAC baseline for the car's age class | proposed: 36 → 100; 18 → 0, baseline weight to set |
| inspection | checklist problems | 0 → 100; 5 → 0 |
| power | PS | 0 at 60 PS; 100 at the setup's "enough power" |
| safety (new) | Euro NCAP stars + test year, else ESP/airbags | 5★ recent → 100; no ESP → 0 |
| distance to view (new) | km from the account's postcode, on the listing | ≤ 25 km → 100; 300 km → 0 |

- **Fixed curves** per account (defaults from the setup, adjustable); a car's points never depend on the other cars **[review: min–max problem]**.
- **Not criteria:** confidence (shown next to the score) **[review]**; seller type and evidence (service history, accident-free claim, HU left, dealer warranty) are **filters**.
- **Scored only when complete:** every weighted criterion has a value and research meets the minimum (§9). The owner's car is scored exactly the same way **[review]**.

### 6.2 Questionnaire

Shorter than the current eight tasks, finer weights: 5–6 cars per screen, adaptive stop when weights are stable, a final screen to confirm or adjust weights. Simulated before release **[review]**.

## 7. Research contract and worker workflow

| Level | Mandatory |
|---|---|
| global | HU, brake fluid, labour rate |
| engine family / gearbox family | identity; engine- or gearbox-specific source check; faults with price, existence and curve |
| engine | identity; oil, plugs, timing drive, coolant schedule |
| gearbox | identity; gearbox service (or NONE FOUND); clutch life |
| generation | identity + phases; ADAC + TÜV + buying guide for all four parts; TÜV/ADAC baseline per age class; KBA recall search; chassis/body wear |
| body style / option | faults and maintenance when they exist (or NONE FOUND) |
| variant | HSN/TSN + engine code, consumption, tax, tyres, Typklassen |
| market | three comparable bands + coefficients |
| listing | capture (build date, engine code, options), history, checklist, quote, distance |

Rules: every fault has a price, existence grade and curve; every "fixed from" window has an A/B source; every recall has a window or "unknown"; no shared row carries a window derived from one listing's mileage **[review]**.

**Worker workflow** (Sonnet, through the queue):
1. Resolve the listing's variant by HSN/TSN + engine code; create missing levels.
2. Work **top-down**: global → families → engine/gearbox → generation → body style/options → variant → market → listing.
3. **Skip** any level already researched; **claim** a level before researching it **[review]**.
4. Use the fixed reference tables (§3.1).
5. No background agents; fail with a clear reason when blocked.

## 8. Build order (PR-sized)

1. **Schema rebuild** (one fresh migration, since data is wiped): families, gearboxes (supersedes PR #170), body styles, options, variant keys, faults, recalls, reliability baseline, maintenance fields, global defaults, history, listing-level quotes, build date and engine code on the listing, market coefficients; listings keep hsn/tsn/trim so they survive the wipe.
2. **Costs**: curve-based repairs, wear parts, heavy-use intervals, percentage resale, history.
3. **Research contract** + to-do.
4. **Ranking**: score curves, budget curve, reliability baseline, completeness gate, filters, safety, distance.
5. **Questionnaire** redesign + simulation.
6. **UI**: Models page levels, dossier sections, settings for curves and filters (four languages).
7. **Protocol, prompts, worker** (top-down, level claims, reference tables).
8. **Validation pilot (before any re-research):** two independent workers each research the same known cases — PSA PureTech (wet belt), VW EA111/EA211, DQ200 DSG, Renault H5Ft, a convertible roof. Compare placement (level), windows and probabilities between the two and against known facts; fix the prompt or the model where they disagree. Then a **ranking sensitivity check**: vary weights, curves and missing data on the pilot cars and confirm the order behaves as expected.
9. **Reset (#167)**: full dump (data commit + backup file) → empty catalogue, knowledge, checks, level sources → keep accounts, tokens, workers, parameters, preferences, listings with captures, photos, decisions, viewing notes, quotes → queue every listing.

**Risks:** the rebuild touches most tables (big PR; mitigate with tests per step); curves and baselines are mostly ESTIMATE/C-quality until better sources exist; the completeness gate will leave many cars "not scored" until research catches up; one HSN/TSN with several engine codes needs the listing to show the engine code; mobile.de search parameters must be verified in the browser.

## 9. Open questions (recommended values)

1. **Minimum research to be scored:** every mandatory contract item at least ACCEPTED, no MISSING (recommended), or a percentage threshold.
2. **Market sample:** ≥ 5 cars per band; refresh after 6 months.
3. **Negotiation discount (private sale):** 5 % (range 3–10 %), ESTIMATED — no primary source found.
4. **Curve defaults** in §6.1: confirm or adjust each; and the **weight of the TÜV/ADAC baseline** inside reliability (proposed 1/3 baseline, 2/3 faults).
5. **Age classes** for the baseline: follow TÜV's classes (2–3, 4–5 … 10–11 years).
6. **Safety source:** Euro NCAP stars + test year.
7. **Fault reference table** and **existence grades** in §3.1: confirm.
