"""capture_listing.py against a test server on the synthetic fixture database. Run: python -m unittest -v"""
import os, tempfile, threading, unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import capture_listing
from carlos import config, server
from tests import fixture as fx

TOKEN = fx.TOKEN
JPG = fx.jpeg([(0xE0, b'photo' * 20)])


class CaptureListingTest(unittest.TestCase):
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
        self.dir = d = Path(self.tmp.name)
        config.DATA_DIR, config.DB, config.MD_DIR, config.MEDIA_DIR = d, d / 'cars.sqlite', d / 'dossiers', d / 'media'
        fx.build(config.DB)
        (d / 'photos').mkdir()
        (d / 'photos' / '1.jpg').write_bytes(JPG)
        (d / 'photos' / 'big.jpg').write_bytes(b'\xff\xd8\xff' + b'x' * capture_listing.MAX_IMAGE_BYTES)
        self.api = capture_listing.Api(self.base, TOKEN)
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def capture(self, **over):
        cap = {'url': 'https://suchen.mobile.de/fahrzeuge/details.html?id=123', 'platform': 'mobile.de', 'listing_id': '123',
               'vehicle_id': fx.V_B2, 'captured_at': '2026-11-02T15:30', 'capture_method': 'Claude in Chrome',
               'title': 'Beta City Plus', 'price_eur': 6990, 'mileage_km': 85000,
               'listing': {'first_registration': '2014-05', 'hu_claim': '05/2027', 'accident_free_claim': 1},
               'description': 'Scheckheftgepflegt.\nNichtraucher.', 'attributes': {'Kilometerstand': '85.000 km', 'HU': '05/2027'},
               'photos': [{'file': 'photos/1.jpg', 'url': 'https://img.example/1.jpg'}, {'file': 'photos/big.jpg'}]}
        cap.update(over)
        return cap

    def run_import(self, cap, dry_run=False):
        return capture_listing.import_capture(self.api, cap, self.dir, dry_run, self.logs.append)

    def detail(self, lid):
        return self.api.call('GET', f'/api/listings/{lid}')

    def test_car_without_a_link(self):  # #375
        cap = self.capture(); cap.pop('url'); cap.pop('platform'); cap.pop('listing_id'); cap['photos'] = []
        a, b = self.run_import(dict(cap)), self.run_import(dict(cap, title='Other'))
        self.assertTrue(a['new_listing'] and b['new_listing'])  # an empty url never matches another listing
        d = self.detail(a['listing_id'])
        self.assertEqual((d['url'], d['platform'], d['price_eur']), (None, 'manual', 6990.0))

    def test_new_listing_full_workflow(self):
        s = self.run_import(self.capture())
        self.assertTrue(s['new_listing'])
        d = self.detail(s['listing_id'])
        self.assertEqual((d['price_eur'], d['mileage_km'], d['first_registration'], d['last_checked'], d['listing_status']),
                         (6990, 85000, '2014-05', '2026-11-02', 'UNDER REVIEW'))
        self.assertEqual(d['hu_claim'], '05/2027')
        src = next(x for x in d['sources'] if x['id'] == d['source_id'])
        self.assertEqual((src['url'], src['quality'], src['source_type']), (d['url'], 'A', 'listing'))
        self.assertEqual(len(d['snapshots']), 1)
        self.assertIn('Nichtraucher.', d['snapshots'][0]['description'])  # verbatim, original language
        self.assertEqual((s['photos_archived'], len(s['photos_skipped'])), (1, 1))  # the >1.5 MB photo is skipped
        self.assertEqual(d['media'][0]['snapshot_id'], s['snapshot_id'])
        actions = {r['inspection_action'] for r in d['reliability'] if r['inspection_action']}
        self.assertTrue(actions)
        self.assertEqual({i['item'] for i in d['inspection']}, actions | {config.VIN_RECALL_CHECK})  # the fixed VIN recall item (#357)
        self.assertTrue(all(i['status'] == 'PENDING' for i in d['inspection']))
        self.assertEqual([e['kind'] for e in d['events']], ['found'])
        self.assertIn('6990 EUR', d['events'][0]['text'])

    def test_recapture_price_change(self):
        lid = self.run_import(self.capture())['listing_id']
        n_items = len(self.detail(lid)['inspection'])
        s = self.run_import(self.capture(url='https://suchen.mobile.de/x?id=123', captured_at='2026-11-09T10:00', price_eur=6500))
        self.assertEqual((s['listing_id'], s['new_listing'], s['photos_archived']), (lid, False, 0))  # photo deduplicated
        d = self.detail(lid)
        self.assertEqual((d['price_eur'], d['last_checked'], len(d['snapshots'])), (6500, '2026-11-09', 2))
        self.assertEqual([x['price_eur'] for x in d['snapshots']], [6990, 6500])  # old capture kept
        self.assertEqual([e['kind'] for e in d['events']], ['found', 'price', 'verification'])
        self.assertIn('6990 EUR → 6500 EUR', d['events'][1]['text'])
        self.assertEqual(len(d['inspection']), n_items)  # checklist not duplicated

    def test_dry_run_writes_nothing(self):
        before = len(self.api.call('GET', '/api/listings')['listings'])
        s = self.run_import(self.capture(), dry_run=True)
        self.assertIsNone(s['listing_id'])
        self.assertEqual(len(self.api.call('GET', '/api/listings')['listings']), before)
        self.assertTrue(all(line.startswith('[dry-run]') for line in self.logs))

    def test_validation_before_any_write(self):
        before = len(self.api.call('GET', '/api/sources'))
        for bad in ({'vehicle_id': None}, {'price_eur': 0}, {'attributes': ['x']}, {'listing': {'verdict': 'buy'}},
                    {'photos': [{}]}, {'url': ''}, {'vehicle_id': 999},
                    # structured facts (#169): fixed codes, YYYY-MM, 5-digit postcode, stars 0–5
                    {'listing': {'seller_type': 'dealer'}}, {'listing': {'hu_until': '05/2027'}}, {'listing': {'postal_code': '9720'}},
                    {'listing': {'seller_rating': 6}}, {'listing': {'accident_free': True}}, {'listing': {'warranty': 2}}):
            with self.assertRaises(ValueError, msg=bad):
                self.run_import(self.capture(**bad))
        self.assertEqual(len(self.api.call('GET', '/api/sources')), before)

    def test_photo_reader(self):
        self.assertEqual(capture_listing.read_photo({'file': 'photos/1.jpg'}, self.dir), (JPG, 'image/jpeg'))
        (self.dir / 'photos' / 'x.gif').write_bytes(b'GIF89a')
        self.assertIsNone(capture_listing.read_photo({'file': 'photos/x.gif'}, self.dir)[0])
        self.assertIsNone(capture_listing.read_photo({'file': 'missing.jpg'}, self.dir)[0])

    def test_photo_file_stays_inside_the_capture_folder(self):  # review M6
        outside = self.dir.parent / 'outside-secret.jpg'
        outside.write_bytes(JPG)
        self.addCleanup(outside.unlink)
        (self.dir / 'photos' / 'link.jpg').symlink_to(outside)
        for f in ('../outside-secret.jpg', str(outside), 'photos/../../outside-secret.jpg', 'photos/link.jpg'):
            body, why = capture_listing.read_photo({'file': f}, self.dir)
            self.assertEqual((body, why), (None, 'file is outside the capture folder'), f)
        self.assertEqual(capture_listing.read_photo({'file': 'photos/../photos/1.jpg'}, self.dir)[1], 'image/jpeg')

    def test_photo_url_guard(self):  # review N7: no LAN, loopback, metadata, other schemes, credentials
        hosts = {'cdn.example': ['93.184.216.34'], 'lan.example': ['192.168.1.20'], 'mixed.example': ['93.184.216.34', '10.0.0.5'],
                 'v6.example': ['::1'], 'mapped.example': ['::ffff:127.0.0.1'], 'meta.example': ['169.254.169.254']}
        resolver = lambda host: hosts.get(host) or [host]                       # an IP literal resolves to itself
        ok = capture_listing.check_photo_url
        ok('https://cdn.example/1.jpg', resolver)
        for bad in ('file:///etc/passwd', 'ftp://cdn.example/1.jpg', 'http://127.0.0.1/x.jpg', 'http://[::1]/x.jpg', 'http://localhost/x.jpg',
                    'http://169.254.169.254/latest/meta-data', 'http://192.168.1.1/x.jpg', 'http://10.0.0.1:8080/x.jpg', 'http://lan.example/x.jpg',
                    'http://mixed.example/x.jpg', 'http://v6.example/x.jpg', 'http://mapped.example/x.jpg', 'http://meta.example/x.jpg',
                    'https://user:pw@cdn.example/1.jpg', 'http:///x.jpg'):
            with self.assertRaises(ValueError, msg=bad):
                ok(bad, lambda h: resolver(h) if h != 'localhost' else ['127.0.0.1'])
            self.assertIsNone(capture_listing.read_photo({'url': bad}, self.dir, lambda h: ['127.0.0.1'] if h == 'localhost' else resolver(h))[0], bad)

    def test_photo_redirect_to_a_private_address_is_refused(self):
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302); self.send_header('Location', 'http://10.0.0.1/secret.jpg'); self.end_headers()
            log_message = lambda *a: None
        srv = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        seen = []
        def resolver(host):                                                     # the test server stands in for a public host
            seen.append(host)
            return ['10.0.0.1'] if host == '10.0.0.1' else ['93.184.216.34']
        body, why = capture_listing.read_photo({'url': f'http://127.0.0.1:{srv.server_port}/1.jpg'}, self.dir, resolver)
        self.assertIsNone(body)
        self.assertIn('private or reserved', why)
        self.assertEqual(seen, ['127.0.0.1', '10.0.0.1'])                       # the redirect target was checked, and refused


class LoadTokenTest(unittest.TestCase):
    """The token comes from the environment only (review H1 follow-up): a .env file is never read."""

    def test_environment_token_is_used(self):
        with mock.patch.dict(os.environ, {'AGENT_TOKEN': 'from-env'}):
            self.assertEqual(capture_listing.load_token(), 'from-env')

    def test_env_file_is_ignored_and_missing_variable_names_itself(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(Path, 'cwd', return_value=Path(d)):
            Path(d, '.env').write_text('AGENT_TOKEN=from-dotenv-file\n')
            with self.assertRaises(SystemExit) as cm:
                capture_listing.load_token()
        self.assertIn('AGENT_TOKEN', str(cm.exception))
        self.assertNotIn('from-dotenv-file', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
