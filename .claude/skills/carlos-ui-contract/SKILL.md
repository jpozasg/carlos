---
name: carlos-ui-contract
description: House rules for ANY change under static/ (HTML, CSS, JS, i18n JSON) and for any user-facing copy, label, tooltip, chart or number shown in the Carlos UI. Load FIRST, before editing static/js, static/css, static/i18n, static/index.html or static/auth.html, before reviewing a UI PR, and before answering "how should this look or read".
---

# Carlos UI contract

The rules for every UI change. They come from `AGENTS.md`, `docs/frontend.md` and two audits of the front end; they do not repeat what `impeccable`, `web-design-guidelines` or `dataviz` already say.

## Load order (do not skip, do not reorder)
1. This skill (data truth, i18n, helpers, the must-check list).
2. `impeccable`, **Operate** mode, for layout and visual decisions (app UI: scanability and known patterns win): read `reference/craft-floor.md` and `reference/operate.md` before editing, nothing from its init/document/hooks/doctor. Chrome stays the cluster look; do not restyle. Its "Refuse" list (glyph icons, progress rings, cards) is for new surfaces: do not rewrite existing screens to satisfy it; for a NEW icon prefer inline SVG with `aria-hidden="true"` or a `.dot`.
3. `dataviz` for `charts.js`, cost bars, break-even, meters, score rings and any new chart or stat tile.
4. `web-design-guidelines` as the **final review pass** on the changed files, after the work is done.
5. When strings or codes changed: run `carlos-i18n-check`. When behaviour or layout changed: `carlos-ui-sweep`.

If a rule here and a generic skill disagree, this skill wins for data and wording; `impeccable` wins for spacing and hierarchy.

## Data truth (a wrong number is worse than a missing one)
- **Unknown is NULL is "pending".** Render it with `PEND()` / `eP()` (`ui.js`). Never `0`, never a bare `—` for a figure that is known to be missing. `euro()` / `num()` return `—` for null: only call them on a value you already guarded, or use `eP()`. Never `x ?? 0`, `x || 0`, `null * 100`, `?? 4`, invented units (`consumption_unit || 'l/100 km'`).
- **Totals reduce to `{sum, missing}`.** If `missing > 0` show the sum as a subtotal with the "+n pending" marker (`subtotal_partial`, `partial_short`), never as a complete total. This includes tables, cards, plates, the ruler and the versus strip.
- **Never call a subtotal a TCO.** `known_cost_per_month` / `known_cost_per_km` always wear the partial marker unless `tco_complete`. Per-month figures use the server's `known_cost_per_month` and `period_months`, never `ownership_years * 12` computed in the client.
- **Coverage, not zero:** reliability reads "n of 3 sources"; a slot without a source reads "not covered".
- **Codes only through `tv(code)`** (statuses, severities, kinds, levels, listing status, fuel types, engine codes) and every code needs a key in the `codes` block of all four languages. **Database free text is never translated** (notes, log, verdicts, listing captures, seller claims): show it verbatim, escaped, with `lang="en"` when it is agent English.
- Facts, seller claims, user data, estimates stay visibly apart (`claimed`, `USER DATA`, `ESTIMATED` tags). An asking price is an asking price. DIY parts, workshop price and hours stay separate, hours are shown and never priced (`AGENTS.md`).
- Every untrusted string goes through `esc()`; every URL through `safeUrl()`.

## Look and structure
- **Tokens only** (`tokens.css`): no new hex or rgb in `app.css` or inline styles (the neutral black/white photo overlays that exist stay), no new custom property without a token in both modes. **One theme** ("cluster"), light and dark. Text never wears a series colour (`--s1..--s8` are for marks).
- Numbers: `font-variant-numeric: tabular-nums`. Dates through `Intl.DateTimeFormat(locale())`; numbers through `num()` / `euro()`; unit text joined to the number by U+00A0; no `toFixed` / `toLocaleString` / `€` concatenation outside chart geometry (detail in must-check 9).
- **Status = icon plus text** (tag with a glyph or dot and the `tv()` label); colour alone never carries meaning. Glyph icons get `aria-hidden="true"`, the meaning lives in text.
- **Every name is a link** (`carLink`, `modelsHref`, variant `#/models/<id>`); only verbatim third-party text stays plain.
- Reuse the helpers in `ui.js` (`esc`, `safeUrl`, `euro`, `eP`, `num`, `yrs`, `PEND`, `facts`, `empty`, `sevTag`, `lvlTag`, `qTag`, `flagsCard`, `toast`, `store`) before writing markup. A second way to show the same concept is a defect (same code = same tag everywhere; a `statusTag(code)`, `busy()`, `ico()` or `unit()` helper does not exist yet: create it in `ui.js` once and reuse it).
- State per browser lives in `store` (`carlos.` prefix); anything else goes through the API like an agent would.
- No build step, no dependency, ES modules, no inline `onclick` in new code.
- Light on a Raspberry Pi and low-end phones: no `transition: all` (list the properties) and a `prefers-reduced-motion` variant for every animation; no new `background-attachment: fixed`, infinite shimmer or glow shadows per list row; document-level `mousemove` / `scroll` handlers are rAF-throttled and do no layout reads; no new request waterfall (detail in must-check "Performance").

## MUST-CHECK (recurring defects)
Answer each item in the PR as done, not applicable (why) or open (issue filed), per `AGENTS.md`. Fix it in every file you touch; an old defect in code you do not touch is filed as an issue, not fixed in the same PR. Detail, fixes and file pointers in `references/must-check.md` (same numbers).
1. Information carried only by `title=` or hover: give visible text or a focusable control.
2. Every request-sending control shows a busy state (disabled + `aria-busy`, restored in `finally`, error shown as text and toast) so a double submit is impossible.
3. Touch targets 44px under `@media (pointer:coarse)`; `:hover` rules inside `@media (hover:hover)`; focus ring not clipped by `overflow` containers, sticky bars never cover the focused element.
4. Glyph icons `aria-hidden="true"`; every image has `alt` (or `alt=""` when the text next to it says the same).
5. One `<h1>` per route; no skipped levels; table headers carry `scope`.
6. Token contrast is AA in light AND dark (text 4.5:1, large and UI 3:1), including text on `--accent` and on the toast.
7. DE and PL expand text up to 2-3x: no `nowrap` on headers, tags or nav that could carry a translation; check at 390px.
8. Strings and codes: every new or changed string exists in `en`, `es`, `de`, `pl` with the same `{placeholders}`; the `codes` block is complete for every code the screen can show; no hard-coded user-facing literal in JS or HTML.
9. Units and dates through `Intl` / `num()` with NBSP; the same metric has the same precision on every screen.
10. Per-month denominators come from the server.
11. Charts: keyboard and screen-reader equivalent (table or labelled segments), touch behaviour, stable colour per series, legend for multi-series.
12. Forms: inline error text with `aria-describedby`, `inputmode="decimal"` for fractional fields, `autocomplete` / `spellcheck` set, unique accessible name per repeated control, destructive actions confirm or undo.
13. Every screen has its states: loading, empty, error, pending, partial, withdrawn / not scored (`carlos-ui-sweep` shows how to force each).

## Definition of Done
Do all of these and say so in the PR; "not run" is stated, never implied.
- `python .claude/skills/carlos-i18n-check/scripts/i18n_check.py`: no new errors (existing ones are in that skill's "Known failures to fix").
- `carlos-ui-sweep` on the touched routes (`--routes ...`) in default state plus the forced states the change affects; read the report, open the screenshots.
- `python -m unittest` green and the integrity check from `README.md`.
- State which screens were checked at **390px and 1280px**, **light and dark**, **EN and DE** (PL when strings grew), and what was not checked.
- `web-design-guidelines` review of the changed files done, findings fixed or listed.
- `docs/frontend.md` updated when a rule, helper or screen changed; the PR follows the `AGENTS.md` Git workflow (issue, branch, `Closes #n`).
