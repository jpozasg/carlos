"""catalogue_promote.py (issue #144): two accounts researched the same car; the dry run leaves the database alone,
the run merges the duplicates into one shared variant, keeps the account's premium private and archives the older
duplicate schedule row."""
import sqlite3, tempfile, unittest
from pathlib import Path
import catalogue_promote, migrate


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'cars.sqlite'
        migrate.run(self.db)
        c = sqlite3.connect(self.db)
        c.executescript("""
            INSERT INTO users (id, username, role) VALUES (1, 'admin', 'admin'), (5, 'jorge', 'user');
            INSERT INTO generations (id, make, model, name, start_year, end_year, owner_id) VALUES
              (10, 'VW', 'Polo', 'V', 2009, 2017, 1), (20, 'VW', 'Polo', 'V', 2014, 2017, 5);
            INSERT INTO engines (id, code, fuel_type, power_kw, displacement_cc, owner_id) VALUES
              (10, 'CJZC', 'Petrol', 66, 1197, 1), (20, 'cjzc ', 'Petrol', 66, 1197, 5);
            INSERT INTO vehicles (id, generation_id, engine_id, hsn, tsn, owner_id) VALUES
              (10, 10, 10, '0603', 'BEB', 1), (20, 20, 20, '0603', 'BEB', 5), (30, 10, 10, NULL, NULL, 1);
            INSERT INTO sources (id, title, source_type, owner_id) VALUES (1, 'ADAC', 'buying_guide', 1), (2, 'mobile.de ad', 'listing', 1);
            INSERT INTO maintenance_items (id, vehicle_id, item, job, interval_km, reference_cost_eur, source_id) VALUES
              (1, 10, 'Oil service', 'OIL_SERVICE', 15000, 120, 1);
            INSERT INTO maintenance_items (id, engine_id, item, job, interval_km, reference_cost_eur) VALUES
              (2, 20, 'Oil and filter', 'OIL_SERVICE', 15000, 110);
            INSERT INTO insurance_data (id, vehicle_id, annual_premium_eur, premium_status, source_id) VALUES (1, 10, 640, 'QUOTE', 1);
            INSERT INTO listings (id, vehicle_id, owner_id) VALUES (1, 10, 1);
            INSERT INTO catalogue_links (owner_id, vehicle_id) VALUES (1, 10), (5, 20);
        """)
        c.commit(); c.close()

    def tearDown(self):
        self.tmp.cleanup()

    def q(self, sql, db=None):
        c = sqlite3.connect(db or self.db)
        try:
            return c.execute(sql).fetchall()
        finally:
            c.close()

    def test_dry_run_then_apply(self):
        out = Path(self.tmp.name) / 'copy.sqlite'
        rep = catalogue_promote.run(self.db, out=out)
        self.assertEqual(self.q('SELECT count(*) FROM vehicles WHERE owner_id IS NULL'), [(0,)])   # dry run: untouched
        self.assertEqual(self.q('SELECT id, owner_id FROM vehicles ORDER BY id', out), [(20, None), (30, 1)])
        self.assertTrue(any('vehicles 10' in m for m in rep['merged']))

        catalogue_promote.run(self.db, apply=True)
        self.assertEqual(self.q('SELECT id, owner_id, engine_id, generation_id FROM vehicles ORDER BY id'), [(20, None, 20, 20), (30, 1, 20, 20)])
        self.assertEqual(self.q('SELECT vehicle_id FROM listings'), [(20,)])
        self.assertEqual(self.q('SELECT owner_id FROM insurance_data'), [(1,)])                     # the quote stays account 1's
        self.assertEqual(self.q('SELECT id, archived FROM maintenance_items ORDER BY id'), [(1, 1), (2, 0)])  # older duplicate archived
        self.assertEqual(self.q('SELECT id, owner_id FROM sources ORDER BY id'), [(1, None), (2, 1)])  # the listing source stays private
        self.assertEqual(self.q('SELECT owner_id, vehicle_id FROM catalogue_links ORDER BY owner_id'), [(1, 20), (5, 20)])
        self.assertEqual(self.q('PRAGMA foreign_key_check'), [])
        self.assertTrue(list((Path(self.tmp.name) / 'backups').glob('cars_*.sqlite')))


if __name__ == '__main__':
    unittest.main()
