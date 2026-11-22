---
name: carlos-ui-sweep
description: Browser QA of the Carlos UI. Use after any change to static/ (js, css, html, i18n) before calling it done, when asked to check the UI, take screenshots, test phone width, dark mode, a language, or look for console errors, horizontal overflow, clipped text or broken states on any route. Runs against a throwaway fixture server, never the real data.
---

# Carlos UI sweep

Drives headless Chromium over every route x EN/DE/PL x light/dark x 1280px/390px on a **throwaway server**: a copy of the synthetic fixture (`tests/fixture.py`) in a fresh temp data dir, on a free port, listening on 127.0.0.1 only. The real `data/` and `$CARLOS_DATA` are never opened. Never point it at the real database, never use the owner's login or browser (Playwright starts its own empty profile).

## Run
Each command is self-contained; `--out` is any directory outside the repository (it is created).
```
python .claude/skills/carlos-ui-sweep/scripts/sweep.py --out /tmp/carlos-sweep    # everything: 24 routes x 12 = 288 pages, several minutes
python .claude/skills/carlos-ui-sweep/scripts/sweep.py --out /tmp/carlos-sweep --routes 'compare?view=costs,listing/2' --langs de --modes dark --widths 390
python .claude/skills/carlos-ui-sweep/scripts/sweep.py --out /tmp/carlos-sweep --state empty|error|loading
python .claude/skills/carlos-ui-sweep/scripts/sweep.py --out /tmp/carlos-sweep --routes listing/3 --sql "UPDATE listings SET listing_status='WITHDRAWN' WHERE id=3"
```
Iterate with `--routes` on the routes you touched, then run everything once at the end. Other flags: `--sql` (repeatable, runs on the throwaway DB only), `--reduced-motion`, `--chromium /usr/bin/chromium` (when Playwright has no browser of its own).

Needs the Python `playwright` package (Arch: `pacman -S python-playwright`, see `docs/skills.md`) and a Chromium. If either is missing the script says so and stops: it installs nothing. Then write "sweep not run: Playwright missing" in the report and do not install it unasked (`webapp-testing` needs Playwright too, and its `with_server.py` must never be used on Carlos).

## How it works
1. `tests.fixture.build()` into a temp dir; adds the account `empty` through `auth.create_user` (no cars, default parameters) and the `onboarding_done` preference so the wizard does not take over. Fixture login: user `admin`, password `correct horse battery`.
2. `python app.py` with `CARLOS_DATA` and `CARLOS_PORT` set (log in `server.log` in the `--out` directory); waits for `/login`.
3. Logs in over HTTP, sets the `carlos_session` cookie, sets `carlos.lang` and `carlos.mode` in `localStorage` before each page load.
4. Per page: waits until the skeleton is gone, probes overflow, clipped text, raw `undefined` / `NaN` / `null` / `[object`, bare i18n keys, `h1` count; collects console errors, page errors and HTTP >= 400; full-page screenshot to `shots/` in the `--out` directory.
5. Writes `report.md` and `report.json` (same directory); exit 1 when any page has a PROBLEM. Notes do not fail: clipped text (judge each; an intentional ellipsis with the full text in reach is fine) . A page with no h1 is a PROBLEM (#424); visually hidden text (`.sr-only`) is not checked for clipping.

Fixture ids: listings 1 (own car), 2, 3; variants 1-4. Routes live in `ROUTES` at the top of `sweep.py`: add a route when a page is added. In the default fixture every car has a complete TCO; listing 3 is stale and over the ideal budget; variant 4 (`models/4`) has NULL HSN/TSN, gearbox and body fields.

## States to force (answer each that your change can affect: done / not applicable / not checked)
| State | How |
|---|---|
| Empty account | `--state empty` (runs only the routes an account without cars can open) |
| API error | `--state error` (every `/api/*` except auth returns 500: the load-failed card with retry must show) |
| Loading | `--state loading` (every API request is held; screenshot at 400 ms: skeleton or text; the report notes a missing `aria-busy="true"`) |
| Pending / NULL values | `--routes models/4`; every NULL shows the "pending" pill, never `0`, `—` or `NaN` |
| Partial totals | `--sql "DELETE FROM tyre_data"` (every car loses its tyres figure): "+1 pending", subtotal label, partial marker beside every `known_cost_per_*` |
| Withdrawn / over budget / stale | withdrawn: `--sql "UPDATE listings SET listing_status='WITHDRAWN' WHERE id=3"`; listing 3 is already stale and over the ideal budget |
| Reduced motion | `--reduced-motion` once for animated pages |
| Long text | DE and PL at 390px (default run) for headers, tags, nav, tables: they are the widest |
| Touch | the 390px run emulates a phone (`has_touch`, `is_mobile`, so `@media (pointer:coarse)` matches); the 44px targets are not measured by the script: say "not checked" or check by hand |
| Keyboard, double click | **manual, the script does not do them**: Tab through the route (visible focus ring, no trap, Escape closes the lightbox); click a save button twice quickly (second click does nothing, button shows busy). Otherwise say "not checked" |

## After the run
- Open the screenshots of every route you touched (at least 390px dark DE and 1280px light EN); a green report does not replace looking.
- Fix problems at the source (shared helper or token), re-run only the failing routes.
- Report: pages run, problems found and fixed, clipped items judged, states forced, what was not checked.
- Console errors on a route are bugs, not noise, except those you forced with `--state error`.
