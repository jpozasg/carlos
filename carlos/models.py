"""The models browser: make → model → generation → engine → variant, each with its linked listings and knowledge."""
from . import config
from .costs import Knowledge
from .db import rows, variants


def model_tree(c):
    """Nested tree with listing ids per variant (for the filters and the links listing ↔ model)."""
    per_vehicle = {}
    for r in c.execute('SELECT id, vehicle_id, listing_status, is_reference, price_eur, mileage_km, listing_id, platform FROM listings ORDER BY id'):
        per_vehicle.setdefault(r['vehicle_id'], []).append(dict(r))
    know = Knowledge(c)
    makes = {}
    for v in variants(c):
        v['listings'] = per_vehicle.get(v['id'], [])
        v['knowledge'] = {t: len(know.of(t, v)) for t in config.SCOPED_TABLES}
        mk = makes.setdefault(v['make'], {'make': v['make'], 'models': {}})
        md = mk['models'].setdefault(v['model'], {'model': v['model'], 'generations': {}})
        g = md['generations'].setdefault(v['generation_id'], {
            'id': v['generation_id'], 'name': v['generation'], 'start_year': v['generation_start_year'],
            'end_year': v['generation_end_year'], 'facelift_year': v['facelift_year'], 'status': v['generation_status'], 'engines': {}})
        e = g['engines'].setdefault(v['engine_id'], {
            'id': v['engine_id'], 'code': v['engine_code'], 'family': v['engine_family'], 'description': v['engine_description'],
            'fuel_type': v['fuel_type'], 'displacement_cc': v['displacement_cc'], 'power_kw': v['power_kw'], 'power_ps': v['power_ps'],
            'aspiration': v['aspiration'], 'injection': v['injection'], 'timing_drive': v['timing_drive'], 'status': v['engine_status'],
            'variants': []})
        e['variants'].append(v)
    out = []
    for mk in sorted(makes.values(), key=lambda m: m['make']):
        models = []
        for md in sorted(mk['models'].values(), key=lambda m: m['model']):
            gens = []
            for g in sorted(md['generations'].values(), key=lambda g: (g['start_year'] or 0, g['id'])):
                g['engines'] = sorted(g['engines'].values(), key=lambda e: (e['displacement_cc'] or 0, e['id']))
                gens.append(g)
            md['generations'] = gens
            models.append(md)
        mk['models'] = models
        out.append(mk)
    return {'makes': out, 'levels': list(config.LEVELS.values())}


def variant_detail(c, vehicle_id):
    """One variant with its engine, generation, every knowledge row (with its level) and its listings."""
    vs = variants(c, 'WHERE v.id=?', (vehicle_id,))
    if not vs:
        return None
    v = vs[0]
    know = Knowledge(c)
    v.update({t: know.of(t, v) for t in config.SCOPED_TABLES})
    v['engine_row'] = rows(c, 'SELECT * FROM engines WHERE id=?', (v['engine_id'],))[0]
    v['generation_row'] = rows(c, 'SELECT * FROM generations WHERE id=?', (v['generation_id'],))[0]
    v['siblings'] = {'same_engine': [x['id'] for x in variants(c, 'WHERE v.engine_id=? AND v.id<>?', (v['engine_id'], v['id']))],
                     'same_generation': [x['id'] for x in variants(c, 'WHERE v.generation_id=? AND v.id<>?', (v['generation_id'], v['id']))]}
    v['listings'] = rows(c, 'SELECT id, listing_id, platform, url, price_eur, mileage_km, first_registration, listing_status, '
                            'is_reference, last_checked FROM listings WHERE vehicle_id=? ORDER BY id', (vehicle_id,))
    v['sources'] = rows(c, 'SELECT * FROM sources WHERE vehicle_id=? OR engine_id=? OR generation_id=? ORDER BY id',
                        (v['id'], v['engine_id'], v['generation_id']))
    return v
