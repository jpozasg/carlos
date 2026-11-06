"""Statistics vs faults (owner, 2026-11-06, #168): for every generation with TÜV/ADAC figures, compare what the official
statistics say about the model at an age class (its figure ÷ the class average in the same report) with what our faults
predict for it (the yearly chance of any of its faults at that age ÷ the catalogue average for that age class). When one
says clearly more trouble and the other clearly less, the generation gets a STATS_MISMATCH review flag and a follow-up
research request is queued for a worker. Nothing is scaled automatically. Reads the main tables (the whole catalogue)."""
import json
from . import config
from .costs import curve_at, shape_curves
from .research_requests import follow_up


def yearly_chance(faults, age):
    """Chance per year that one of the faults happens to a car of this age at typical mileage (sum over the faults of
    the curve's rise over that year; age curves by years, km curves at TYPICAL_KM_PER_YEAR)."""
    total, km = 0.0, config.TYPICAL_KM_PER_YEAR
    for f in faults:
        km_c, age_c = shape_curves(f)
        if age_c:
            total += curve_at(age_c, age + 1, config.CURVE_END_YEARS) - curve_at(age_c, age, config.CURVE_END_YEARS)
        elif km_c:
            total += curve_at(km_c, (age + 1) * km, config.CURVE_END_KM) - curve_at(km_c, age * km, config.CURVE_END_KM)
    return total


def generation_faults(c, gid):
    """The faults a generation's cars carry: its own, its body styles' and options', and those of its variants, engines,
    engine families, gearboxes and gearbox families (every level that reaches its cars)."""
    q = '''SELECT f.* FROM main.faults f WHERE f.archived=0 AND (f.generation_id=:g
        OR f.vehicle_id IN (SELECT id FROM main.vehicles WHERE generation_id=:g)
        OR f.engine_id IN (SELECT engine_id FROM main.vehicles WHERE generation_id=:g)
        OR f.engine_family_id IN (SELECT e.family_id FROM main.vehicles v JOIN main.engines e ON e.id=v.engine_id WHERE v.generation_id=:g)
        OR f.gearbox_id IN (SELECT gearbox_id FROM main.vehicles WHERE generation_id=:g)
        OR f.gearbox_family_id IN (SELECT gb.family_id FROM main.vehicles v JOIN main.gearboxes gb ON gb.id=v.gearbox_id WHERE v.generation_id=:g)
        OR f.body_style_id IN (SELECT id FROM main.body_styles WHERE generation_id=:g)
        OR f.option_id IN (SELECT id FROM main.options WHERE generation_id=:g))'''
    return [dict(r) for r in c.execute(q, {'g': gid})]


def check(c):
    """Flags generations whose statistics and faults disagree clearly (both ways) and queues a follow-up for each new flag.
    Returns the new flags' ids."""
    stats = [dict(r) for r in c.execute('SELECT * FROM main.reliability_stats WHERE archived=0 AND class_average IS NOT NULL')]
    if not stats:
        return []
    faults = {gid: generation_faults(c, gid) for gid in {s['generation_id'] for s in stats}}
    by_age = {}
    for s in stats:
        age = (s['age_from'] + s['age_to']) / 2
        by_age.setdefault((s['age_from'], s['age_to']), []).append((s, yearly_chance(faults[s['generation_id']], age)))
    new, r = [], config.STATS_MISMATCH_RATIO
    with c:
        for cls, entries in by_age.items():
            mean = sum(p for _, p in entries) / len(entries)
            for s, p in entries:
                stat_ratio, fault_ratio = s['value'] / s['class_average'], (p / mean if mean else None)
                if fault_ratio is None or not (stat_ratio >= r and fault_ratio <= 1 / r or stat_ratio <= 1 / r and fault_ratio >= r):
                    continue
                if c.execute("SELECT 1 FROM main.review_flags WHERE generation_id=? AND kind='STATS_MISMATCH' AND status='OPEN'",
                             (s['generation_id'],)).fetchone():
                    continue
                more = stat_ratio >= r
                what = (f"{s['kind']} {s['age_from']}–{s['age_to']} years: {s['value']:g} {s['unit']} vs class average "
                        f"{s['class_average']:g} ({stat_ratio:.1f}×); our faults predict {fault_ratio:.1f}× the catalogue average")
                why = ('the statistics show clearly more trouble than our faults explain: look for missing faults'
                       if more else 'our faults predict clearly more trouble than the statistics show: look for overstated faults')
                fid = c.execute("INSERT INTO main.review_flags (generation_id, kind, what, why, created_by) VALUES (?,?,?,?,?)",
                                (s['generation_id'], 'STATS_MISMATCH', what, why, 'consistency check')).lastrowid
                follow_up(c, fid, f'Review flag {fid} (generation {s["generation_id"]}): {why}. {what}.')
                new.append(fid)
    return new
