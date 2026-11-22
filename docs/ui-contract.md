# UI to data contract

What every page of the Carlos front end shows, where each value comes from, how it is formatted, what a user can change and where it is saved. Written from the code: `static/js/app.js`, `static/js/ui.js`, `static/js/i18n.js`, `static/js/api.js`, `static/js/quiz.js`, `static/js/charts.js`, `static/js/requests.js`, `static/js/pages/*.js`, `static/js/auth.js`, `static/js/legal.js`, `static/index.html`, `static/auth.html`, `static/privacy.html`, `static/impressum.html`, `static/i18n/en.json`. Server producers are named where the field is built (`carlos/costs.py`, `carlos/ranking.py`, `carlos/models.py`, `carlos/todo.py`, `carlos/server.py`, `carlos/pages.py`).

Verify a page against this file:

- Endpoints a page calls: `grep -n "get(\|post(\|patch(\|del(\|send(\|ui(" static/js/pages/<page>.js`
- Storage keys: `grep -rn "store\.\(get\|set\)(\|localStorage" static/js static/*.html`
- Fixed codes passed to `tv()`: `grep -rnoE "tv\([^)]*\)" static/js`

Sections: 1 conventions shared by every page, 2 the 15 pages and routes, 3 field dictionary, 4 browser storage, 5 fixed codes translated by `tv()`, 6 endpoint index, 7 mismatches found while checking.

---

## 1. Conventions shared by every page

### 1.1 Shell and router (`app.js`, `index.html`)

- Startup order: `applyTheme()`, `i18n.load(initialLang())`, `loadAll()`, `renderShell()`, then `route()`.
- `loadAll()` calls `GET /api/auth/me`, `/api/parameters`, `/api/tco`, `/api/todo`, `/api/sources`, `/api/preferences`, and `/api/storage` (admin only; any error becomes `null`). An admin also gets `/api/admin/users`. The result fills the state object `S`. A failure of `loadAll` shows the card "load failed" with the server message.
- First run: with no hash (or `#/compare`), an account whose preference `onboarding_done` is not set is sent to `#/start`.
- Hash router: `#/<page>[/<id>][?query]`. `current()` splits it. An unknown page falls back to `compare`. Each route loads its module with a dynamic import and calls `render(main, route)`. A route that lacks its own `h1` gets a visually hidden one (the page name). A route without `?keep=1` scrolls to the top.
- Header chips: fuel-price chip (`annual_km` · `ownership_years` · `fuel_price_eur_l` from `S.p`; warn class when `fuel_price_stale` or a preview is on, prefix `✎` during a preview); storage chip (`/api/storage`, admin only: `total_bytes` / `limit_bytes` in MB, warn at 80 %, bad at 90 %).
- Header controls: language segmented control (EN, ES, DE, PL), account chip (`S.me.username`), logout (`POST /api/auth/logout`), and for admins a "view as" select over the active accounts in `S.accounts` (sets cookie `carlos_view`, then reloads). A banner shows while viewing another account.
- Nav: compare, ranking, models, sources, settings (plus admin for admins). `aria-current` follows the route; a dossier counts as compare.
- Footer: `footer` text, the ODbL credit, the source-code link (from `<meta name="carlos-source">`, filled by the server with `SOURCE_URL`), privacy, imprint.
- Route errors: a card with `load_failed`, the error message and a Retry button (reloads the page).

### 1.2 Formatting helpers (`ui.js`)

| helper | input | output |
|---|---|---|
| `euro(n)` | number | `Intl` EUR, 0 decimals, locale grouping. `null` gives `—` |
| `num(n, d=2)` | number | max `d` decimals, grouping. `null` gives `—` |
| `eP(n)` | number or null | `euro(n)`, or the "Pending" span when null |
| `PEND()` | none | `<span class="pending">Pending</span>` |
| `pct(v, d=0)` | fraction 0–1 | `num(v*100, d)` + NBSP + `%`; null gives "Pending" (never "0 %") |
| `yrs(n)` | years | `num(n,1)` + "year"/"years" (plural by `n`) |
| `perMonth(u, suffix)` | listing row | `known_cost_per_month` as euro + suffix; the `(partial)` tag unless `tco_complete` |
| `totalP(r)` | `sumKnown` result `{sum, missing, n}` | "Pending" if nothing known; euro plus `+N pending` tag while `missing > 0` |
| `partsLaborP(a, b)` | parts, labour | both null: Pending; one null: the known part + `(partial)` tag |
| `rangeTxt(a, b, d)` | two numbers | `a–b`; an open end shows `…`; both null: Pending |
| `consumptionTxt(u)` | listing row | `num(consumption)` + `consumption_unit` (no unit invented); null gives Pending |
| `consumptionSpread(u)` | listing row | `min–max` (2 decimals) and `n=<sample>` |
| `fmtDate(iso)` | `YYYY-MM-DD…` | `dateStyle: medium` in the UI locale; other strings are shown raw |
| `sevTag(s)` | severity code | coloured tag: bad for HIGH…, warn for MEDIUM, good otherwise; the text is `tv(s)` |
| `lvlTag(l, r)` | level code, row | level tag (`tv(l)`) plus the first-registration window `applies_from–applies_to` when present |
| `qTag(q)` | quality A–D | letter badge; any other value shows `X` |
| `intervalTxt(km, mo)` | interval | `"<km> km or <n> months"`; both null gives `—` |
| `costStack` in `charts.js` | `components` of each car | segment width = value; a null or zero segment is not drawn; the tip shows euro and share |

Null rule: an unknown figure is shown as **Pending** (`PEND()`). A dash `—` appears where the helper returns it directly (`euro(null)`, `num(null)`) or where a dash is the meaning (for example the owned car's asking price, shown as "Owned").

Partial-total rule: a total that adds known parts only is never shown as complete. It carries `+N pending` (a list of rows, `totalP`), or the `(partial)` tag (`perMonth`, `partsLaborP`, the Compare subtotal, the ruler value). A complete total is shown only when `tco_complete` is true, and the Compare overview and the cards use `known_cost_subtotal` with the tag `subtotal_partial`.

### 1.3 Codes and text

- `tv(code)` returns the label from the `codes` block of `static/i18n/<lang>.json`, falling back to the English `codes` block, then to the raw value. Free text is never passed through `tv()`.
- `t(key, vars)` returns the string from the language file, then English, then the key. Plurals are `{one, few?, other}` objects. `{name}` placeholders are replaced.
- `comp(k)` is `tv(k)` with the first letter capitalised (used for the eight TCO component keys).

### 1.4 Writes: where a value is saved

- Server: all data (parameters, preferences, ranking answers and weights, checklist, notes, decisions, photos, quotes, requests, admin actions). The shared rule: a failed save is shown inline or in a toast that stays until closed (`toast(msg, true)`, role alert). A success toast goes after 3.5 s.
- Browser: only the view settings listed in section 4. Nothing else is written to browser storage.
- In memory only (lost on reload): quiz answers before the last task, the Settings draft (kept across a language or colour-mode switch), the dossier's viewing-mode flag, the photo index, invite and token texts shown on the Admin page, and form drafts (restored by the dossier's quiet redraw, see 2.6).
- URL: the tab (`?tab=`), the Compare view (`?view=`), the Models filters, the ranking quiz (`?quiz=1`), the setup step (`?step=`). A dossier tab change uses `history.replaceState`.

### 1.5 Cookies set by the app

- `carlos_view`: set by `app.js` (viewCookie) for the "view as" feature, `SameSite=Strict`, `path=/`, `Secure` on https, removed with `max-age=0` on exit.
- `carlos_session`: set by the server (HttpOnly, SameSite=Strict). The front end never reads it.

---

## 2. The pages and routes

Fifteen pages: root, compare (with six views), ranking, quiz (on ranking and in the setup wizard), listing dossier (six tabs), models (list and variant), sources, settings, admin, requests (on compare and admin), setup wizard (seven steps), login, invite, privacy, imprint.

### 2.1 Root and shell (`/`, `index.html`, `app.js`)

- **Shows:** the header, nav, footer and the route's page. With no hash it redirects to `#/compare` or `#/start`.
- **Endpoints:** `GET /api/auth/me`, `/api/parameters`, `/api/tco`, `/api/todo`, `/api/sources`, `/api/preferences`, `/api/storage` (admin), `/api/admin/users` (admin). `POST /api/auth/logout`. Translation files `GET /static/i18n/<lang>.json`.
- **Values:** header fuel chip from `parameters` (`annual_km`, `ownership_years`, `fuel_price_eur_l`), `fuel_price_stale` (warn), storage from `/api/storage` (`total_bytes`, `limit_bytes`), account from `me.username`, "view as" list from `/api/admin/users` (`id`, `username`, `is_active`).
- **Formatting:** `num(annual_km, 0) km/year`, `yrs(ownership_years)`, `num(fuel_price_eur_l, 2) €/l`, storage `num(MB, 1) / num(MB, 0) MB`.
- **User can change:** language, colour mode (Settings), "view as" account, logout, the route.
- **Saved:** language and mode in `carlos.lang` and `carlos.mode`, viewing account in `carlos_view`, logout clears the session on the server.
- **tv() codes:** the nav and footer use `t()` only; none.

### 2.2 Compare (`#/compare`, `#/compare?view=ruler|overview|costs|breakeven|details|photos`)

- **Shows:** a versus strip (owned car against the best complete car), the request panel (section 2.10), a control bar (selection presets, sort, direction, three filters, CSV export, six view buttons), and the view.
- **Endpoints:** `GET /api/tco` (from `loadAll` and `refreshTco`, with the Settings preview query), `GET /api/requests` (panel), `POST /api/requests` and `PATCH /api/requests/<id>` (panel actions).
- **Views:**
  - **ruler:** one row per car in the ordering. Value = `known_cost_per_month` on an axis from `min × 0.9` to `max × 1.05` (ticks at a round step). Shows `rank`, `cover`, `make`/`model`/`displacement`/`first_registration` (carLabel), `location` or `platform`, `delta_vs_reference / period_months` per month, a partial marker when not `tco_complete`.
  - **overview:** table. Columns: selection checkbox (not for the reference car), `rank`, car (`cover`, name, `location`/`platform`), `score` (bar at `score`%), `price_eur` (asking price, "Owned" for the reference), `mileage_km`, `metrics.age`, `known_cost_per_month` (perMonth), `known_cost_subtotal` (eP, with the `subtotal_partial` tag listing `missing_components`), `delta_vs_reference` (▲ +€ when more expensive than the owned car, ▼ € when cheaper), status tags (`budget_status`, `price_change`, `stale`, `listing_status`).
  - **costs:** a stacked bar per car from `components` for the selected component keys, widths by value. The total is `sumKnown` over the selected keys. `/month` appears when all selected keys are known and `period_months` is set. A `+N pending` marker when only some selected keys are missing (hatched segment). All selected keys missing: Pending. A negative component is listed as text.
  - **breakeven:** a line chart and table for the selected candidates against the owned car (SVG from `breakeven`: `ref_monthly`, `upfront`, `monthly`, `months`, `resale_end`, `ref_resale_end`, `payback_months`, `end_advantage`). Table: upfront, running cost/month, saving/month (`ref_monthly − monthly`), payback (`never`, `after N` when past the period, else months), end advantage (switch better / keep better). Cars not ready list the `breakeven.missing` strings.
  - **details:** full table. Groups: unit (asking price, mileage, age, km/year, power, insurance/yr, tax/yr, reliability with coverage, the three reliability slots ENGINE / HU / BREAKDOWNS with source links, confidence %, score and rank, consumption and spread); use (fuel, insurance, tax, maintenance); own (repairs, tyres, purchase/sale); depreciation; total (selected total or `incomplete_n`, subtotal, per month, range `tco_pessimistic`–`tco_optimistic`, delta, `initial_outlay`, `diy_hours`).
  - **photos:** cards with `cover`, `photo_count`, rank badge with score, tags, a 9-part cost-data meter (`known` of `S.components.length`, from `missing_components`), verdict text and a compare toggle.
- **Ordering:** key-based sort (score, price, mileage, age, km/year, consumption, insurance, tax, cost per month, known cost per month, power, reliability, inspection, confidence, selected cost). Unknown values always go last. `known_month` puts partial subtotals after complete ones.
- **Filters:** `pinRef` (owned car first), `overBudget` (hides `over_max`), `withdrawn` (hides `WITHDRAWN`, on by default). The owned car is never hidden.
- **Formatting:** score `num(score, 0)`; age `num(age, 1)` in the table and `yrs` in cards; mileage `num(km, 0)`; consumption per section 1.2; euro helpers as above.
- **User can change:** which cars are compared (checkboxes, presets all / none / best 5 / within budget / shortlist), sort key and direction, the three filters, the view, the cost components shown in costs (presets all / running / none), the break-even highlights (top 5 by end cost by default, or chips), CSV export (downloads the ordered list client-side).
- **Saved:** browser only: `carlos.selected`, `carlos.knownIds`, `carlos.costSel`, `carlos.beHi`, `carlos.sort`, `carlos.sortPrev`, `carlos.filters`, `carlos.cview`. A car added since the last visit is selected automatically (`knownIds`).
- **tv() codes:** missing component keys (`tv(m)` in the overview tag and the cost card: `fuel`, `insurance`, `tax`, `maintenance`, `repairs`, `tyres`, `purchase_sale`, `depreciation`), `tv(what)` in the break-even missing list, `tv('WITHDRAWN')` in the status tag.

### 2.3 Ranking (`#/ranking`, `#/ranking?quiz=1`)

- **Shows:** the ranked list (rank, car, criteria contribution bar with a tip per criterion, one sentence "why", score), the unscored cars with the reason, the criteria legend, the priority profile (weights with the count of answers behind each), the weight sliders (in a closed "fine-tune" block), and the formula table (criterion, better direction, basis).
- **Endpoints:** no reads of its own (uses `S.ranking`, `S.units`, `S.p` from `/api/tco`). Writes: `POST /api/parameters` with `{ranking_weights}` (slider change, 500 ms after the last move; reset sends `null`), and `{ranking_answers, ranking_weights: null}` when the quiz ends.
- **Values:** `ranking.criteria`, `ranking.weights`, `ranking.answered`, `ranking.manual`, `ranking.retired_answers`, `ranking.tally` (per criterion: `shown`, `best`, `worst`), `ranking.candidates`. Each car: `rank`, `score`, `explain[]` (`criterion`, `weight`, `score`, `contribution`, `why_missing`), `excluded` (`over_max` or `filter:<name>`), `not_scored` (`criteria`, `research`), `listing_status`.
- **Formatting:** score `num(score, 0)`; contribution `num(x, 0)` + %; weights integers 0–5; reference car listed by score without a rank ("your current car, not ranked").
- **User can change:** weights (sliders, integers 0–5), reset to the answers, retake the quiz.
- **Saved:** server, `POST /api/parameters` (`ranking_weights`, `ranking_answers`). Failed slider save restores the server weights on the sliders and shows the message.
- **tv() codes:** none on this page (criteria labels use `t('c_<key>')`).

### 2.4 Quiz (`quiz.js`, on `#/ranking?quiz=1` and in setup step 5)

- **Shows:** six best–worst tasks (`ranking.py` `TASKS`: three row tasks `u1`–`u3` first, then three column tasks `u4`–`u6`). Each task shows six cars (letters A–F, shuffled) with six rows each (`t('bw_row_<criterion>')`); each car has one advantage row, the rest are equal. The questionnaire may stop after the three row tasks (`EARLY = 3` in `quiz.js`, the same as `EARLY_STOP_AFTER` in `ranking.py`).
- **Values:** the task list `ranking.tasks` (`id`, `criteria` of six keys) and `ranking.answers` (from `/api/tco`). Row values come from `attributes(params)`: the budget row uses `budget_ideal_eur` from the parameters (rounded to 100; 8000 when unset), the rest are constants in `quiz.js` (mileage 150,000 / 100,000 km, age from the current year, power 75 / 115 PS, Euro NCAP 3 / 5 stars, distance 150 / 20 km, cost "12 %" less).
- **Endpoints:** none on its own. The host page saves: `POST /api/parameters` `{ranking_answers, ranking_weights: null}` when the quiz is done (Ranking page: then the page reloads; setup: then `loadAll` and the summary).
- **Formatting:** money `euro`, numbers `num(…,0)`, text from the language file.
- **User can do:** tap a car first, tap another car last (tap the chosen car again to undo), Back, Skip a task, Enter to continue, keys 1–6 to pick the car in that position, cancel (Ranking page). The early stop happens when the three row answers are consistent (no criterion picked both first and last).
- **Saved:** nothing until the final answer. Partial answers live in memory only.
- **tv() codes:** none.

### 2.5 Listing dossier (`#/listing/<id>`, tabs `?tab=overview|costs|maintenance|reliability|viewing|log`)

- **Shows:** the photo viewer (with removed-photo restore and permanent delete), the score ring (`scoreBox`), the spec plate (cost per month strip, facts, reliability plate), a car title (link to its variant page), a decision bar (shortlist, viewing, reject with a reason, reset), the checklist gaps from `/api/todo`, and the facts block. Then six tabs.
- **Endpoints:** `GET /api/listings/<id>` (every render), `GET /api/tco` (after changes, via `refreshTco`), `POST /api/ui/listing_quotes` (manual insurance quote), `POST /api/ui/inspection_items` (new checklist item), `PATCH /api/ui/inspection_items/<id>` (`{status}` or `{notes}`), `POST /api/ui/listing_events` (`{listing_id, text}`, a viewing note), `POST /api/ui/media/<id>` (a JPEG body, shrunk in the browser to 1280 px, EXIF removed by the canvas copy), `PATCH /api/ui/photo/<id>` (`{archived: 1}` remove, `{archived: 0}` restore), `DELETE /api/ui/photo/<id>` (`{id, confirm: true}`, permanent), `POST /api/ui/decision/<id>` (`{decision: shortlist|viewing|reject|reset, reason}`).
- **Score and plate values:** `score`, `rank`, `excluded`, `not_scored`, `explain[]`, `metrics` (`reliability`, `confidence`, `age`), `reliability_sources` (`slots`, `present`, `of`), `known_cost_per_month`, `tco_complete`, `price_eur`, `mileage_km`, `first_registration`, `engine_code`, `power_ps`, `consumption` with `consumption_unit`.
- **Score ring:** one arc per criterion, length = its contribution; a notch at the mean score of the scored cars (`S.units` with a score, not withdrawn); band good ≥ 70, average ≥ 40, poor below 40 (word `score_<band>`).
- **Reliability plate:** `reliability_sources.slots` per ENGINE, HU, BREAKDOWNS: `points` meter (bands good ≥ 60, average ≥ 35, else poor), `present` of `of` sources ("n of 3 sources").
- **Overview tab:** `review_flags` (what, status, kind, level, why, reviews: date, worker, outcome, conclusion, finding). Ranking card: `score` (or the reason it is not scored), rank, weights manual tag, status tags, the `explain` table (criterion, weight, value formatted per criterion, anchor, score bar, contribution %, reason when missing), and `research_levels` (per level: state, missing and accepted counts, open items).
- **Maintenance tab:** `maintenance_plan` (item, `restarted` with `maintenance_resets.basis`, status, notes, level, interval, DIY or workshop, `price_eur`, `occurrences` × n, `cost_eur`, `diy_hours`, source), certain maintenance (`unit_costs` category maintenance: `item`, notes, parts + labour), total (`components.maintenance` or the partial sum), hours. Risks card: `fault_plan` (expected cost total, unknown when `cost_detail.repairs_expected` is null), certain repairs (`unit_costs` category repairs), `cost_detail.repairs_certain`, `components.repairs`.
- **Reliability tab:** slot table (source link, edition, value as published, points), source cards per fixed source (`rating_keys`, `ratings`: TÜV age-class table, ADAC band table, other values), one card per part (ENGINE, GEARBOX, CHASSIS, ELECTRICS, other): weak points (`fault_plan` with frequency band and shape, severity, probability as %, price, expected cost, inspection action, source), recalls (`recalls`: code, defect, remedy), legacy rows (`reliability`), history (`history`: item, status, evidence, event date, km, cost).
- **Viewing tab:** seller claims (`accident_free_claim`, `owners_claim`, `hu_claim`, `service_history_claim`, and `maintenance_resets` with basis SELLER CLAIM); checklist (`inspection`: status buttons OK / PROBLEM / N/A / PENDING, note field per item, add item; counts `OK/total`); viewing panel (photo upload and a note), shown in viewing mode.
- **Costs tab:** table of the eight components (`components`), per month (`component / period_months`), bar share of the known subtotal, subtotal (`known_cost_subtotal`) and `known_cost_per_month`, missing components. Then one block per component:
  - fuel: consumption (`consumption`, metric, spread, source), fuel price and electricity price (`cost_detail`), period km and months, observations (category consumption: metric, status, evidence quality, notes).
  - insurance: `insurance` rows (quote date or year, expiry from `quote_max_age_days`, premium, status, insurer, tariff, source) or `annual_insurance`. Quote form (not for the owned car, see 2.5 writes).
  - tax: `tax` rows (`annual_tax_eur`, status, source, registration window `registered_from`–`registered_to`, `tax_exempt_months`, basis).
  - maintenance: `cost_detail.maintenance_scheduled`, `maintenance_certain`, `maintenance_diy_hours`, certain rows.
  - repairs: `cost_detail.repairs_certain`, `repairs_expected`, certain rows.
  - tyres: `tyres` rows (size, `tyre_type`, status, price per tyre × tyres per set, `life_km`, fitting per set), `cost_detail.tyre_wear`, certain rows.
  - purchase/sale: asking price (not for the owned car), certain purchase/sale rows.
  - depreciation: asking price, `valuations` (kind `sale_today` or `resale_end`, `horizon_years`, expected with low and high range bar, status, source, notes), `cost_detail.resale_rescaled_from_years`.
- **Log tab:** archive (last capture time, title, price, the captured attributes, description, photo count, price history), the event timeline (`events`: date, kind, text), and sources of the car (quality, title, level, URL).
- **Formatting:** price and costs euro or Pending; mileage `num(km, 0) km`; age `yrs`; power `num(…,0) PS`; score `num(…,0)`; confidence `num(…,0) %`; probability `pct(p, 1)`; dates raw (`event_date`, `checked_date`), except `fmtDate` in photo labels.
- **Decision effects (server):** shortlist and viewing set `verdict` and keep the listing `UNDER REVIEW`; reject sets `verdict` to "Rejected by the owner: <reason>" and `listing_status` to `WITHDRAWN` (out of the ranking); reset clears the verdict and returns the listing to `UNDER REVIEW`. Each writes a `decision` event.
- **User can change:** decision (shortlist, viewing, reject with reason, reset), checklist status and notes, add checklist items, add viewing notes, upload photos, remove or restore or delete photos, enter an insurance quote by hand (premium, period year/month, insurer, tariff, quote date, cover, deductible, SF class), open the listing, switch viewing mode, switch tabs, choose another car (picker).
- **Saved:** server, through `/api/ui/*` (see Endpoints). The viewing-mode flag and photo index are in memory. Tab in the URL.
- **tv() codes:** `tv(d.listing_status)` (UNDER REVIEW, OWNED, WITHDRAWN), `tv(i.status)` and `tv(st)` (OK, PROBLEM, PENDING, N/A), `tv(ev.kind)` (event kinds), `tv(x.premium_status)` (QUOTE, USER DATA, ...), `tv(x.tyre_type)`, `tv(x.status)`, `tv(x.evidence)`, `tv(v.status)` (valuations), `tv(r.status)` (maintenance and risks), `tv(k.fuel_type)` (source keys), `tv(f.status)`, `tv(f.kind)`, `tv(f.level)`, `tv(r.outcome)` (review outcome), `tv(x.status)` (history), `tv(lvl)` (level tags), `tv(sev)` (severity), `tv(f.frequency_band)`, `tv(f.shape)`, `tv(r.existence)`, `tv(r.consequence)`.

### 2.6 Dossier redraw rules

- A quiet redraw (after a save) keeps open `<details>`, the drafts (`vnote`, `newcheck`, `rejectWhy`) and the focused control. The scroll position is kept.
- A checklist tap changes only that row (no redraw). A failure stays on that row until its next successful save.

### 2.7 Models (`#/models`, `#/models?make=&model=&engine=&fuel=&transmission=`, `#/models/<variant id>`)

- **Shows, list:** cascade of five filters (make, model, engine code, fuel type, gearbox), then the tree: generation header (make and model link, name, start–end year, facelift year, generation status), engines (code link, description, fuel type, power, aspiration, injection, timing drive), variants (trim, transmission, HSN/TSN, listing chips with price, "no listings", gap count from `/api/todo`).
- **Shows, variant:** research card (per level, see 2.5), review flags, variant facts (transmission, gearbox code and type, gearbox family, engine family, body, HSN/TSN, emissions, CO₂, technical status, notes), engine facts (code, description, fuel type, displacement cm³, power PS, aspiration, injection, timing drive, notes), generation facts (make, model, generation, years, facelift, status, notes), siblings on the same engine and generation, and tables: maintenance items (active only; price is `diy_parts_cost_eur` for DIY or `reference_cost_eur`), faults (consequence, frequency band, parts + labour, existence), recalls (safety tag), source keys (external key, fuel, link, checked date), source ratings (edition, value, link), observations (consumption: value, n / min / max, status, source), insurance rows, tax rows, tyre rows, sources (quality, level, title, supports).
- **Endpoints:** `GET /api/models` (once; cached in `S.models`), `GET /api/vehicles/<id>` (variant page).
- **Formatting:** power `num(…,0) PS`; displacement `num(…,0) cm³`; CO₂ `num(…,0) g/km`; prices `eP` or `partsLaborP`; tyre life `num(…,0) km`; years plain.
- **User can change:** the filters (saved). No writes.
- **Saved:** browser only, `carlos.mfilters` (JSON of the five filters). URL query sets the filters on entry.
- **tv() codes:** `tv(g.status)`, `tv(e.fuel_type)`, `tv(e.aspiration)`, `tv(e.injection)`, `tv(e.timing_drive)`, `tv(v.technical_status)`, `tv(v.generation_status)`, `tv(v.gearbox_type)`, `tv(r.status)`, `tv(r.consequence)`, `tv(r.existence)`, `tv(r.premium_status)`, `tv(r.fuel_type)`, `tv('SAFETY')`, `tv(lvl)` (level tags). The sources table uses no `tv()`.

### 2.8 Sources (`#/sources`)

- **Shows:** a fixed table of the five reliability sources (name, quality, level, terms key, URL pattern; a constant in `pages/sources.js`), then every source of the account grouped by what it belongs to (variant, engine, generation or shared). Each: quality tag, title, URL or "no URL", `supports`, `limitations`, `source_type`, accessed date, id.
- **Endpoints:** none on its own (uses `S.sources` from `/api/sources` and `S.units` for group names).
- **Formatting:** dates raw.
- **User can change:** the text filter (matches title, URL, supports, limitations, source type). No writes.
- **Saved:** nothing (filter in memory).
- **tv() codes:** `tv` not used on this page for source fields. Level tags use `lvlTag` (`variant`, `engine`, `generation`, `shared`).

### 2.9 Settings (`#/settings`)

- **Shows:** calculation parameters (annual km and years with range sliders, fuel price and date with "today", diesel price and date, ideal and maximum budget, `exclude_over_max` select, postal code, purchase mode, home charging, charging share, electricity prices and dates, wallbox cost), the derived total km and months, fuel-price age (warn over 30 days), ranking filters, appearance (mode, language), account (username, role, password change, data export), agent token (admins), a link to the setup wizard.
- **Endpoints:** `GET /api/tco?<calc params>` (live preview, 350 ms debounce, only when a calc field changed), `POST /api/parameters` (save all parameter fields), `POST /api/preferences` (each filter change, `{filter_*: value or null}`), `POST /api/account/password` (`{old, new}`), `GET /api/account/export` (JSON download), `POST /api/account/token` (admin; the token is shown once).
- **Values:** `S.saved` (saved parameters) and `S.p` (preview), `S.prefs` (`filter_*`), `S.me` (username, role, `has_token`).
- **Formatting:** annual km and years as numbers; fuel age `t('fuel_age', {n: days})`; derived line `t('derived', {km, m})`.
- **User can change:** every parameter (Save and Discard enabled only when the form differs), the four filters (saved at once), mode and language, password, export, new token.
- **Saved:** parameters and filters on the server; mode in `carlos.mode`; language in `carlos.lang`. Preview is never saved.
- **tv() codes:** none (choices use `t('pm_*')`, `t('hc_*')`, `t('eo_*')`, `t('fv_*')`).

### 2.10 Requests (panel on Compare, queue on Admin)

- **Panel (compare):** a collapsed block with a form (URL, note) and the last 10 requests: the URL link, status tag, request time, a cancel button for `QUEUED` requests, the car link when `listing_id` is set, the parts list (`parts`: unit names, the state text, detail line, missing count when failed), the result line when failed.
- **Endpoints:** `GET /api/requests`, `POST /api/requests` (`{url, note}`), `PATCH /api/requests/<id>` (`{status: CANCELLED}`).
- **Parts:** CAPTURE, then the research stages in order; `SKIPPED` counts as done; RESEARCH_B and ARBITER are hidden when skipped.
- **Admin queue (admin page):** requested time, account, URL and note, status and worker, who requested it (`requested_by`), the child parts with admin detail (worker, attempts, missing items, first result line), listing id. Data: `GET /api/admin/requests`.
- **Formatting:** raw times; statuses via `tv`.
- **User can change:** submit a request, cancel a queued one.
- **Saved:** server. Panel open or closed in `carlos.reqsOpen`.
- **tv() codes:** request status (QUEUED, RUNNING, WAITING, DONE, SKIPPED, FAILED, CANCELLED) for the request and each part (`tv(s)`, `tv(p.status)`).

### 2.11 Setup wizard (`#/start`, `#/start?step=0..6`)

- **Steps:** 0 drive (km, years, driving mix, current car), 1 money (budgets, purchase mode, fuel and diesel prices), 2 search (postal code, search centre, radius, preferred fuel, preferred gearbox), 3 workshop (optional: DIY jobs), 4 charging (optional: home charging, share, wallbox cost, electricity prices), 5 priorities (the quiz, optional), 6 done (summary and profile).
- **Endpoints:** `GET /api/preferences` (on render), `POST /api/parameters` (step fields and the quiz answers), `POST /api/preferences` (choices, `diy_jobs`, search, `onboarding_done`). Quiz end: `POST /api/parameters` `{ranking_answers, ranking_weights: null}`, then `loadAll`. Step 6 render: `POST /api/preferences {onboarding_done: <date>}` once. "Set up later": `onboarding_done: 'skipped'`.
- **Values:** `S.saved`, `S.ranking` (tasks, answers, answered, profile), preferences by key.
- **Formatting:** km `num(…,0) km`, euro, kWh price `num(…,2) €/kWh`, derived line.
- **User can change:** every field of the steps; the quiz; skip a step (posts nothing); go to a finished step (any earlier step, or any step once onboarding is done).
- **Saved:** server only (`project_parameters` and `project_preferences` through the API). A date is stamped on a price field that changed (`fuel_price_date`, `diesel_price_date`, `electricity_*_date`). Step index in the URL.
- **tv() codes:** none. Choices are stored as English text (`Mostly town`, `Petrol`, `Plug-in hybrid`, ...) and shown by `t('o_<key>_<code>')`. A stored value that matches no choice is shown as "kept" text.

### 2.12 Login (`/login`, `auth.html` + `js/auth.js`)

- **Shows:** username and password fields, sign-in button, language select (EN, ES, DE, PL), footer links (source code, privacy, imprint). Title and labels from `t()`.
- **Endpoints:** `POST /api/auth/login` `{username, password}`. On success: `location = '/'`.
- **Errors:** 401 → `auth_wrong`; 429 → `auth_locked`; 4xx with a server message → that message; any 5xx, a network failure or a non-JSON answer (a proxy page) → `auth_unreachable`.
- **User can change:** language, the credentials.
- **Saved:** session cookie by the server; language in `carlos.lang`.
- **tv() codes:** none.

### 2.13 Invite (`/invite/<token>`, same page)

- **Shows:** the same page in set-password mode. Username is read-only, filled from the invite. Password fields (minimum 8 characters) and a repeated password (checked in the browser before sending: a mismatch is marked and not sent).
- **Endpoints:** `GET /api/auth/invite/<token>` (fills the username; 404 → `auth_invite_gone`, 401 → `auth_wrong`, other errors as in 2.12; a failed check disables the form), `POST /api/auth/invite/<token> {password}`.
- **User can change:** the password, the language.
- **Saved:** the password is set by the server; the session cookie is set by the server. Language in `carlos.lang`.
- **tv() codes:** none.

### 2.14 Privacy (`/privacy`, `static/privacy.html`)

- **Shows:** the privacy notice in English only (static HTML with a stylesheet; no script). The only substitution is the source-code URL (`{{SOURCE_URL}}`), done by the server.
- **Endpoints:** none.
- **Storage it describes (section 8):** the session cookie `carlos_session`, the view cookie `carlos_view`, and local storage entries "whose names start with `carlos.`" (language, colour mode, filters, sort). The code uses more keys: see section 4 and section 7.
- **User can change:** nothing.
- **tv() codes:** none.

### 2.15 Imprint (`/impressum`, `impressum.html` + `js/legal.js`)

- **Shows:** the operator's imprint text as written, escaped, in a preformatted block (from `DATA_DIR/impressum.txt`, cut at 20,000 bytes). When the file is missing, the server's placeholder "No imprint text is set for this instance yet." (id `imp-missing`).
- **Translated by `legal.js`:** the page title, heading, the placeholder, the footer labels (source code, privacy). The operator's text is not translated.
- **Endpoints:** none.
- **User can change:** language only.
- **Saved:** language in `carlos.lang` (via `i18n.load`).
- **tv() codes:** none.

---

## 3. Field dictionary

Each row: the field in the response, what it means, how the UI shows it. Producers are the server functions in brackets.

### 3.1 `GET /api/tco` (and `/api/listings`): top level

| field | meaning | shown as |
|---|---|---|
| `parameters` | the calculation parameters (preview overrides applied) | header chip, Settings form, Compare period text |
| `preview` | true while a Settings preview is on | warn chip, banner on Compare, ✎ mark |
| `components` | the eight TCO component keys in order (`config.TCO_COMPONENTS`) | column and bar order, cost-data count |
| `listings` | one row per car (section 3.2) | every car view |
| `budget` | `{ideal, max}` (`costs.budget`) | not drawn directly (budget status is per car) |
| `ranking` | `criteria`, `tasks`, `candidates`, plus answers and weights (`ranking_state`) | ranking page and quiz |
| `fuel_price_stale` | fuel price older than 30 days (`config.STALE_FUEL_PRICE_DAYS`) | warn chip |

### 3.2 Listing row (`/api/tco` `listings[]`, also a field of `/api/listings/<id>`)

| field | meaning | shown as |
|---|---|---|
| `id`, `listing_id`, `is_reference`, `url`, `platform`, `location` | identity, the reference (owned) car | links, labels, "Owned" / "Your current car" |
| `make`, `model`, `trim`, `generation`, `engine_code`, `displacement_cc`, `first_registration` | car identity (`UNITS_SQL`) | carLabel: make, model, `displacement/1000` to one decimal, year |
| `price_eur` | asking price | euro, or Pending; "Owned" for the reference |
| `mileage_km` | odometer | `num(…,0)` km, or Pending |
| `power_ps`, `consumption`, `consumption_unit`, `consumption_metric`, `consumption_min`, `consumption_max`, `consumption_sample` | power and the consumption figure with its source spread (`costs.py`) | `num`, `consumptionTxt`, `consumptionSpread` |
| `annual_insurance`, `annual_tax` | yearly premium and tax (`costs.py`) | euro per year, or Pending |
| `components` | the eight component values for the period (`fuel` … `depreciation`) | euro per component; null = Pending |
| `missing_components` | keys with null (`todo.py` and `costs.py`) | "(partial)" tag, the cost-data meter, Compare tags |
| `known_cost_subtotal` | sum of the known components, period (`costs.py`) | euro (Pending when none known); tagged partial |
| `known_cost_per_month` | the subtotal ÷ months | perMonth with the partial tag |
| `known_cost_per_km` | the subtotal ÷ km (ownership km) | `num(…,3)` €/km in the card |
| `tco_complete` | all eight components known | "complete" wording, tags, the versus strip |
| `tco_pessimistic`, `tco_optimistic` | range of the total with the depreciation range | "range" row in details (both needed) |
| `delta_vs_reference` | total minus the owned car's total, both complete (`costs.py`) | ▲/▼ euro; "needs TCO" when null |
| `initial_outlay` | asking price minus the owned car's expected sale | euro, or Pending |
| `diy_hours` | owner's hours (not priced) | `num(…,1) h` |
| `period_months`, `period_km` | ownership period | "N km · N months" |
| `breakeven` | `ready`, `missing`, and when ready `upfront`, `monthly`, `ref_monthly`, `months`, `resale_end`, `ref_resale_end`, `payback_months`, `end_advantage`, `end_net` for the reference | break-even chart, table, and the "missing" list |
| `budget_status` | `over_max`, `over_ideal` or `within` (`ranking.py`, `costs.py`) | tags, filter, selection preset |
| `price_change` | `{eur, since}` between the first and last price record | tag with ▼/▲ and date |
| `stale` | not checked for longer than 14 days (`STALE_LISTING_DAYS`) | "Not checked for over 14 days" tag |
| `score` | the Carlos score 0–100, null when not scored (`ranking.py`) | score bar, ring, rank badge |
| `rank` | position among scored candidates | rank column, "#n" |
| `excluded` | `over_max` or `filter:<name>` | "over your maximum budget" / filter label |
| `not_scored` | `{criteria, research}` (what blocks the score) | "N cars not scored yet" reason |
| `explain[]` | per criterion: `criterion`, `value`, `weight`, `score`, `contribution`, `anchor`, `why_missing`, `coverage` | ranking table, ring, bars |
| `metrics` | the criterion values: `cost_month`, `cash_now`, `mileage`, `age`, `reliability`, `inspection`, `inspection_coverage`, `power`, `budget`, `safety`, `distance`, `confidence`, `km_per_year`, `consumption`, `insurance`, `tax` | details and cards |
| `metrics.confidence` | mean research grade as a percentage (`research.confidence`) | `num(…,0) %` |
| `metrics.reliability` | the mean of the reliability slots (`costs.reliability_sources`, `score`) | `num(…,0)` with coverage text |
| `reliability_sources` | `{score, coverage, present, of, slots: {ENGINE, HU, BREAKDOWNS}, missing}` | slot meters, "n of 3 sources", links |
| `cover`, `photo_count` | first photo and count | card and grid thumbnails |
| `verdict` | the owner's decision text | verdict line, decision state (`Shortlisted…`, `Viewing planned…`, `Rejected…`) |
| `listing_status` | `UNDER REVIEW`, `OWNED`, `WITHDRAWN` | status tag, withdrawn filter |
| `seller`, `seller_type`, `warranty`, `hu_until`, `service_history`, `accident_free`, `seller_rating`, `seller_reviews` | listing columns (`SELECT l.*`) | dossier facts; the rating row is read from `seller_rating` or parsed from the listing's `Händlerbewertung` text |

### 3.3 `GET /api/listings/<id>` (dossier only, extra fields)

| field | meaning | shown as |
|---|---|---|
| `media[]`, `removed_media[]` | photos (`file_path`, id), archived photos (id, `captured_at`) | viewer strip, removed list |
| `snapshots[]`, `price_history[]` | captures (`captured_at`, title, price, `attributes_json`, description), price points | archive card |
| `events[]` | listing log (`event_date`, `kind`, `text`) | timeline (kinds via `tv`) |
| `inspection[]`, `inspection_counts` | checklist items (`status`, `item`, `notes`) and counts | checklist, "OK/total" |
| `history[]` | known history of this car (`item`, `status`, `evidence`, `event_date`, `km`, `parts_eur`, `labor_eur`) | history card |
| `unit_costs[]` | certain one-off costs by `category` (maintenance, repairs, tyres, purchase_sale) with `parts_eur`, `labor_eur`, `item`, `notes`, `source_id` | certain rows |
| `maintenance_resets[]` | scheduled jobs restarted at purchase: `maintenance_item_id`, `basis` (CERTAIN REPAIR, SELLER CLAIM, DOCUMENTED) | reset tag, seller-claim list |
| `maintenance_plan[]` | plan rows: `item`, `level`, `interval_km`, `interval_months`, `diy`, `price_eur`, `occurrences`, `cost_eur`, `diy_hours`, `restarted`, `status`, `source_id` (`maintenance_plan()`) | maintenance table |
| `fault_plan[]` | researched weak points: `component`, `issue`, `part`, `severity`, `probability`, `frequency_band`, `shape`, `price_eur`, `expected_eur`, `fixed`, `window_uncertain`, `inspection_action`, `level`, `source_id` | risk and reliability tables |
| `recalls[]` | recalls of the car (`code`, `defect`, `remedy`, `part`, `level`, `source_id`) | reliability card |
| `reliability[]` | legacy weak-point rows (`component`, `issue`, `severity`, `is_recall`) | legacy list |
| `rating_keys[]`, `ratings[]` | fixed-source keys (`source_key`, `external_key`, `url`, `fuel_type`) and their published values (`value_num`, `value_text`, `band`, `reg_year`, `age_from`, `age_to`, `class_average`, `edition`) | source cards and tables |
| `research_levels` | per level (`variant`, `engine`, `generation`, ...): `state` (verified, researched, incomplete), `missing[]`, `accepted[]`, `items[]` (`id`, `title`, `grade`, `hint`) | research card (level tags via `tv`) |
| `review_flags[]` | open or cleared reviews (`what`, `why`, `status`, `kind`, `level`, `reviews[]`) | flags card |
| `insurance[]`, `quotes[]` | insurance rows (`annual_premium_eur`, `premium_status`, `quote_date`, `insurer`, `tariff`, `notes`, `source_id`) and manual quotes | insurance table |
| `quote_max_age_days` | quote validity (60, `config.QUOTE_MAX_AGE_DAYS`) | "valid until" or "expired" text |
| `tax[]` | tax rows (`annual_tax_eur`, `status`, `registered_from`, `registered_to`, `basis`, `source_id`) | tax block |
| `tyres[]` | tyre rows (`size`, `tyre_type`, `price_per_tyre_eur`, `tyres_per_set`, `life_km`, `fitting_per_set_eur`, `status`) | tyres block |
| `valuations[]` | `kind` (`sale_today`, `resale_end`), `expected_eur`, `low_eur`, `high_eur`, `horizon_years`, `status`, `source_id`, `notes` | depreciation block, range bar |
| `observations[]` | knowledge rows of category consumption (`metric`, `status`, `evidence_quality`, `notes`) | fuel block |
| `cost_detail` | `repairs_certain`, `repairs_expected`, `tyre_wear`, `maintenance_certain`, `maintenance_scheduled`, `tyres_certain`, `fuel_price_eur_l`, `electricity_eur_kwh`, `resale_rescaled_from_years`, `wallbox_eur`, `maintenance_diy_hours` | cost blocks |
| `engine_row`, `generation_row` | the engine and generation rows (notes, description) | facts |
| `sources[]` | sources of the car (`quality`, `title`, `url`, `limitations`, level ids) | sources block, source links |
| `tax_exempt_months` | months exempt from tax (electric cars) | tax block |

### 3.4 Ranking state (`/api/tco` `ranking`, `/api/parameters` profile)

| field | meaning | shown as |
|---|---|---|
| `criteria` | the nine criteria with `better` (higher or lower), `unit`, `basis` | legend, formula table |
| `weights` | per criterion 0–5 (from answers or saved by hand) | sliders, profile |
| `derived_weights` | the weights the answers give | used for `manual` |
| `manual` | weights differ from the answers | "set by hand" tag |
| `answered` | answers exist | profile, retake link |
| `retired_answers` | answers from an earlier questionnaire | "ask again" callout |
| `tally[k]` | per criterion `shown`, `best`, `worst` from the answers | "n answers" text |
| `answers` | the answers map `task id → "best>worst"` | quiz resume |
| `tasks[]` | the questionnaire tasks (`id`, `criteria`) | quiz |
| `candidates` | number of candidate cars | "n candidates" |

### 3.5 Parameters and preferences

| field | meaning | shown as |
|---|---|---|
| `annual_km`, `ownership_years` | the calculation horizon | "km/year", years, derived total |
| `fuel_price_eur_l`, `fuel_price_date` | petrol price and its date | `num(…,2) €/l`, date, age text (warn over 30 days) |
| `diesel_price_eur_l`, `diesel_price_date` | diesel price and date | same |
| `budget_ideal_eur`, `budget_max_eur` | budget (ideal and maximum asking price) | budget tags, ranking budget score |
| `exclude_over_max` | 1 = leave cars over the maximum out (default), 0 = keep them ranked | select "exclude / keep" |
| `postal_code` | origin of distances (5 digits) | distance, Settings and wizard field |
| `purchase_mode` | `cash` or `financing` | radio, label `pm_*` |
| `home_charging`, `home_charging_pct` | electric cars: home charging type and share | radio, label `hc_*`, range |
| `electricity_home_eur_kwh`, `electricity_public_eur_kwh` (+ `_date`) | electricity prices | `num(…,2) €/kWh` |
| `wallbox_cost_eur` | wallbox cost | euro |
| `ranking_answers`, `ranking_weights` | quiz answers and hand-set weights (JSON text on the server) | ranking page |
| preferences `driving_mix`, `current_car`, `preferred_fuel`, `preferred_transmission`, `search_center`, `search_radius`, `diy_jobs`, `onboarding_done`, `filter_*` | wizard choices and filters (English text, label by `t()`) | wizard, Settings filters |

### 3.6 Models tree (`GET /api/models`)

| field | meaning | shown as |
|---|---|---|
| `makes[]` → `models[]` → `generations[]` → `engines[]` → `variants[]` | the catalogue tree | nested list |
| generation: `name`, `start_year`, `end_year`, `facelift_year`, `status` | generation facts | header; status via `tv` |
| engine: `code`, `description`, `fuel_type`, `power_ps`, `aspiration`, `injection`, `timing_drive` | engine facts | tags, labels via `tv` |
| variant: `id`, `trim`, `transmission`, `hsn`, `tsn` | variant identity | link, sub-label |
| variant `listings[]`: `id`, `listing_id`, `is_reference`, `price_eur` | cars of this variant | chips |

### 3.7 Variant (`GET /api/vehicles/<id>`)

| field | meaning | shown as |
|---|---|---|
| `research` | per level research summary (section 3.3) | research card |
| `maintenance_items[]` (`active`) | maintenance rows (`item`, `interval_km`, `interval_months`, `diy`, `diy_parts_cost_eur`, `reference_cost_eur`, `status`, `source_id`) | table |
| `faults[]` | faults (`component`, `issue`, `consequence`, `frequency_band`, `shape`, `parts_eur`, `labor_eur`, `existence`) | table |
| `recalls[]` | recalls (`code`, `defect`, `safety`) | table |
| `source_keys[]`, `source_ratings[]` | fixed-source keys and ratings | tables |
| `observations[]` | consumption observations (`metric`, `value_num`, `value_text`, `unit`, `sample_count`, `min_value`, `max_value`, `status`) | table |
| `insurance_data[]`, `tax_data[]`, `tyre_data[]` | the knowledge rows of the variant | tables |
| `siblings.same_engine`, `siblings.same_generation` | other variant ids | links |
| `sources[]` | the variant's sources | table |
| `engine_row`, `generation_row`, `listings` | engine, generation and listings of the variant | facts |

### 3.8 Setup, todo and sources

| field | meaning | shown as |
|---|---|---|
| `GET /api/todo` `listings[].listing_id`, `listings[].todo[]` | open checklist items per listing (English text) | gaps list on the dossier |
| `GET /api/todo` `models[].vehicle_id`, `models[].todo[]` | open items per variant | gap count badge on the models page |
| `GET /api/sources[]` `id`, `title`, `url`, `quality`, `supports`, `limitations`, `source_type`, `accessed_date`, `vehicle_id`, `engine_id`, `generation_id` | sources | Sources page, per-car source tables |

### 3.9 Requests and admin

| field | meaning | shown as |
|---|---|---|
| `GET /api/requests[]` `id`, `url`, `status`, `requested_at`, `listing_id`, `result`, `parts[]` (`unit`, `status`, `attempts`, `missing`, `shared_id`, `detail`) | a request and its stages (`research_requests.py`) | request panel (status via `tv`) |
| `GET /api/admin/requests[]` `username`, `requested_by`, `worker`, `claimed_at`, `note`, `children[]` | the queue | admin table |
| `GET /api/admin/workers[]` `name`, `is_active`, `state`, `last_seen`, `url`, `username`, `listing_id`, `unit`, `parent_id`, `last_error`, `last_error_at` | workers (`research_requests.py`) | workers table (`ws_*` labels) |
| `GET /api/admin/users[]` `id`, `username`, `role`, `is_active`, `has_password`, `created_at` | accounts (`auth.py`) | accounts table |
| `GET /api/admin/changes[]` `id`, `changed_at`, `writer`, `account`, `table_name`, `row_id`, `action` | change log | change table, paged by `before=<id>` |
| `GET /api/storage` `total_bytes`, `limit_bytes` | data size against the limit (admin) | header chip |
| `GET /api/auth/me` `id`, `username`, `role`, `has_token` | the signed-in account | header, Settings |

### 3.10 Dossier and listing numbers (Pending rules)

| value | when Pending | when partial |
|---|---|---|
| `known_cost_subtotal` | nothing known | a tag listing the missing components |
| `known_cost_per_month` | nothing known | `(partial)` after the value |
| `components.<k>` | null (no value for that component) | — (one component is one value; the total is the partial row) |
| maintenance total | no rows and nothing certain | `+N pending` (`totalP`) |
| risks expected total | `cost_detail.repairs_expected` null | `+N pending` (`totalP`) |
| `partsLaborP` (faults) | both parts and labour null | `(partial)` when one is null |
| `score` | not scored: the reason from `not_scored` / `excluded` | — |

---

## 4. Browser storage

Only `localStorage`. Nothing in `sessionStorage` or IndexedDB. Every access is in `try/catch`. Keys are `carlos.<name>` written by `store.set` (JSON) unless noted.

| key | written by | value | read by | what it holds |
|---|---|---|---|---|
| `carlos.lang` | `i18n.js` `load()` | raw string `en`, `es`, `de` or `pl` (not JSON) | `i18n.js` `initialLang()` | interface language |
| `carlos.mode` | `app.js` `applyTheme`, Settings | JSON `"auto"`, `"light"` or `"dark"` | `boot.js` (before first paint), `app.js`, `settings.js` | colour mode |
| `carlos.sort` | `compare.js` | JSON `{key, dir}` | `compare.js` | Compare sort key and direction |
| `carlos.sortPrev` | `compare.js` | JSON `{key, dir}` | `compare.js` | the sort before "sort by selected cost" |
| `carlos.filters` | `compare.js` | JSON `{overBudget, withdrawn, pinRef}` | `compare.js` | Compare filters |
| `carlos.selected` | `compare.js` | JSON array of listing ids | `compare.js` | cars chosen for the comparison |
| `carlos.knownIds` | `compare.js` | JSON array of listing ids | `compare.js` | cars already seen (a new car is selected once) |
| `carlos.costSel` | `compare.js` | JSON array of component keys, or missing (= all) | `compare.js` | components in the cost chart |
| `carlos.beHi` | `compare.js` | JSON array of listing ids, or null (= the top five) | `compare.js` | highlighted lines on the break-even chart |
| `carlos.cview` | `compare.js` | view name (JSON string) | `compare.js` | last Compare view when the URL has none |
| `carlos.mfilters` | `models.js` | JSON `{make, model, engine, transmission, fuel}` | `models.js` | models filters |
| `carlos.reqsOpen` | `requests.js` | JSON boolean | `requests.js` | request panel open or closed |

Cookies (section 1.5): `carlos_session` (server, HttpOnly), `carlos_view` (`app.js`, the viewed account).

The privacy notice names the `carlos.` keys as "language, colour mode, filters, sort" (section 7).

---

## 5. Fixed codes translated by `tv()`

`tv(code)` looks the code up in the `codes` block of the language file (118 entries in `en.json`). Unknown codes are shown as they are. The table lists the families the pages pass to `tv()`, with the page that uses them.

| family | codes (from the `codes` block) | page |
|---|---|---|
| TCO component keys | `fuel`, `insurance`, `tax`, `maintenance`, `repairs`, `tyres`, `purchase_sale`, `depreciation` | compare, dossier, status tags |
| listing event kinds | `found`, `verification`, `correction`, `price`, `decision`, `user_data`, `warning`, `archive`, `photos`, `viewing` | dossier log |
| levels | `variant`, `engine`, `generation`, `shared`, `listing`, `engine_family`, `gearbox`, `gearbox_family`, `body_style`, `option` | every level tag |
| listing status | `UNDER REVIEW`, `OWNED`, `WITHDRAWN` | dossier, status tags |
| inspection status | `OK`, `PROBLEM`, `N/A`, `PENDING` | dossier checklist |
| statuses (data) | `VERIFIED`, `PARTIAL`, `PENDING`, `ESTIMATED`, `OBSERVED`, `USER DATA`, `QUOTE`, `OFFICIAL FEE LEVEL`, `PRIMARY`, `NOT AFFECTED`, `DOCUMENTED`, `SELLER CLAIM`, `VIN CHECK`, `PRESENT`, `OPEN`, `CLEARED`, `RESOLVED` | dossier, variant, tax, tyres, valuations, history |
| severity | `HIGH`, `HIGH IF APPLICABLE`, `MEDIUM`, `LOW-MEDIUM`, `LOW` | `sevTag`, fault tables |
| fault consequence | `WEAR_KM`, `AGE`, `WINDOW`, `RANDOM` (shape); `ENGINE_DAMAGE`, `STRANDS`, `SAFETY`, `UNUSABLE`, `COST`, `COSMETIC` (consequence) | fault tables, variant |
| fault frequency | `systemic`, `widespread`, `common`, `occasional`, `rare` | fault tables, flags |
| evidence | `CONFIRMED`, `REPORTED`, `STATISTIC`, `EXPERT`, `ESTIMATE`, `STATS_MISMATCH`, `SOURCES_DISAGREE`, `FIX_UNCERTAIN`, `OTHER` | fault and history evidence |
| review flags | `OPEN`, `CLEARED` (status); review kind and outcome are passed through `tv()` and shown raw when not in the block | flags card |
| engine | `Petrol`, `Diesel`, `Hybrid`, `Plug-in hybrid`, `Electric`; aspiration `NATURALLY ASPIRATED`, `TURBO`, `SUPERCHARGED`; injection `PORT`, `DIRECT`, `DUAL`, `CARBURETTOR`; timing `CHAIN`, `BELT`, `WET BELT`, `GEAR` | engine tags, variant pages |
| gearbox | `MANUAL`, `DCT`, `AT`, `CVT`, `SINGLE-SPEED` | variant |
| request status | `QUEUED`, `RUNNING`, `WAITING`, `DONE`, `SKIPPED`, `FAILED`, `CANCELLED` | requests, admin |
| sources | `TUEV`, `ADAC` (names) | sources tags |
| recall | `SAFETY` | variant recalls |
| units | `engine_family`, `gearbox`, `gearbox_family`, `body_style` (labels) | variant facts |

Codes the pages pass through `tv()` that are not in the block are shown raw (English). Free text (notes, descriptions, titles) is never passed through `tv()`.

---

## 6. Endpoint index

| endpoint | method | page |
|---|---|---|
| `/api/auth/me` | GET | shell (all) |
| `/api/parameters` | GET | shell, setup, Settings |
| `/api/parameters` | POST | Settings save, Ranking (weights, quiz), setup, quiz end |
| `/api/tco` | GET | shell, Compare, Ranking, Settings preview (`?` calc params) |
| `/api/todo` | GET | shell, dossier gaps, models gap counts |
| `/api/sources` | GET | shell, Sources |
| `/api/preferences` | GET | shell, setup |
| `/api/preferences` | POST | Settings filters, setup choices, `onboarding_done` |
| `/api/storage` | GET | shell chip (admin) |
| `/api/models` | GET | Models (list and variant) |
| `/api/vehicles/<id>` | GET | Models variant page |
| `/api/listings/<id>` | GET | dossier |
| `/api/requests` | GET, POST | request panel |
| `/api/requests/<id>` | PATCH | request cancel |
| `/api/ui/listing_quotes` | POST | dossier insurance form |
| `/api/ui/inspection_items` | POST | dossier add checklist item |
| `/api/ui/inspection_items/<id>` | PATCH | dossier checklist status and notes |
| `/api/ui/listing_events` | POST | dossier viewing note |
| `/api/ui/media/<listing id>` | POST (JPEG body) | dossier photo upload |
| `/api/ui/photo/<id>` | PATCH, DELETE | dossier photo remove, restore, delete |
| `/api/ui/decision/<listing id>` | POST | dossier decision bar |
| `/api/account/password` | POST | Settings |
| `/api/account/export` | GET | Settings |
| `/api/account/token` | POST | Settings (admin) |
| `/api/auth/login` | POST | login |
| `/api/auth/logout` | POST | header logout |
| `/api/auth/invite/<token>` | GET, POST | invite |
| `/api/admin/users` | GET, POST | admin, header view-as |
| `/api/admin/users/<id>` | PATCH, DELETE | admin (active, role, erase) |
| `/api/admin/users/<id>/invite` | POST | admin invite link |
| `/api/admin/workers` | GET, POST | admin workers |
| `/api/admin/workers/<id>` | PATCH | admin activate and deactivate |
| `/api/admin/workers/<id>/token` | POST | admin new worker token |
| `/api/admin/requests` | GET | admin queue |
| `/api/admin/changes` | GET (`limit`, `before`) | admin change log |
| `/static/i18n/<lang>.json` | GET | every page (translations) |

---

## 7. Mismatches and gaps found while checking

These are facts about the current code, not changes made here.

1. **Privacy notice is incomplete about browser storage.** `privacy.html` section 8 names "language, colour mode, filters, sort" under `carlos.`. The code also stores `carlos.selected`, `carlos.knownIds`, `carlos.costSel`, `carlos.beHi`, `carlos.cview`, `carlos.sortPrev`, `carlos.reqsOpen` and `carlos.mfilters` (section 4). Route to the legal audit before the next release.
2. **Two thresholds are copied into the UI.** `ui.js` `statusTags` writes `t('stale', {n: 14})` and `settings.js` uses `> 30` for the fuel-price age. The server values are `config.STALE_LISTING_DAYS = 14` and `config.STALE_FUEL_PRICE_DAYS = 30`. The values match today; a change in `config.py` would not reach the UI. Sending the value in the payload would remove the copy.
3. **Sources page names only the levels of listed cars.** `sources.js` builds its group names from `S.units`. A source attached to a variant, engine or generation with no listing is shown as "Variant #id", "Engine #id" or "Generation #id", not its name.
4. **Settings ranking filters write on change, without Save.** `settings.js` posts each filter when it changes; the parameter form has its own Save and Discard. The two behave differently; this is by design, but it is not stated on the page.
5. **The quiz is described wrongly in the docs.** `docs/frontend.md` and the header comment of `quiz.js` say "eight tasks of four cars" and keys 1–4. The code (`ranking.py` `TASKS`, `quiz.js`) has six tasks of six cars (A–F, keys 1–6). This page follows the code. Fix the two docs.
6. **The quiz values are constants in the front end.** Mileage, age, power, Euro NCAP and distance figures in `quiz.js` `attributes()` are not from the server; only the budget row follows the parameters. A change to the ranking curves in `ranking.py` would not change the quiz text.
7. **Dossier claims use the legacy columns.** `accident_free_claim`, `owners_claim`, `hu_claim`, `service_history_claim` are shown on the dossier. The filter columns `accident_free` and `service_history` (YES, NO, CLAIMED, from issue #169) are not shown there. The capture writes both sets; the dossier shows the older text.

Pages verified: 15 (section 2). Front-end files read: 19 JS files, 4 HTML files, `en.json`.
