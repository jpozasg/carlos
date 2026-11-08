"""Research reset (issue #167, tool #194): empties all model research and keeps only one account's listings.

Dry run by default: prints what it would do and changes nothing. --apply backs the database up (migrate.backup) and
runs everything in one transaction, then checks integrity and foreign keys. Idempotent: a second run finds nothing to do.

Kept: users, sessions, invites, tokens, workers, parameters, preferences, the change log, and the KEEP account's
listings with their captures, photos, events, viewing checklist (results kept, link to the old weak point cleared),
listing quotes, listing history, the reference car's sale-today valuation and its research requests.
Emptied: every catalogue level (generations, engines and families, gearboxes and families, body styles, options,
variants), every knowledge row, research checks, review flags and their reviews, statistics, market models, the old
resale estimates (resale_end), maintenance resets and unit costs (replaced by listing history), catalogue links, and
the sources nothing kept cites. A kept row that cites a source on a model level keeps it as a private, level-free
source of the account. The other accounts' listings are deleted with their child rows and photo files.
Listings keep hsn, tsn, engine_code_seen, build_date and trim, so the worker re-finds or recreates their variant.

Usage: python research_reset.py <cars.sqlite> [--apply] [--keep-account 5] [--drop-requests]"""
import sqlite3
import sys
from pathlib import Path

import migrate

RESEARCH = ('maintenance_items', 'faults', 'recalls', 'reliability_items', 'repair_risks', 'reliability_stats',
            'market_models', 'observations', 'insurance_data', 'tax_data', 'tyre_data', 'research_checks',
            'research_matches', 'research_findings', 'flag_reviews', 'review_flags', 'catalogue_links', 'listing_options', 'maintenance_resets', 'unit_costs')
LEVELS = ('vehicles', 'engines', 'gearboxes', 'engine_families', 'gearbox_families', 'body_styles', 'options', 'generations')
LEVEL_COLS = ('vehicle_id', 'engine_id', 'gearbox_id', 'generation_id', 'engine_family_id', 'gearbox_family_id',
              'body_style_id', 'option_id')


def tables(c):
    return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def cols(c, t):
    return [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]


def steps(c, keep, drop_requests=False):
    """(description, sql, params) in order; counts are taken before running each step."""
    ts = tables(c)
    gone = 'SELECT id FROM listings WHERE owner_id != ?'
    out = []
    # 1. the other accounts' listings: their child rows first, then the listings
    for t in ts:
        if t != 'listings' and 'listing_id' in cols(c, t) and t != 'research_requests':
            out.append((f'{t}: rows of other accounts\' listings', f'DELETE FROM "{t}" WHERE listing_id IN ({gone})', (keep,)))
    out += [('research_requests: other accounts and follow-ups of the wiped research',
             'DELETE FROM research_requests WHERE owner_id != ? OR flag_id IS NOT NULL', (keep,)),
            ('listings: other accounts (incl. fictional references)', 'DELETE FROM listings WHERE owner_id != ?', (keep,))]
    # 2. the kept listings lose their links into the research
    out += [('listings: variant cleared (re-found from hsn/tsn/engine code)', 'UPDATE listings SET vehicle_id=NULL WHERE vehicle_id IS NOT NULL', ()),
            ('inspection_items: link to the old weak point cleared', 'UPDATE inspection_items SET reliability_item_id=NULL, fault_id=NULL, recall_id=NULL '
             'WHERE reliability_item_id IS NOT NULL OR fault_id IS NOT NULL OR recall_id IS NOT NULL', ()),
            ('listing_history: links to wiped jobs/faults/recalls cleared',
             'UPDATE listing_history SET maintenance_item_id=NULL, fault_id=NULL, recall_id=NULL '
             'WHERE maintenance_item_id IS NOT NULL OR fault_id IS NOT NULL OR recall_id IS NOT NULL', ()),
            ('valuations: old resale estimates (the market model replaces them)', "DELETE FROM valuations WHERE kind='resale_end'", ())]
    # 3. research and catalogue levels
    out += [(f'{t}: emptied', f'DELETE FROM "{t}"', ()) for t in RESEARCH + LEVELS if t in ts]
    # 4. sources: a kept row's model-level source becomes private and level-free; the rest nothing cites goes
    refs = ' UNION '.join(f'SELECT source_id FROM "{t}" WHERE source_id IS NOT NULL'
                          for t in ts if t != 'sources' and 'source_id' in cols(c, t))
    level = ' OR '.join(f'{x} IS NOT NULL' for x in LEVEL_COLS if x in cols(c, 'sources'))
    out += [('sources: cited by kept rows, detached from their model level (private to the account)',
             f'UPDATE sources SET {", ".join(f"{x}=NULL" for x in LEVEL_COLS if x in cols(c, "sources"))}, owner_id={int(keep)} '
             f'WHERE ({level}) AND id IN ({refs})', ()),
            ('sources: cited by nothing kept', f'DELETE FROM sources WHERE id NOT IN ({refs})', ())]
    if drop_requests:  # a clean slate: the kept account's request history points at wiped research
        out.append(('workers: current request cleared', 'UPDATE workers SET request_id=NULL WHERE request_id IS NOT NULL', ()))
        out.append(('research_requests: all (history of the wiped research)', 'DELETE FROM research_requests', ()))
    return out


def run(db, apply=False, keep=5, drop_requests=False):
    """Runs every step in one transaction (exact row counts); the dry run rolls it back. Returns {description: rows}."""
    db = Path(db)
    c = sqlite3.connect(db, isolation_level=None)
    c.execute('PRAGMA foreign_keys=OFF')
    try:
        if not c.execute('SELECT 1 FROM users WHERE id=?', (keep,)).fetchone():
            raise SystemExit(f'account {keep} does not exist')
        media = [r[0] for r in c.execute('SELECT file_path FROM listing_media WHERE listing_id IN '
                                         '(SELECT id FROM listings WHERE owner_id != ?)', (keep,))]
        if apply:
            print('Backup:', migrate.backup(db))
        done = {}
        c.execute('BEGIN')
        try:
            for d, sql, p in steps(c, keep, drop_requests):
                n = c.execute(sql, p).rowcount
                if n:
                    done[d] = n
                    print(f'{n:6d}  {d}')
            bad = c.execute('PRAGMA foreign_key_check').fetchall()
            if bad:
                raise sqlite3.IntegrityError(f'foreign key violations {bad[:5]}')
            c.execute('COMMIT' if apply else 'ROLLBACK')
        except Exception:
            c.execute('ROLLBACK'); raise
        print(f'{len(media):6d}  photo files of other accounts\' listings')
        if not done and not media:
            print('Nothing to do.')
            return done
        if not apply:
            print('Dry run: nothing changed. Run with --apply to reset (a backup is made first).')
            return done
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        for f in media:  # after the commit: a failed reset never loses photos
            (db.parent / 'media' / f).unlink(missing_ok=True)
        print('Reset applied; integrity ok, no foreign-key violations.')
        return done
    finally:
        c.close()


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0].startswith('-'):
        raise SystemExit(__doc__)
    keep = int(args[args.index('--keep-account') + 1]) if '--keep-account' in args else 5
    run(args[0], "--apply" in args, keep, '--drop-requests' in args)
