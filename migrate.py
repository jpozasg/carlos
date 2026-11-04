"""Applies pending migrations/NNN_*.sql (by PRAGMA user_version), with a prior backup and one transaction each.
A missing database is created from schema.sql (the baseline) at the schema version written in its header."""
from pathlib import Path
import datetime, re, sqlite3, sys

ROOT = Path(__file__).resolve().parent
KEEP_BACKUPS = 5


def backup(db):
    d = Path(db).parent / 'backups'; d.mkdir(exist_ok=True)
    dst = d / f"cars_{datetime.datetime.now():%Y%m%d_%H%M%S_%f}.sqlite"
    src, out = sqlite3.connect(db), sqlite3.connect(dst)
    src.backup(out); out.close(); src.close()
    for old in sorted(d.glob('cars_*.sqlite'))[:-KEEP_BACKUPS]:  # 500 MB quota on the Raspberry Pi
        old.unlink()
    return dst


def migrations():
    return sorted((int(p.name[:3]), p) for p in (ROOT / 'migrations').glob('[0-9][0-9][0-9]_*.sql'))


def baseline_version(schema_sql):
    m = re.search(r'user_version=(\d+)', schema_sql)
    return int(m[1]) if m else 0


def latest_version():
    """The schema version a fresh or fully migrated database has: the baseline of schema.sql or the last migration."""
    files = migrations()
    return max(baseline_version((ROOT / 'schema.sql').read_text(encoding='utf-8')), files[-1][0] if files else 0)


def create(db):
    """New database from schema.sql at its baseline version (fresh installs; the test fixture)."""
    sql = (ROOT / 'schema.sql').read_text(encoding='utf-8')
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    try:
        c.executescript(sql)
        c.execute(f'PRAGMA user_version={baseline_version(sql)}')
        c.commit()
    finally:
        c.close()


def run(db=ROOT / 'cars.sqlite'):
    db = Path(db)
    if not db.exists():
        create(db)
    c = sqlite3.connect(db)
    # Migrations rebuild tables (SQLite's documented procedure): foreign keys off during the script and
    # PRAGMA foreign_key_check before the commit, so a violation rolls the whole migration back.
    c.execute('PRAGMA foreign_keys=OFF')
    try:
        current = c.execute('PRAGMA user_version').fetchone()[0]
        pending = [(n, p) for n, p in migrations() if n > current]
        if not pending:
            return []
        print('Backup:', backup(db))
        for n, p in pending:
            try:
                c.executescript(f'BEGIN;\n{p.read_text(encoding="utf-8")}\nPRAGMA user_version={n};')
                bad = c.execute('PRAGMA foreign_key_check').fetchall()
                if bad:
                    raise sqlite3.IntegrityError(f'{p.name}: foreign key violations {bad[:5]}')
                c.execute('COMMIT')
            except Exception:
                c.rollback(); raise
            print('Migration applied:', p.name)
        assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        return [p.name for _, p in pending]
    finally:
        c.close()


def dump_schema(db, out=ROOT / 'schema.sql'):
    """Regenerates schema.sql (the reference schema and the baseline for new databases) from a migrated database."""
    c = sqlite3.connect(db)
    version = c.execute('PRAGMA user_version').fetchone()[0]
    rows = c.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                     "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END, rowid").fetchall()
    c.close()
    text = (f'-- Reference schema generated from the database (PRAGMA user_version={version}). Changes: add migrations/NNN_*.sql.\n'
            + ''.join(r[0] + ';\n' for r in rows))
    Path(out).write_text(text, encoding='utf-8')
    return out


if __name__ == '__main__':
    target = Path(sys.argv[-1]) if len(sys.argv) > 1 and not sys.argv[-1].startswith('--') else ROOT / 'cars.sqlite'
    if '--schema' in sys.argv:
        print('Schema written:', dump_schema(target))
    else:
        run(target)
