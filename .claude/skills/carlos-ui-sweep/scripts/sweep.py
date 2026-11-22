#!/usr/bin/env python3
"""Carlos UI sweep: drives headless Chromium through every route x language x mode x width on a THROWAWAY server.

The server runs on a copy of the synthetic test fixture (tests/fixture.py) in its own temp data dir on a free port;
the real data dir is never opened. Needs the Python `playwright` package and a Chromium (nothing is installed here).

    python .claude/skills/carlos-ui-sweep/scripts/sweep.py --out DIR [--state default|empty|error|loading]
        [--routes compare,listing/2] [--langs en,de,pl] [--modes light,dark] [--widths 1280,390] [--sql "UPDATE ..."] [--reduced-motion] [--chromium /usr/bin/chromium]

Writes DIR/shots/*.png, DIR/report.json, DIR/report.md and DIR/server.log. Exit 1 when a page has a console error, a failed
request, horizontal overflow, a raw undefined/NaN/[object, more than one h1 or a bare i18n key. Clipped text and a missing
h1 is a failure since #424 (every route renders one); clipped text stays a note.
"""
import argparse, json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ROUTES = ['compare?view=ruler', 'compare?view=overview', 'compare?view=costs', 'compare?view=breakeven', 'compare?view=details',
          'compare?view=photos', 'ranking', 'ranking?quiz=1', 'listing/2', 'listing/3', 'listing/1', 'listing/2?tab=costs',
          'listing/2?tab=maintenance', 'listing/2?tab=reliability', 'listing/2?tab=viewing', 'listing/2?tab=log', 'models', 'models/1',
          'models/4', 'sources', 'settings', 'admin', 'start?step=1', 'start?step=3']
# the account `empty` owns no listing or variant and is no admin: listing/N, models/N and admin would only show 404 / 401
EMPTY_ROUTES = ['compare?view=ruler', 'compare?view=overview', 'ranking', 'models', 'sources', 'settings', 'start?step=1']
# the ids of tests/fixture.py: listings 1 (own car) 2, 3; variants 1-4 (4 has NULL gaps)

PROBE = """() => {
  const vw = innerWidth, bad = [], clip = [], sel = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const overflow = document.documentElement.scrollWidth > vw + 1;
  if (overflow) for (const e of document.body.querySelectorAll('*')) { const r = e.getBoundingClientRect(); if (r.width && r.right > vw + 1 && bad.length < 6 && !e.closest('[class*=scroll],.tablewrap,.rail,.dtabs,nav,pre,table')) bad.push(sel(e) + ' right=' + Math.round(r.right)); }
  for (const e of document.querySelectorAll('main *, header *')) { const s = getComputedStyle(e); if (!e.classList.contains('sr-only') && e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0 && (s.overflowX === 'hidden' || s.textOverflow === 'ellipsis') && e.textContent.trim() && clip.length < 8) clip.push(sel(e) + ': ' + e.textContent.trim().slice(0, 40)); }
  const text = document.getElementById('main').innerText;
  const raw = (text.match(/\\bundefined\\b|\\bNaN\\b|\\[object|\\bnull\\b/g) || []).slice(0, 3);
  const keys = [...document.getElementById('main').querySelectorAll('*')].filter(e => !e.children.length && /^[a-z]{2,}(_[a-z0-9]+)+$/.test(e.textContent.trim())).map(e => e.textContent.trim()).slice(0, 5);
  return { overflow, offenders: bad, clipped: clip, raw, keys, h1: document.querySelectorAll('h1').length, busy: document.getElementById('main').getAttribute('aria-busy'), loading: !!document.querySelector('#main .skel'), failed: !!document.querySelector('#main .card.err') };
}"""


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def make_data(tmp, sql=()):
    os.environ['CARLOS_DATA'] = str(tmp)  # before importing carlos: config reads it once
    sys.path.insert(0, str(ROOT))
    from tests import fixture as fx
    from carlos import auth
    db = Path(tmp) / 'cars.sqlite'
    fx.build(db)
    c = sqlite3.connect(db)
    empty = auth.create_user(c, 'empty')  # the app's own function: it also creates the account's parameters row (the server needs one)
    with c:
        c.execute('UPDATE users SET password_hash=? WHERE id=?', (auth.hash_password(fx.PASSWORD), empty))
        for uid in (fx.ADMIN, empty):  # skip the first-run wizard
            c.execute("INSERT INTO project_preferences (owner_id, preference_key, preference_value) VALUES (?, 'onboarding_done', '2026-01-01')", (uid,))
    # forced states (withdrawn, partial totals...): runs on the throwaway copy only; ATTACH would reach the real database
    c.set_authorizer(lambda action, *a: sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
    for q in sql:
        with c: c.execute(q)
    c.close()
    return fx


def login(base, user, password):
    req = urllib.request.Request(base + '/api/auth/login', json.dumps({'username': user, 'password': password}).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        return r.headers['Set-Cookie'].split(';')[0].split('=', 1)[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True, help='output directory (screenshots and reports)')
    ap.add_argument('--state', default='default', choices=['default', 'empty', 'error', 'loading'])
    ap.add_argument('--routes', help='comma list; default: all')
    ap.add_argument('--langs', default='en,de,pl')
    ap.add_argument('--modes', default='light,dark')
    ap.add_argument('--widths', default='1280,390')
    ap.add_argument('--sql', action='append', help='extra SQL run on the THROWAWAY database before the server starts (repeatable)')
    ap.add_argument('--reduced-motion', action='store_true', help='emulate prefers-reduced-motion: reduce')
    ap.add_argument('--chromium', help='path to a Chromium/Chrome binary (default: Playwright\'s own, else /usr/bin/chromium)')
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('Python package "playwright" is missing. Install it yourself (pip install playwright) or run this where it exists; '
                 'the sweep installs nothing. Alternative: follow the manual checklist in SKILL.md.')
    out = Path(a.out); (out / 'shots').mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='carlos-sweep-')  # throwaway data dir, deleted at the end (it is ours)
    fx = make_data(tmp, a.sql or [])
    port = free_port(); base = f'http://127.0.0.1:{port}'
    log_file = open(out / 'server.log', 'w')
    srv = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT, env={**os.environ, 'CARLOS_DATA': tmp, 'CARLOS_PORT': str(port)},
                           stdout=log_file, stderr=subprocess.STDOUT)  # app.py binds 127.0.0.1 only (carlos/config.py HOST)
    results, failures = [], 0
    try:
        for _ in range(60):
            try: urllib.request.urlopen(base + '/login').read(); break
            except Exception: time.sleep(0.25)
        else:
            sys.exit(f'throwaway server did not start, see {out / "server.log"}')
        cookie = login(base, 'empty' if a.state == 'empty' else 'admin', fx.PASSWORD)
        routes = a.routes.split(',') if a.routes else EMPTY_ROUTES if a.state == 'empty' else ROUTES
        with sync_playwright() as pw:
            exe = a.chromium or (shutil.which('chromium') if not Path(pw.chromium.executable_path).exists() else None)
            try:
                browser = pw.chromium.launch(executable_path=exe, args=['--no-sandbox'])
            except Exception as e:
                sys.exit(f'no Chromium could be started ({str(e).splitlines()[0]}). Pass --chromium /path/to/chromium; the sweep installs nothing.')
            for lang in a.langs.split(','):
                for mode in a.modes.split(','):
                    for w in map(int, a.widths.split(',')):
                        ctx = browser.new_context(viewport={'width': w, 'height': 900 if w > 600 else 800}, device_scale_factor=1, has_touch=w < 600, is_mobile=w < 600,
                                          reduced_motion='reduce' if a.reduced_motion else 'no-preference')  # a phone run must match (pointer: coarse)
                        ctx.add_cookies([{'name': 'carlos_session', 'value': cookie, 'url': base}])
                        ctx.add_init_script(f"try{{localStorage.setItem('carlos.lang','{lang}');localStorage.setItem('carlos.mode','\"{mode}\"')}}catch(e){{}}")
                        if a.state == 'error':
                            ctx.route('**/api/**', lambda r: r.fulfill(status=500, content_type='application/json', body='{"error":"forced by the sweep"}') if '/api/auth/' not in r.request.url else r.continue_())
                        if a.state == 'loading':
                            ctx.route('**/api/**', lambda r: None)  # hold every API request forever: the skeleton stays on screen
                        page = ctx.new_page(); log = []
                        page.on('console', lambda m, log=log: log.append(m.text) if m.type == 'error' else None)
                        page.on('pageerror', lambda e, log=log: log.append('pageerror: ' + str(e)))
                        page.on('response', lambda r, log=log: log.append(f'{r.status} {r.url}') if r.status >= 400 and a.state != 'error' else None)
                        for route in routes:
                            log.clear()
                            page.goto(f'{base}/#/{route}'); page.reload()  # a hash change alone would not re-run the init script
                            if a.state == 'loading': page.wait_for_timeout(400)
                            else:
                                try: page.wait_for_function("() => !document.querySelector('#main .skel')", timeout=8000)
                                except Exception: pass
                                page.wait_for_timeout(300)
                            res = page.evaluate(PROBE)
                            name = f"{route.replace('/', '-').replace('?', '_').replace('=', '-').replace('&', '_')}__{a.state}__{lang}_{mode}_{w}"
                            page.screenshot(path=str(out / 'shots' / f'{name}.png'), full_page=True)
                            errs = [] if a.state == 'error' else list(log)
                            notes = [f'clipped {c}' for c in res['clipped']]
                            if a.state == 'loading' and res['busy'] != 'true': notes.append('loading state without aria-busy="true"')
                            problems = errs + (['horizontal overflow: ' + '; '.join(res['offenders'])] if res['overflow'] else []) \
                                + (['raw text: ' + ', '.join(res['raw'])] if res['raw'] and a.state != 'error' else []) \
                                + (['bare i18n key: ' + ', '.join(res['keys'])] if res['keys'] else []) \
                                + (['%d h1 elements' % res['h1']] if res['h1'] > 1 else []) \
                                + (['no h1 (#424)'] if not res['h1'] and a.state in ('default', 'empty') else []) \
                                + (['still loading'] if res['loading'] and a.state != 'loading' else []) \
                                + (['load-failed card missing'] if a.state == 'error' and not res['failed'] else [])
                            failures += bool(problems)
                            results.append(dict(route=route, lang=lang, mode=mode, width=w, state=a.state, problems=problems, notes=notes, shot=f'shots/{name}.png'))
                        ctx.close()
            browser.close()
    finally:
        srv.terminate()
        try: srv.wait(10)
        except subprocess.TimeoutExpired: srv.kill()
        log_file.close()
        shutil.rmtree(tmp, ignore_errors=True)
    (out / 'report.json').write_text(json.dumps(results, indent=1))
    lines = [f'# Carlos UI sweep ({a.state}): {len(results)} pages, {failures} with problems', '']
    for r in results:
        if r['problems'] or r['notes']:
            lines.append(f"- {r['route']} {r['lang']} {r['mode']} {r['width']}px ({r['shot']})")
            lines += [f'  - PROBLEM {p}' for p in r['problems']] + [f'  - note {c}' for c in r['notes']]
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines[:60])); print(f'report: {out / "report.md"}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
