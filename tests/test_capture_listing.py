"""capture_listing.py against a test server on the synthetic fixture database. Run: python -m unittest -v"""
import tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
import capture_listing
from carlos import config, server
from tests import fixture as fx

TOKEN = fx.TOKEN
JPG = b'\xff\xd8\xff\xe0' + b'photo' * 20


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
        self.assertEqual({i['item'] for i in d['inspection']}, actions)
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


if __name__ == '__main__':
    unittest.main()
