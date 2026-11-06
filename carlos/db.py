"""SQLite access. Connections are opened per request; the path is read from config at call time (tests swap it)."""
import sqlite3
from . import config


def connect():
    c = sqlite3.connect(config.DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


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


def for_variant(all_rows, v):
    """Rows that apply to a variant: its own, its engine's, its gearbox's (#164) and its generation's (v has id, engine_id,
    generation_id and optionally gearbox_id)."""
    return [r for r in all_rows if r.get('vehicle_id') == v['id']
            or (r.get('engine_id') is not None and r['engine_id'] == v['engine_id'])
            or (r.get('gearbox_id') is not None and r['gearbox_id'] == v.get('gearbox_id'))
            or (r.get('generation_id') is not None and r['generation_id'] == v['generation_id'])]


def latest(all_rows, col):
    """Value of `col` in the newest row (highest id) that has one; None when no row has it."""
    for r in sorted(all_rows, key=lambda r: -r['id']):
        if r.get(col) is not None:
            return r[col]
    return None


VARIANT_SQL = '''SELECT v.id, v.generation_id, v.engine_id, v.gearbox_id, v.trim, v.transmission, v.body_style, v.model_year,
  v.emissions_standard, v.co2_g_km, v.hsn, v.tsn, v.technical_status, v.notes vehicle_notes,
  g.make, g.model, g.name generation, g.start_year generation_start_year, g.end_year generation_end_year,
  g.facelift_year, g.status generation_status,
  e.code engine_code, e.family engine_family, e.description engine_description, e.fuel_type, e.displacement_cc,
  e.cylinders, e.power_kw, e.power_ps, e.aspiration, e.injection, e.timing_drive, e.status engine_status,
  x.code gearbox_code, x.type gearbox_type, x.gears gearbox_gears
FROM vehicles v JOIN generations g ON g.id=v.generation_id JOIN engines e ON e.id=v.engine_id LEFT JOIN gearboxes x ON x.id=v.gearbox_id'''


def variants(c, where='', args=()):
    return rows(c, f'{VARIANT_SQL} {where} ORDER BY g.make, g.model, g.start_year, v.id', args)


def variant_name(v):
    return f"{v['make']} {v['model']} {v['trim'] or ''}".strip()
