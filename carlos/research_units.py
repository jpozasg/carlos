"""Units of a research request (#218 phase 2): which contract items (carlos/research.py ITEMS and the listing items) each
unit owns, and in which stages the units run after the listing is captured. `lst.insurance` is the INSURANCE unit (browser, only for accounts that opted in, see research_requests.advance)."""
UNITS = ('CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING', 'INSURANCE', 'RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')  # the last four: two-agent research (#253), staged writes in carlos/staging.py
BROWSER_UNITS = ('CAPTURE', 'TAX', 'INSURANCE')
# INSURANCE last: the slowest and most often blocked browser step runs after everything else is written
LEGACY_UNITS = ('VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX')  # kept so open legacy requests finish
LEGACY_STAGES = (('VARIANT',), ('GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX'), ('TAX',), ('LISTING',), ('INSURANCE',))
# #253 P5a: two independent research runs, the server compares, the arbiter settles material disputes, the merge writes; TAX needs the merged identity
STAGES = (('RESEARCH_A', 'RESEARCH_B'), ('ARBITER',), ('MERGE',), ('TAX',), ('LISTING',), ('INSURANCE',))
SECOND_RUN = False  # #283: one research run per car (RESEARCH_A); True also runs RESEARCH_B and compares/arbitrates the pair (#253)
FLOW = 'dual'  # rollback switch: 'units' gives new requests the legacy stages again
SERVER_UNITS = ('MERGE',)  # the worker runs no Claude for these
DUAL_UNITS = ('RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')
RESEARCH_MAX_ATTEMPTS = 2  # a research run closes DONE with gaps after this many attempts (the other run and the merge may still cover them)

_PARTS = ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')
UNIT_ITEMS = {
    'CAPTURE': ['lst.capture', 'lst.photos'],
    'VARIANT': ['var.identity', 'var.consumption', 'var.tyres', 'var.gearbox', 'var.gearbox_level', 'gbx.identity'],
    'GENERATION': ['gen.identity', 'gen.facelift', 'gen.recalls', 'gen.risks', 'gen.baseline', 'gen.safety', 'bdy.risks']
                  + [f'rel.{p}.{s}' for p in _PARTS for s in ('adac', 'tuev', 'guide')],
    'GEN_MAINTENANCE': ['gen.hu', 'gen.brake_fluid', 'gen.brakes'],
    'ENGINE': ['eng.identity', 'eng.identity_ev', 'eng.hv_battery', 'eng.drive_coolant', 'eng.reduction_gear_oil', 'eng.oil',
               'eng.spark_plugs', 'eng.timing_belt', 'eng.timing_chain', 'eng.coolant',
               'eng.risks', 'fam.risks', 'rel.ENGINE.engine_specific'],
    'GEARBOX': ['gbx.service', 'gbx.clutch', 'gbx.risks', 'rel.GEARBOX.gearbox_specific'],
    'TAX': ['var.tax', 'lst.tax_covered'],
    'LISTING': ['lst.valuation', 'lst.purchase_sale', 'lst.checklist'],
    'INSURANCE': ['lst.insurance'],
}
UNIT_OF = {i: u for u, ids in UNIT_ITEMS.items() for i in ids}
# #253: the runs that write to staging (their /api/agent writes never reach the catalogue) and the items they cover (no lst.*)
STAGED_UNITS = ('RESEARCH_A', 'RESEARCH_B', 'ARBITER')
RESEARCH_ITEMS = [i for u in LEGACY_UNITS for i in UNIT_ITEMS[u]]
ITEM_UNIT = {'RESEARCH_A': 'RESEARCH', 'RESEARCH_B': 'RESEARCH'}  # both runs own the same items
# the variant column a unit is keyed on (NULL = never shared between requests); the listing id for CAPTURE and LISTING
LEVEL_COLUMN = {'VARIANT': 'id', 'TAX': 'id', 'GENERATION': 'generation_id', 'GEN_MAINTENANCE': 'generation_id',
                'ENGINE': 'engine_id', 'GEARBOX': 'gearbox_id'}
