# MUST-CHECK detail (from the two audits of static/ at 75de5f1)

Fix once in the shared helper, never per call site. Line numbers drift: grep the pattern. Helper names below that do not exist yet (`busy`, `ico`, `unit`) are to be created once in `ui.js`, then reused.

## 1. Title-only information
Pattern: `title="` carrying the only copy of a meaning (`qTag` quality A-D, `lvlTag` level hint, price-change date, `abbr.prov`, header chips). Mouse-only, invisible on touch, unreliable for screen readers.
Fix: visible text, or a focusable control (`<button>` / `details.rownote`). `title` may repeat visible text, never replace it.

## 2. Busy / disabled state
Pattern: `await post/patch/send` from a click or submit with no state change (start.js steps, settings.js, admin.js, requests.js, dossier decision and viewing buttons, quiz).
Fix: one helper (`busy(btn, promise)`, does not exist yet, create it in `ui.js`): `disabled = true`, `aria-busy="true"`, label "Saving…" (one `t()` key, with the ellipsis character, not three dots), restore in `finally`, failure shown inline and as `toast(msg, true)` (errors persist longer and use `role="alert"`). `auth.html` too.

## 3. Touch and hover
`.seg button`, header chips, `.btn.sm`, `.chipbtn`, `.linkbtn`, `.toggle input`, `.views button`, `.rail button` are under 44px. One rule: `@media (pointer:coarse){ ... min-height:44px }`; small checkboxes get a padded label hit area. Wrap every `:hover` effect in `@media (hover:hover)`; add `touch-action:manipulation`, `overscroll-behavior:contain` on the lightbox, `scroll-padding-top` for the sticky header and `.cbar` (and `scroll-padding-bottom` for `.setup-nav`). Focus ring: `.seg{overflow:hidden}`, `.dtabs`, `.rail` and `nav.main{overflow-x:auto}` clip the 2px offset outline of their children, so use `outline-offset:-2px` inside them; a global `:focus-visible{border-radius}` changes the shape of pills on focus, do not add one.

## 4. Glyph icons
`⚠ ✎ 👤 📋 📷 ✓ ✗ ½ ⤓ ▼ ▲ ⏱` need `aria-hidden="true"`; the status word sits next to them. Prefer one `ico(char)` helper over loose characters. Grades such as `✗` / `½` in research levels also need the word (MISSING / ACCEPTED). Images: `alt` per photo (lightbox: set it in `showPhoto`); a card thumbnail next to its own title is `alt=""`.

## 5. Headings
No `<h1>` exists today. `route()` should render one page title `<h1>` per route (the page's `<h2>` becomes it), cards `<h2>`/`<h3>`, no jumps (dossier uses `<h4>` under `<h2>`). `auth.html` too, with a `<main>`. Tables (`tbl()` in dossier.js, `flagsCard`): `<th scope="col">` for column headers and `<th scope="row">` for the first cell of a row (compare table), optional visually hidden `<caption>`.

## 6. Contrast of tokens
Compute, do not eyeball (WCAG: text 4.5:1, large text and UI parts 3:1), in light and dark and on every surface the token meets (`--bg`, `--surface`, `--surface-2`, `-soft` backgrounds). Known failures to re-check after any token edit (measured 2026-11-22): `--accent-contrast` #fff on `--accent` in light 3.99:1, `--text-3` on `--surface-2` 3.72:1 and on `--bg` 4.01:1 in light, white on `--bad` in the dark toast 3.03:1. Series marks on light surfaces are under 3:1 for `--s3` (2.2-2.7), `--s4` (1.7-2.0) and `--s5` (2.1-2.5): such a mark needs a value label, outline or pattern beside it (colour alone never carries meaning). `--s6` on dark surfaces is 3.3-3.9:1 (fine for marks, never for text). "Auto" mode must follow `prefers-color-scheme` in CSS (`os-dark` alone does nothing).

## 7. Text expansion (DE / PL)
DE and PL run 1.6x to 3x the English length (`flt_hu_months` PL 3.3x, `diy_hours` PL 3.1x, `codes.QUEUED` DE 3.3x). Never `white-space:nowrap` on `thead th`, `.tag`, `.toggle`, `nav.main a`, `.plate dd` unless the cell has a width budget; allow wrapping and `hyphens:auto` with `lang` set; headings `text-wrap:balance`. `overflow:hidden; text-overflow:ellipsis` needs `white-space:nowrap` + `min-width:0` and the full text reachable. Always look at DE and PL at 390px.

## 8. Strings and codes
Every new or changed string exists in `en`, `es`, `de`, `pl` with the same `{placeholders}` (`carlos-i18n-check` fails on parity, placeholders, empty values and a literal `t('key')` missing from `en.json`); no hard-coded user-facing literal in JS or HTML (`static/auth.html` is English only today: do not add more there without the owner's go-ahead).
Every code a screen can show needs a `codes.<CODE>` key in en, es, de, pl: severities, statuses, listing status, fuel types, reset basis, inspection results, event kinds, levels. `tv()` falls back to the raw English code silently; `carlos-i18n-check` is the gate. Dynamic key families (`t('why_' + x)`, `t('m_' + x)`, `t('rp_' + x)`) cannot be checked statically: when the server can emit a new value, add the key in the same PR and give `t()` callers a visible fallback.

## 9. Units, dates, precision
- Number through `num()` / `euro()` (`Intl` via `locale()`), the unit from a constant or a `t()` key, joined by U+00A0 so they never wrap apart (`Intl style:'unit'` and `'percent'` use ordinary spaces in en/es/pl, so replace the separator; they also know only sanctioned units such as kilometer, liter, percent, month: no `PS`/`kW`, no `€/km`, no `g/km`). One `unit(n, 'km')` helper (create it once) replaces the loose `' km'`, `' PS'`, `' %'`, `' €/km'` concatenations. Polish power is `KM`/kW, not `PS`.
- Dates: ISO from the API is formatted with `Intl.DateTimeFormat(locale())`, never printed raw.
- `carShort` uses `num(cc/1000, 1)`, not `toFixed`.
- Same metric, same precision on every screen (reliability 0 dp, age 1 dp with the year unit, mileage with `km`, score 0 dp). One minus sign convention (Intl), no `▼ €0` for a zero delta.
- Probabilities and shares: `p == null ? PEND() : pct(p)`; `null * 100` is `0` and a lie.

## 10. Per-month denominators
Use the server's `known_cost_per_month`, `known_cost_per_km` and `period_months`. A client-side `ownership_years * 12` disagrees as soon as the horizon is not a whole number of years. Where the server sends no per-month figure, add it to the API rather than dividing in the browser.

## 11. Charts (on top of `dataviz`)
- Cost stack: segments need `role="img"` + `aria-label` summarising values, or a visually hidden table; legend with text; minimum segment width keeps tiny parts visible; a partial car must not look cheap (hatch or "+n pending").
- Break-even: tooltip also on touch and keyboard (the `beTable` is the text alternative, link to it); colour per car is assigned by a stable index, not by how many cars are highlighted; no more than 8 series; the scroller on a phone has `tabindex="0"` and a label; labels stay readable at 390px.
- `--s1..--s8` are one palette used for components, criteria and levels: never put two of those meanings on one screen without a legend.

## 12. Forms
Inline `<p class="hint err" id="x-err">` plus `aria-describedby` and `aria-invalid`, the toast only as a second channel; focus the first invalid field. `inputmode="decimal"` when `step` is fractional (fuel price, consumption, deductible), `numeric` otherwise. `autocomplete="off"` `spellcheck="false"` on names and URLs. A hidden file input must stay keyboard reachable (visually hidden, not `hidden`). Tabs: either the full tab pattern (`tabpanel`, `aria-controls`, roving tabindex, arrows) or no `role="tab"`. Global key handlers (photo arrows, quiz digits) must ignore inputs, the tablist and an open dialog. Repeated controls need a unique accessible name (viewing-mode note input: `aria-label="note: <item>"`; step-rail buttons: the step name). An action link is a `<button class="linkbtn">`, never `href="#"` (the hash router would take it for the compare page). A re-render (`draw()`) must not throw keyboard focus to the top: update in place or restore focus. Credentials and destructive actions (token regenerate, worker revoke, cancel a queued request) confirm or offer undo; a form with typed text warns before it is left unsaved.

## 13. States every screen must have
Loading (`aria-busy`, text), empty (what is missing and the next step), error (what failed, retry, `role="alert"`), pending (NULL figures), partial (subtotals), withdrawn / archived / not scored. `carlos-ui-sweep` lists how to force each.

## Performance and motion (host: Raspberry Pi 2B, low-end phones)
- `transition: all` is out; list properties. Every animation, transition and hover scale has a `prefers-reduced-motion: reduce` variant (one global rule is enough).
- Paint cost: no new `background-attachment: fixed` (the cluster body gradient is the known case), no infinite `background-position` shimmer, no glow `box-shadow` / `text-shadow` per list row.
- Handlers: the document-level `mousemove` tooltip and `beHover` read layout per event; any new `mousemove` / `scroll` / `resize` handler is rAF-throttled, returns early when the target is unchanged and does not interleave reads and writes.
- Start-up: `i18n.load()` and `loadAll()` can run together; font `preload` for the two woff2 files; long lists (more than about 50 rows) get `content-visibility:auto`.
