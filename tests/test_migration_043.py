"""Migration 043 (#353): source_keys and source_ratings, and reliability_stats dropped only while empty. Synthetic data."""
import sqlite3, tempfile, unittest
from pathlib import Path
from carlos import config
from tests import fixture as fx
from tests.fixture import E_A, G1

SQL = (config.ROOT / 'migrations' / '043_reliability_sources.sql').read_text(encoding='utf-8')
KEY = {'source_key': 'AUTOSCORE', 'external_key': 'n46', 'url': 'https://autoscore.pro/engine/n46', 'checked_date': '2026-11-10'}
RATING = {'source_key': 'TUEV_REPORT', 'external_key': 'VW Polo', 'edition': '2026', 'age_from': 6, 'age_to': 7, 'value_num': 20.1,
          'class_average': 16.0, 'url': 'https://www.tuev-verband.de/pressemitteilungen/tuev-report-2026', 'checked_date': '2026-11-10'}


class Migration043Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db = Path(self.tmp.name) / 'cars.sqlite'
        fx.build(db)
        self.c = sqlite3.connect(db)
        self.c.execute('PRAGMA foreign_keys=ON')
        self.addCleanup(self.c.close)

    def put(self, table, row):
        row = {**row, 'source_id': fx.SRC_HU}
        return self.c.execute(f'INSERT INTO {table} ({",".join(row)}) VALUES ({",".join("?" * len(row))})', list(row.values())).lastrowid

    def refused(self, table, row):
        with self.assertRaises(sqlite3.IntegrityError):
            self.put(table, row)

    def test_tables_and_checks(self):
        names = {r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'source_keys', 'source_ratings'} <= names)
        self.assertNotIn('reliability_stats', names)
        self.put('source_keys', {**KEY, 'engine_id': E_A})
        self.put('source_keys', {**KEY, 'source_key': 'ADAC_GWINFO', 'generation_id': G1, 'fuel_type': 'Diesel'})
        self.refused('source_keys', {**KEY, 'engine_id': E_A, 'generation_id': G1})            # exactly one level
        self.refused('source_keys', KEY)
        self.refused('source_keys', {**KEY, 'engine_id': E_A, 'url': 'http://x.test'})         # https only
        self.refused('source_keys', {**KEY, 'generation_id': G1, 'fuel_type': 'Gas'})
        self.refused('source_keys', {**KEY, 'engine_id': 999999})                              # foreign key
        self.refused('source_keys', {**KEY, 'engine_id': E_A, 'owner_id': fx.ADMIN})           # shared catalogue only
        self.put('source_ratings', RATING)
        self.put('source_ratings', {**RATING, 'source_key': 'ADAC_PANNENSTATISTIK', 'age_from': None, 'age_to': None, 'reg_year': 2016, 'band': 3})
        for bad in ({'age_from': None}, {'age_to': 5}, {'reg_year': 2016}, {'band': 6}, {'band': 0}, {'value_num': -1},
                    {'class_average': 0}, {'cost_min_eur': 500, 'cost_max_eur': 200}, {'sample_count': 0}, {'url': 'ftp://x'}):
            self.refused('source_ratings', {**RATING, 'edition': f'x{len(bad)}', **bad})

    def test_unique_only_among_live_rows(self):
        k = self.put('source_keys', {**KEY, 'engine_id': E_A})
        self.refused('source_keys', {**KEY, 'engine_id': E_A, 'external_key': 'other'})        # one key per source and level
        r = self.put('source_ratings', RATING)
        self.refused('source_ratings', {**RATING, 'external_key': 'vw polo'})                 # case-insensitive
        self.c.execute('UPDATE source_keys SET archived=1 WHERE id=?', (k,))
        self.c.execute('UPDATE source_ratings SET archived=1 WHERE id=?', (r,))
        self.put('source_keys', {**KEY, 'engine_id': E_A, 'external_key': 'other'})            # a new edition after archiving
        self.put('source_ratings', RATING)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_drops_reliability_stats_only_when_empty(self):
        for rows, dropped in ((1, False), (0, True)):
            c = sqlite3.connect(':memory:')
            c.execute('CREATE TABLE reliability_stats (id INTEGER PRIMARY KEY, value REAL)')
            c.executemany('INSERT INTO reliability_stats (value) VALUES (?)', [(5.0,)] * rows)
            c.commit()
            try:
                c.executescript(f'BEGIN;\n{SQL}\nCOMMIT;')
            except sqlite3.IntegrityError:
                c.rollback()                                                                    # what migrate.run does on a failure
            names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual('reliability_stats' not in names, dropped)
            self.assertEqual('source_ratings' in names, dropped)                               # all or nothing
            if not dropped:
                self.assertEqual(c.execute('SELECT count(*) FROM reliability_stats').fetchone()[0], 1)
            c.close()


if __name__ == '__main__':
    unittest.main()
