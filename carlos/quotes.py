"""A manual insurance quote entered by the account for one of its own cars (issue #399): the same `listing_quotes` row a
worker quote is, so the cost calculation reads it the same way. Nothing here contacts a comparison site."""
import datetime, math
from .agent import agent_write

COVERS = ('Haftpflicht', 'Teilkasko', 'Vollkasko')
MAX_ANNUAL_EUR, MAX_PER_LISTING = 20000, 30
SOURCE = {'title': 'Insurance quote entered by the account', 'source_type': 'user_data', 'quality': 'D',
          'supports': 'The annual premium the account holder was quoted, as typed in by them',
          'limitations': 'Unverified: a premium typed in by the account holder from a comparison site, an insurer or a phone call; no document is stored'}


def _num(d, key, required=False):
    v = d.get(key)
    if v is None or v == '':
        if required:
            raise ValueError(f'{key} is required')
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f'{key} must be a number')
    return float(v)


def _text(d, key, limit):
    v = str(d.get(key) or '').strip()
    if len(v) > limit:
        raise ValueError(f'{key}: at most {limit} characters')
    return v or None


def manual_quote(c, uid, d, today):
    """Validates the form and inserts the quote, its log entry (`user_data`) and, on first use, the account's source.
    Only a car of this account that is for sale counts (the listings view hides every other account's rows)."""
    if not isinstance(d, dict):
        raise ValueError('Expected a JSON object')
    lid = d.get('listing_id')
    row = c.execute('SELECT is_reference FROM listings WHERE id=?', (lid,)).fetchone() if isinstance(lid, int) and not isinstance(lid, bool) else None
    if row is None:
        raise ValueError('listing_id: no such car in this account')
    if row[0]:
        raise ValueError('Quotes apply to cars for sale; your own car keeps the premium you pay')
    if c.execute('SELECT count(*) FROM listing_quotes WHERE listing_id=?', (lid,)).fetchone()[0] >= MAX_PER_LISTING:
        raise ValueError(f'At most {MAX_PER_LISTING} quotes per car')
    amount, period = _num(d, 'premium_eur', True), d.get('period') or 'year'
    if amount <= 0:
        raise ValueError('premium_eur must be greater than 0')
    if period not in ('year', 'month'):
        raise ValueError('period must be year or month')
    annual = round(amount * (12 if period == 'month' else 1), 2)
    if annual > MAX_ANNUAL_EUR:
        raise ValueError(f'premium_eur: more than {MAX_ANNUAL_EUR} EUR per year is not a plausible premium')
    try:
        dt = datetime.date.fromisoformat(str(d.get('quote_date') or today))
    except ValueError:
        raise ValueError('quote_date must be a date like 2026-11-22')
    if dt > datetime.date.fromisoformat(today) or dt.year < 2000:
        raise ValueError('quote_date cannot be in the future')
    insurer, tariff, sf = _text(d, 'insurer', 80), _text(d, 'tariff', 80), _text(d, 'sf_class', 8)
    cover, ded = d.get('cover') or None, _num(d, 'deductible_eur')
    if cover not in (None, *COVERS):
        raise ValueError(f'cover must be one of {COVERS}')
    if ded is not None and not 0 <= ded <= 10000:
        raise ValueError('deductible_eur must be between 0 and 10000')
    profile = {k: v for k, v in (('cover', cover), ('deductible_eur', ded), ('sf_class', sf), ('entered_period', period)) if v is not None}
    src = c.execute("SELECT id FROM sources WHERE source_type='user_data' ORDER BY id LIMIT 1").fetchone()
    src = src[0] if src else agent_write(c, 'sources', None, {**SOURCE, 'accessed_date': today}, uid)
    qid = agent_write(c, 'listing_quotes', None, {
        'listing_id': lid, 'annual_premium_eur': annual, 'premium_status': 'QUOTE', 'insurer': insurer, 'tariff': tariff,
        'quote_date': dt.isoformat(), 'quote_profile': profile, 'source_id': src,
        'notes': 'Entered by the account holder' + (f' as {amount:.2f} EUR per month (annual = 12 x)' if period == 'month' else '')}, uid)
    extra = ', '.join(x for x in (insurer, tariff, cover, f'deductible {ded:g} EUR' if ded is not None else None, f'SF {sf}' if sf else None) if x)
    agent_write(c, 'listing_events', None, {'listing_id': lid, 'event_date': today, 'kind': 'user_data', 'source_id': src,
                'text': f'Insurance quote entered by the account: {annual:.2f} EUR per year, dated {dt.isoformat()}' + (f' ({extra})' if extra else '')}, uid)
    return qid
