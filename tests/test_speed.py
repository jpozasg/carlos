"""Speed without behaviour change (issue #405): the cost cache per account and database state, gzip and ETag, the deferred
dossier export of photos and checklist ticks, WAL with a busy timeout, and the export failure path. Synthetic fixture only.
Run: python -m unittest tests.test_speed -v"""
import gzip, json, sqlite3, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import markdown_export
from carlos import auth, config, db, server
from tests import fixture as fx
from tests.fixture import CAR_A

TOKEN = fx.TOKEN


class SpeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Handler.log_message = lambda *a: None
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.srv.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):  # fresh database per test (the server reads config.DB on every request)
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        config.DATA_DIR, config.DB, config.MD_DIR, config.MEDIA_DIR = d, d / 'cars.sqlite', d / 'dossiers', d / 'media'
        fx.build(config.DB, repair_faults=True)
        server._deferred.pop(fx.ADMIN, None)  # a pending deferred export left by an earlier test would fire on the wrong database

    def tearDown(self):
        self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        """(status, raw body, response headers); the admin's agent token unless headers say otherwise."""
        h = {'Authorization': f'Bearer {TOKEN}', **(headers or {})}
        data = None
        if body is not None:
            h['Content-Type'] = 'application/json'
            data = json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data, h, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            body = e.read(); e.close()
            return e.code, body, e.headers

    # ------------------------------------------------------------------ the cost cache
    def test_one_build_serves_the_page_the_listing_and_the_export_of_one_state(self):
        with mock.patch.object(server, 'tco_rows', wraps=server.tco_rows) as tco:
            self.req('GET', '/api/tco'); self.req('GET', '/api/todo'); self.req('GET', f'/api/listings/{CAR_A}')
            self.assertEqual(tco.call_count, 1)  # the page load ranks once
            self.assertEqual(self.req('PATCH', f'/api/agent/listings/{CAR_A}', {'price_eur': 6100})[0], 200)
            self.assertEqual(tco.call_count, 2)  # the export after the write is the one new build
            status, body, _ = self.req('GET', f'/api/listings/{CAR_A}')
            self.assertEqual(tco.call_count, 2)  # the listing reads the build of that state
            self.assertEqual(json.loads(body)['price_eur'], 6100)

    def test_a_write_from_another_connection_invalidates_the_build(self):
        self.assertEqual(self.req('GET', '/api/tco')[0], 200)
        c = sqlite3.connect(config.DB)  # a script or another process writes the database directly
        c.execute('UPDATE listings SET notes=? WHERE id=?', ('written outside the server', CAR_A)); c.commit(); c.close()
        status, body, _ = self.req('GET', f'/api/listings/{CAR_A}')
        self.assertEqual(json.loads(body)['notes'], 'written outside the server')

    def test_preview_parameters_neither_replace_nor_read_the_saved_state(self):
        body = json.loads(self.req('GET', '/api/tco?annual_km=12000')[1])
        self.assertEqual(body['parameters']['annual_km'], 12000)
        self.assertEqual(json.loads(self.req('GET', '/api/tco')[1])['parameters']['annual_km'], 15000)

    def test_each_account_view_gets_its_own_build(self):
        c1 = db.connect(); auth.scope(c1, fx.ADMIN, curator=True); p = db.params(c1)
        c2 = db.connect(); auth.scope(c2, fx.ADMIN, curator=True)
        c2.scope = (fx.ADMIN + 1, True)  # stands for another account's view: the key must differ, so nothing is shared
        with mock.patch.object(server, 'tco_rows', wraps=server.tco_rows) as tco:
            server.costed(c1, p); server.costed(c1, p)
            self.assertEqual(tco.call_count, 1)
            server.costed(c2, p)
            self.assertEqual(tco.call_count, 2)
        c1.close(); c2.close()

    def test_a_connection_inside_a_transaction_is_built_afresh(self):
        c = db.connect(); auth.scope(c, fx.ADMIN, curator=True); p = db.params(c)
        with mock.patch.object(server, 'tco_rows', wraps=server.tco_rows) as tco:
            c.execute('UPDATE main.listings SET notes=? WHERE id=?', ('uncommitted', CAR_A))  # opens a transaction
            self.assertTrue(c.in_transaction)
            server.costed(c, p); server.costed(c, p)
            self.assertEqual(tco.call_count, 2)  # an uncommitted state is never cached
            c.rollback()

    # ------------------------------------------------------------------ gzip and ETag
    def test_text_responses_are_gzipped_only_when_the_client_accepts_it(self):
        _, plain, h = self.req('GET', '/api/tco')
        self.assertNotIn('Content-Encoding', h)
        _, packed, h = self.req('GET', '/api/tco', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(h['Content-Encoding'], 'gzip')
        self.assertIn('Accept-Encoding', h['Vary'])
        self.assertEqual(json.loads(gzip.decompress(packed)), json.loads(plain))
        _, js, h = self.req('GET', '/static/js/app.js', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(gzip.decompress(js), (config.STATIC / 'js' / 'app.js').read_bytes())

    def test_static_files_revalidate_with_an_etag_and_keep_the_security_headers(self):
        status, body, h = self.req('GET', '/static/js/app.js')
        self.assertEqual(status, 200)
        self.assertEqual(h['Cache-Control'], 'no-cache')
        status, body, h2 = self.req('GET', '/static/js/app.js', headers={'If-None-Match': h['ETag']})
        self.assertEqual((status, body), (304, b''))
        self.assertIn('default-src', h2['Content-Security-Policy'])  # the 304 carries the headers too
        status, body, _ = self.req('GET', '/static/js/app.js', headers={'If-None-Match': '"stale"'})
        self.assertEqual(status, 200)  # a changed file is sent again

    # ------------------------------------------------------------------ exports
    def test_a_failed_dossier_export_after_a_committed_write_is_logged_not_an_http_error(self):
        with mock.patch.object(markdown_export, 'export_all', side_effect=OSError('disk full')):
            status, body, _ = self.req('PATCH', f'/api/agent/listings/{CAR_A}', {'notes': 'kept'})
        self.assertEqual(status, 200)
        self.assertNotIn(b'disk full', body)  # internals stay in the log
        c = sqlite3.connect(config.DB)
        self.assertEqual(c.execute('SELECT notes FROM listings WHERE id=?', (CAR_A,)).fetchone()[0], 'kept')
        c.close()

    def test_a_failed_dossier_write_leaves_no_temp_file(self):
        c = db.connect(); auth.scope(c, fx.ADMIN, curator=True)
        with mock.patch.object(markdown_export, 'render', side_effect=OSError('render failed')):
            with self.assertRaises(OSError):
                server.export_markdown(c, fx.ADMIN)
        self.assertEqual(list((config.MD_DIR / str(fx.ADMIN)).glob('*.tmp')), [])

    def test_concurrent_exports_of_one_account_do_not_share_a_temp_file(self):
        errors = []

        def export():
            try:
                c = db.connect(); auth.scope(c, fx.ADMIN, curator=True)
                server.export_markdown(c, fx.ADMIN); c.close()
            except Exception as e:  # collected for the assertion below
                errors.append(e)
        threads = [threading.Thread(target=export) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(list((config.MD_DIR / str(fx.ADMIN)).glob('*.tmp')), [])

    def test_photo_and_checklist_exports_wait_and_run_once_per_account(self):
        with mock.patch.object(server.threading, 'Timer') as timer, mock.patch.object(server, 'export_markdown') as export:
            status, body, _ = self.req('POST', '/api/ui/inspection_items', {'listing_id': CAR_A, 'item': 'Brakes'})
            self.assertEqual(status, 201)
            item = json.loads(body)['id']
            self.assertEqual(self.req('PATCH', f'/api/ui/inspection_items/{item}', {'status': 'OK'})[0], 200)
            self.assertEqual(self.req('PATCH', f'/api/ui/inspection_items/{item}', {'status': 'PROBLEM'})[0], 200)
            export.assert_not_called()  # no export on the write itself
            self.assertEqual(timer.call_count, 1)  # a burst of ticks schedules one export
            server.export_deferred(fx.ADMIN)
            export.assert_called_once()

    def test_a_content_write_still_exports_at_once(self):
        with mock.patch.object(server, 'export_markdown', wraps=server.export_markdown) as export:
            self.assertEqual(self.req('PATCH', f'/api/agent/listings/{CAR_A}', {'notes': 'content'})[0], 200)
        export.assert_called()

    # ------------------------------------------------------------------ the database
    def test_the_database_runs_in_wal_mode_with_a_30_second_busy_timeout(self):
        c = db.connect()
        self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(c.execute('PRAGMA busy_timeout').fetchone()[0], 30000)
        c.close()

    def test_connect_does_not_fail_while_another_connection_holds_a_write_lock(self):
        # a rollback-journal file whose WAL switch is blocked by an open write transaction (the export thread vs a request)
        raw = sqlite3.connect(config.DB); raw.execute('PRAGMA journal_mode=DELETE'); raw.commit(); raw.close()
        writer = sqlite3.connect(config.DB, isolation_level=None)
        writer.execute('BEGIN IMMEDIATE')
        results, errors = [], []

        def open_one():
            try:
                c = db.connect()
                results.append(c.execute('PRAGMA journal_mode').fetchone()[0])
                c.close()
            except Exception as e:  # recorded, asserted below
                errors.append(e)

        threads = [threading.Thread(target=open_one) for _ in range(4)]
        for t in threads: t.start()
        time.sleep(0.2)  # the threads retry the switch while the writer still holds its lock
        writer.execute('COMMIT'); writer.close()
        for t in threads: t.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(results, ['wal'] * 4)
        c = db.connect()  # and the file is WAL for every later connection
        self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        c.close()


if __name__ == '__main__':
    unittest.main()
