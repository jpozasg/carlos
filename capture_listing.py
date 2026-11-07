"""Imports a listing capture (JSON) through the local agent API, in the order AGENTS.md prescribes.

The capture is produced by the agent while reading the listing in the user's own browser (Claude in Chrome) or from
a page the user saved. This script never contacts the listing site itself, except for plain downloads of the photo
URLs given in the capture; a refused download is reported and skipped, never retried around a block.

Usage:  python capture_listing.py capture.json [--dry-run] [--api http://127.0.0.1:8000]
Format: see CAPTURE_FORMAT below (also printed with --help).
"""
import argparse, json, os, re, sys, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode
from carlos import config  # NEW_CAR_MAX_KM: a new car is refused before any write (#165)

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 1_500_000  # same limit as app.py: capture the ~1024 px version, not the original
IMAGE_TYPES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png', b'RIFF': 'image/webp'}
# Honest client name: we do not imitate a browser to get past bot protection.
USER_AGENT = 'carlos/capture_listing.py (personal archive)'
# Optional listings columns copied as-is from the capture (seller claims stay in the *_claim columns).
LISTING_FIELDS = ('first_registration', 'seller', 'location', 'seller_address', 'accident_free_claim', 'owners_claim',
                  'hu_claim', 'service_history_claim', 'equipment', 'listing_date', 'notes', 'battery_soh_claim',
                  # structured facts for the ranking filters, the distance and the dossier (#169)
                  'seller_type', 'warranty', 'hu_until', 'service_history', 'accident_free', 'seller_rating', 'seller_reviews',
                  'postal_code')
# lease columns (#127) stay in the schema for listings captured before #165, but a capture never writes them
LEASE_FIELDS = ('lease_kind', 'lease_monthly_eur', 'lease_term_months', 'lease_km_per_year', 'lease_down_payment_eur',
                'lease_fees_eur', 'lease_extra_km_eur', 'lease_fewer_km_eur', 'lease_includes')
# electric cars (#125): the battery is the costliest part; every electric listing gets this checklist item
SOH_CHECK = ('Battery state of health: ask for a SoH certificate (method, date, km) no older than 3 months; ADAC guide '
             '>= 88 % at 100,000 km; check the remaining battery warranty (usually 8 years / 160,000 km / 70 %)')
CAPTURE_FORMAT = '''Capture JSON (null = unknown, never 0):
{
  "url": "https://suchen.mobile.de/fahrzeuge/details.html?id=...",   required
  "platform": "mobile.de",                                           required
  "listing_id": "54052815747808",                                    platform's own id
  "vehicle_id": 7,                                                   required: existing vehicles.id
  "captured_at": "2026-11-02T15:30",                                 required
  "capture_method": "Claude in Chrome",                              or "page saved by the user"
  "title": "...", "price_eur": 6990, "mileage_km": 85000,            listing facts
  "listing": {"first_registration": "2014-05", "seller": "...", "location": "...",
              "accident_free_claim": 1, "owners_claim": 2, "hu_claim": "05/2027",
              "service_history_claim": "...", "equipment": "...", "listing_date": "...",
              "battery_soh_claim": 94,                                electric: battery health % as claimed
              "seller_type": "DEALER", "warranty": 1, "hu_until": "2027-05",     DEALER/PRIVATE; 1/0; HU month
              "service_history": "YES", "accident_free": "CLAIMED",        YES/NO/CLAIMED as the ad states it
              "seller_rating": 4.8, "seller_reviews": 120,                   dealer's stars and review count (null: private / not shown)
              "postal_code": "97209"},                                      the car's postcode (for the distance)
  (second-hand purchases only, #165: no lease fields; a new car or a lease-only ad is refused)
  "description": "verbatim seller text, original language",
  "attributes": {"Kilometerstand": "85.000 km", "...": "every feature exactly as shown"},
  "photos": [{"url": "https://img.../1024.jpg"}, {"file": "photos/1.jpg", "url": "original url"}],
  "source_quality": "A"                                              optional, default A (as for other listings)
}'''


class ApiError(Exception):
    def __init__(self, message, code=None, body=None):
        super().__init__(message); self.code, self.body = code, body  # body: the parsed JSON answer (409 conflicts, #221)


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip('/'), token
        self.account = os.environ.get('CARLOS_ACCOUNT')  # the shared worker writes into the requester's account (issue #113)

    def call(self, method, path, body=None, raw=None, ctype='application/json'):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data, method=method,
                                     headers={'Authorization': f'Bearer {self.token}', 'Content-Type': ctype,
                                              **({'X-Carlos-Account': self.account} if self.account else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = None
            try:
                body = json.load(e)
                msg = body.get('error')
            except ValueError:
                msg = e.reason
            if e.code == 401:
                msg = f'{msg}. The token in .env (or AGENT_TOKEN) is no longer valid: a new token created in Settings replaces it; paste the new one'
            raise ApiError(f'{method} {path}: HTTP {e.code}: {msg}', e.code, body) from None


def load_token():
    if os.environ.get('AGENT_TOKEN'):
        return os.environ['AGENT_TOKEN']
    env = ROOT / '.env'
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith('AGENT_TOKEN=') and line.split('=', 1)[1].strip():
            return line.split('=', 1)[1].strip()
    raise SystemExit('AGENT_TOKEN not found (environment or .env); start app.py once to generate it')


def validate(cap):
    """Checks the capture before any write, so a bad file never leaves a half-imported listing."""
    if not isinstance(cap, dict):
        raise ValueError('The capture must be a JSON object')
    for k in ('url', 'platform', 'captured_at'):
        if not isinstance(cap.get(k), str) or not cap[k].strip():
            raise ValueError(f'{k} is required (text)')
    if not isinstance(cap.get('vehicle_id'), int) or isinstance(cap.get('vehicle_id'), bool):
        raise ValueError('vehicle_id is required: register the model in vehicles first')
    for k in ('price_eur', 'mileage_km'):
        v = cap.get(k)  # a price is never 0; 0 km is refused below as a new car (#165)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v == 0 and k == 'price_eur'):
            raise ValueError(f'{k} must be a positive number or null (unknown)')
    if not isinstance(cap.get('attributes', {}), dict):
        raise ValueError('attributes must be an object with every feature exactly as shown')
    if not isinstance(cap.get('listing', {}), dict):
        raise ValueError('listing must be an object of listings columns')
    soh = cap.get('listing', {}).get('battery_soh_claim')
    if soh is not None and (isinstance(soh, bool) or not isinstance(soh, (int, float)) or not 0 < soh <= 100):
        raise ValueError('battery_soh_claim must be a percentage (0–100] or null (unknown)')
    lst = cap.get('listing', {})
    for k, allowed in (('seller_type', ('DEALER', 'PRIVATE')), ('service_history', ('YES', 'NO', 'CLAIMED')),
                       ('accident_free', ('YES', 'NO', 'CLAIMED')), ('warranty', (0, 1))):
        if lst.get(k) is not None and (isinstance(lst[k], bool) or lst[k] not in allowed):
            raise ValueError(f'{k} must be one of {allowed} or null (not shown in the ad)')
    if lst.get('hu_until') is not None and not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', str(lst['hu_until'])):
        raise ValueError('hu_until must be YYYY-MM or null')
    if lst.get('postal_code') is not None and not re.fullmatch(r'\d{5}', str(lst['postal_code'])):
        raise ValueError('postal_code must be 5 digits or null')
    r_, n_ = lst.get('seller_rating'), lst.get('seller_reviews')
    if r_ is not None and (isinstance(r_, bool) or not isinstance(r_, (int, float)) or not 0 <= r_ <= 5):
        raise ValueError('seller_rating must be stars 0–5 or null (private seller / not shown)')
    if n_ is not None and (isinstance(n_, bool) or not isinstance(n_, int) or n_ < 0):
        raise ValueError('seller_reviews must be a count or null')
    # Carlos compares second-hand purchases only (issue #165): a used ad that also shows a lease offer is captured as a
    # purchase (leave the lease out); a lease-only ad and a new car are not captured
    if any(lst.get(k) is not None for k in LEASE_FIELDS):
        raise ValueError('lease fields are not captured: Carlos compares second-hand purchases only (#165); capture the '
                         'purchase price and leave the lease offer out (a lease-only ad is not supported)')
    if lst.get('first_registration') is None and cap.get('mileage_km') is not None and cap['mileage_km'] < config.NEW_CAR_MAX_KM:
        raise ValueError('a new car (no first registration, under '
                         f'{config.NEW_CAR_MAX_KM} km) is not captured: Carlos compares second-hand cars only (#165)')
    extra = set(cap.get('listing', {})) - set(LISTING_FIELDS)
    if extra:
        raise ValueError(f'listing fields not allowed: {sorted(extra)} (allowed: {LISTING_FIELDS})')
    photos = cap.get('photos', [])
    if not isinstance(photos, list) or any(not isinstance(p, dict) or not (p.get('url') or p.get('file')) for p in photos):
        raise ValueError('photos must be a list of {"url": ...} and/or {"file": ...}')


def find_existing(api, cap):
    """A listing already in the database: same URL, or same platform + platform id."""
    for row in api.call('GET', '/api/listings')['listings']:
        if row['is_reference']:
            continue
        if row['url'] == cap['url'] or (cap.get('listing_id') and row['listing_id'] == str(cap['listing_id'])
                                        and (row['platform'] or '').lower() == cap['platform'].lower()):
            return row
    return None


def read_photo(photo, base_dir):
    """Returns (bytes, mime) or (None, reason). Local files win over URLs."""
    try:
        if photo.get('file'):
            body = (base_dir / photo['file']).read_bytes()
        else:
            req = urllib.request.Request(photo['url'], headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return None, f'download refused (HTTP {e.code}); not retried'
    except (OSError, ValueError) as e:
        return None, f'could not read: {e}'
    if len(body) > MAX_IMAGE_BYTES:
        return None, f'larger than {MAX_IMAGE_BYTES} bytes; capture the ~1024 px version'
    mime = next((m for magic, m in IMAGE_TYPES.items() if body.startswith(magic)), None)
    if mime is None or (mime == 'image/webp' and body[8:12] != b'WEBP'):
        return None, 'not a JPEG, PNG or WebP image'
    return body, mime


def checklist_items(reliability_rows, existing):
    """(item text, reliability_item_id) for the weak points that have no checklist item yet. One item per weak point,
    keyed by reliability_item_id; a recall's item names the recall so each recall has its own check (issue #54)."""
    linked = {i.get('reliability_item_id') for i in existing}
    texts = {i['item'] for i in existing}
    out = []
    for r in sorted(reliability_rows, key=lambda r: r['id']):
        action = (r.get('inspection_action') or '').strip()
        if not action or r['id'] in linked:
            continue
        text = f"Recall: {r['component']} — {action}" if r.get('is_recall') else action
        if text in texts and not r.get('is_recall'):
            continue  # the same check already on the list for another weak point
        out.append((text, r['id']))
        texts.add(text)
    return out


def fmt(v, unit):
    return 'unknown' if v is None else f'{v:g} {unit}'


def lease_txt(lst):
    """The lease offer for the log, as the ad states it (#127)."""
    if lst.get('lease_monthly_eur') is None:
        return ''
    return (f"; lease {fmt(lst['lease_monthly_eur'], 'EUR/month')}, {fmt(lst.get('lease_term_months'), 'months')}, "
            f"{fmt(lst.get('lease_km_per_year'), 'km/year')}, down payment {fmt(lst.get('lease_down_payment_eur'), 'EUR')}")


def import_capture(api, cap, base_dir=Path('.'), dry_run=False, log=print):
    """Runs the import and returns a summary. With dry_run, only reads and logs the planned writes."""
    validate(cap)
    day = cap['captured_at'][:10]
    method = cap.get('capture_method') or 'browser capture'
    photos = cap.get('photos', [])
    existing = find_existing(api, cap)
    ids = {'listing': existing and existing['id'], 'new': existing is None}

    def write(http, path, body, what):
        log(f'{"[dry-run] " if dry_run else ""}{http} {path}: {what}')
        return None if dry_run else api.call(http, path, body)['id']

    # 1) source (one per listing; re-captures reuse it) → 2) the model must already exist → 3) listing
    if existing is None:
        if not any(v['id'] == cap['vehicle_id'] for v in api.call('GET', '/api/vehicles')):
            raise ValueError(f"vehicles id={cap['vehicle_id']} does not exist: register the model first")
        source_id = write('POST', '/api/agent/sources', {
            'vehicle_id': cap['vehicle_id'], 'title': f"{cap.get('title') or 'Listing'} listing on {cap['platform']}",
            'url': cap['url'], 'source_type': 'listing', 'quality': cap.get('source_quality', 'A'), 'accessed_date': day,
            'supports': 'Asking price, mileage, registration, seller, equipment and seller claims as published',
            'limitations': 'Asking price, not a transaction. Claims about accidents, owners, HU and history are not '
                           'an independent inspection.'}, 'listing source')
        ids['listing'] = write('POST', '/api/agent/listings', {
            'vehicle_id': cap['vehicle_id'], 'source_id': source_id, 'platform': cap['platform'],
            'listing_id': None if cap.get('listing_id') is None else str(cap['listing_id']), 'url': cap['url'],
            'price_eur': cap.get('price_eur'), 'mileage_km': cap.get('mileage_km'), 'last_checked': day,
            'listing_status': 'UNDER REVIEW', 'is_reference': 0, **cap.get('listing', {})}, 'new listing')
    else:
        source_id = existing['source_id']
        if source_id is None:
            raise ValueError(f"listing {existing['id']} has no source_id; register its source first")
        log(f"Existing listing {existing['id']} matched ({existing['url']})")
    lid = ids['listing']

    # 4) capture (never overwrites older ones) and photos
    snapshot_id = write('POST', '/api/agent/listing_snapshots', {
        'listing_id': lid, 'captured_at': cap['captured_at'], 'source_id': source_id, 'title': cap.get('title'),
        'price_eur': cap.get('price_eur'), 'mileage_km': cap.get('mileage_km'), 'description': cap.get('description'),
        'attributes_json': cap.get('attributes') or None,
        'notes': f"Capture of the {cap['platform']} listing via {method}; {len(photos)} photo(s) listed."}, 'capture')
    archived, skipped = 0, []
    for p in photos:
        if dry_run:
            log(f"[dry-run] POST /api/agent/media/{lid}: photo {p.get('file') or p['url']}"); continue
        body, info = read_photo(p, base_dir)
        if body is None:
            skipped.append(f"{p.get('file') or p['url']}: {info}"); log(f'Photo skipped: {skipped[-1]}'); continue
        q = urlencode({'url': p.get('url') or f"file:{p['file']}", 'snapshot_id': snapshot_id})
        r = api.call('POST', f'/api/agent/media/{lid}?{q}', raw=body, ctype=info)
        archived += r['created']

    # checklist from the model's reliability items (new listings only; re-captures keep the user's ticks)
    if existing is None:
        d = {} if dry_run else api.call('GET', f'/api/listings/{lid}')
        for item, rel_id in checklist_items(d.get('reliability', []), []) + ([(SOH_CHECK, None)] if d.get('fuel_type') == 'Electric' else []):
            write('POST', '/api/agent/inspection_items', {'listing_id': lid, 'item': item, 'status': 'PENDING',
                                                          'reliability_item_id': rel_id}, 'checklist item')
        if dry_run:
            log('[dry-run] checklist items from the model reliability_items.inspection_action')

    # log; price/mileage changes update the listing and get their own entry
    photo_note = f'{archived} new photo(s) archived' + (f', {len(skipped)} skipped' if skipped else '')
    if existing is None:
        write('POST', '/api/agent/listing_events', {
            'listing_id': lid, 'event_date': day, 'kind': 'found', 'source_id': source_id,
            'text': f"Listing captured from {cap['platform']} via {method}: asking price {fmt(cap.get('price_eur'), 'EUR')}, "
                    f"{fmt(cap.get('mileage_km'), 'km')}{lease_txt(cap.get('listing', {}))}; {photo_note}."}, 'found log entry')
    else:
        patch, changes = {'last_checked': day}, []
        if existing.get('vehicle_id') != cap['vehicle_id']:  # re-research after the reset (#194) attaches the new variant
            patch['vehicle_id'] = cap['vehicle_id']
        new = {**cap.get('listing', {}), 'price_eur': cap.get('price_eur'), 'mileage_km': cap.get('mileage_km')}
        for k, unit in (('price_eur', 'EUR'), ('mileage_km', 'km'), ('lease_monthly_eur', 'EUR/month')):
            if new.get(k) is not None and new[k] != existing.get(k):
                patch[k] = new[k]; changes.append(f'{k} {fmt(existing.get(k), unit)} → {fmt(new[k], unit)}')
        write('PATCH', f'/api/agent/listings/{lid}', patch, ', '.join(changes) or 'last_checked')
        if changes:
            write('POST', '/api/agent/listing_events', {'listing_id': lid, 'event_date': day, 'kind': 'price',
                  'source_id': source_id, 'text': f"Listing changed on {cap['platform']}: {'; '.join(changes)}."}, 'price log entry')
        write('POST', '/api/agent/listing_events', {
            'listing_id': lid, 'event_date': day, 'kind': 'verification', 'source_id': source_id,
            'text': f"Listing re-captured on {cap['platform']} via {method}; still online; {photo_note}."}, 'verification log entry')
    return {'listing_id': lid, 'new_listing': existing is None, 'snapshot_id': snapshot_id,
            'photos_archived': archived, 'photos_skipped': skipped, 'dry_run': dry_run}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0], epilog=CAPTURE_FORMAT,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('capture', type=Path)
    ap.add_argument('--dry-run', action='store_true', help='show the planned writes without writing')
    ap.add_argument('--api', default=os.environ.get('CAR_API', 'http://127.0.0.1:8000'))
    a = ap.parse_args(argv)
    cap = json.loads(a.capture.read_text(encoding='utf-8'))
    try:
        summary = import_capture(Api(a.api, load_token()), cap, a.capture.parent, a.dry_run)
    except (ValueError, ApiError) as e:
        raise SystemExit(f'Import failed: {e}')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
