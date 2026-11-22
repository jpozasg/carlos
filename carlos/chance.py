"""The owner's own chance that a fault fixed on one of the account's cars fails again within the owner's period (issue #379).
It is kept on that car's DONE history row, so the shared fault row and every other car keep their figures; costs.fault_plan
reads it. Each set or cleared figure is logged as user data."""
from .agent import NotFound, agent_write
from .quotes import _text


def owner_chance(c, uid, row_id, d, source, today):
    """Sets, or with null clears, the chance on one DONE fault row of this account. `source` () returns the account's
    user-data source id and is called only once the figure is valid."""
    if not isinstance(d, dict) or not d or not set(d) <= {'owner_probability', 'owner_reason'}:
        raise ValueError('Expected {"owner_probability": 0..1 or null, "owner_reason": text}')
    p = d.get('owner_probability')
    if p is not None and (isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1):  # also refuses nan
        raise ValueError('owner_probability must be a number from 0 to 1, or null when unknown (never 0 by default)')
    reason = _text(d, 'owner_reason', 300)
    if p is None and reason:
        raise ValueError('owner_reason is kept only with owner_probability')
    if p is not None and not reason:
        raise ValueError('owner_reason is required with owner_probability: say why this car is likely to fail again')
    h = c.execute('SELECT listing_id, fault_id, status, item FROM listing_history_all WHERE id=?', (row_id,)).fetchone()
    if h is None:
        raise NotFound(f'listing_history id={row_id} does not exist')
    if h['status'] != 'DONE' or h['fault_id'] is None:
        raise ValueError('The chance applies to a DONE repair of a fault (a history row with status DONE and a fault)')
    agent_write(c, 'listing_history', row_id, {'owner_probability': p, 'owner_reason': reason}, uid)
    text = (f"Owner's chance that '{h['item']}' fails again within the ownership period: {p:.0%} ({reason})" if p is not None
            else f"Owner's chance for '{h['item']}' cleared: the fault's own curve applies again")
    agent_write(c, 'listing_events', None, {'listing_id': h['listing_id'], 'event_date': today, 'kind': 'user_data',
                                            'source_id': source(), 'text': text}, uid)
    return row_id
