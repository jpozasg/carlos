#!/usr/bin/env python3
"""Carlos i18n check (Python 3.9, standard library only, no server, no real database).

Errors (exit 1): a language file of i18n.js LANGS is missing or invalid; key sets, {placeholders} or plural forms differ
from en.json; an empty translation; a fixed code has no entry in the `codes` block of a language; a literal t('key') that
en.json lacks; toLocaleString / euro-sign concatenation in static/js (use euro/num from ui.js).
Warnings (exit 0): DE/PL strings over 1.6x the English length; strings identical to English; hard-coded user-facing
literals; toFixed.
A line ending in `// i18n-ok` is skipped by the source greps.

    python .claude/skills/carlos-i18n-check/scripts/i18n_check.py [--root REPO] [--fixed-codes codes.json]
"""
import argparse, json, os, re, sys, tempfile
from pathlib import Path

PLURAL = {'zero', 'one', 'two', 'few', 'many', 'other'}
EXTRA_OK = {'few', 'many'}  # Polish (and others) may have more plural forms than English
RATIO = 1.6
# Codes AGENTS.md lists that no table enumerates (statuses, severities, listing_status, fuel types, reset basis).
STATUS_CODES = ['VERIFIED', 'PARTIAL', 'PENDING', 'ESTIMATED', 'OBSERVED', 'USER DATA', 'QUOTE', 'OFFICIAL FEE LEVEL', 'PRIMARY',
                'HIGH', 'HIGH IF APPLICABLE', 'MEDIUM', 'LOW-MEDIUM', 'LOW', 'UNDER REVIEW', 'OWNED', 'WITHDRAWN']
# fixed_codes fields whose values are not rendered through tv() (checked in static/js at 67f98cb): job and component codes
# are shown from item text; parts through t('part_' + x); reset basis through RESET in dossier.js; valuation kind and
# lease kind through t('sale_today' | 'lk_' + x); maintenance_items.kind and research_checks.result are not shown.
# If a screen starts to call tv() on one of them, remove it here so a missing key fails again.
NOT_RENDERED = re.compile(r'\.job$|^faults\.component_code$|^reliability_items\.part$|^(faults|recalls)\.part$|'
                          r'^maintenance_resets\.basis$|^valuations\.kind$|^listings\.lease_kind$|^maintenance_items\.kind$|'
                          r'^research_checks\.result$')


def flatten(d, pre=''):
    """{'a.b': text or {plural forms}} with nested blocks (codes) flattened."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and not (v and set(v) <= PLURAL):
            out.update(flatten(v, pre + k + '.'))
        else:
            out[pre + k] = v
    return out


def text_of(v):
    return ' '.join(v.values()) if isinstance(v, dict) else str(v)


def holders(v):
    return set(re.findall(r'\{(\w+)\}', text_of(v)))


def load_fixed_codes(root, fixed_file):
    if fixed_file:
        return json.loads(Path(fixed_file).read_text(encoding='utf8')), None
    if not (root / 'carlos' / 'agent.py').exists():
        return {}, 'no carlos/agent.py under the root: fixed_codes check skipped'
    os.environ['CARLOS_DATA'] = str(Path(tempfile.gettempdir()) / 'carlos-i18n-check-unused')  # never the real data dir
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True  # leave no __pycache__ in the checkout
    try:
        from carlos import agent  # reads constants only; opens no database
    except Exception as e:  # pragma: no cover
        return {}, f'could not import carlos.agent ({e}): fixed_codes check skipped'
    return agent.FIXED_CODES, None


def expected_langs(js):
    """The language codes of `export const LANGS = {en: ..., es: ...}` in i18n.js (fallback: en, es, de, pl)."""
    try:
        body = re.search(r'LANGS\s*=\s*\{([^}]*)\}', (js / 'i18n.js').read_text(encoding='utf8')).group(1)
        return re.findall(r'(\w+)\s*:', body) or ['en', 'es', 'de', 'pl']
    except (OSError, AttributeError):
        return ['en', 'es', 'de', 'pl']


def check_json(i18n, errors, warnings, langs=('en', 'es', 'de', 'pl')):
    data = {}
    for p in sorted(i18n.glob('*.json')):
        try:
            data[p.stem] = flatten(json.loads(p.read_text(encoding='utf8')))
        except ValueError as e:
            errors.append(f'json: {p.name} is not valid JSON ({e})')
    for lang in langs:
        if lang not in data:
            errors.append(f'parity: {lang}.json is missing or invalid (it is in LANGS of i18n.js)')
    en = data.get('en')
    if en is None:
        return data
    for lang, d in data.items():
        if lang == 'en':
            continue
        for k in sorted(set(en) - set(d)):
            errors.append(f'parity: {lang} lacks key {k}')
        for k in sorted(set(d) - set(en)):
            errors.append(f'parity: {lang} has extra key {k}')
        for k in sorted(set(en) & set(d)):
            a, b = en[k], d[k]
            if not text_of(b).strip():
                errors.append(f'empty: {lang}.{k} is empty')
            if holders(a) != holders(b):
                errors.append(f'placeholders: {lang}.{k} has {sorted(holders(b))}, en has {sorted(holders(a))}')
            if isinstance(a, dict) != isinstance(b, dict):
                errors.append(f'plural: {lang}.{k} is {"plural" if isinstance(b, dict) else "plain"}, en is {"plural" if isinstance(a, dict) else "plain"}')
            elif isinstance(a, dict) and (set(a) - set(b) or set(b) - set(a) - EXTRA_OK):
                errors.append(f'plural: {lang}.{k} forms {sorted(b)} vs en {sorted(a)}')
    for lang in sorted(data):
        same = [k for k in en if lang != 'en' and data[lang].get(k) == en[k] and len(text_of(en[k])) > 12 and ' ' in text_of(en[k]) and not k.startswith('codes.')]
        if same:
            warnings.append(f'untranslated: {lang} has {len(same)} strings identical to English: ' + ', '.join(same[:8]))
    for lang in ('de', 'pl'):
        if lang not in data:
            continue
        long = [(len(text_of(data[lang][k])) / len(text_of(en[k])), k) for k in en
                if k in data[lang] and len(text_of(en[k])) >= 6 and len(text_of(data[lang][k])) > RATIO * len(text_of(en[k]))]
        if long:
            top = ', '.join(f'{k} {r:.1f}x' for r, k in sorted(long, reverse=True)[:12])
            warnings.append(f'expansion: {lang} {len(long)} strings over {RATIO}x English (worst: {top}); check nowrap headers and tags at 390px')
    return data


def check_codes(data, fixed, errors, warnings, statuses=True):
    wanted = {}
    for field, vals in fixed.items():
        for v in vals:
            wanted.setdefault(str(v), set()).add(field)
    for c in STATUS_CODES if statuses else ():
        wanted.setdefault(c, set()).add('AGENTS.md statuses')
    for lang, d in data.items():
        have = {k[6:] for k in d if k.startswith('codes.')}
        miss = {c: f for c, f in wanted.items() if c not in have}
        hard = sorted(c for c, f in miss.items() if not all(NOT_RENDERED.search(x) for x in f))
        soft = sorted(c for c, f in miss.items() if all(NOT_RENDERED.search(x) for x in f))
        if hard:
            errors.append(f'codes: {lang} lacks {len(hard)} codes: ' + ', '.join(hard))
        if soft:
            warnings.append(f'codes: {lang} lacks {len(soft)} job/component codes (not rendered through tv(), verify): ' + ', '.join(soft[:8]) + ' ...')


LITERALS = [
    (re.compile(r'>\s*([A-Za-z][A-Za-z ,.\'!?:-]{2,})\s*<'), 'text between tags'),
    (re.compile(r'\b(?:title|placeholder|aria-label|alt)="([A-Za-z][^"$]{2,})"'), 'attribute text'),
    (re.compile(r'\b(?:toast|setStatus|empty|alert|confirm)\(\s*[\'"]([^\'"]*[A-Za-z]{3}[^\'"]*)[\'"]'), 'toast/empty text'),
    (re.compile(r'\.(?:textContent|innerText)\s*=\s*[\'"]([^\'"]*[A-Za-z]{3}[^\'"]*)[\'"]'), 'textContent'),
]
BYPASS_ERR = [(re.compile(r'toLocale(?:String|DateString|TimeString)\('), 'toLocaleString (use euro/num/Intl through locale())'),
              (re.compile(r'€|&euro;|\\u20ac', re.I), 'euro sign in code (use euro/num; a unit such as €/km is num() plus a t() suffix)')]
KEY_CALL = re.compile(r"(?<![\w.$])(?:i18n\.)?t\(\s*'([A-Za-z0-9_.]+)'\s*[,)]")  # literal keys only; 'why_' + x cannot be seen
BYPASS_WARN = [(re.compile(r'\.toFixed\('), 'toFixed (locale-blind; fine only for chart geometry)')]


def check_js(js, errors, warnings, keys=None):
    lit, byp_e, byp_w, nokey = [], [], [], []
    for p in sorted(js.rglob('*.js')):
        for n, line in enumerate(p.read_text(encoding='utf8').splitlines(), 1):
            s = line.strip()
            if s.startswith(('//', '*', '/*')) or 'i18n-ok' in line:
                continue
            line = re.sub(r'\s//.*$', '', line)  # a trailing comment is not copy (URLs have no space before //)
            code = re.sub(r'\$\{[^{}]*\}', '', line)  # text inside ${...} is code, not copy
            loc = f'{p.relative_to(js.parent)}:{n}'
            for rx, what in LITERALS:
                for m in rx.finditer(code):
                    if not re.search(r'[A-Za-z]{3}', m.group(1)) or re.fullmatch(r'[A-Z0-9_/ -]{1,12}', m.group(1).strip()):
                        continue  # units and codes such as km, EUR, HSN/TSN
                    lit.append(f'{loc} {what}: "{m.group(1).strip()[:40]}"')
            for rx, what in BYPASS_ERR:
                if rx.search(line):
                    byp_e.append(f'{loc} {what}')
            for rx, what in BYPASS_WARN:
                if rx.search(line):
                    byp_w.append(f'{loc} {what}')
            for m in KEY_CALL.finditer(line):
                if keys is not None and m.group(1) not in keys:
                    nokey.append(f'{loc} t(\'{m.group(1)}\') has no key in en.json')
    errors.extend('key: ' + x for x in nokey)
    errors.extend('format: ' + x for x in byp_e)
    warnings.extend('format: ' + x for x in byp_w)
    warnings.extend('literal: ' + x for x in lit)


def run(root, fixed_file=None):
    root = Path(root)
    errors, warnings = [], []
    js = root / 'static' / 'js'
    data = check_json(root / 'static' / 'i18n', errors, warnings, expected_langs(js))
    fixed, note = load_fixed_codes(root, fixed_file)
    if note:
        warnings.append(note)
    else:
        check_codes(data, fixed, errors, warnings, statuses=not fixed_file)
    check_js(js, errors, warnings, set(data['en']) if 'en' in data else None)
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=str(Path(__file__).resolve().parents[4]), help='repository root (default: this repository)')
    ap.add_argument('--fixed-codes', help='JSON {"table.column": [codes]} instead of importing carlos.agent')
    a = ap.parse_args(argv)
    errors, warnings = run(a.root, a.fixed_codes)
    for w in warnings:
        print('WARN  ' + w)
    for e in errors:
        print('ERROR ' + e)
    print(f'{len(errors)} errors, {len(warnings)} warnings')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
