"""What a non-staged unit (CAPTURE, TAX, LISTING) may write with its per-request token, and the scope of a staged run
for rows without a level (#386, finding N2). Synthetic database (tests/fixture.py), real HTTP server, no network."""
import json, sqlite3, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from carlos import agent, auth, config, server, staging
from tests import fixture as fx
from tests.fixture import ADMIN, CAR_A, CAR_B, E_A, E_B, G1, G2, SRC_GUIDE, SRC_HU, SRC_LISTING, SRC_QUOTE, SRC_TAX_OFFICIAL, V_A, V_B, TOKEN

UNITS = ('CAPTURE', 'TAX', 'LISTING', 'RESEARCH_A', 'MERGE', 'VARIANT', 'NONE')
TAX = {'annual_tax_eur': 99, 'status': 'VERIFIED', 'basis': '1400 cc, 140 g/km', 'source_id': SRC_TAX_OFFICIAL}


class UnitScopeTest(unittest.TestCase):
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
        self.addCleanup(self.tmp.cleanup)
        self.sql("INSERT INTO research_requests (id, owner_id, url, status, listing_id, unit) VALUES (100, ?, 'u', 'WAITING', ?, 'CAPTURE')", (ADMIN, CAR_A))
        self.tokens = {}
        for rid, unit in enumerate(UNITS, 101):
            self.tokens[unit] = f'tok-{unit}'
            self.sql("INSERT INTO research_requests (id, owner_id, url, status, listing_id, parent_id, unit, claimed_at, request_token_hash, scope) "
                     "VALUES (?, ?, 'u', 'RUNNING', ?, 100, ?, datetime('now'), ?, ?)",
                     (rid, ADMIN, None if unit == 'CAPTURE' else CAR_A, None if unit == 'NONE' else unit, auth.digest(self.tokens[unit]),
                      json.dumps([['engine_id', E_A], ['generation_id', G1], ['vehicle_id', V_A]])))

    def sql(self, q, args=()):
        c = sqlite3.connect(config.DB)
        try:
            r = c.execute(q, args).fetchall(); c.commit(); return r
        finally:
            c.close()

    def api(self, unit, method, path, body=None):
        h = {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.tokens[unit]}'}
        r = urllib.request.Request(f'{self.base}/api/{path}', json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            resp = urllib.request.urlopen(r); return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def shared_tax(self, vehicle_id):
        return self.sql('SELECT id FROM tax_data WHERE vehicle_id=?', (vehicle_id,))[0][0]

    # ---------------------------------------------------------------- non-staged units
    def test_tax_unit_writes_tax_on_its_variant_only(self):
        self.assertEqual(self.api('TAX', 'POST', 'agent/tax_data', {**TAX, 'vehicle_id': V_A})[0], 201)
        st, e = self.api('TAX', 'POST', 'agent/tax_data', {**TAX, 'vehicle_id': V_B})
        self.assertEqual(st, 403, e); self.assertIn('outside the variant', e['error'])
        self.assertEqual(self.api('TAX', 'POST', 'agent/tax_data', {**TAX, 'engine_id': E_B})[0], 403)      # a level of another car
        # a shared row of its own variant may be corrected; another variant's row, or moving one there, not
        self.assertEqual(self.api('TAX', 'PATCH', f'agent/tax_data/{self.shared_tax(V_A)}', {'annual_tax_eur': 95})[0], 200)
        self.assertEqual(self.api('TAX', 'PATCH', f'agent/tax_data/{self.shared_tax(V_B)}', {'annual_tax_eur': 1})[0], 403)
        self.assertEqual(self.api('TAX', 'PATCH', f'agent/tax_data/{self.shared_tax(V_A)}', {'vehicle_id': V_B})[0], 403)
        self.assertEqual(self.sql('SELECT annual_tax_eur FROM tax_data WHERE id=?', (self.shared_tax(V_B),)), [(60,)])

    def test_a_unit_writes_only_its_own_tables(self):
        for unit, table, body in (('TAX', 'faults', {'engine_id': E_A}), ('TAX', 'maintenance_items', {'engine_id': E_A}),
                                  ('TAX', 'unit_costs', {'listing_id': CAR_A}),
                                  ('LISTING', 'tax_data', {**TAX, 'vehicle_id': V_A}), ('LISTING', 'faults', {'engine_id': E_A}),
                                  ('CAPTURE', 'faults', {'engine_id': E_A}), ('CAPTURE', 'tax_data', {**TAX, 'vehicle_id': V_A})):
            st, e = self.api(unit, 'POST', f'agent/{table}', body)
            self.assertEqual(st, 403, (unit, table, e)); self.assertIn(f'{unit} writes only', e['error'])
        self.assertEqual(self.api('TAX', 'PATCH', f'agent/engines/{E_A}', {'status': 'PARTIAL'})[0], 403)
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/generations/{G1}', {'status': 'PARTIAL'})[0], 403)
        self.assertEqual(self.sql('SELECT status FROM engines WHERE id=?', (E_A,)), [('VERIFIED',)])

    def test_listing_unit_does_its_work(self):
        self.assertEqual(self.api('LISTING', 'POST', 'agent/unit_costs', {'listing_id': CAR_A, 'category': 'repairs', 'item': 'Brake discs',
                                                                           'parts_eur': 120, 'status': 'ESTIMATED', 'source_id': SRC_GUIDE})[0], 201)
        self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_events', {'listing_id': CAR_A, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'x'})[0], 201)
        self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_quotes', {'listing_id': CAR_A, 'annual_premium_eur': 777, 'premium_status': 'QUOTE',
                                                                             'quote_date': fx.TODAY, 'source_id': SRC_QUOTE})[0], 403)   # quotes are entered by hand, no unit writes them
        # a source on a level of this car; a source on another car's level; a shared source without a level cannot be changed
        self.sql("INSERT INTO sources (id, engine_id, title, source_type, quality, accessed_date) VALUES (50, ?, 'Other engine guide', 'buying_guide', 'C', ?)", (E_B, fx.TODAY))
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/sources/{SRC_GUIDE}', {'limitations': 'one guide'})[0], 200)   # engine E_A: in the chain
        self.assertEqual(self.api('LISTING', 'PATCH', 'agent/sources/50', {'quality': 'A'})[0], 403)
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/sources/{SRC_HU}', {'quality': 'A'})[0], 403)
        self.assertEqual(self.sql('SELECT quality FROM sources WHERE id IN (50, ?)', (SRC_HU,)), [('B',), ('C',)])
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/sources/{SRC_LISTING}', {'limitations': 'own listing source'})[0], 200)  # the account's own row

    def test_capture_creates_but_never_changes_the_catalogue(self):
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/generations', {'make': 'Gamma', 'model': 'Van', 'name': 'Mk1', 'start_year': 2010})[0], 201)
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/sources', {'vehicle_id': V_A, 'title': 'Listing', 'url': 'https://example.test/x', 'source_type': 'listing',
                                                                        'quality': 'A', 'accessed_date': fx.TODAY})[0], 201)
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'price_eur': 5900})[0], 200)          # the account's own listing
        for table, rid in (('engines', E_A), ('generations', G2), ('vehicles', V_B), ('sources', SRC_GUIDE)):
            st, e = self.api('CAPTURE', 'PATCH', f'agent/{table}/{rid}', {'status': 'PARTIAL'} if table != 'sources' else {'quality': 'A'})
            self.assertEqual(st, 403, (table, e)); self.assertIn('CAPTURE does not change', e['error'])

    def test_own_rows_moved_off_the_cars_chain_are_refused(self):  # round 2 finding B: a level move of an owned row stays on the car's chain
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': V_B})[0], 403)   # a foreign variant re-point
        self.assertEqual(self.sql('SELECT vehicle_id FROM listings WHERE id=?', (CAR_A,)), [(V_A,)])
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': V_A, 'price_eur': 5900})[0], 200)
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/sources/{SRC_LISTING}', {'engine_id': E_B})[0], 403)  # the own source moved to another car's engine
        self.assertEqual(self.sql('SELECT engine_id FROM sources WHERE id=?', (SRC_LISTING,)), [(None,)])

    def test_capture_reattaches_its_listing_to_its_own_variant_only(self):  # #194: a re-run attaches the variant it found or created
        self.tokens['ADMIN'] = TOKEN
        found = self.api('ADMIN', 'POST', 'agent/vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Found 1.4', 'transmission': 'Manual',
                                                             'body_style': 'Hatchback, 5 doors', 'emissions_standard': 'Euro 5', 'co2_g_km': 140,
                                                             'hsn': '7777', 'tsn': 'CCC', 'technical_status': 'VERIFIED'})[1]['id']
        st, e = self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': V_B})
        self.assertEqual(st, 403, e); self.assertIn('outside the variant', e['error'])                           # a foreign variant (another generation)
        self.assertEqual(self.api('LISTING', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': found})[0], 403)  # LISTING does not re-attach
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': found})[0], 200)  # the variant of its own generation
        self.assertEqual(self.sql('SELECT vehicle_id FROM listings WHERE id=?', (CAR_A,)), [(found,)])
        made = self.api('CAPTURE', 'POST', 'agent/vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Made 1.4', 'transmission': 'Manual',
                                                              'body_style': 'Hatchback, 5 doors', 'emissions_standard': 'Euro 5', 'co2_g_km': 140,
                                                              'hsn': '8888', 'tsn': 'DDD', 'technical_status': 'VERIFIED'})
        self.assertEqual(made[0], 201, made)
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': made[1]['id']})[0], 200)  # a variant this run created
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'vehicle_id': V_B})[0], 403)           # and back to a foreign one: refused

    def test_a_unit_writes_only_its_own_listings_rows(self):  # SEC-1: a request token patches its own car's rows, never another car's
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'price_eur': 5900})[0], 200)   # its listing: the first it writes
        self.assertEqual(self.api('CAPTURE', 'PATCH', 'agent/inspection_items/3', {'status': 'PROBLEM'})[0], 403)  # the checklist of CAR_B
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/listing_events', {'listing_id': CAR_B, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'x'})[0], 403)
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_B}', {'price_eur': 1})[0], 403)
        self.assertEqual(self.api('CAPTURE', 'PATCH', 'agent/inspection_items/1', {'status': 'PROBLEM'})[0], 200)  # its own checklist
        self.assertEqual(self.sql('SELECT status FROM inspection_items WHERE id=3'), [('OK',)])
        self.assertEqual(self.sql('SELECT price_eur FROM listings WHERE id=?', (CAR_B,)), [(7500,)])
        self.assertEqual(self.api('LISTING', 'PATCH', 'agent/inspection_items/3', {'status': 'PROBLEM'})[0], 403)  # a request with its listing set
        self.assertEqual(self.api('LISTING', 'PATCH', 'agent/inspection_items/2', {'status': 'PROBLEM'})[0], 200)

    def test_a_capture_listing_names_only_a_variant_it_created(self):  # SEC-2: a new listing on a foreign variant is refused
        new = {'listing_id': 'N1', 'url': 'https://example.test/n1', 'platform': 'Test', 'source_id': SRC_LISTING, 'listing_status': 'UNDER REVIEW',
               'is_reference': 0, 'last_checked': fx.TODAY, 'price_eur': 100}
        st, e = self.api('CAPTURE', 'POST', 'agent/listings', {**new, 'vehicle_id': V_B})
        self.assertEqual(st, 403, e); self.assertIn('outside the variant', e['error'])
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/listings', {**new, 'vehicle_id': V_A})[0], 403)   # an existing variant it did not create
        self.assertEqual(self.sql("SELECT count(*) FROM listings WHERE listing_id='N1'"), [(0,)])
        self.tokens['ADMIN'] = TOKEN
        made = self.api('CAPTURE', 'POST', 'agent/vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Made 1.4', 'transmission': 'Manual',
                                                              'body_style': 'Hatchback, 5 doors', 'emissions_standard': 'Euro 5', 'co2_g_km': 140,
                                                              'hsn': '9999', 'tsn': 'EEE', 'technical_status': 'VERIFIED'})[1]['id']
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/listings', {**new, 'vehicle_id': made})[0], 201)   # the variant this run created

    def test_a_capture_reusing_a_known_variant_is_logged_and_may_list_on_it(self):  # SEC-2: a reuse by HSN/TSN is the run's own link
        self.tokens['ADMIN'] = TOKEN
        known = self.api('ADMIN', 'POST', 'agent/vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Known 1.4', 'transmission': 'Manual',
                                                             'body_style': 'Hatchback, 5 doors', 'emissions_standard': 'Euro 5', 'co2_g_km': 140,
                                                             'hsn': '6161', 'tsn': 'KKK', 'technical_status': 'VERIFIED'})[1]['id']
        st, e = self.api('CAPTURE', 'POST', 'agent/vehicles', {'generation_id': G1, 'engine_id': E_A, 'trim': 'Known 1.4', 'transmission': 'Manual',
                                                                  'body_style': 'Hatchback, 5 doors', 'emissions_standard': 'Euro 5', 'co2_g_km': 140,
                                                                  'hsn': '6161', 'tsn': 'KKK', 'technical_status': 'VERIFIED'})
        self.assertEqual((st, e.get('id'), e.get('existing')), (200, known, True))
        self.assertEqual(self.sql("SELECT row_id, action FROM change_log WHERE request_id=101 AND table_name='vehicles'"), [(known, 'reuse')])
        new = {'listing_id': 'R1', 'url': 'https://example.test/r1', 'platform': 'Test', 'source_id': SRC_LISTING, 'listing_status': 'UNDER REVIEW',
               'is_reference': 0, 'last_checked': fx.TODAY, 'price_eur': 100, 'vehicle_id': known}
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/listings', new)[0], 201)   # the reused variant
        self.assertEqual(self.api('CAPTURE', 'POST', 'agent/listings', {**new, 'listing_id': 'R2', 'vehicle_id': V_B})[0], 403)   # a foreign one still

    def test_retired_units_and_an_unlisted_unit_are_closed(self):  # owner decision 2026-11-22: the single-run units are refused
        st, e = self.api('VARIANT', 'PATCH', f'agent/engines/{E_B}', {'notes': 'retired unit'})
        self.assertEqual(st, 403, e); self.assertIn('retired', e['error'])
        self.assertEqual(self.sql('SELECT notes FROM engines WHERE id=?', (E_B,)), [(None,)])
        st, e = self.api('MERGE', 'POST', 'agent/listing_events', {'listing_id': CAR_A, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'x'})
        self.assertEqual(st, 403, e); self.assertIn('writes nothing', e['error'])

    def test_unit_less_token_is_refused_every_write(self):  # owner decision 2026-11-22: a request without a unit is refused
        st, e = self.api('NONE', 'PATCH', f'agent/engines/{E_B}', {'notes': 'no unit'})
        self.assertEqual(st, 403, e); self.assertIn('without a unit', e['error'])
        self.assertEqual(self.api('NONE', 'PATCH', f'agent/sources/{SRC_HU}', {'quality': 'A'})[0], 403)
        self.assertEqual(self.sql('SELECT notes FROM engines WHERE id=?', (E_B,)), [(None,)])
        self.assertEqual(self.api('NONE', 'PATCH', f'agent/listings/{CAR_A}', {'price_eur': 5900})[0], 403)

    def media(self, unit, listing_id):
        h = {'Content-Type': 'image/jpeg', 'Authorization': f'Bearer {self.tokens[unit]}'}
        r = urllib.request.Request(f'{self.base}/api/agent/media/{listing_id}?url=https%3A%2F%2Fexample.test%2Fp.jpg',
                                   fx.jpeg([(0xE0, b'photo' * 20)]), h, method='POST')
        try:
            return urllib.request.urlopen(r).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_photos_only_for_the_requests_own_listing(self):  # review H2 point 4
        self.assertEqual(self.media('CAPTURE', CAR_A), 403)     # the capture has not created or touched it yet
        self.assertEqual(self.api('CAPTURE', 'PATCH', f'agent/listings/{CAR_A}', {'price_eur': 5900})[0], 200)
        self.assertEqual(self.media('CAPTURE', CAR_A), 201)     # the listing this run wrote
        self.assertEqual(self.media('CAPTURE', CAR_B), 403)
        self.assertEqual(self.media('LISTING', CAR_A), 200)     # the request's own listing (the same photo: already stored, 200)
        self.assertEqual(self.media('LISTING', CAR_B), 403)
        self.assertEqual(self.sql('SELECT count(*) FROM listing_media WHERE listing_id=?', (CAR_B,)), [(0,)])

    def test_every_token_write_records_its_request(self):
        self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_events', {'listing_id': CAR_A, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'x'})[0], 201)
        self.assertEqual(self.sql("SELECT request_id FROM change_log WHERE table_name='listing_events' ORDER BY id DESC LIMIT 1"), [(103,)])
        self.tokens['ADMIN'] = TOKEN   # the owner's agent token: no request
        self.assertEqual(self.api('ADMIN', 'POST', 'agent/listing_events', {'listing_id': CAR_A, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'y'})[0], 201)
        self.assertEqual(self.sql("SELECT request_id FROM change_log WHERE table_name='listing_events' ORDER BY id DESC LIMIT 1"), [(None,)])

    def test_a_run_writing_more_than_fifty_listing_rows_is_flagged_once(self):
        ev = {'listing_id': CAR_A, 'event_date': fx.TODAY, 'kind': 'verification', 'text': 'x'}
        for _ in range(agent.LISTING_WRITE_ALERT):
            self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_events', ev)[0], 201)
        self.assertEqual(self.sql("SELECT count(*) FROM change_log WHERE action='flag'"), [(0,)])      # 50 is not more than 50
        self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_events', ev)[0], 201)
        self.assertEqual(self.api('LISTING', 'POST', 'agent/listing_events', ev)[0], 201)
        flags = self.sql("SELECT row_id, new_json FROM change_log WHERE action='flag'")
        self.assertEqual(len(flags), 1); self.assertEqual(flags[0][0], 103); self.assertIn('listing-level rows', flags[0][1])
        self.assertEqual(self.sql("SELECT count(*) FROM change_log WHERE request_id=103 AND table_name='listing_events'"), [(52,)])

    def test_another_accounts_row_is_refused(self):
        self.sql("INSERT INTO sources (id, owner_id, title, source_type, accessed_date) VALUES (60, 99, 'Her listing', 'listing', ?)", (fx.TODAY,))
        st, e = self.api('LISTING', 'PATCH', 'agent/sources/60', {'limitations': 'mine now'})
        self.assertEqual(st, 404, e)                                              # hidden by the account scope, as before: no existence leak
        self.assertEqual(self.sql('SELECT limitations FROM sources WHERE id=60'), [(None,)])

    def test_check_unit_write_directly(self):
        c = sqlite3.connect(config.DB); c.row_factory = sqlite3.Row
        req = {'unit': 'TAX', 'listing_id': CAR_A}
        self.assertEqual(staging.variant_chain(c, CAR_A), [['vehicle_id', V_A], ['generation_id', G1], ['engine_id', E_A]])
        self.assertEqual(staging.variant_chain(c, 9999), [])
        staging.check_unit_write(c, req, 'tax_data', None, {**TAX, 'vehicle_id': V_A})
        with self.assertRaises(staging.NotAllowed):
            staging.check_unit_write(c, {**req, 'listing_id': None}, 'tax_data', None, {**TAX, 'vehicle_id': V_A})   # no car, no level
        with self.assertRaises(staging.NotAllowed):                                                                     # a retired unit writes nothing
            staging.check_unit_write(c, {'unit': 'VARIANT', 'listing_id': CAR_A}, 'engines', E_B, {})
        with self.assertRaises(staging.NotAllowed):                                                                     # a request without a unit writes nothing
            staging.check_unit_write(c, {'unit': None, 'listing_id': CAR_A}, 'listing_events', None, {'listing_id': CAR_A})
        with self.assertRaises(staging.NotAllowed):                                                                     # a staged run never gets here
            staging.check_unit_write(c, {'unit': 'RESEARCH_A', 'listing_id': CAR_A}, 'engines', E_B, {})
        staging.check_unit_write(c, req, 'tax_data', None, 'not a dict')                                                # agent_write answers 400 for that
        c.close()

    def test_check_unit_write_reads_through_the_scope(self):  # review D-08: a row the account cannot see is not read at all
        c = sqlite3.connect(config.DB); c.row_factory = sqlite3.Row
        auth.scope(c, 99)  # an account whose catalogue does not include V_B: its shared tax row is hidden from it
        self.assertEqual(c.execute('SELECT count(*) FROM tax_data WHERE id=?', (self.shared_tax(V_B),)).fetchone()[0], 0)
        staging.check_unit_write(c, {'unit': 'TAX', 'listing_id': CAR_A}, 'tax_data', self.shared_tax(V_B), {'annual_tax_eur': 1})  # no 403 from the hidden row
        c.close()

    # ---------------------------------------------------------------- staged runs: rows without a level
    def test_staged_run_cannot_patch_a_row_without_a_level(self):
        self.sql("INSERT INTO maintenance_items (id, item, schedule, interval_months, reference_cost_eur, status, source_id) "
                 "VALUES (90, 'HU/AU default', 'ITEM', 24, 163, 'OFFICIAL FEE LEVEL', ?)", (SRC_HU,))      # a global default
        st, e = self.api('RESEARCH_A', 'PATCH', 'agent/maintenance_items/90', {'reference_cost_eur': 1})
        self.assertEqual(st, 403, e); self.assertIn('no level', e['error'])
        st, e = self.api('RESEARCH_A', 'PATCH', f'agent/sources/{SRC_HU}', {'quality': 'A'})                  # a shared source without a level
        self.assertEqual(st, 403, e)
        self.assertEqual(self.api('RESEARCH_A', 'PATCH', 'agent/maintenance_items/90', {'engine_id': E_A})[0], 403)   # giving it a level does not open the way
        # the account's own level-free source is the requester's to correct; a new row without a level is still a new finding
        self.assertEqual(self.api('RESEARCH_A', 'PATCH', f'agent/sources/{SRC_LISTING}', {'limitations': 'own'})[0], 200)
        self.assertEqual(self.sql('SELECT count(*) FROM research_findings WHERE target_id IN (90, ?)', (SRC_HU,)), [(0,)])

    def test_staged_patch_cannot_move_an_out_of_scope_row_into_scope(self):
        row = self.sql('SELECT id FROM maintenance_items WHERE generation_id=?', (G2,))[0][0]                  # the HU item of generation 2, outside the scope
        st, e = self.api('RESEARCH_A', 'PATCH', f'agent/maintenance_items/{row}', {'vehicle_id': V_A})
        self.assertEqual(st, 403, e)                  # before #386 the in-scope vehicle_id hid the row's own generation
        self.assertEqual(self.sql('SELECT count(*) FROM research_findings')[0], (0,))


if __name__ == '__main__':
    unittest.main()
