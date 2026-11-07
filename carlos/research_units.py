"""Units of a research request (#218 phase 2): which contract items (carlos/research.py ITEMS and the listing items) each
unit owns, and in which stages the units run after the listing is captured. `lst.insurance` is the owner's and never queued."""
UNITS = ('CAPTURE', 'VARIANT', 'GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX', 'TAX', 'LISTING')
BROWSER_UNITS = ('CAPTURE', 'TAX')
STAGES = (('VARIANT',), ('GENERATION', 'GEN_MAINTENANCE', 'ENGINE', 'GEARBOX'), ('TAX',), ('LISTING',))

_PARTS = ('ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS')
UNIT_ITEMS = {
    'CAPTURE': ['lst.capture', 'lst.photos'],
    'VARIANT': ['var.identity', 'var.consumption', 'var.tyres', 'var.gearbox', 'var.gearbox_level', 'gbx.identity'],
    'GENERATION': ['gen.identity', 'gen.facelift', 'gen.recalls', 'gen.risks', 'gen.baseline', 'gen.safety', 'bdy.risks']
                  + [f'rel.{p}.{s}' for p in _PARTS for s in ('adac', 'tuev', 'guide')],
    'GEN_MAINTENANCE': ['gen.hu', 'gen.brake_fluid', 'gen.brakes', 'gen.battery', 'gen.wipers', 'gen.cabin_filter'],
    'ENGINE': ['eng.identity', 'eng.identity_ev', 'eng.hv_battery', 'eng.drive_coolant', 'eng.reduction_gear_oil', 'eng.oil',
               'eng.air_filter', 'eng.spark_plugs', 'eng.fuel_filter', 'eng.timing_belt', 'eng.timing_chain', 'eng.coolant',
               'eng.risks', 'fam.risks', 'rel.ENGINE.engine_specific'],
    'GEARBOX': ['gbx.service', 'gbx.clutch', 'gbx.risks', 'gfam.risks', 'rel.GEARBOX.gearbox_specific'],
    'TAX': ['var.tax', 'lst.tax_covered'],
    'LISTING': ['lst.valuation', 'lst.purchase_sale', 'lst.checklist'],
}
UNIT_OF = {i: u for u, ids in UNIT_ITEMS.items() for i in ids}
# the variant column a unit is keyed on (NULL = never shared between requests); the listing id for CAPTURE and LISTING
LEVEL_COLUMN = {'VARIANT': 'id', 'TAX': 'id', 'GENERATION': 'generation_id', 'GEN_MAINTENANCE': 'generation_id',
                'ENGINE': 'engine_id', 'GEARBOX': 'gearbox_id'}
