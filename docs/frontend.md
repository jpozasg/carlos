# Front end

Plain ES modules served by the app, no build step, no dependencies. `static/`:

| File | Role |
|---|---|
| `index.html` | the shell (header, main, footer, lightbox, toast); applies the saved theme before the first paint |
| `auth.html` | sign-in and invite page (served at `/login` and `/invite/<token>`) |
| `css/tokens.css` | design tokens and the themes; `css/app.css` layout and components |
| `js/app.js` | state `S`, data loading, hash router (`#/compare?view=…`, `#/ranking`, `#/listing/<id>`, `#/models`, `#/models/<variant id>`, `#/sources`, `#/settings`, `#/admin` (admins: workers, accounts, research queue, change log), `#/start?step=N`, `#/ranking?quiz=1`, `#/models?make=…&model=…&engine=…`), header, theme and language switching |
| `js/api.js` | `get`, `post`, `patch`, `send`; a 401 sends the browser to `/login` |
| `js/i18n.js` | `t(key, vars)`, plural objects `{one, other}`, `tv(code)` for fixed database codes, language detection |
| `js/ui.js` | formatting (`euro`, `num`, `yrs`), escaping, tags, `store` (localStorage per browser), toast |
| `js/charts.js` | cost composition bars and the break-even SVG |
| `js/quiz.js` | the ranking questionnaire (eight best–worst tasks of four cars; tap or keys 1–4 for first, then last; Enter continues) and the priorities profile with the count behind each weight; used by the Ranking page and the setup wizard |
| `js/pages/*.js` | one module per page, each exporting `render(main, route)` |
| `i18n/en.json`, `es.json`, `de.json`, `pl.json` | the strings; `en.json` is the reference, the others must have the same keys |
| `fonts/` | Bricolage Grotesque (SIL OFL), self-hosted, the one UI family |
| `brand/` | `mark.svg` (symbol used in the header, coloured by the theme), `favicon.svg`, `logo.svg`, `icon-192.png`, `icon-512.png`; `manifest.webmanifest` |

Admins get a **view as** switcher in the header (issue #142): picking an account sets the `carlos_view` cookie and reloads; every page then shows that account as its owner sees it, under a banner "Viewing as …" with a way back. The first-run wizard never opens while viewing as another account.

## Research requests and their parts (#218 phase 2)
`static/js/requests.js` (`partsHtml`): a request lists its parts in stage order (Capture, Variant, Generation, Maintenance, Engine, Gearbox, Tax, Listing) from `parts` (Compare, users: done / in progress / waiting / pending / failed, SKIPPED counts as done, "n of m parts done", missing-item count on a failed part) or `children` (Accounts page, admins: the real status incl. SKIPPED "already existed", "done by request #N", "waits for request #N", worker, attempt, collapsible missing item ids, result). Two-run research (#253): RESEARCH_A, RESEARCH_B, ARBITER and MERGE are parts too (`unit.RESEARCH_A` "Research run 1", `unit.RESEARCH_B` "Research run 2", `unit.ARBITER` "Second opinion", `unit.MERGE` "Merge"), each with the server's `detail` line: staged counts and the last finding, disputes answered, or agreement / written / skipped / flags. Capture is the parent row. A server without these fields shows only the request status. Workers show their current `unit` and `parent_id`. Each part has an icon and text, never colour alone.

## Rules
- **One theme** (issue #181): the default "cluster" look, with light, dark or automatic mode. Its tokens are the custom properties in `tokens.css` (`:root[data-theme="cluster"]`, plus the light variant under `[data-mode="light"]`) and a few decorative rules at the end of `app.css`. The data-viz series colours (`--s1`…`--s8`) are one validated palette.
- To add a language: add it to `LANGS` in `i18n.js`, translate `en.json` into `i18n/<code>.json` (same keys, same structure), and add the locale to the `Intl` formatting through `LANGS`.
- **Free text from the database is never translated** (notes, log, verdicts, listing captures). Fixed codes (statuses, event kinds, component keys, levels, engine codes such as `WET BELT`) go through `tv()` and the `codes` block of the language files.
- **Unknown is shown as "pending", never as 0** (`PEND()`, `eP()`).
- **Decisions** (dossier): shortlist, plan a viewing, reject with an optional reason (archives the car out of the ranking), undo; `POST /api/ui/decision/<id>`. Compare offers "Shortlisted" as a selection once any car is shortlisted or has a viewing planned.
- **Provisional scores:** `scoreTxt()` marks every score computed from less than half of the weighted data with a "?" and an explanation; the Ranking page explains it once above the list.
- **Target design levels (#174, #168):** each level has its own colour (`.lvl-<level>`). The Models page shows the variant's gearbox, families and body style, its faults (band and shape, or a sourced curve), recalls, TÜV/ADAC figures and review flags; the dossier shows the faults with the chance over the ownership period and the expected cost, the known history and insurance quotes, and the open review flags of every level it inherits (`flagsCard` in `ui.js`, shared by both pages).
- **Every name leads somewhere:** a listing links to its dossier (`carLink`), a variant to `#/models/<id>`, a model, generation or engine to the models tree filtered to it (`modelsHref`). Only verbatim third-party text (source titles, listing captures) stays plain.
- **Insurance quotes by the worker (#218):** Settings has an opt-in checkbox card ("Let the research worker get insurance quotes for my cars", preference `insurance_worker_quotes`, off by default, saved at once through `POST /api/preferences` with the login session; shows the date it was switched on and lists the profile fields still missing). The parts view labels the unit `rp_INSURANCE`; admins see a SKIPPED reason as the secondary `result` line.
- **Setup wizard** (`pages/start.js`, `#/start`): shown on the first visit until the preference `onboarding_done` exists (finished or put off), reopened from Settings. Steps: driving, money, search, drivers (policyholder and further regular drivers), insurance (cover, history, usage, discounts), workshop, priorities (the questionnaire), summary. Once finished, every step can be opened from the step rail. Each step saves through `POST /api/parameters` and `POST /api/preferences`, prefilled from what is stored; a choice left empty keeps an older free-text value.
- Numbers wear `font-variant-numeric: tabular-nums`; text never wears a series colour; a legend is present for every multi-series chart.
- Everything the user does in the UI (parameters, questionnaire, viewing mode, account) goes through the same API an agent would use; the UI has no privileged path.
- State remembered per browser (`localStorage`, prefix `carlos.`): mode, language, sort, filters, selection, cost selection, break-even highlight, model filters. Everything else lives in the account.

## Dossier information map (#340)

The dossier answers four questions, one tab each; a piece of data is shown in one place and linked from the others (never copied). The header (photos, score, cost plate) is always visible; on a phone the plate's facts are collapsed.

| Tab | Question | Content (API field) |
|---|---|---|
| Overview | What is this car and how does it rank? | facts and seller claims, decision bar, review flags, to-do gaps, ranking explanation, research levels (`explain`, `research`) |
| Costs | What does each of the eight components cost, from which inputs, from which source? | summary table of the eight `components` (total, per month, share, state); one block per component with its inputs and source: **fuel** (`consumption`, `observations` consumption, `cost_detail.fuel_price_eur_l`, period km), **insurance** (`quotes`, `insurance`, `annual_insurance`), **tax** (`tax`: amount, basis, registration window, status), **maintenance** (certain / scheduled split from `cost_detail`, DIY hours, link to the Maintenance tab), **repairs** (certain / expected split, link), **tyres** (`tyres`: size, price, set, life, fitting), **purchase/sale** (`unit_costs` of that category, price), **depreciation** (`valuations`, asking price, horizon); own one-off costs (`unit_costs`) |
| Maintenance & repairs | What will keeping it running cost? | maintenance plan (`maintenance_plan`, `maintenance_resets`, certain jobs), repair risks (`repair_risks`), certain repairs, and the expected cost of the faults as one line linking to Reliability |
| Reliability | What is known to go wrong? | per part (ENGINE, GEARBOX, CHASSIS, ELECTRICS) with its score out of 9: weak points (`fault_plan`: severity, band, chance, price, expected cost, inspection action, source), recalls (`recalls`, with the checklist state from `reliability_detail`), legacy `reliability` rows; then TÜV/ADAC figures (`reliability_stats`), known history of this car (`history`) |
| Viewing | What do I check in person? | checklist (`inspection`), viewing mode |
| Log & sources | Where does it come from? | listing archive (`snapshots`, `media`), log (`events`), `sources` of the car, price history |

Moved, not removed: the faults table (Maintenance & repairs to Reliability, grouped by part), insurance quotes (Reliability to Costs), the loose valuations block (Costs, under depreciation).

## Checking changes
Start the app and open the pages in a browser; or headless: `chromium --headless=new --screenshot=out.png --window-size=1280,900 http://127.0.0.1:8000/#/compare` with a session cookie set by a bootstrap page (see `tests/` for the API side). Check phone width (390 px), every theme, light and dark, and the console for errors.
