"""The evenness script (.claude/skills/research-audit) on the synthetic fixture; it must stay read-only and print no personal data."""
import contextlib, datetime, importlib.util, io, os, shutil, sqlite3, tempfile, unittest
from tests import fixture

SCRIPT = os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills', 'research-audit', 'scripts', 'evenness.py')
spec = importlib.util.spec_from_file_location('evenness', SCRIPT)
evenness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evenness)


class Evenness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = fixture.build(os.path.join(self.dir.name, 'cars.sqlite'))
        c = sqlite3.connect(self.path)
        old = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
        with c:  # one fault without basis or quote, a zero price, a stale quote, a one-price DIY job, a bare NONE FOUND
            c.execute("INSERT INTO faults (engine_id, component, part, consequence, existence, source_id, frequency_band, share_low, share_high, shape, parts_eur, labor_eur, diy_hours, component_code) "
                      "VALUES (?, 'Timing chain stretch', 'ENGINE', 'ENGINE_DAMAGE', 'REPORTED', ?, 'common', 0.1, 0.2, 'WEAR_KM', 400, 600, 0, 'TIMING_CHAIN')", (fixture.E_A, fixture.SRC_GUIDE))
            c.execute("UPDATE insurance_data SET quote_date=? WHERE vehicle_id=? AND premium_status='QUOTE'", (old, fixture.V_A))
            c.execute("INSERT INTO unit_costs (listing_id, category, item, parts_eur, status, source_id) VALUES (?, 'maintenance', 'Timing chain kit (due by age)', 500, 'ESTIMATED', ?)",
                      (fixture.CAR_A, fixture.SRC_GUIDE))
            c.execute("INSERT INTO research_checks (engine_id, task, source_id, result, notes, contract_version) VALUES (?, 'eng.coolant', ?, 'NONE FOUND', 'nothing', 10)",
                      (fixture.E_B, fixture.SRC_GUIDE))
        c.close()
        self.before = self.read()

    def read(self):
        with open(self.path, 'rb') as f:
            return f.read()

    def tearDown(self):
        self.dir.cleanup()

    def run_script(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            evenness.main([self.path])
        return out.getvalue()

    def test_table_and_defects(self):
        out = self.run_script()
        self.assertIn('L2 Alpha Hatch Mk1', out)
        self.assertIn('FAULT_NO_BASIS', out)
        self.assertIn('FAULT_NO_QUOTE', out)
        self.assertIn('ZERO_NOT_NULL', out)
        self.assertIn('STALE_QUOTE', out)
        self.assertIn('DIY_PAIR', out)
        self.assertIn('CHECK_NO_EVIDENCE', out)
        self.assertIn('CERTAIN_NO_RESTART', out)
        self.assertIn('DOUBLE_COUNT', out)  # the certain chain kit and the chain fault share two content words

    def test_expected_fault_cost(self):
        c = sqlite3.connect(self.path)
        car = evenness.Car(c, evenness.q(c, 'SELECT * FROM listings WHERE id=?', fixture.CAR_A)[0])
        m, _ = evenness.metrics(car, datetime.date.today())
        c.close()
        self.assertEqual(m['exp_fault_eur'], 150)  # (400 + 600) x 0.15
        self.assertEqual(m['engine_faults'], 1)

    def test_read_only_and_no_personal_data(self):
        out = self.run_script()
        self.assertEqual(self.before, self.read())
        for secret in ('Dealer A', 'Testville', '1111', 'AAA', 'admin'):  # seller, location, HSN/TSN, username
            self.assertNotIn(secret, out)
        c = evenness.connect(self.path)
        with self.assertRaises(sqlite3.OperationalError):
            c.execute('CREATE TABLE x (a)')
        c.close()

    def sql(self, sql, *args):
        c = sqlite3.connect(self.path)
        with c:
            c.execute(sql, args)
        c.close()

    def fault(self, col, i, **kw):
        row = dict(component='Oil leak', part='ENGINE', consequence='COST', existence='REPORTED', source_id=fixture.SRC_GUIDE, frequency_band='common',
                   share_low=0.1, share_high=0.2, shape='WEAR_KM', parts_eur=100, labor_eur=100, component_code='OIL_LEAK', **{col: i})
        row.update(kw)
        self.sql('INSERT INTO faults (%s) VALUES (%s)' % (','.join(row), ','.join('?' * len(row))), *row.values())

    def car(self, listing=fixture.CAR_A):
        c = sqlite3.connect(self.path)
        m, d = evenness.metrics(evenness.Car(c, evenness.q(c, 'SELECT * FROM listings WHERE id=?', listing)[0]), datetime.date.today())
        c.close()
        return m, [x[0] for x in d]

    def test_build_window_excludes_a_fault_fixed_before_the_car(self):
        self.fault('engine_id', fixture.E_A, applies_to='2010-12')  # the car is first registered 2011-06
        self.assertEqual(self.car()[0]['faults'], 1)  # only the chain fault of setUp
        self.fault('engine_id', fixture.E_A, component='Oil pump', component_code='OIL_PUMP', applies_to='2011-12')
        self.assertEqual(self.car()[0]['faults'], 2)

    def test_body_style_faults_count(self):
        self.sql('INSERT INTO body_styles (id, generation_id, name) VALUES (1, ?, ?)', fixture.G1, 'Hatch')
        self.sql('UPDATE vehicles SET body_style_id=1 WHERE id=?', fixture.V_A)
        self.fault('body_style_id', 1, component='Roof seal', component_code='SEAL')
        self.assertEqual(self.car()[0]['faults'], 2)

    def test_same_code_on_two_levels_is_a_duplicate_unless_marked_distinct(self):
        self.fault('generation_id', fixture.G1, component='Chain', component_code='TIMING_CHAIN')
        self.assertIn('DUPLICATE_LEVELS', self.car()[1])
        self.sql("UPDATE faults SET notes='Distinct from fault #1: the generation row is the chain guide' WHERE generation_id=?", fixture.G1)
        self.assertNotIn('DUPLICATE_LEVELS', self.car()[1])

    def test_check_evidence_rules(self):
        chk = "INSERT INTO research_checks (%s, task, source_id, result, notes, contract_version) VALUES (?, ?, ?, ?, ?, 10)"
        self.sql(chk % 'generation_id', fixture.G1, 'gen.facelift', fixture.SRC_GUIDE, 'N/A', 'no facelift in this generation')  # a reason is enough
        self.sql(chk % 'engine_id', fixture.E_A, 'eng.coolant', fixture.SRC_GUIDE, 'NONE FOUND', 'our research found nothing')  # "research" is not a search
        self.sql(chk % 'generation_id', fixture.G1, 'rel.tuev', fixture.SRC_GUIDE, 'N/A', 'not in the report')  # a source claim needs the URL
        self.sql(chk % 'engine_id', fixture.E_A, 'eng.risks', fixture.SRC_GUIDE, 'NONE FOUND', 'https://example.test/am14')  # contradicts the chain fault
        _, codes = self.car()
        self.assertEqual(codes.count('CHECK_NO_EVIDENCE'), 2)
        self.assertIn('NONE_FOUND_CONTRADICTED', codes)

    def test_listing_without_a_variant_is_reported_not_a_crash(self):
        self.sql("INSERT INTO listings (id, vehicle_id, source_id, platform, listing_status, is_reference, owner_id) VALUES (9, NULL, ?, 'Test', 'UNDER REVIEW', 0, 1)", fixture.SRC_LISTING)
        out = self.run_script()
        self.assertIn('NO_VARIANT', out)
        self.assertIn('L2 Alpha Hatch Mk1', out)

    def test_opens_a_path_with_uri_characters(self):
        odd = os.path.join(self.dir.name, 'a b%20c#d?e')
        os.mkdir(odd)
        shutil.copy(self.path, os.path.join(odd, 'cars.sqlite'))
        c = evenness.connect(os.path.join(odd, 'cars.sqlite'))
        self.assertEqual(c.execute('SELECT count(*) FROM listings').fetchone()[0], 3)
        c.close()


if __name__ == '__main__':
    unittest.main()
