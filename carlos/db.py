"""SQLite access. Connections are opened per request; the path is read from config at call time (tests swap it)."""
import sqlite3
import time
from . import config


class Connection(sqlite3.Connection):
    scope = None  # (user id, curator) once auth.scope ran on it: what the ranking cache keys on (server.costed)


def connect():
    # WAL: readers never wait for the writer; the 30 s busy timeout covers the few writes that overlap (worker + browser)
    c = sqlite3.connect(config.DB, timeout=30, factory=Connection)
    c.row_factory = sqlite3.Row
    _set_wal(c)
    c.execute('PRAGMA foreign_keys=ON')
    return c


def _set_wal(c):
    """Switches the file to WAL once. The switch takes an exclusive lock and the busy timeout does not wait for it, so
    while another connection holds a lock it fails at once: retry briefly, then go on, since that connection sets WAL."""
    for attempt in range(6):
        try:
            if c.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                c.execute('PRAGMA journal_mode=WAL')
            return
        except sqlite3.OperationalError as e:
            if 'database is locked' not in str(e):
                raise
            time.sleep(0.05 * (attempt + 1))


def params(c):
    """The current owner's parameters (the connection is scoped to one owner by auth.scope)."""
    return dict(c.execute('SELECT * FROM project_parameters').fetchone())


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]


def level_of(row):
    """Which level a knowledge row is attached to: variant, engine, generation or shared (sources without any)."""
    for col, name in config.LEVELS.items():
        if row.get(col) is not None:
            return name
    return 'shared'


def scoped(c, table, order='id'):
    """All rows of a knowledge table with their level, so they can be resolved per variant without a query each."""
    out = rows(c, f'SELECT * FROM {table} ORDER BY {order}')
    for r in out:
        r['level'] = level_of(r)
    return out


# a variant's level ids under these keys (VARIANT_SQL / costs.UNITS_SQL); option_ids: the listing's options present
_VARIANT_KEY = {'vehicle_id': 'id', 'engine_id': 'engine_id', 'generation_id': 'generation_id', 'gearbox_id': 'gearbox_id',
                'engine_family_id': 'engine_family_id', 'gearbox_family_id': 'gearbox_family_id', 'body_style_id': 'body_style_id'}


def applies(r, v):
    """A knowledge row applies to a variant when its level is one of the variant's (variant, engine and its family,
    gearbox and its family, generation, body style, or an option present on the listing); a row without a level (a
    global maintenance default, #174) applies to every car."""
    levels = [(col, r.get(col)) for col in config.LEVEL_COLUMNS if r.get(col) is not None]
    if not levels:
        return 'interval_km' in r  # only maintenance rows can be global defaults
    col, val = levels[0]
    return val in (v.get('option_ids') or ()) if col == 'option_id' else v.get(_VARIANT_KEY[col]) == val


def for_variant(all_rows, v):
    """Rows that apply to a variant: its own and those of every level above it (see applies)."""
    return [r for r in all_rows if applies(r, v)]


def latest(all_rows, col):
    """Value of `col` in the newest row (highest id) that has one; None when no row has it."""
    for r in sorted(all_rows, key=lambda r: -r['id']):
        if r.get(col) is not None:
            return r[col]
    return None


VARIANT_SQL = '''SELECT v.id, v.generation_id, v.engine_id, v.gearbox_id, v.body_style_id, e.family_id engine_family_id,
  gb.family_id gearbox_family_id, gb.code gearbox_code, gb.type gearbox_type, v.trim, v.transmission, v.body_style, v.model_year,
  v.emissions_standard, v.co2_g_km, v.hsn, v.tsn, v.technical_status, v.notes vehicle_notes,
  g.make, g.model, g.name generation, g.start_year generation_start_year, g.end_year generation_end_year,
  g.facelift_year, g.status generation_status,
  e.code engine_code, e.family engine_family, e.description engine_description, e.fuel_type, e.displacement_cc,
  e.cylinders, e.power_kw, e.power_ps, e.aspiration, e.injection, e.timing_drive, e.status engine_status,
  ef.name engine_family_name, gf.name gearbox_family_name, bs.name body_style_name
FROM vehicles v JOIN generations g ON g.id=v.generation_id JOIN engines e ON e.id=v.engine_id
LEFT JOIN gearboxes gb ON gb.id=v.gearbox_id LEFT JOIN engine_families ef ON ef.id=e.family_id
LEFT JOIN gearbox_families gf ON gf.id=gb.family_id LEFT JOIN body_styles bs ON bs.id=v.body_style_id'''


def variants(c, where='', args=()):
    return rows(c, f'{VARIANT_SQL} {where} ORDER BY g.make, g.model, g.start_year, v.id', args)


def variant_name(v):
    return f"{v['make']} {v['model']} {v['trim'] or ''}".strip()
