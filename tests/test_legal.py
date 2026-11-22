"""The AGPL source link on every page, /privacy and /impressum, an account's JSON export and the admin's erasure. Runs on
the synthetic database of tests/fixture.py and a throwaway data directory: no real data, no personal data.
Run: python -m unittest tests.test_legal -v"""
import json, sqlite3, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from carlos import auth, config, db, pages, server
from tests import fixture as fx
from tests.fixture import CAR_A, TODAY

SRC = 'https://src.example.test/carlos'


class LegalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.srv.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        config.DATA_DIR, config.DB, config.MD_DIR, config.MEDIA_DIR = d, d / 'cars.sqlite', d / 'dossiers', d / 'media'
        fx.build(config.DB)
        auth.FAILS.clear()
        patch = mock.patch.object(config, 'SOURCE_URL', SRC)
        patch.start(); self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    # --- helpers
    def req(self, method, path, body=None, token=None, cookie=None, raw=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        if cookie:
            headers['Cookie'] = f'{auth.COOKIE}={cookie}'
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            resp = urllib.request.urlopen(r)
            text = resp.read()
            return resp.status, (json.loads(text) if text[:1] in (b'{', b'[') else text)
        except urllib.error.HTTPError as e:
            text = e.read(); e.close()
            return e.code, (json.loads(text) if text[:1] == b'{' else text)

    def login(self, username, password):
        r = urllib.request.Request(self.base + '/api/auth/login', json.dumps({'username': username, 'password': password}).encode(),
                                   {'Content-Type': 'application/json'}, method='POST')
        return urllib.request.urlopen(r).headers.get('Set-Cookie').split(';')[0].split('=', 1)[1]

    def sql(self, q, args=()):
        c = sqlite3.connect(config.DB)
        try:
            return c.execute(q, args).fetchall()
        finally:
            c.close()

    def account(self, name, password='a long password'):
        """A second, ordinary account with one car for sale (a listing, a viewing note and a source of its own)."""
        c = db.connect()
        try:
            uid = auth.create_user(c, name, 'user')
            c.execute('UPDATE main.users SET password_hash=? WHERE id=?', (auth.hash_password(password), uid))
            c.execute("INSERT INTO sources (owner_id, title, source_type, accessed_date) VALUES (?,?,?,?)", (uid, f'{name} source', 'listing', TODAY))
            sid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO listings (owner_id, vehicle_id, source_id, platform, listing_id, url, price_eur, mileage_km, listing_status, is_reference, last_checked) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uid, fx.V_A, sid, 'Test', f'{name}-1', f'https://example.test/{name}', 5000, 80000, 'UNDER REVIEW', 0, TODAY))
            lid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute("INSERT INTO listing_events (listing_id, event_date, kind, text, source_id) VALUES (?,?,?,?,?)", (lid, TODAY, 'viewing', f'{name} note', sid))
            c.commit()
        finally:
            c.close()
        return uid, lid, sid

    # --- 1. the source link (AGPL-3.0 section 13) on every page
    def test_every_page_links_to_the_source_1(self):
        for path in ('/login', '/invite/abc', '/privacy', '/impressum'):
            st, body = self.req('GET', path)
            self.assertEqual(st, 200, path)
            self.assertIn(f'href="{SRC}"'.encode(), body, path)
            self.assertNotIn(b'{{SOURCE_URL}}', body, path)
        st, body = self.req('GET', '/')  # the app's footer is drawn by app.js from this meta tag
        self.assertIn(f'<meta name="carlos-source" content="{SRC}">'.encode(), body)
        self.assertNotIn(b'{{SOURCE_URL}}', body)

    def test_source_url_is_escaped_in_the_page_1(self):
        with mock.patch.object(config, 'SOURCE_URL', 'https://x.example/"><script>'):
            self.assertNotIn(b'<script>', pages.page('auth.html'))

    # --- 2. /privacy and /impressum
    def test_privacy_page_states_the_processors_and_rights_2(self):
        body = self.req('GET', '/privacy')[1].decode()
        for text in ('Anthropic', 'Administrators of this instance', 'Download my data', 'scrypt', '60 days', 'supervisory authority'):
            self.assertIn(text, body)
        self.assertNotIn('<script', body)  # no script on the privacy page

    def test_imprint_is_a_placeholder_until_the_operator_writes_it_2(self):
        body = self.req('GET', '/impressum')[1].decode()
        self.assertIn('id="imp-missing"', body)
        self.assertNotIn('<pre class="imprint">', body)

    def test_imprint_comes_from_the_data_directory_and_is_escaped_2(self):
        (config.DATA_DIR / 'impressum.txt').write_text('Operator Example\nSample Street 1\n<script>alert(1)</script>', encoding='utf-8')
        body = self.req('GET', '/impressum')[1].decode()
        self.assertIn('<pre class="imprint">Operator Example\nSample Street 1\n&lt;script&gt;alert(1)&lt;/script&gt;</pre>', body)
        self.assertNotIn('id="imp-missing"', body)
        self.assertNotIn('<script>alert', body)

    def test_imprint_text_is_cut_at_the_limit_2(self):
        (config.DATA_DIR / 'impressum.txt').write_text('Q' * (pages.IMPRINT_MAX_BYTES + 5000), encoding='utf-8')
        self.assertEqual(pages.imprint().count(b'Q'), pages.IMPRINT_MAX_BYTES)

    def test_repository_has_no_imprint_text_3(self):
        # the operator's text is never in the repository: only the template with its placeholder is
        template = (config.STATIC / 'impressum.html').read_text(encoding='utf-8')
        self.assertIn('{{IMPRINT}}', template)
        self.assertFalse((config.ROOT / 'static' / 'impressum.txt').exists())

    # --- 3. the account's own export
    def test_export_holds_only_the_accounts_own_rows_3(self):
        uid, lid, sid = self.account('maria')
        cookie = self.login('maria', 'a long password')
        st, doc = self.req('GET', '/api/account/export', cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(doc['account'], {'id': uid, 'username': 'maria', 'role': 'user', 'created_at': doc['account']['created_at']})
        self.assertEqual([r['id'] for r in doc['tables']['listings']], [lid])
        self.assertEqual([r['id'] for r in doc['tables']['sources']], [sid])
        self.assertEqual([r['text'] for r in doc['tables']['listing_events']], ['maria note'])
        self.assertNotIn(CAR_A, [r['id'] for r in doc['tables']['listings']])  # the admin's car is not in it
        self.assertFalse(set(doc['tables']) & {'users', 'sessions', 'invites', 'change_log', 'workers'})
        text = json.dumps(doc)
        self.assertNotIn('_hash"', text)
        self.assertNotIn(auth.digest(fx.TOKEN), text)
        self.assertNotIn(fx.TOKEN, text)

    def test_admin_export_does_not_contain_other_accounts_3(self):
        _, lid, _ = self.account('maria')
        st, doc = self.req('GET', '/api/account/export', token=fx.TOKEN)
        self.assertEqual(st, 200)
        ids = [r['id'] for r in doc['tables']['listings']]
        self.assertIn(CAR_A, ids)
        self.assertNotIn(lid, ids)

    def test_export_needs_a_login_3(self):
        self.assertEqual(self.req('GET', '/api/account/export')[0], 401)

    # --- 4. erasure (admin only, typed username, export first)
    def test_erasure_is_admin_only_and_needs_the_typed_username_4(self):
        uid, lid, _ = self.account('maria')
        cookie = self.login('maria', 'a long password')
        self.assertEqual(self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'maria'}, cookie=cookie)[0], 401)
        admin = self.login('admin', fx.PASSWORD)
        self.assertEqual(self.req('DELETE', '/api/admin/users/1', {'username': 'admin'}, cookie=admin)[0], 400)  # never the own account
        self.assertEqual(self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'Maria'}, cookie=admin)[0], 400)  # exact match
        self.assertEqual(self.req('DELETE', f'/api/admin/users/{uid}', {}, cookie=admin)[0], 400)
        self.assertEqual(self.req('DELETE', '/api/admin/users/999', {'username': 'nobody'}, cookie=admin)[0], 404)
        self.assertFalse((config.DATA_DIR / 'exports').exists())  # refused before anything is written
        self.assertEqual(len(self.sql('SELECT 1 FROM users WHERE id=?', (uid,))), 1)
        self.assertEqual(len(self.sql('SELECT 1 FROM listings WHERE id=?', (lid,))), 1)

    def test_erasure_writes_the_export_then_deletes_only_that_account_4(self):
        uid, lid, sid = self.account('maria')
        peter, plid, psid = self.account('peter')
        (config.MEDIA_DIR / str(lid)).mkdir(parents=True); (config.MEDIA_DIR / str(lid) / 'a.jpg').write_bytes(b'\xff\xd8')
        (config.MEDIA_DIR / str(plid)).mkdir(parents=True); (config.MEDIA_DIR / str(plid) / 'b.jpg').write_bytes(b'\xff\xd8')
        (config.MD_DIR / str(uid)).mkdir(parents=True); (config.MD_DIR / str(peter)).mkdir(parents=True)
        maria_cookie = self.login('maria', 'a long password')
        catalogue = self.sql('SELECT (SELECT count(*) FROM vehicles), (SELECT count(*) FROM engines), (SELECT count(*) FROM generations)')
        admin_before = self.sql('SELECT id, listing_id, price_eur FROM listings WHERE owner_id=1 ORDER BY id')
        peter_before = self.sql('SELECT count(*) FROM listing_events WHERE listing_id=?', (plid,))

        admin = self.login('admin', fx.PASSWORD)
        st, out = self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'maria'}, cookie=admin)
        self.assertEqual(st, 200, out)
        self.assertEqual(out['deleted']['listings'], 1)
        self.assertTrue(out['export'].startswith('exports/account-'))
        written = json.loads((config.DATA_DIR / out['export']).read_text(encoding='utf-8'))
        self.assertEqual(written['account']['username'], 'maria')
        self.assertEqual([r['id'] for r in written['tables']['listings']], [lid])
        self.assertEqual(oct((config.DATA_DIR / out['export']).stat().st_mode & 0o777), '0o600')

        # the account is gone: its rows, its sessions, its photos and dossiers, and its sign-in
        self.assertEqual(self.sql('SELECT count(*) FROM users WHERE id=?', (uid,))[0][0], 0)
        self.assertEqual(self.sql('SELECT count(*) FROM listings WHERE owner_id=?', (uid,))[0][0], 0)
        self.assertEqual(self.sql('SELECT count(*) FROM listing_events WHERE listing_id=?', (lid,))[0][0], 0)
        self.assertEqual(self.sql('SELECT count(*) FROM sources WHERE owner_id=?', (uid,))[0][0], 0)
        self.assertEqual(self.sql('SELECT count(*) FROM sessions WHERE user_id=?', (uid,))[0][0], 0)
        self.assertEqual(self.req('GET', '/api/tco', cookie=maria_cookie)[0], 401)
        self.assertFalse((config.MEDIA_DIR / str(lid)).exists())
        self.assertFalse((config.MD_DIR / str(uid)).exists())

        # every other account and the shared catalogue are untouched
        self.assertEqual(self.sql('SELECT count(*) FROM listing_events WHERE listing_id=?', (plid,)), peter_before)
        self.assertEqual(self.sql('SELECT count(*) FROM listings WHERE owner_id=?', (peter,))[0][0], 1)
        self.assertTrue((config.MEDIA_DIR / str(plid) / 'b.jpg').is_file())
        self.assertTrue((config.MD_DIR / str(peter)).is_dir())
        self.assertEqual(self.sql('SELECT count(*) FROM listings WHERE owner_id=1'), [(len(admin_before),)])
        self.assertEqual(self.sql('SELECT id, listing_id, price_eur FROM listings WHERE owner_id=1 ORDER BY id'), admin_before)
        self.assertEqual(self.sql('SELECT (SELECT count(*) FROM vehicles), (SELECT count(*) FROM engines), (SELECT count(*) FROM generations)'), catalogue)
        self.login('peter', 'a long password')
        self.assertEqual(self.req('GET', '/api/admin/users', cookie=admin)[1][-1]['username'], 'peter')

    def test_erasure_refused_when_another_row_would_dangle_nothing_changes_4(self):
        uid, lid, sid = self.account('maria')
        # a shared catalogue row (owner NULL) that cites the account's source: it cannot be left pointing at nothing
        self.sql_write("INSERT INTO tyre_data (vehicle_id, source_id, notes) VALUES (?,?,?)", (fx.V_A, sid, 'cites maria'))
        admin = self.login('admin', fx.PASSWORD)
        st, out = self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'maria'}, cookie=admin)
        self.assertEqual(st, 400)
        self.assertIn('erase refused', out['error'])
        self.assertEqual(len(self.sql('SELECT 1 FROM users WHERE id=?', (uid,))), 1)
        self.assertEqual(len(self.sql('SELECT 1 FROM listings WHERE id=?', (lid,))), 1)
        self.assertEqual(self.sql('SELECT source_id FROM tyre_data WHERE notes=?', ('cites maria',)), [(sid,)])

    def test_erasure_clears_only_audit_links_of_other_accounts_4(self):
        uid, lid, sid = self.account('maria')
        self.sql_write("INSERT INTO change_log (table_name, row_id, action, new_json, user_id) VALUES ('listings', ?, 'update', '{}', ?)", (lid, uid))
        self.sql_write("INSERT INTO research_requests (owner_id, requested_by, url, status, requested_at) VALUES (1, ?, ?, ?, ?)",
                       (uid, 'https://example.test/req', 'QUEUED', TODAY))
        admin = self.login('admin', fx.PASSWORD)
        st, out = self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'maria'}, cookie=admin)
        self.assertEqual(st, 200, out)
        self.assertEqual(self.sql("SELECT count(*) FROM change_log WHERE user_id=?", (uid,))[0][0], 0)
        self.assertEqual(self.sql("SELECT requested_by FROM research_requests WHERE url=?", ('https://example.test/req',)), [(None,)])

    def test_erasure_after_a_research_run_scrubs_the_change_log_4(self):  # review D-02, D-03
        uid, lid, sid = self.account('maria')
        admin_lid = self.sql('SELECT id FROM listings WHERE owner_id=1 ORDER BY id LIMIT 1')[0][0]
        self.sql_write("INSERT INTO research_requests (owner_id, requested_by, url, status, requested_at) VALUES (?, NULL, ?, ?, ?)",
                       (uid, 'https://example.test/maria-run', 'QUEUED', TODAY))
        rid = self.sql('SELECT id FROM research_requests WHERE url=?', ('https://example.test/maria-run',))[0][0]
        # a research run of the account wrote Maria's listing (request_id set) and, as its owner, the admin's listing
        self.sql_write("INSERT INTO change_log (table_name, row_id, action, old_json, new_json, request_id) VALUES ('listings', ?, 'update', ?, ?, ?)",
                       (lid, '{"price_eur": 1}', '{"notes": "maria private"}', rid))
        self.sql_write("INSERT INTO change_log (table_name, row_id, action, old_json, new_json) VALUES ('listings', ?, 'update', 'admin old', 'admin new')", (admin_lid,))
        admin = self.login('admin', fx.PASSWORD)
        st, out = self.req('DELETE', f'/api/admin/users/{uid}', {'username': 'maria'}, cookie=admin)
        self.assertEqual(st, 200, out)  # erased, not refused: the run's audit row keeps its link cleared
        self.assertEqual(self.sql('SELECT count(*) FROM research_requests WHERE id=?', (rid,))[0][0], 0)
        self.assertEqual(self.sql('SELECT old_json, new_json, request_id FROM change_log WHERE row_id=? AND table_name=?', (lid, 'listings')),
                         [(None, '{"erased": true}', None)])
        self.assertEqual(self.sql('SELECT count(*) FROM change_log WHERE old_json LIKE ? OR new_json LIKE ?', ('%maria%', '%maria%')), [(0,)])
        self.assertEqual(self.sql('SELECT old_json, new_json FROM change_log WHERE row_id=? AND table_name=?', (admin_lid, 'listings')),
                         [('admin old', 'admin new')])  # another account's values stay

    def sql_write(self, q, args=()):
        c = sqlite3.connect(config.DB)
        try:
            c.execute(q, args); c.commit()
        finally:
            c.close()


if __name__ == '__main__':
    unittest.main()
