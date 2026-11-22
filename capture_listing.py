"""Imports a listing capture (JSON) through the local agent API, in the order AGENTS.md prescribes.

The capture is produced by the agent while reading the listing in the user's own browser (Claude in Chrome) or from
a page the user saved. This script never contacts the listing site itself, except for plain downloads of the photo
URLs given in the capture; a refused download is reported and skipped, never retried around a block.

Usage:  python capture_listing.py capture.json [--dry-run] [--api http://127.0.0.1:8000]
Format: see CAPTURE_FORMAT below (also printed with --help).
"""
import argparse, ipaddress, json, os, re, socket, sys, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit
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
                  'postal_code', 'hsn', 'tsn')  # hsn/tsn: when the ad's text or attributes state them (#313)
# a capture never writes the lease columns (#165): a used ad that also shows a lease is captured as a purchase, a lease-only ad is refused
LEASE_FIELDS = ('lease_kind', 'lease_monthly_eur', 'lease_term_months', 'lease_km_per_year', 'lease_down_payment_eur',
                'lease_fees_eur', 'lease_extra_km_eur', 'lease_fewer_km_eur', 'lease_includes')
# electric cars (#125): the battery is the costliest part; every electric listing gets this checklist item
SOH_CHECK = ('Battery state of health: ask for a SoH certificate (method, date, km) no older than 3 months; ADAC guide '
             '>= 88 % at 100,000 km; check the remaining battery warranty (usually 8 years / 160,000 km / 70 %)')
CAPTURE_FORMAT = '''Capture JSON (null = unknown, never 0):
{
  "url": "https://suchen.mobile.de/fahrzeuge/details.html?id=...",   the ad; omit it for a car the owner describes (no link, #375)
  "platform": "mobile.de",                                           optional without a url (default "manual")
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
    if 'url' not in cap or cap['url'] is None:  # a car the owner describes without a link (#375): no ad to match or re-read
        cap['url'] = None  # an empty text '' is still refused below
        cap.setdefault('platform', 'manual'); cap.setdefault('capture_method', 'entered by the owner')
    for k in ('platform', 'captured_at') + (() if cap['url'] is None else ('url',)):
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
        if (cap['url'] and row['url'] == cap['url']) or (cap.get('listing_id') and row['listing_id'] == str(cap['listing_id'])
                                        and (row['platform'] or '').lower() == cap['platform'].lower()):
            return row
    return None


def resolve_host(host):
    """The addresses a host name resolves to (injectable in tests)."""
    return [ai[4][0] for ai in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)]


def check_photo_url(url, resolver=resolve_host):
    """ValueError unless `url` is a plain http(s) link whose host resolves only to public addresses: a capture is
    text from a web page, and must not make this machine fetch its LAN, loopback or cloud-metadata addresses (the
    image would then be stored in the requester's account, review N7). shortcut: the name is resolved here and again
    by urllib, so DNS rebinding in between is not closed; acceptable for an owner-run helper reading photo links."""
    u = urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise ValueError('photo links must be plain http(s) URLs without credentials')
    for addr in resolver(u.hostname):
        ip = ipaddress.ip_address(addr.split('%')[0])
        if not (getattr(ip, 'ipv4_mapped', None) or ip).is_global:
            raise ValueError('photo host resolves to a private or reserved address')


class _GuardRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, resolver):
        self.resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_photo_url(newurl, self.resolver)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_photo(photo, base_dir, resolver=resolve_host):
    """Returns (bytes, mime) or (None, reason). Local files win over URLs; a file must lie inside `base_dir` (no
    `..`, no absolute path, no symlink out of it); a URL must be public (check_photo_url), also after redirects."""
    try:
        if photo.get('file'):
            base = base_dir.resolve()
            f = (base / photo['file']).resolve()
            if not f.is_relative_to(base):
                return None, 'file is outside the capture folder'
            body = f.read_bytes()
        else:
            check_photo_url(photo['url'], resolver)
            req = urllib.request.Request(photo['url'], headers={'User-Agent': USER_AGENT})
            with urllib.request.build_opener(_GuardRedirects(resolver)).open(req, timeout=30) as resp:
                body = resp.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return None, f'download refused (HTTP {e.code}); not retried'
    except (OSError, ValueError, TypeError) as e:
        return None, f'could not read: {e}'
    if len(body) > MAX_IMAGE_BYTES:
        return None, f'larger than {MAX_IMAGE_BYTES} bytes; capture the ~1024 px version'
    mime = next((m for magic, m in IMAGE_TYPES.items() if body.startswith(magic)), None)
    if mime is None or (mime == 'image/webp' and body[8:12] != b'WEBP'):
        return None, 'not a JPEG, PNG or WebP image'
    return body, mime


LINK_COLUMNS = ('reliability_item_id', 'fault_id', 'recall_id')


def checklist_items(detail, existing):
    """(item text, link) for the weak points that have no checklist item yet; link = {column: id} (reliability_item_id,
    fault_id or recall_id). `detail` is the listing detail: its reliability items, faults (fault_plan) and recalls (#223).
    A reliability item and a fault get their `inspection_action` (none, no item); a recall row always gets an item naming
    the recall (issue #54); one item per weak point; the same check text is not listed twice. The VIN recall check
    (config.VIN_RECALL_CHECK, with the KBA link) is added once to every list (#357)."""
    linked = {(c, i[c]) for i in existing if not i.get('archived') for c in LINK_COLUMNS if i.get(c) is not None}
    texts = {i['item'].strip() for i in existing if not i.get('archived')}
    out = []
    weak = [('reliability_item_id', r) for r in sorted(detail.get('reliability', []), key=lambda r: r['id'])] + \
           [('fault_id', f) for f in sorted(detail.get('fault_plan', []), key=lambda f: f['id'])] + \
           [('recall_id', r) for r in sorted(detail.get('recalls', []), key=lambda r: r['id'])]
    for col, r in weak:
        if (col, r['id']) in linked:
            continue
        action = (r.get('inspection_action') or '').strip()
        recall = col == 'recall_id' or bool(r.get('is_recall'))
        if col == 'recall_id':
            text = f"Recall {r['code']}: {r['defect']} — dealer VIN check that it was done"
        elif recall:
            text = f"Recall: {r['component']} — {action or 'dealer VIN check that it was done'}"
        elif not action:
            continue
        else:
            text = action
        if text in texts and not recall:
            continue  # the same check already on the list for another weak point
        out.append((text, {col: r['id']}))
        texts.add(text)
    if config.VIN_RECALL_CHECK not in texts:  # fixed for every listing, whatever recalls are researched (#357)
        out.append((config.VIN_RECALL_CHECK, {}))
    return out


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
                           'an independent inspection.'} if cap['url'] else {
            'vehicle_id': cap['vehicle_id'], 'title': f"{cap.get('title') or 'Car'} described by the owner",
            'source_type': 'user_data', 'quality': cap.get('source_quality', 'D'), 'accessed_date': day,
            'supports': 'Asking price, mileage, registration and equipment as the owner states them (no ad link)',
            'limitations': 'Told by the owner, not checked against an ad or documents; the price is an asking price, not a transaction.'},
            'listing source')
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
        for item, link in checklist_items(d, []) + ([(SOH_CHECK, {})] if d.get('fuel_type') == 'Electric' else []):
            write('POST', '/api/agent/inspection_items', {'listing_id': lid, 'item': item, 'status': 'PENDING', **link}, 'checklist item')
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
        if existing.get('vehicle_id') != cap['vehicle_id']:  # re-research after the reset (#194) attaches the new variant
            patch['vehicle_id'] = cap['vehicle_id']
        new = {**cap.get('listing', {}), 'price_eur': cap.get('price_eur'), 'mileage_km': cap.get('mileage_km')}
        for k, unit in (('price_eur', 'EUR'), ('mileage_km', 'km')):
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
