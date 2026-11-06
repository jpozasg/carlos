"""Distance to view a car (#169): straight-line km between two German postcodes from a bundled table (plz_de.csv, one
point per postcode = the mean of its boundary vertices; data © OpenStreetMap contributors, ODbL 1.0). Offline: no
postcode leaves the machine."""
import functools, math
from pathlib import Path

TABLE = Path(__file__).with_name('plz_de.csv')


@functools.lru_cache(maxsize=1)
def points():
    out = {}
    for line in TABLE.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#'):
            pc, la, lo = line.split(',')
            out[pc] = (float(la), float(lo))
    return out


def km(a, b):
    """Great-circle km between two postcodes; None when either is unknown. shortcut: straight line, not road distance
    (roads add roughly 20–30 %); upgrade only if a free offline routing source appears."""
    p, q = points().get((a or '').strip()), points().get((b or '').strip())
    if not p or not q:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (*p, *q))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)
