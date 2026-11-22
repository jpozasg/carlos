---
name: carlos-i18n-check
description: Run after ANY change to static/i18n/*.json, to a t()/tv() call, to a status or code that the UI can show, to fixed_codes in carlos/agent.py or carlos/config.py, or to number/currency/unit formatting in static/js. Also run before a UI PR is declared done and when asked to check translations, language parity or hard-coded strings.
---

# Carlos i18n check

One command, no server, no database, standard library only:

```
python .claude/skills/carlos-i18n-check/scripts/i18n_check.py            # this repository
python .claude/skills/carlos-i18n-check/scripts/i18n_check.py --root DIR # another checkout of your own (its carlos/agent.py is imported)
```

Exit 1 when there are errors; warnings are printed first and never fail the run. A line containing `i18n-ok` (put it in a trailing `// i18n-ok: reason` comment) is skipped by the source greps.

## What it checks
| Level | Check |
|---|---|
| ERROR | every language of `LANGS` in `static/js/i18n.js` has a valid JSON file; `en`, `es`, `de`, `pl` have identical key sets (the `codes` block included); no empty translation; `{placeholders}` equal per key; plural keys have the same forms (PL may add `few`/`many`) |
| ERROR | every entry of `FIXED_CODES` (imported from `carlos/agent.py`, constants only, a never-created temp `CARLOS_DATA`) and every status or severity code of `AGENTS.md` has a key in `codes` of each language. Fields the UI does not render through `tv()` are only warned about: `*.job`, `faults.component_code`, `*.part`, `maintenance_resets.basis`, `valuations.kind`, `listings.lease_kind`, `maintenance_items.kind`, `research_checks.result` (see the comment above `NOT_RENDERED` in the script; if a screen starts to call `tv()` on one of them, remove it there) |
| ERROR | a literal `t('some_key')` in `static/js` whose key is not in `en.json` (`t('why_' + x)` and template keys cannot be seen) |
| ERROR | `toLocaleString`, or `€` / `&euro;` on a code line in `static/js` (a trailing `//` comment is ignored): use `euro()` / `num()` / `Intl` through `locale()` |
| WARN | DE or PL text over 1.6x the English length: look at it at 390px and in table headers |
| WARN | a DE/ES/PL string identical to the English one (over 12 characters, with a space): translate it |
| WARN | hard-coded user-facing literals (text between tags, `title`/`placeholder`/`aria-label`/`alt`, `toast('...')`, `empty('...')`, `textContent = '...'`): heuristic, review each; units and codes are filtered |
| WARN | `toFixed` (fine only for chart geometry) |

## Procedure
1. Edit the language files in all four languages in the same change (`en.json` is the reference; same keys, same structure; write English first, the others are translations, not copies; plural keys `{one, other}`, PL also `few`).
2. Run the script. Fix every ERROR you caused. A new warning needs a reason or a fix.
3. For dynamic key families (`t('why_' + x)`, `t('m_' + x)`) the script cannot see the values: list the values the server can send yourself and add the keys.
4. Run `python -m unittest tests.test_i18n tests.test_i18n_check`.
5. Report the counts before and after (errors, warnings), not just "ok".

A unit such as `€/km`, `€/l` or `g/km` cannot come from `Intl.NumberFormat` (`style:'unit'` knows only sanctioned units such as kilometer, liter, percent; it has no currency-per-unit and no `PS`/`kW`). Format the number with `num()` (or the euro amount with a currency `Intl.NumberFormat` and the right fraction digits) and append the unit from a `t()` key, joined by U+00A0.

## Known failures (issue #382 fixed the codes block and four of the six euro literals; recorded 2026-11-22)
`tests/test_i18n_check.py::test_repository_has_no_errors` asserts zero errors, so a regression fails the suite. One temporary exception is filtered there: the two euro literals `pages/compare.js:95` (`€/km`) and `pages/dossier.js:295` (`€/l`, `€/kWh`), owned by the data-truth package; replace them with `num()` + `t('unit_eur_km' / 'unit_eur_l' / 'unit_eur_kwh')` joined by U+00A0, then delete the filter and this paragraph. Current result: 2 errors (those), 14 warnings.
- **Warnings worth a look:** DE 51 and PL 57 strings over 1.6x (worst PL `flt_hu_months` 3.3x, `diy_hours` 3.1x; DE `codes.QUEUED` 3.3x, `p_deductible` 2.8x); `toFixed` in `ui.js:36` (`carShort`, locale-blind: use `num(cc/1000, 1)`), `dossier.js:45,61,67`, `charts.js:46`; literals `app.js:55` ("Carlos", brand: fine), `requests.js:55` (`https://` placeholder: fine), `ranking.js:19` (false positive).
- Not covered by the script (audit findings): `static/auth.html` is English only; `t()` returns the key silently when a dynamic key is missing; `scoreTxt` "?" drift in `docs/frontend.md`; 44 unused keys.

**Trust:** `--root` imports `carlos/agent.py` from that tree (its module code runs). Point it only at a checkout you trust (this repository or its worktrees); for any other tree pass `--fixed-codes <json>` instead. Run it as `python3 -I`.
