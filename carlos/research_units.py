"""Units of a research request (#218 phase 2): which contract items (carlos/research.py ITEMS and the listing items) each
unit owns, and in which stages the units run after the listing is captured. The insurance quote is not a unit: it is entered by hand per listing (2026-11-22).
The single-run units (VARIANT, GENERATION, GEN_MAINTENANCE, ENGINE, GEARBOX) and requests without a unit are retired (owner decision 2026-11-22):
`refusal()` says why a request is refused; the worker never runs them."""
UNITS = ('CAPTURE', 'TAX', 'LISTING', 'RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')  # RESEARCH_A/B, ARBITER, MERGE: two-agent research (#253), staged writes in carlos/staging.py
RETIRED_UNITS = ('VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'INSURANCE')  # refused at claim, never run (INSURANCE: removed 2026-11-22)
BROWSER_UNITS = ('CAPTURE', 'TAX')
# #253 P5a: two independent research runs, the server compares, the arbiter settles material disputes, the merge writes; TAX needs the merged identity
STAGES = (('RESEARCH_A', 'RESEARCH_B'), ('ARBITER',), ('MERGE',), ('TAX',), ('LISTING',))
SECOND_RUN = False  # #283: one research run per car (RESEARCH_A); True also runs RESEARCH_B and compares/arbitrates the pair (#253)
SERVER_UNITS = ('MERGE',)  # the worker runs no Claude for these
DUAL_UNITS = ('RESEARCH_A', 'RESEARCH_B', 'ARBITER', 'MERGE')
RESEARCH_MAX_ATTEMPTS = 2  # a research run closes DONE with gaps after this many attempts (the other run and the merge may still cover them)

UNIT_ITEMS = {
    'CAPTURE': ['lst.capture', 'lst.photos'],
    'TAX': ['var.tax', 'lst.tax_covered'],
    'LISTING': ['lst.valuation', 'lst.purchase_sale', 'lst.checklist'],
}
# the contract items the research runs own (RESEARCH_A and RESEARCH_B own the same ones)
RESEARCH_ITEMS = ['var.identity', 'var.consumption', 'var.tyres', 'var.gearbox_level', 'gbx.identity',
                  'gen.identity', 'gen.facelift', 'gen.recalls', 'gen.risks', 'gen.safety', 'bdy.risks',
                  'rel.adac_gwinfo', 'rel.adac', 'rel.tuev',
                  'gen.hu', 'gen.brake_fluid', 'gen.brakes',
                  'eng.identity', 'eng.identity_ev', 'eng.hv_battery', 'eng.drive_coolant', 'eng.reduction_gear_oil', 'eng.oil',
                  'eng.spark_plugs', 'eng.timing_belt', 'eng.timing_chain', 'eng.coolant',
                  'eng.risks', 'fam.risks', 'rel.autoscore', 'rel.enginescope',
                  'gbx.service', 'gbx.clutch', 'gbx.risks']
UNIT_OF = {i: u for u, ids in UNIT_ITEMS.items() for i in ids}
UNIT_OF.update({i: 'RESEARCH' for i in RESEARCH_ITEMS})
# #253: the runs that write to staging (their /api/agent writes never reach the catalogue) and the items they cover (no lst.*)
STAGED_UNITS = ('RESEARCH_A', 'RESEARCH_B', 'ARBITER')
ITEM_UNIT = {'RESEARCH_A': 'RESEARCH', 'RESEARCH_B': 'RESEARCH'}  # both runs own the same items
# the variant column a unit is keyed on (NULL = never shared between requests)
LEVEL_COLUMN = {'TAX': 'id'}


def refusal(unit):
    """Why a request with this unit is refused (owner decision 2026-11-22), None when the current flow runs it."""
    if unit is None:
        return ('refused: a request without a unit is the retired single run (2026-11-22); queue the listing again from the Compare page')
    if unit in RETIRED_UNITS:
        return f'refused: unit {unit} is retired (2026-11-22); only the current units run. Queue the listing again from the Compare page'
    if unit not in UNITS:
        return f'refused: unknown unit {unit}'
    return None
