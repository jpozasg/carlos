"""Paths and constants. The code lives in ROOT; the data (database, photos, backups, dossiers) lives in DATA_DIR,
which is its own private repository: env CARLOS_DATA, default ROOT/data."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('CARLOS_DATA') or ROOT / 'data').resolve()
DB = DATA_DIR / 'cars.sqlite'
MEDIA_DIR = DATA_DIR / 'media'
MD_DIR = DATA_DIR / 'dossiers'
ENV = ROOT / '.env'
STATIC = ROOT / 'static'
HOST, PORT = '127.0.0.1', int(os.environ.get('CARLOS_PORT') or 8000)

# Raspberry Pi with 8 GB: the whole project (database, photos, backups) must stay under 1 GB (owner, 2026-11-07).
STORAGE_LIMIT = 1024 * 1024 ** 2
STORAGE_BUDGET = 900 * 1024 ** 2  # headroom for backups and database growth
MAX_IMAGE_BYTES = 1_500_000  # shortcut: no resizing without Pillow; the capturer must download the ~1024 px version
IMAGE_TYPES = {b'\xff\xd8\xff': ('image/jpeg', 'jpg'), b'\x89PNG': ('image/png', 'png'), b'RIFF': ('image/webp', 'webp')}

# Components of a complete TCO (AGENTS.md); order matters (chart colours). Each is None (unknown) or an amount.
TCO_COMPONENTS = ['fuel', 'insurance', 'tax', 'maintenance', 'repairs', 'tyres', 'purchase_sale', 'depreciation']
RUNNING_COMPONENTS = ('fuel', 'insurance', 'tax', 'maintenance', 'repairs', 'tyres')
UNIT_COST_CATEGORIES = ['repairs', 'maintenance', 'tyres', 'purchase_sale']
# Reliability (issue #54): every weak point belongs to one part; each part counts its RELIABILITY_TOP worst points, so
# documenting more mild issues never makes a car look worse, only a more severe finding does. Higher is better:
# each part keeps RELIABILITY_PART_MAX minus those points, the score is the sum of the parts (max 36).
RELIABILITY_PARTS = ['ENGINE', 'GEARBOX', 'CHASSIS', 'ELECTRICS']
RELIABILITY_TOP = 3
RELIABILITY_PART_MAX = RELIABILITY_TOP * 3  # higher is better: each part starts at 9 (3 × HIGH) and loses its worst points
# Controlled job codes of maintenance items and repair risks (migration 022, part 4 of #106); append new jobs here.
JOBS = ['OIL_SERVICE', 'AIR_FILTER', 'CABIN_FILTER', 'SPARK_PLUGS', 'TIMING_DRIVE', 'COOLANT', 'BRAKE_FLUID', 'BRAKES_FRONT',
        'BRAKES_REAR', 'BATTERY', 'BULBS', 'WIPERS', 'HU', 'FUEL_FILTER', 'DRIVE_BELT', 'CLUTCH',
        'DRIVE_COOLANT', 'REDUCTION_GEAR_OIL', 'GEARBOX_OIL']  # electric drive: battery/motor coolant loop, reduction gear oil (#121)
# engines.fuel_type (#121): a full hybrid is costed as petrol; an electric car's energy is electricity (kWh)
FUEL_TYPES = ['Petrol', 'Diesel', 'Hybrid', 'Plug-in hybrid', 'Electric']
HOME_CHARGING = ['none', 'socket', 'wallbox', 'wallbox_planned']
# leasing (#127): the kind of lease offer, what its rate may include (TCO keys plus GAP cover), the account's choice
LEASE_KINDS = ['km', 'residual', 'abo']
LEASE_INCLUDES = ['insurance', 'tax', 'maintenance', 'repairs', 'tyres', 'gap']
ACQUISITION_MODES = ['buy', 'lease', 'both']
# The setup's DIY choices (preference diy_jobs, the values of DIY in static/js/pages/start.js) → the jobs they cover. A
# job with a code is DIY for an account exactly when one of its choices covers it; a job no choice covers (HU, brake
# fluid, drive belt) is a workshop job. "yearly service" has no job of its own: rows without a code keep their diy flag.
DIY_JOBS = {'oil and filters': ['OIL_SERVICE', 'AIR_FILTER', 'CABIN_FILTER', 'FUEL_FILTER'], 'spark plugs': ['SPARK_PLUGS'],
            'yearly service': [], 'brake pads and discs': ['BRAKES_FRONT', 'BRAKES_REAR'], 'battery': ['BATTERY'],
            'bulbs': ['BULBS'], 'wipers': ['WIPERS'], 'coolant': ['COOLANT'], 'timing belt or chain': ['TIMING_DRIVE'],
            'clutch': ['CLUTCH']}
DIYABLE_JOBS = {j for jobs in DIY_JOBS.values() for j in jobs}  # the research needs both prices of these jobs
STALE_LISTING_DAYS, STALE_FUEL_PRICE_DAYS = 14, 30
QUOTE_MAX_AGE_DAYS = 60  # issue #5: insurance quotes expire
TAX_OFFICIAL_SOURCE = 'tax_official_calculator'  # sources.source_type of the BMF Kfz-Steuer-Rechner

# Fuel consumption: one real-world source for every car, the reference included, so the owner's driving style does not
# favour or penalise the own car (user decision 2026-11-03). The owner's own figure is kept as a cross-check only.
PRIMARY_CONSUMPTION = 'Autokostencheck average'
# Electric cars: one source for every electric car, in kWh/100 km (the same source per drivetrain). Spritmonitor blocks
# automated readers (Cloudflare) and autokostencheck has no real-world EV averages, so the owner chose (2026-11-06, #154)
# ev-database.org's modelled real-world consumption of the exact variant and battery: vehicle side, without charging losses.
PRIMARY_CONSUMPTION_EV = 'EVDB real consumption'
# Charging losses (ADAC: 6–10 % at a wallbox, 13–24 % at a household socket): every kWh in the battery costs this much
# more at the meter; a household socket adds costs.SOCKET_EXTRA_LOSS on top (the extra over a wallbox), never twice.
EV_CHARGING_LOSS = 0.08
# Kfz-Steuer of electric cars (§ 3d KraftStG as amended by the 8. KraftStÄndG, in force 2026-01-01): first registered by
# this month → exempt for 10 years, until this month at the latest (year, month)
EV_TAX_EXEMPT_REGISTERED_BY, EV_TAX_EXEMPT_UNTIL = (2030, 12), (2035, 12)
# a new car (issue #150): no first registration and under this mileage (delivery/demo km); its first HU is due 36 months
# after registration, then every 24 (StVZO Anlage VIII 2.1)
NEW_CAR_MAX_KM, NEW_CAR_FIRST_HU_MONTHS = 100, 36
OWNER_CONSUMPTION = 'Owner measured average'
# Insurance: the reference car uses the premium the user actually pays (USER DATA) over comparison quotes.
USER_PREMIUM = 'USER DATA'

# Knowledge tables attach to exactly one level: variant (vehicle_id), engine (engine_id) or generation (generation_id).
SCOPED_TABLES = ('observations', 'insurance_data', 'tax_data', 'maintenance_items', 'reliability_items', 'repair_risks', 'tyre_data',
                 'research_checks',  # research_checks: the contract's recorded source checks (issue #114)
                 'faults', 'recalls', 'reliability_stats',  # target design (#174): faults, recalls, TÜV/ADAC baseline
                 'review_flags')  # problems to review on a level (#168)
SCOPE_COLUMNS = ('vehicle_id', 'engine_id', 'generation_id')
# Target design levels (docs/target-design.md §2): the new tables and maintenance/research_checks/sources carry all of them.
LEVEL_COLUMNS = SCOPE_COLUMNS + ('gearbox_id', 'engine_family_id', 'gearbox_family_id', 'body_style_id', 'option_id')
LEVELS = {'vehicle_id': 'variant', 'engine_id': 'engine', 'generation_id': 'generation', 'gearbox_id': 'gearbox',
          'engine_family_id': 'engine_family', 'gearbox_family_id': 'gearbox_family', 'body_style_id': 'body_style',
          'option_id': 'option'}
GLOBAL_LEVEL_TABLES = ('maintenance_items',)  # a row without a level is a global default (HU, brake fluid, labour rate)
GEARBOX_TYPES = ['MANUAL', 'DCT', 'AT', 'CVT', 'SINGLE-SPEED']
FAULT_CONSEQUENCES = ['ENGINE_DAMAGE', 'STRANDS', 'SAFETY', 'UNUSABLE', 'COST', 'COSMETIC']
# Severity is derived, never chosen (owner, 2026-11-06, #168): HIGH when it can destroy the engine or gearbox, strand the
# car or is a safety risk, or costs at least SEVERITY_HIGH_EUR; MEDIUM from SEVERITY_MEDIUM_EUR or when the car is
# unusable until fixed; LOW below that while the car still drives.
SEVERITY_HIGH_EUR, SEVERITY_MEDIUM_EUR = 1500, 500
# Fault probability method (owner, 2026-11-06, #168): the wording of the sources → a band of the share of cars affected by
# BAND_REFERENCE_KM or BAND_REFERENCE_YEARS: (central value used for the cost, low, high). 'systemic' needs a manufacturer
# trace (extended warranty, Kulanz, TPI, class action); a forum-only fault is one band milder, never above 'common'.
BAND_REFERENCE_KM, BAND_REFERENCE_YEARS = 200_000, 15
FREQUENCY_BANDS = {'systemic': (0.50, 0.40, 0.70), 'widespread': (0.25, 0.20, 0.40), 'common': (0.12, 0.08, 0.20),
                   'occasional': (0.05, 0.03, 0.08), 'rare': (0.015, 0.005, 0.03)}
FORUM_MAX_BAND = 'common'
# every curve continues to these limits (no zero risk beyond the last point stated); four shapes
CURVE_END_KM, CURVE_END_YEARS = 300_000, 20
FAULT_SHAPES = ['WEAR_KM', 'AGE', 'WINDOW', 'RANDOM']
HEAVY_USE_MIX = ('Mostly town',)  # setup driving_mix values that mean heavy use (short trips)
# Statistics vs faults (#168): a model whose TÜV/ADAC figure is STATS_MISMATCH_RATIO × the class average or more while its
# faults predict at most 1 / ratio × the catalogue average for that age (or the other way round) is flagged and gets a
# follow-up research request; nothing is scaled automatically.
STATS_MISMATCH_RATIO = 1.5
TYPICAL_KM_PER_YEAR = 15000  # to place an age class on a fault's km curve in the consistency check
NCAP_REGIME_YEAR = 2009  # Euro NCAP's stricter overall rating; earlier ratings count one star less (#169)
PRIVATE_SALE_DISCOUNT = 0.05  # asking → private sale price (#166): ESTIMATED, range 3–10 %, no primary source found
MARKET_MIN_PER_BAND, MARKET_MAX_AGE_DAYS = 5, 183  # resale sample (#166): ≥ 5 cars in each of the three bands, 6 months

# knowledge rows that may carry a first-registration window (applies_from/applies_to, issue #153)
WINDOWED_TABLES = ('maintenance_items', 'repair_risks', 'reliability_items', 'faults', 'recalls')

# Controlled component codes of faults (#221 phase 3, docs/design-two-agent-research.md section 4): {part: [(code, covers, pattern)]}.
# `pattern` (first match wins, in this order) feeds the back-fill and the suggestion in 400 texts, never a silent code on insert.
FAULT_COMPONENTS = {
    'ENGINE': [
        ('TIMING_BELT', 'belt, wet belt, tensioner, belt-driven water pump', r'timing belt|wet belt|belt in oil|toothed belt|camshaft belt'),
        ('TIMING_CHAIN', 'chain, guides, tensioner, rattle', r'timing chain|chain (stretch|rattle|tensioner)|tensioner.*rattle'),
        ('CAM_PHASER', 'camshaft adjuster, VANOS, cam gear/pulley', r'vanos|camshaft (adjuster|pulley|gear|phaser)|cam (phaser|gear|pulley)|vvt'),
        ('OIL_CONSUMPTION', 'piston rings, valve stem seals, crankcase ventilation / PCV', r'oil consumption|piston ring|pcv|crankcase vent|valve stem'),
        ('OIL_LEAK', 'gaskets and seals leaking oil', r'oil (loss|leak)|valve cover|sump gasket|rear main seal'),
        ('ENGINE_INTERNALS', 'oil pump, lifters, crankshaft, bores, head gasket, oil pressure',
         r'oil pump|lifter|tappet|crankshaft(?! position)|cylinder bore|head gasket|oil pressure|bearing shell|piston'),
        ('COOLING', 'water pump, thermostat, hoses, expansion tank, radiator, fan', r'cool|water pump|thermostat|radiator|expansion tank|hose'),
        ('IGNITION', 'coils, ignition module, plugs (misfire)', r'ignition|coil|spark plug|misfire'),
        ('FUEL_SYSTEM', 'injectors, high-pressure pump/line, in-tank pump, intake-valve deposits',
         r'injector|fuel pump|high.pressure (pump|line)|fuel (line|rail)|intake valve|carbon deposit'),
        ('TURBO', 'turbocharger, wastegate, boost control', r'turbo|wastegate|boost'),
        ('EMISSIONS', 'EGR, DPF, catalyst, lambda sensors, AdBlue/SCR, charcoal canister, tank venting, exhaust manifold',
         r'egr|dpf|particulate|catalyst|catalytic|lambda|adblue|scr\b|charcoal|canister|tank vent|exhaust manifold|nox'),
        ('ENGINE_MANAGEMENT', 'throttle body, air-mass meter, intake flaps, engine sensors and ECU, idle/judder control',
         r'throttle|air.mass|maf|intake flap|twinport|crankshaft position|sensor|ecu|idle|judder'),
        ('ENGINE_MOUNTS', 'engine and gearbox mounts', r'engine mount|motor mount|gearbox mount|engine bracket'),
        ('HV_BATTERY', 'high-voltage / hybrid traction battery', r'hybrid battery|hv battery|traction battery|nimh|battery pack|battery module'),
        ('ELECTRIC_DRIVE', 'motor, inverter, DC-DC, on-board charger and port, 48 V starter-generator',
         r'inverter|dc.dc|on.board charger|charging port|electric motor|48 ?v|mild.hybrid|e.?drive'),
        ('OTHER', 'needs `notes` saying what it is', r'(?!)')],
    'GEARBOX': [
        ('DUAL_MASS_FLYWHEEL', 'dual-mass flywheel', r'flywheel'),
        ('CLUTCH_ACTUATION', 'slave/master cylinder, release bearing, clutch actuator, delay valve',
         r'slave|master cylinder|release bearing|actuator|delay valve|clutch (hydraulic|cable)'),
        ('CLUTCH', 'clutch disc/pressure plate, dry or wet dual-clutch packs (judder, wear)', r'clutch|dq\d+|dual.clutch|double clutch'),
        ('MECHATRONICS', 'DCT/AT control unit, valve block, accumulator, solenoids', r'mechatronic|valve block|control unit|accumulator|solenoid|tcu'),
        ('AT_CVT_INTERNALS', 'torque converter, automatic/CVT internals, shift quality', r'automatic|cvt|torque converter|shift quality|planetary'),
        ('GEARS_SYNCHROS', 'synchronisers, gear wheels', r'synchro|gear wheel|crunch'),
        ('BEARINGS_DIFFERENTIAL', 'shaft bearings, differential, satellite gears (whine)', r'differential|satellite|bearing|whine'),
        ('SHIFT_MECHANISM', 'linkage, cables, lever bushes', r'shift (mechanism|linkage|cable|lever)|gear linkage|selector'),
        ('GEARBOX_LEAK', 'gearbox and output-shaft seals', r'gearbox (oil )?leak|input shaft seal|output seal|transmission leak|oil leak'),
        ('DRIVESHAFT', 'driveshafts, CV joints and boots, propshaft and joint disc', r'drive ?shaft|cv joint|propshaft|prop shaft|joint disc|gelenkscheibe|boot'),
        ('OTHER', 'needs `notes`', r'(?!)')],
    'CHASSIS': [
        ('PARKING_BRAKE', 'handbrake lever, cable, mechanism', r'parking brake|handbrake|hand brake'),
        ('BRAKE_LINES', 'brake hoses and lines, servo, pedal', r'brake (hose|line)|servo|brake pedal|booster'),
        ('BRAKES', 'pads, discs, calipers, drums, ABS/ESP hydraulic unit', r'brake|caliper|disc|drum|pads'),
        ('WHEEL_BEARINGS', 'wheel bearings', r'wheel bearing'),
        ('SPRINGS_DAMPERS', 'coil springs, spring seats, shock absorbers, strut top mounts', r'spring|damper|shock|strut'),
        ('STEERING', 'tie-rod ends, steering joints and gear, play, power-steering hoses/assist', r'steering|tie.rod|power.steering|ehps'),
        ('SUSPENSION_ARMS', 'control arms, bushes, ball joints, anti-roll bar links, axle mounts and bolts',
         r'suspension|control arm|wishbone|bush|ball joint|anti.roll|stabili[sz]er|axle|subframe'),
        ('EXHAUST', 'pipes, flex pipe, silencers', r'exhaust|silencer|muffler|flex pipe'),
        ('WATER_INGRESS', 'seals, drains, leaks into the cabin or boot', r'water (ingress|leak)|leak.*(cabin|boot)|drain'),
        ('ROOF', 'sunroof, panoramic roof, convertible roof (body style / option level)', r'roof|sunroof|convertible|soft ?top'),
        ('BODY_RUST', 'sills, wheel arches, seams, underbody, tailgate rust', r'rust|corrosion|sill|wheel arch|underbody|body panel'),
        ('BODY_FITTINGS', 'dashboard, wiper linkage, door/tailgate mechanics, seat-belt anchors, wheels',
         r'dashboard|wiper|door|tailgate|seat.?belt|seat|trim|wheel|hinge|lock'),
        ('OTHER', 'needs `notes`', r'(?!)')],
    'ELECTRICS': [
        ('BATTERY_12V', 'starter/start-stop battery, terminals, positive cable', r'12 ?v battery|start.stop battery|battery (plus|terminal|connector|cable)|^battery'),
        ('STARTER_ALTERNATOR', 'starter, solenoid, relay, alternator', r'starter|alternator|generator(?! gas)|relay'),
        ('AIRBAG', 'airbags, gas generators, airbag control unit, occupant sensing, pretensioners', r'airbag|gas generator|pretensioner|occupant|takata'),
        ('ABS_ESP', 'ABS sensors and ABS/ESP control unit', r'abs|esp\b|wheel speed'),
        ('LIGHTING', 'headlights, aim, levelling, tail lights, indicators, bulbs', r'light|lamp|headlight|indicator|bulb|led\b'),
        ('AIR_CONDITIONING', 'compressor, condenser, refrigerant, flap actuators, blower', r'a/c|air.?con|climate|compressor|condenser|refrigerant|blower|heater'),
        ('INFOTAINMENT', 'display, touchscreen, radio/navigation, instrument cluster, emergency call',
         r'infotainment|touchscreen|display|radio|navigation|instrument cluster|e-?call|screen'),
        ('DRIVER_ASSISTANCE', 'cameras, radar, tyre pressure monitoring', r'camera|radar|tyre pressure|tire pressure|tpms|assist'),
        ('WIRING', 'harnesses, plugs, fretting corrosion, power distributor, grounds, moisture', r'wiring|harness|plug|fretting|distributor|ground|connector'),
        ('BODY_ELECTRONICS', 'window regulators and switches, central locking, immobiliser, ignition lock, seat heating, washer pump, stalks',
         r'window|central locking|immobili[sz]er|ignition lock|seat heating|washer|stalk|switch|mirror'),
        ('OTHER', 'needs `notes`', r'(?!)')],
}
FAULT_COMPONENT_CODES = sorted({code for rows in FAULT_COMPONENTS.values() for code, _, _ in rows})


def suggest_component(part, text):
    """The code whose pattern first matches a component name (for the back-fill and error texts); None when nothing fits."""
    import re
    return next((code for code, _, pat in FAULT_COMPONENTS.get(part, ()) if re.search(pat, str(text or ''), re.I)), None)
