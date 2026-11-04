# Front end

Plain ES modules served by the app, no build step, no dependencies. `static/`:

| File | Role |
|---|---|
| `index.html` | the shell (header, main, footer, lightbox, toast); applies the saved theme before the first paint |
| `auth.html` | sign-in and invite page (served at `/login` and `/invite/<token>`) |
| `css/tokens.css` | design tokens and the themes; `css/app.css` layout and components |
| `js/app.js` | state `S`, data loading, hash router (`#/compare?view=…`, `#/ranking`, `#/listing/<id>`, `#/models`, `#/models/<variant id>`, `#/sources`, `#/settings`, `#/admin`, `#/start?step=N`, `#/ranking?quiz=1`, `#/models?make=…&model=…&engine=…`), header, theme and language switching |
| `js/api.js` | `get`, `post`, `patch`, `send`; a 401 sends the browser to `/login` |
| `js/i18n.js` | `t(key, vars)`, plural objects `{one, other}`, `tv(code)` for fixed database codes, language detection |
| `js/ui.js` | formatting (`euro`, `num`, `yrs`), escaping, tags, `store` (localStorage per browser), toast |
| `js/charts.js` | cost composition bars and the break-even SVG |
| `js/quiz.js` | the ranking questionnaire (one scenario per screen, keys 1–4 and Enter) and the priorities profile with the answers behind each weight; used by the Ranking page and the setup wizard |
| `js/pages/*.js` | one module per page, each exporting `render(main, route)` |
| `i18n/en.json`, `es.json`, `de.json`, `pl.json` | the strings; `en.json` is the reference, the others must have the same keys |
| `fonts/` | Bricolage Grotesque (SIL OFL), self-hosted, the one UI family |
| `brand/` | `mark.svg` (symbol used in the header, coloured by the theme), `favicon.svg`, `logo.svg`, `icon-192.png`, `icon-512.png`; `manifest.webmanifest` |

## Rules
- **Themes change looks only.** Every theme runs the same JavaScript, calls the same API and shows the same data in the same places. A theme is a block of custom properties in `tokens.css` (`:root[data-theme="…"]`, plus its dark variant under `[data-mode="dark"]` and `.os-dark`) and, at most, a few decorative rules at the end of `app.css` scoped to `[data-theme="…"]`. Never put data, text or layout in a theme. The data-viz series colours (`--s1`…`--s8`) are the same validated palette in every theme so charts stay comparable.
- To add a theme: add its token block to `tokens.css`, its key to `THEMES` in `app.js` and the `THEME_SW` swatches in `pages/settings.js`, and the two strings `theme_<key>` / `theme_<key>_hint` to every language file.
- To add a language: add it to `LANGS` in `i18n.js`, translate `en.json` into `i18n/<code>.json` (same keys, same structure), and add the locale to the `Intl` formatting through `LANGS`.
- **Free text from the database is never translated** (notes, log, verdicts, listing captures). Fixed codes (statuses, event kinds, component keys, levels, engine codes such as `WET BELT`) go through `tv()` and the `codes` block of the language files.
- **Unknown is shown as "pending", never as 0** (`PEND()`, `eP()`).
- **Every name leads somewhere:** a listing links to its dossier (`carLink`), a variant to `#/models/<id>`, a model, generation or engine to the models tree filtered to it (`modelsHref`). Only verbatim third-party text (source titles, listing captures) stays plain.
- **Setup wizard** (`pages/start.js`, `#/start`): shown on the first visit until the preference `onboarding_done` exists (finished or put off), reopened from Settings. Steps: driving, money, search, insurance profile, workshop, priorities (the questionnaire), summary. Each step saves through `POST /api/parameters` and `POST /api/preferences`, prefilled from what is stored; a choice left empty keeps an older free-text value.
- Numbers wear `font-variant-numeric: tabular-nums`; text never wears a series colour; a legend is present for every multi-series chart.
- Everything the user does in the UI (parameters, questionnaire, viewing mode, account) goes through the same API an agent would use; the UI has no privileged path.
- State remembered per browser (`localStorage`, prefix `carlos.`): theme, mode, language, sort, filters, selection, cost selection, break-even highlight, model filters. Everything else lives in the account.

## Checking changes
Start the app and open the pages in a browser; or headless: `chromium --headless=new --screenshot=out.png --window-size=1280,900 http://127.0.0.1:8000/#/compare` with a session cookie set by a bootstrap page (see `tests/` for the API side). Check phone width (390 px), every theme, light and dark, and the console for errors.
