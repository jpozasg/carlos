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
STALE_LISTING_DAYS, STALE_FUEL_PRICE_DAYS = 14, 30
QUOTE_MAX_AGE_DAYS = 60  # issue #5: insurance quotes expire
TAX_OFFICIAL_SOURCE = 'tax_official_calculator'  # sources.source_type of the BMF Kfz-Steuer-Rechner

# Fuel consumption: one real-world source for every car, the reference included, so the owner's driving style does not
# favour or penalise the own car (user decision 2026-11-03). The owner's own figure is kept as a cross-check only.
PRIMARY_CONSUMPTION = 'Autokostencheck average'
OWNER_CONSUMPTION = 'Owner measured average'
# Insurance: the reference car uses the premium the user actually pays (USER DATA) over comparison quotes.
USER_PREMIUM = 'USER DATA'

# Knowledge tables attach to exactly one level: variant (vehicle_id), engine (engine_id) or generation (generation_id).
SCOPED_TABLES = ('observations', 'insurance_data', 'tax_data', 'maintenance_items', 'reliability_items', 'repair_risks', 'tyre_data')
SCOPE_COLUMNS = ('vehicle_id', 'engine_id', 'generation_id')
LEVELS = {'vehicle_id': 'variant', 'engine_id': 'engine', 'generation_id': 'generation'}
