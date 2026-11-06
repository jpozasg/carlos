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

# Raspberry Pi with 8 GB: the whole project (database, photos, backups) must stay under 500 MB.
STORAGE_LIMIT = 500 * 1024 ** 2
STORAGE_BUDGET = 450 * 1024 ** 2  # headroom for backups and database growth
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
        'DRIVE_COOLANT', 'REDUCTION_GEAR_OIL',  # electric drive: battery/motor coolant loop, reduction gear oil (#121)
        'GEARBOX_OIL']  # DCT / automatic / CVT oil service, on the gearbox level (#164)
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

# Knowledge tables attach to exactly one level: variant (vehicle_id), engine (engine_id), generation (generation_id) or,
# for the tables in GEARBOX_TABLES, gearbox (gearbox_id, issue #164).
SCOPED_TABLES = ('observations', 'insurance_data', 'tax_data', 'maintenance_items', 'reliability_items', 'repair_risks', 'tyre_data',
                 'research_checks')  # research_checks: the contract's recorded source checks (issue #114)
SCOPE_COLUMNS = ('vehicle_id', 'engine_id', 'generation_id', 'gearbox_id')
LEVELS = {'vehicle_id': 'variant', 'engine_id': 'engine', 'generation_id': 'generation', 'gearbox_id': 'gearbox'}
GEARBOX_TABLES = ('maintenance_items', 'repair_risks', 'reliability_items', 'research_checks')  # and sources
GEARBOX_TYPES = ['MANUAL', 'DCT', 'AT', 'CVT', 'SINGLE-SPEED']  # DCT = dual clutch (DSG), AT = torque-converter automatic

# knowledge rows that may carry a first-registration window (applies_from/applies_to, issue #153)
WINDOWED_TABLES = ('maintenance_items', 'repair_risks', 'reliability_items')
