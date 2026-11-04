"""Imports a listing capture (JSON) through the local agent API, in the order AGENTS.md prescribes.

The capture is produced by the agent while reading the listing in the user's own browser (Claude in Chrome) or from
a page the user saved. This script never contacts the listing site itself, except for plain downloads of the photo
URLs given in the capture; a refused download is reported and skipped, never retried around a block.

Usage:  python capture_listing.py capture.json [--dry-run] [--api http://127.0.0.1:8000]
Format: see CAPTURE_FORMAT below (also printed with --help).
"""
import argparse, json, os, sys, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 1_500_000  # same limit as app.py: capture the ~1024 px version, not the original
IMAGE_TYPES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png', b'RIFF': 'image/webp'}
# Honest client name: we do not imitate a browser to get past bot protection.
USER_AGENT = 'carlos/capture_listing.py (personal archive)'
# Optional listings columns copied as-is from the capture (seller claims stay in the *_claim columns).
LISTING_FIELDS = ('first_registration', 'seller', 'location', 'seller_address', 'accident_free_claim', 'owners_claim',
                  'hu_claim', 'service_history_claim', 'equipment', 'listing_date', 'notes')
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
              "service_history_claim": "...", "equipment": "...", "listing_date": "..."},
  "description": "verbatim seller text, original language",
  "attributes": {"Kilometerstand": "85.000 km", "...": "every feature exactly as shown"},
  "photos": [{"url": "https://img.../1024.jpg"}, {"file": "photos/1.jpg", "url": "original url"}],
  "source_quality": "A"                                              optional, default A (as for other listings)
}'''


class ApiError(Exception):
    pass


class Api:
    def __init__(self, base, token):
        self.base, self.token = base.rstrip('/'), token

    def call(self, method, path, body=None, raw=None, ctype='application/json'):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data, method=method,
                                     headers={'Authorization': f'Bearer {self.token}', 'Content-Type': ctype})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get('error')
            except ValueError:
                msg = e.reason
            if e.code == 401:
                msg = f'{msg}. The token in .env (or AGENT_TOKEN) is no longer valid: a new token created in Settings replaces it; paste the new one'
            raise ApiError(f'{method} {path}: HTTP {e.code}: {msg}') from None


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
        v = cap.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
            raise ValueError(f'{k} must be a positive number or null (unknown), never 0')
    if not isinstance(cap.get('attributes', {}), dict):
        raise ValueError('attributes must be an object with every feature exactly as shown')
    if not isinstance(cap.get('listing', {}), dict):
        raise ValueError('listing must be an object of listings columns')
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


def fmt(v, unit):
    return 'unknown' if v is None else f'{v:g} {unit}'


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
        actions = [] if dry_run else [r['inspection_action'] for r in api.call('GET', f'/api/listings/{lid}')['reliability']]
        for item in dict.fromkeys(a.strip() for a in actions if a and a.strip()):
            write('POST', '/api/agent/inspection_items', {'listing_id': lid, 'item': item, 'status': 'PENDING'}, 'checklist item')
        if dry_run:
            log('[dry-run] checklist items from the model reliability_items.inspection_action')

    # log; price/mileage changes update the listing and get their own entry
    photo_note = f'{archived} new photo(s) archived' + (f', {len(skipped)} skipped' if skipped else '')
    if existing is None:
        write('POST', '/api/agent/listing_events', {
            'listing_id': lid, 'event_date': day, 'kind': 'found', 'source_id': source_id,
            'text': f"Listing captured from {cap['platform']} via {method}: asking price {fmt(cap.get('price_eur'), 'EUR')}, "
                    f"{fmt(cap.get('mileage_km'), 'km')}; {photo_note}."}, 'found log entry')
    else:
        patch, changes = {'last_checked': day}, []
        for k, unit in (('price_eur', 'EUR'), ('mileage_km', 'km')):
            if cap.get(k) is not None and cap[k] != existing[k]:
                patch[k] = cap[k]; changes.append(f'{k} {fmt(existing[k], unit)} → {fmt(cap[k], unit)}')
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
    ap.add_argument('--api', default='http://127.0.0.1:8000')
    a = ap.parse_args(argv)
    cap = json.loads(a.capture.read_text(encoding='utf-8'))
    try:
        summary = import_capture(Api(a.api, load_token()), cap, a.capture.parent, a.dry_run)
    except (ValueError, ApiError) as e:
        raise SystemExit(f'Import failed: {e}')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
