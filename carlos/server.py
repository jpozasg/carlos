"""HTTP server: login and accounts, the read API for the UI, the parameters, the agent's write API."""
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import datetime, json, math, os, re, secrets, sqlite3
import markdown_export
from . import auth, config, research, research_requests as rq, research_units
from .agent import (AGENT_TABLES, Conflict, CODE_FORMATS, FIXED_CODES, RULES, SOURCE_REQUIRED, NotAllowed, NotFound, QuotaExceeded,
                    UnsupportedMediaType, agent_delete, agent_write, check_writable, linked_accounts, resolve_variant, row_owner, save_media,
                    storage_usage, table_columns)
from .costs import budget, check_budget, days_since, listing_detail, tco_rows
from .db import connect, params, rows
from .models import model_tree, variant_detail
from .ranking import CRITERIA, TASKS, check_answers, rank, ranking_state, weights_from, weights_from_answers
from .todo import todo

VIEW_COOKIE = "carlos_view"  # an admin viewing as another account (issue #142); set by the header switcher

# UI-editable parameters: type and whether they must be > 0 (required) or >= 0 (optional).
PARAM_NUM = {'annual_km': (int, True), 'ownership_years': (int, True), 'fuel_price_eur_l': (float, True),
             'diesel_price_eur_l': (float, False),
             'drivers_count': (int, False), 'driver_age': (int, False), 'insurance_deductible_eur': (float, False),
             'budget_ideal_eur': (float, False), 'budget_max_eur': (float, False),
             # electric cars (#121): € per kWh at home and in public, the share charged at home (0–100), a planned wallbox
             'electricity_home_eur_kwh': (float, False), 'electricity_public_eur_kwh': (float, False),
             'home_charging_pct': (int, False), 'wallbox_cost_eur': (float, False),
             'lease_rate_max_eur': (float, False),  # leasing (#127): the highest monthly rate
             'exclude_over_max': (int, False)}  # ranking (#169): 1/NULL = cars over the maximum budget are not ranked
PARAM_TEXT = {'fuel_price_date', 'diesel_price_date', 'postal_code', 'sf_class', 'insurance_cover', 'purchase_mode',
              'home_charging', 'electricity_home_date', 'electricity_public_date', 'acquisition_mode'}
PARAM_CODES = {'home_charging': config.HOME_CHARGING, 'acquisition_mode': config.ACQUISITION_MODES}
DATE_PARAMS = ('fuel_price_date', 'diesel_price_date', 'electricity_home_date', 'electricity_public_date')
# Parameters that change the calculation; GET /api/tco?<key>=<value> previews them without saving.
CALC_PARAMS = ('annual_km', 'ownership_years', 'fuel_price_eur_l', 'diesel_price_eur_l', 'budget_ideal_eur', 'budget_max_eur',
               'electricity_home_eur_kwh', 'electricity_public_eur_kwh', 'home_charging_pct', 'wallbox_cost_eur', 'lease_rate_max_eur')
STATIC_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
                '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2'}


MAX_JSON_BYTES = 1_000_000  # no JSON body of this API comes near it; stops unauthenticated memory floods


class Forbidden(Exception):
    pass


def ranked_rows(c, p):
    """Listings with costs, metrics and ranking; returns (rows, number of ranking candidates)."""
    out = tco_rows(c, p)
    f = {r['preference_key']: r['preference_value'] for r in rows(c, "SELECT preference_key, preference_value FROM project_preferences WHERE preference_key LIKE 'filter_%'")}
    return out, rank(out, weights_from(p), {**p, **f})


def detail(c, listing_id, p):
    return listing_detail(c, listing_id, p, ranked_rows(c, p)[0])


def export_markdown(c, user_id):
    """Dossiers of one account in dossiers/<user id>/ (every write of that account regenerates them).
    The costs and ranking of all listings are computed once and shared by every dossier."""
    p = params(c)
    rows = ranked_rows(c, p)[0]
    return markdown_export.export_all(c, config.MD_DIR / str(user_id), p, lambda c, lid, p: listing_detail(c, lid, p, rows))


def clean_params(data):
    """Validates and normalises parameters; raises ValueError with a readable message."""
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    out = {}
    for k, v in data.items():
        if k == 'ranking_weights':
            if v is not None and (not isinstance(v, dict) or set(v) - set(CRITERIA) or any(
                    isinstance(w, bool) or not isinstance(w, int) or not 0 <= w <= 5 for w in v.values())):
                raise ValueError('ranking_weights must map ranking criteria to integers 0–5 (null = from the answers)')
            out[k] = json.dumps(v) if v is not None else None
        elif k == 'ranking_answers':
            out[k] = json.dumps(check_answers(v))
        elif k in PARAM_TEXT:
            v = str(v).strip()[:100] if v is not None else ''
            if k in DATE_PARAMS and v:
                datetime.date.fromisoformat(v)
            if k in PARAM_CODES and v and v not in PARAM_CODES[k]:
                raise ValueError(f'{k} must be one of {PARAM_CODES[k]}')
            out[k] = v or None
        elif k in PARAM_NUM:
            typ, required = PARAM_NUM[k]
            if v is None or v == '':
                if required:
                    raise ValueError(f'{k} is required')
                out[k] = None; continue
            if isinstance(v, bool):
                raise ValueError(f'{k} must be numeric')
            f = float(v)
            if not math.isfinite(f):
                raise ValueError(f'{k} must be finite')
            if typ is int and not f.is_integer():
                raise ValueError(f'{k} must be an integer')
            if f < 0 or (required and f == 0):
                raise ValueError(f'{k} must be {"greater than 0" if required else "non-negative"}')
            if k == 'exclude_over_max' and f > 1:
                raise ValueError('exclude_over_max must be 0 or 1')
            if k == 'home_charging_pct' and f > 100:
                raise ValueError('home_charging_pct must be between 0 and 100')
            out[k] = typ(f)
        else:
            raise ValueError(f'Unknown parameter: {k}')
    return out


class Handler(BaseHTTPRequestHandler):
    user = None

    # ------------------------------------------------------------------ responses
    def send_json(self, obj, status=200, cookie=None):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers(); self.wfile.write(b)

    def send_file(self, path, ctype, cache=None):
        b = path.read_bytes()
        self.send_response(200); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
        if cache:
            self.send_header('Cache-Control', cache)
        self.end_headers(); self.wfile.write(b)

    def read_json(self):
        # Requiring JSON forces a CORS preflight in browsers: another site cannot write.
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            raise UnsupportedMediaType('Content-Type must be application/json')
        length = int(self.headers.get('Content-Length', '0'))
        if length > MAX_JSON_BYTES:
            raise ValueError(f'Body too large: {length} bytes, maximum {MAX_JSON_BYTES}')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        return data

    def session_cookie(self, value, clear=False):
        secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
        age = 0 if clear else auth.SESSION_DAYS * 86400
        return f'{auth.COOKIE}={value}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict{secure}'

    # ------------------------------------------------------------------ who is asking
    def identify(self, c):
        """Session cookie (browser) or Bearer token (agent). Sets self.user; returns it."""
        bearer = re.fullmatch(r'Bearer (\S+)', self.headers.get('Authorization', '') or '')
        self.request = None
        if bearer:
            self.user = auth.user_by_token(c, bearer[1])
            if self.user is None:  # a per-request token (issue #141): the research run of one claimed request
                self.request = rq.request_by_token(c, bearer[1])
                if self.request is not None:
                    self.user = c.execute('SELECT * FROM main.users WHERE id=? AND is_active=1', (self.request['owner_id'],)).fetchone()
                    if self.user is None:
                        raise Forbidden('The account of this request is no longer active')
                    return self.user
                if rq.worker_by_token(c, bearer[1]) is not None:
                    raise NotAllowed('A worker token only sends heartbeats, claims and finishes requests (/api/worker/)')
                raise Forbidden('Invalid token')
            if self.user['role'] != 'admin':  # agents work with an admin token; people sign in (issue #130)
                raise NotAllowed('Agent tokens work for admin accounts only; sign in to use the app')
            return self.user
        cookies = SimpleCookie(self.headers.get('Cookie', ''))
        raw = cookies[auth.COOKIE].value if auth.COOKIE in cookies else None
        self.user = auth.user_by_session(c, raw)
        return self.user

    def require(self, c, admin=False):
        """Logs the caller in and scopes the connection. An admin token may act for another account with the header
        X-Carlos-Account: <user id> (the shared research worker writing into the requester's account, issue #109);
        self.uid is then that account, self.user stays the admin (the change log records who wrote)."""
        if self.identify(c) is None:
            raise Forbidden('Login required')
        if self.request is not None:  # catalogue writes as the worker always did, listing data only in the requester's account
            p = urlsplit(self.path).path
            if admin or self.headers.get('X-Carlos-Account') or not (
                    self.command == 'GET' and not p.startswith('/api/worker/')
                    or self.command in ('POST', 'PATCH') and p.startswith('/api/agent/')):
                raise NotAllowed("A request token reads and writes research data for the requester's account only (no admin, settings, queue or deletes)")
            self.admin, self.uid = True, self.request['owner_id']
            auth.scope(c, self.uid, curator=True)
            return self.user
        if admin and self.user['role'] != 'admin':
            raise Forbidden('Admin only')
        self.admin, self.uid = self.user['role'] == 'admin', self.user['id']
        acting, p = self.headers.get('X-Carlos-Account'), urlsplit(self.path).path
        # "view as account" (issue #142): an admin's browser session carries the account in the carlos_view cookie, so
        # pages and photos (<img> sends no headers) show that account; never for admin pages, non-admins are ignored
        view = SimpleCookie(self.headers.get('Cookie', '')).get(VIEW_COOKIE)
        by_cookie = not acting and self.admin and not self.headers.get('Authorization') and view is not None and not p.startswith('/api/admin/')
        if by_cookie:
            acting = view.value
        if acting:
            if not self.admin or not (by_cookie or self.headers.get('Authorization')):
                raise NotAllowed('X-Carlos-Account needs an admin agent token')
            # research requests too: an admin agent may queue one for the account (issue #139); the viewing admin may
            # also tap checklists, decisions and photos (/api/ui/)
            if self.command != 'GET' and not (p.startswith('/api/agent/') or p == '/api/requests' or p.startswith('/api/requests/')
                                              or by_cookie and p.startswith('/api/ui/')):
                raise NotAllowed('Viewing as another account: reads, /api/agent/ and /api/ui/ writes and research requests only (never passwords, tokens or settings)')
            row = c.execute('SELECT id FROM main.users WHERE id=? AND is_active=1', (int(acting) if acting.isdigit() else -1,)).fetchone()
            if row is None and not by_cookie:
                raise ValueError(f'X-Carlos-Account={acting}: no such active account')
            if row is not None:  # a stale view cookie (account gone) falls back to the admin's own account
                self.uid = row[0]
        auth.scope(c, self.uid, curator=self.admin)
        return self.user

    # ------------------------------------------------------------------ routing
    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_PATCH(self):
        self.handle_request('PATCH')

    def do_DELETE(self):
        self.handle_request('DELETE')

    def handle_request(self, method):
        path = urlsplit(self.path).path
        if method == 'GET' and path in ('/', '/index.html'):
            self.send_file(config.STATIC / 'index.html', STATIC_TYPES['.html']); return
        if method == 'GET' and (path == '/login' or path.startswith('/invite/')):
            self.send_file(config.STATIC / 'auth.html', STATIC_TYPES['.html']); return
        static = re.fullmatch(r'/static/((?:[\w-]+/)*[\w-]+\.[a-z0-9]+)', path)
        if method == 'GET' and static:
            f = config.STATIC / static[1]
            ctype = STATIC_TYPES.get(f.suffix)
            if not f.is_file() or ctype is None:
                self.send_error(404); return
            self.send_file(f, ctype, 'no-cache'); return
        c = connect()
        try:
            if path.startswith('/api/auth/'):
                self.auth_api(c, method, path)
            elif method == 'GET' and path.startswith('/media/'):
                self.media(c, path)
            elif path.startswith('/api/'):
                self.api(c, method, path)
            else:
                self.send_error(404)
        except Forbidden as e:
            self.send_json({'error': str(e)}, 401)
        except UnsupportedMediaType as e:
            self.send_json({'error': str(e)}, 415)
        except NotAllowed as e:
            self.send_json({'error': str(e)}, 403)
        except NotFound as e:
            self.send_json({'error': str(e)}, 404)
        except QuotaExceeded as e:
            self.send_json({'error': str(e)}, 507)
        except Conflict as e:
            self.send_json(e.payload, 409)
        except (ValueError, sqlite3.Error) as e:  # JSONDecodeError is a ValueError; CHECK/FK violations are sqlite3.Error
            self.send_json({'error': str(e)}, 400)
        finally:
            c.close()

    # ------------------------------------------------------------------ login, invites
    def auth_api(self, c, method, path):
        invite = re.fullmatch(r'/api/auth/invite/([\w-]+)', path)
        if path == '/api/auth/me' and method == 'GET':
            u = self.identify(c)
            self.send_json(auth.public(u) if u else {'error': 'Login required'}, 200 if u else 401)
        elif path == '/api/auth/login' and method == 'POST':
            d = self.read_json()
            client = (self.headers.get('X-Forwarded-For') or self.client_address[0]).split(',')[0].strip()
            raw = auth.login(c, str(d.get('username') or ''), str(d.get('password') or ''), client)
            if raw is None:
                self.send_json({'error': 'Wrong username or password'}, 429 if auth.locked(client) else 401); return
            u = auth.user_by_session(c, raw)
            self.send_json(auth.public(u), cookie=self.session_cookie(raw))
        elif path == '/api/auth/logout' and method == 'POST':
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            auth.logout(c, cookies[auth.COOKIE].value if auth.COOKIE in cookies else None)
            self.send_json({'ok': True}, cookie=self.session_cookie('', clear=True))
        elif invite and method == 'GET':
            row = auth.invite_user(c, invite[1])
            self.send_json({'username': row['username']} if row else {'error': 'Invite link invalid or expired'}, 200 if row else 404)
        elif invite and method == 'POST':
            d = self.read_json()
            auth.check_new_password(d.get('password'))
            uid = auth.accept_invite(c, invite[1], d['password'])
            if uid is None:
                self.send_json({'error': 'Invite link invalid or expired'}, 404); return
            raw = auth.new_session(c, uid)
            self.send_json(auth.public(auth.user_by_session(c, raw)), 201, cookie=self.session_cookie(raw))
        else:
            self.send_json({'error': 'Endpoint not found'}, 404)

    def media(self, c, path):
        m = re.fullmatch(r'/media/(\d+)/([0-9a-f]{64}\.(?:jpg|png|webp))', path)
        self.require(c)
        f = config.MEDIA_DIR / m[1] / m[2] if m else None
        if not m or not f.is_file() or c.execute('SELECT 1 FROM listing_media WHERE file_path=?', (f'{m[1]}/{m[2]}',)).fetchone() is None:
            self.send_error(404); return
        self.send_file(f, {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}[f.suffix[1:]], 'private, max-age=31536000, immutable')

    # ------------------------------------------------------------------ the API (login required)
    def api(self, c, method, path):
        if path.startswith('/api/admin/'):
            self.admin_api(c, method, path); return
        bearer = re.fullmatch(r'Bearer (\S+)', self.headers.get('Authorization', '') or '')
        w = rq.worker_by_token(c, bearer[1]) if bearer and path.startswith('/api/worker/') else None
        if w is not None:
            self.worker_api(c, method, path, w); return
        user = self.require(c)
        uid = self.uid
        query = parse_qs(urlsplit(self.path).query)
        p = params(c)
        if method == 'GET':
            m = re.fullmatch(r'/api/listings/(\d+)', path)
            mv = re.fullmatch(r'/api/vehicles/(\d+)', path)
            if path == '/api/storage':
                self.send_json(storage_usage())
            elif path == '/api/vehicles':
                self.send_json(rows(c, 'SELECT v.*, g.make, g.model, g.name generation, e.code engine_code, e.fuel_type, '
                                       'e.displacement_cc, e.power_ps FROM vehicles v JOIN generations g ON g.id=v.generation_id '
                                       'JOIN engines e ON e.id=v.engine_id ORDER BY v.id'))
            elif mv:
                d = variant_detail(c, int(mv[1]))
                self.send_json(d if d else {'error': 'Vehicle not found'}, 200 if d else 404)
            elif path == '/api/models':
                self.send_json(model_tree(c))
            elif path == '/api/generations':
                self.send_json(rows(c, 'SELECT * FROM generations ORDER BY make, model, start_year, id'))
            elif path == '/api/engines':
                self.send_json(rows(c, 'SELECT * FROM engines ORDER BY id'))
            elif path == '/api/parameters':
                self.send_json(p)
            elif path == '/api/ui/check':
                self.send_json({'ok': True})
            elif path == '/api/ranking':
                self.send_json({**ranking_state(p), 'criteria': CRITERIA, 'tasks': TASKS})
            elif path == '/api/preferences':
                self.send_json(rows(c, 'SELECT * FROM project_preferences ORDER BY preference_key'))
            elif path in ('/api/tco', '/api/listings'):
                over = {k: v[-1] for k, v in query.items() if k in CALC_PARAMS}
                p = {**p, **clean_params(over)}  # preview: overrides are validated and never stored
                check_budget(p)
                out, n = ranked_rows(c, p)
                fuel_age = days_since(p['fuel_price_date'], datetime.date.today())
                self.send_json({'parameters': p, 'preview': bool(over), 'components': config.TCO_COMPONENTS, 'listings': out,
                                'budget': budget(p),
                                'ranking': {**ranking_state(p), 'criteria': CRITERIA, 'tasks': TASKS, 'candidates': n},
                                'fuel_price_stale': None if fuel_age is None else fuel_age > config.STALE_FUEL_PRICE_DAYS})
            elif m:
                d = detail(c, int(m[1]), p)
                self.send_json(d if d else {'error': 'Listing not found'}, 200 if d else 404)
            elif path == '/api/sources':
                self.send_json(rows(c, 'SELECT * FROM sources ORDER BY vehicle_id, engine_id, generation_id, id'))
            elif path == '/api/requests':
                self.send_json(rq.mine(c, uid))
            elif path == '/api/health':
                st = storage_usage()
                self.send_json({'integrity': c.execute('PRAGMA quick_check').fetchone()[0],
                                'schema_version': c.execute('PRAGMA user_version').fetchone()[0],
                                'listings': c.execute('SELECT count(*) FROM listings').fetchone()[0],
                                'storage_ratio': round(st['total_bytes'] / st['limit_bytes'], 4)})
            elif path in ('/api/todo', '/api/agent/todo'):
                self.send_json(todo(c, p, ranked_rows(c, p)[0]))
            elif path == '/api/agent/schema':
                self.send_json({'writable_tables': {t: table_columns(c, t) for t in sorted(AGENT_TABLES)},
                                'source_required_on_insert': sorted(SOURCE_REQUIRED),
                                'code_formats': {f'{t}.{col}': pat for (t, col), pat in CODE_FORMATS.items()},
                                'fixed_codes': FIXED_CODES, 'scoped_tables': list(config.SCOPED_TABLES),
                                'scope_columns': list(config.LEVEL_COLUMNS), 'rules': RULES,
                                'research_contract': research.published()})
            else:
                self.send_json({'error': 'Endpoint not found'}, 404)
            return
        # writes
        agent = re.fullmatch(r'/api/agent/([\w-]+)(?:/(\d+))?', path)
        ui = re.fullmatch(r'/api/ui/(inspection_items|listing_events|media|decision)(?:/(\d+))?', path)
        req = re.fullmatch(r'/api/(?:requests|worker/requests)/(\d+)', path)
        if (agent and agent[2] and method in ('PATCH', 'DELETE', 'POST') and self.admin and self.request is None
                and self.headers.get('Authorization') and not self.headers.get('X-Carlos-Account')):
            # the admin agent token reaches every account (issue #143): a row of another account is written as that account
            table, rid = ('listings', int(agent[2])) if agent[1] == 'media' else (agent[1], int(agent[2]))
            owner = row_owner(c, table, rid, None) if table in AGENT_TABLES and (method != 'POST' or agent[1] == 'media') else None
            if owner is not None and owner != uid:
                self.uid = uid = owner
                auth.scope(c, uid, curator=True)
        if path == '/api/requests' and method == 'POST':
            rid = rq.create(c, uid, self.read_json(), by=self.user['id'] if self.user['id'] != uid else None)
            self.send_json(next(r for r in rq.mine(c, uid) if r['id'] == rid), 201)
        elif req and path.startswith('/api/requests/') and method == 'PATCH':
            if self.read_json() != {'status': 'CANCELLED'}:
                raise ValueError('An account can only cancel a request: {"status": "CANCELLED"}')
            rq.cancel(c, uid, int(req[1]))
            self.send_json({'id': int(req[1]), 'status': 'CANCELLED'})
        elif path.startswith('/api/worker/'):  # the shared research worker (issue #113): admin tokens only
            if not self.admin:
                raise NotAllowed('The research queue is worked by the shared worker (an admin token)')
            if path == '/api/worker/claim' and method == 'POST':
                self.send_json({'request': rq.claim(c, self.read_json().get('worker'))})
            elif req and method == 'POST':
                self.send_json(rq.finish(c, int(req[1]), self.read_json(), missing=self.missing_items))
            else:
                self.send_json({'error': 'POST /api/worker/claim or POST /api/worker/requests/<id>'}, 404)
        elif path == '/api/parameters' and method == 'POST':
            data = clean_params(self.read_json())
            check_budget({**p, **data})
            if data:
                with c:
                    c.execute(f'UPDATE main.project_parameters SET {",".join(f"{k}=?" for k in data)} WHERE owner_id=?', [*data.values(), uid])
                export_markdown(c, uid)  # dossiers show the period and prices of the saved parameters
            self.send_json(params(c))
        elif path == '/api/preferences' and method == 'POST':
            # upsert {key: value}; null removes the key. Free text for agents to read (docs/data-model.md)
            d = self.read_json()
            if not isinstance(d, dict) or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,49}', str(k)) for k in d) or len(d) > 50:
                raise ValueError('Expected an object of preference_key (snake_case) → value')
            if 'insurance_worker_quotes' in d:  # consent for the worker's insurance quotes is the account's own decision
                if re.match(r'Bearer ', self.headers.get('Authorization', '') or ''):
                    raise NotAllowed('Consent to worker insurance quotes can only be changed by the account itself (Settings), never with a token')
                if d['insurance_worker_quotes'] not in (None, '', 'yes'):
                    raise ValueError("insurance_worker_quotes: 'yes' or empty (off)")
                if d['insurance_worker_quotes'] == 'yes':
                    d = {**d, 'insurance_worker_quotes': f'yes {datetime.date.today().isoformat()}'}
            with c:
                for k, v in d.items():
                    if v is None or str(v).strip() == '':
                        c.execute('DELETE FROM main.project_preferences WHERE owner_id=? AND preference_key=?', (uid, k))
                    else:
                        c.execute('INSERT INTO main.project_preferences (owner_id, preference_key, preference_value) VALUES (?,?,?) '
                                  'ON CONFLICT (owner_id, preference_key) DO UPDATE SET preference_value=excluded.preference_value',
                                  (uid, k, str(v).strip()[:1000]))
            self.send_json(rows(c, 'SELECT * FROM project_preferences ORDER BY preference_key'))
        elif path == '/api/account/password' and method == 'POST':
            d = self.read_json()
            if not auth.check_password(user['password_hash'], str(d.get('old') or '')):
                raise Forbidden('Wrong current password')
            auth.check_new_password(d.get('new'))
            auth.set_password(c, uid, d['new'])
            self.send_json({'ok': True})
        elif path == '/api/account/token' and method == 'POST':
            if self.user['role'] != 'admin':
                raise NotAllowed('Agent tokens are for admin accounts (the shared research worker); sign in to use the app')
            self.send_json({'token': auth.new_token(c, uid), 'note': 'Shown once; the previous token no longer works'}, 201)
        elif ui:
            result = self.ui_write(c, method, ui[1], int(ui[2]) if ui[2] else None, uid)
            export_markdown(c, uid)
            self.send_json(result, 201 if method == 'POST' else 200)
        elif agent and agent[1] == 'export-md' and method == 'POST':
            self.send_json({'written': [str(f.name) for f in export_markdown(c, uid)]})
        elif agent and agent[1] == 'media':
            if method != 'POST' or not agent[2]:
                self.send_json({'error': 'POST /api/agent/media/<listing_id>?url=...&snapshot_id=...'}, 405); return
            if not self.headers.get('Content-Type', '').startswith('image/'):
                raise UnsupportedMediaType('Content-Type must be image/jpeg, image/png or image/webp')
            length = int(self.headers.get('Content-Length', '0'))
            if length > config.MAX_IMAGE_BYTES:
                raise ValueError(f'Image is {length} bytes; maximum {config.MAX_IMAGE_BYTES}')
            row_id, created = save_media(c, int(agent[2]), self.rfile.read(length), query)
            if created:
                export_markdown(c, uid)
            self.send_json({'table': 'listing_media', 'id': row_id, 'created': created}, 201 if created else 200)
        elif agent and agent[1] in AGENT_TABLES and method == 'DELETE':
            if not agent[2]:
                self.send_json({'error': 'DELETE /api/agent/<table>/<id> deletes one row (ask the owner first)'}, 405); return
            if not self.admin:
                check_writable(c, agent[1], int(agent[2]), {})
            others = linked_accounts(c, agent[1], int(agent[2]))
            removed = agent_delete(c, agent[1], int(agent[2]), uid)
            self.export_all(c, uid, others)
            self.send_json({'table': agent[1], 'id': int(agent[2]), 'deleted': True, 'removed_children': removed})
        elif agent and agent[1] in AGENT_TABLES:
            data = self.read_json()
            if (method == 'PATCH') != bool(agent[2]):
                self.send_json({'error': 'POST /api/agent/<table> inserts; PATCH /api/agent/<table>/<id> updates'}, 405); return
            if not self.admin:
                check_writable(c, agent[1], int(agent[2]) if agent[2] else None, data)
            existing = resolve_variant(c, data, uid) if agent[1] == 'vehicles' and method == 'POST' else None
            if existing:  # the shared catalogue already has this HSN/TSN: reuse it (issue #109)
                export_markdown(c, uid)
                self.send_json({'table': 'vehicles', 'id': existing, 'existing': True}); return
            row_id = agent_write(c, agent[1], int(agent[2]) if agent[2] else None, data, uid, self.admin, user['id'])
            self.export_all(c, uid, linked_accounts(c, agent[1], row_id))
            self.send_json({'table': agent[1], 'id': row_id}, 201 if method == 'POST' else 200)
        else:
            self.send_json({'error': 'Endpoint not found'}, 404)

    def missing_items(self, owner_id, listing_id):
        """The contract items still MISSING on a listing (all but the owner-only insurance quote), graded as the to-do list does (#218)."""
        s = connect()
        try:
            auth.scope(s, owner_id, curator=True)
            row = next((r for r in ranked_rows(s, params(s))[0] if r['id'] == listing_id), None)
            if row is None:  # fail closed: a listing that cannot be graded is not done
                return sorted(research_units.UNIT_OF) + ['lst.insurance']
            return [i['id'] for i in row.get('research', []) if i.get('grade') == 'MISSING']  # callers choose what they need
        finally:
            s.close()

    def worker_api(self, c, method, path, w):
        """A registered worker (issue #141): heartbeat, claim (returns the per-request token), finish its own request."""
        req = re.fullmatch(r'/api/worker/requests/(\d+)', path)
        if path == '/api/worker/heartbeat' and method == 'POST':
            rq.heartbeat(c, w['id'], self.read_json())
            self.send_json({'ok': True})
        elif path == '/api/worker/claim' and method == 'POST':
            self.read_json()
            with c:
                c.execute("UPDATE main.workers SET last_seen=datetime('now') WHERE id=?", (w['id'],))
            self.send_json({'request': rq.claim(c, w['name'], w['id'])})
        elif req and method == 'POST':
            own = c.execute("SELECT 1 FROM main.research_requests WHERE id=? AND worker=? AND status='RUNNING'", (int(req[1]), w['name'])).fetchone()
            if own is None:
                raise NotAllowed('A worker finishes only the request it claimed')
            self.send_json(rq.finish(c, int(req[1]), self.read_json(), missing=self.missing_items))
        else:
            self.send_json({'error': 'POST /api/worker/heartbeat, /api/worker/claim or /api/worker/requests/<id>'}, 404)

    def export_all(self, c, uid, others=()):
        """Dossiers of this account and of every other account that shows the changed catalogue row.
        shortcut: regenerates every dossier of each account on each write; fine for dozens of listings."""
        export_markdown(c, uid)
        for o in set(others) - {uid}:
            s = connect(); auth.scope(s, o); export_markdown(s, o); s.close()

    def user_source(self, c, uid, today):
        """The account's 'User-provided data' source (created on first use)."""
        src = c.execute("SELECT id FROM sources WHERE source_type='user_reported' ORDER BY id LIMIT 1").fetchone()
        return src[0] if src else agent_write(c, 'sources', None, {'title': 'User-provided data', 'source_type': 'user_reported', 'accessed_date': today,
                                                                   'supports': 'Observations and decisions of the user', 'limitations': 'User statements'}, uid)

    def ui_write(self, c, method, kind, row_id, uid):
        """Viewing mode (phone): the few writes the UI does directly. Everything goes through agent_write."""
        today = datetime.date.today().isoformat()
        if kind == 'media':
            if method != 'POST' or row_id is None:
                raise NotFound('POST /api/ui/media/<listing_id>')
            if not self.headers.get('Content-Type', '').startswith('image/'):
                raise UnsupportedMediaType('Content-Type must be image/jpeg, image/png or image/webp')
            length = int(self.headers.get('Content-Length', '0'))
            if length > config.MAX_IMAGE_BYTES:
                raise ValueError(f'Image is {length} bytes; maximum {config.MAX_IMAGE_BYTES}')
            new_id, created = save_media(c, row_id, self.rfile.read(length), {'url': ['user upload (viewing mode)']})
            return {'table': 'listing_media', 'id': new_id, 'created': created}
        data = self.read_json()
        if kind == 'inspection_items' and method == 'PATCH' and row_id is not None:
            data = {k: v for k, v in data.items() if k in ('status', 'notes')}
            if 'status' in data:  # back to PENDING means not checked: no date
                data['checked_date'] = None if data['status'] == 'PENDING' else today
            new_id = agent_write(c, 'inspection_items', row_id, data, uid)
        elif kind == 'inspection_items' and method == 'POST':
            new_id = agent_write(c, 'inspection_items', None, {'listing_id': data.get('listing_id'), 'item': data.get('item')}, uid)
        elif kind == 'decision' and method == 'POST' and row_id is not None:
            # the owner's decision on a car: verdict + a 'decision' log entry; rejecting archives it out of the ranking
            d, reason = data.get('decision'), str(data.get('reason') or '').strip()[:300]
            verdicts = {'shortlist': 'Shortlisted by the owner', 'viewing': 'Viewing planned by the owner',
                        'reject': 'Rejected by the owner' + (f': {reason}' if reason else ''), 'reset': None}
            if d not in verdicts:
                raise ValueError('decision must be shortlist, viewing, reject or reset')
            row = c.execute('SELECT is_reference FROM listings WHERE id=?', (row_id,)).fetchone()
            if row is None or row[0]:
                raise ValueError('Decisions apply to cars for sale, not to your own car')
            agent_write(c, 'listings', row_id, {'verdict': verdicts[d], 'listing_status': 'WITHDRAWN' if d == 'reject' else 'UNDER REVIEW'}, uid)
            src = self.user_source(c, uid, today)
            new_id = agent_write(c, 'listing_events', None, {'listing_id': row_id, 'event_date': today, 'kind': 'decision',
                                                             'text': verdicts[d] or 'Decision reset by the owner: back under review', 'source_id': src}, uid)
        elif kind == 'listing_events' and method == 'POST':
            src = c.execute("SELECT id FROM sources WHERE source_type='user_reported' ORDER BY id LIMIT 1").fetchone()
            if src is None:
                src = [agent_write(c, 'sources', None, {'title': 'User-provided data', 'source_type': 'user_reported', 'accessed_date': today,
                                                        'supports': 'Observations by the user at viewings', 'limitations': 'User statements'}, uid)]
            new_id = agent_write(c, 'listing_events', None, {'listing_id': data.get('listing_id'), 'event_date': today,
                                                             'kind': 'viewing', 'text': data.get('text'), 'source_id': src[0]}, uid)
        else:
            raise NotFound('Unsupported viewing-mode request')
        return {'table': kind, 'id': new_id}

    # ------------------------------------------------------------------ admin: accounts
    def admin_api(self, c, method, path):
        admin = self.require(c, admin=True)
        m = re.fullmatch(r'/api/admin/users/(\d+)(/invite)?', path)
        wk = re.fullmatch(r'/api/admin/workers/(\d+)(/token)?', path)
        tbl = re.fullmatch(r'/api/admin/data/(\w+)', path)
        if tbl and method == 'GET':  # every account's rows of one table (the admin agent, issue #143)
            if tbl[1] not in AGENT_TABLES | {'users', 'catalogue_links', 'research_requests', 'workers', 'change_log'}:
                raise NotFound(f'No such table: {tbl[1]}')
            q = parse_qs(urlsplit(self.path).query)
            where = ' WHERE owner_id=?' if 'owner_id' in q and tbl[1] in auth.OWNED + auth._KNOW + ('research_requests',) else ''
            cols = '*' if tbl[1] not in ('users', 'workers') else ('id, username, role, is_active, created_at' if tbl[1] == 'users' else rq.WORKER_COLS)
            sql = f'SELECT {cols} FROM main.{tbl[1]}{where} ORDER BY id DESC LIMIT ?'
            self.send_json(rows(c, sql, ([int(q['owner_id'][-1])] if where else []) + [min(int(q.get('limit', ['1000'])[-1]), 5000)]))
        elif path == '/api/admin/workers' and method == 'GET':  # registered workers (issue #141)
            self.send_json(rq.workers(c))
        elif path == '/api/admin/workers' and method == 'POST':
            wid, raw = rq.new_worker(c, self.read_json().get('name'))
            self.send_json({'id': wid, 'token': raw, 'note': 'Shown once: give it to the worker as WORKER_TOKEN'}, 201)
        elif wk and wk[2] and method == 'POST':
            self.send_json({'id': int(wk[1]), 'token': rq.new_worker_token(c, int(wk[1])), 'note': 'Shown once; the previous token no longer works'})
        elif wk and not wk[2] and method == 'PATCH':
            d = self.read_json()
            if set(d) != {'is_active'}:
                raise ValueError('Only is_active (0/1) can be changed')
            rq.set_worker_active(c, int(wk[1]), d['is_active'])
            self.send_json(next(x for x in rq.workers(c) if x['id'] == int(wk[1])))
        elif path == '/api/admin/changes' and method == 'GET':  # recent writes, newest first, paged by ?before=<id> (issue #142)
            q = parse_qs(urlsplit(self.path).query)
            before, limit = int(q.get('before', ['0'])[-1] or 0), min(int(q.get('limit', ['50'])[-1]), 200)
            self.send_json(rows(c, "SELECT ch.id, ch.changed_at, ch.table_name, ch.row_id, ch.action, w.username AS writer, a.username AS account "
                                   "FROM main.change_log ch LEFT JOIN main.users w ON w.id=ch.user_id "
                                   "LEFT JOIN main.users a ON a.id=COALESCE(json_extract(ch.new_json, '$.owner_id'), "
                                   "(SELECT l.owner_id FROM main.listings l WHERE l.id=json_extract(ch.new_json, '$.listing_id'))) "
                                   "WHERE ? = 0 OR ch.id < ? ORDER BY ch.id DESC LIMIT ?", (before, before, limit)))
        elif path == '/api/admin/requests' and method == 'GET':
            self.send_json(rq.everything(c))
        elif path == '/api/admin/users' and method == 'GET':
            self.send_json([auth.public(u) for u in c.execute('SELECT * FROM main.users ORDER BY id')])
        elif path == '/api/admin/users' and method == 'POST':
            d = self.read_json()
            username = str(d.get('username') or '').strip()
            if not re.fullmatch(r'[\w.-]{2,40}', username):
                raise ValueError('username: 2–40 letters, digits, dots, dashes or underscores')
            role = d.get('role') or 'user'
            if role not in ('admin', 'user'):
                raise ValueError('role must be admin or user')
            uid = auth.create_user(c, username, role)
            self.send_json({'id': uid, 'username': username, 'invite': self.invite_url(auth.new_invite(c, uid, admin['id']))}, 201)
        elif m and m[2] and method == 'POST':
            if c.execute('SELECT 1 FROM main.users WHERE id=?', (int(m[1]),)).fetchone() is None:
                raise NotFound('No such user')
            self.send_json({'invite': self.invite_url(auth.new_invite(c, int(m[1]), admin['id']))}, 201)
        elif m and not m[2] and method == 'PATCH':
            d = self.read_json()
            if int(m[1]) == admin['id'] and (d.get('is_active') == 0 or d.get('role') == 'user'):
                raise ValueError('You cannot deactivate or demote your own account')
            if set(d) - {'is_active', 'role'} or d.get('is_active') not in (None, 0, 1) or d.get('role') not in (None, 'admin', 'user'):
                raise ValueError('Only is_active (0/1) and role (admin/user) can be changed')
            with c:
                if 'is_active' in d:
                    c.execute('UPDATE main.users SET is_active=? WHERE id=?', (d['is_active'], int(m[1])))
                    if d['is_active'] == 0:
                        c.execute('DELETE FROM main.sessions WHERE user_id=?', (int(m[1]),))
                if 'role' in d:
                    c.execute('UPDATE main.users SET role=? WHERE id=?', (d['role'], int(m[1])))
            u = c.execute('SELECT * FROM main.users WHERE id=?', (int(m[1]),)).fetchone()
            if u is None:
                raise NotFound('No such user')
            self.send_json(auth.public(u))
        else:
            self.send_json({'error': 'Endpoint not found'}, 404)

    def invite_url(self, raw):
        host = self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or f'{config.HOST}:{config.PORT}'
        proto = self.headers.get('X-Forwarded-Proto') or 'http'
        return f'{proto}://{host}/invite/{raw}'


def load_secret(name, generate):
    """A secret from the environment or .env. If missing or empty (e.g. .env copied from .env.example), one is
    generated and written to .env: filling the empty KEY= line in place, or appending it (file mode 600, out of Git)."""
    if os.environ.get(name):
        return os.environ[name]
    env = config.ENV
    lines = env.read_text().splitlines() if env.exists() else []
    for line in lines:
        if line.startswith(name + '=') and line.split('=', 1)[1].strip():
            return line.split('=', 1)[1].strip()
    value = generate()
    empty = next((i for i, line in enumerate(lines) if line.startswith(name + '=')), None)
    if empty is None:
        lines.append(f'{name}={value}')
    else:
        lines[empty] = f'{name}={value}'
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(env, 0o600)
    return value


def bootstrap(c):
    """First admin: the AGENT_TOKEN in .env is the admin's agent token until one is set in the UI; users without a
    password get a one-time invite link printed at startup."""
    admin = c.execute("SELECT * FROM main.users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
    if admin and admin['api_token_hash'] is None:
        token = load_secret('AGENT_TOKEN', lambda: secrets.token_urlsafe(32))
        with c:
            c.execute('UPDATE main.users SET api_token_hash=? WHERE id=?', (auth.digest(token), admin['id']))
    for u in c.execute('SELECT * FROM main.users WHERE password_hash IS NULL AND is_active=1').fetchall():
        print(f"Set the password of '{u['username']}' (valid {auth.INVITE_HOURS} h): "
              f'http://{config.HOST}:{config.PORT}/invite/{auth.new_invite(c, u["id"])}')


def main(argv=()):
    import migrate
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    migrate.run(config.DB)
    c = connect()
    bootstrap(c)
    if '--export-md' in argv:
        for (uid,) in c.execute('SELECT id FROM main.users').fetchall():
            s = connect(); auth.scope(s, uid); export_markdown(s, uid); s.close()
    c.close()
    if '--export-md' in argv:
        return
    print(f'Carlos running at http://{config.HOST}:{config.PORT} · data in {config.DATA_DIR}')
    ThreadingHTTPServer((config.HOST, config.PORT), Handler).serve_forever()
