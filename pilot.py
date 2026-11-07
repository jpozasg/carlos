"""Research pilot (issue #167): two independent research runs of the same known cars on two reset copies of the
database, compared with pilot_compare.py before the real reset and the full re-research.

  python pilot.py setup [--dir DIR]   copies the real database twice (DIR/a, DIR/b; default: <data dir>/backups/pilot,
                                      ignored by the data repository),
                                      applies the migrations and the research reset (account 5 kept) and copies the
                                      pilot cars' photos; never writes the real database
  python pilot.py queue [--dir DIR]   with both pilot servers running, queues the pilot cars as research requests
                                      for the carlostester account on each (admin token: AGENT_TOKEN or .env) for the REQUESTER account (carlostester); re-run it to queue
                                      the rest when the account's 5 open requests are full
  python pilot.py commands [--dir DIR]  prints the commands to start the servers and the owner's workers

The pilot cars cover the known cases of the owner's listings: PureTech wet belt, EA211 (two models), EA111, a DSG
and a full hybrid."""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import migrate
import research_reset
from capture_listing import Api, ApiError, load_token
from carlos import config

ACCOUNT = 5     # kept by the reset: only the source of the pilot cars' URLs and photos
REQUESTER = 4   # carlostester: the account the pilot requests and the researched cars belong to (owner, 2026-11-07)
CARS = {40: 'Peugeot 208 1.2 PureTech (wet belt)', 54: 'VW Polo 1.2 TSI (EA211)', 64: 'VW Golf Sportsvan 1.4 TSI (EA211)',
        47: 'VW Golf VI 1.4 (EA111)', 56: 'Seat Leon ST 1.8 TSI DSG', 60: 'Toyota Yaris 1.5 Hybrid'}
RUNS = {'a': 8021, 'b': 8022}


def setup(d):
    for run in RUNS:
        dst = d / run
        if dst.exists():
            shutil.rmtree(dst)
        (dst / 'media').mkdir(parents=True)
        src = sqlite3.connect(f'file:{config.DB}?mode=ro', uri=True)
        out = sqlite3.connect(dst / 'cars.sqlite')
        src.backup(out); out.close(); src.close()
        migrate.run(dst / 'cars.sqlite')
        research_reset.run(dst / 'cars.sqlite', apply=True, keep=ACCOUNT)
        c = sqlite3.connect(dst / 'cars.sqlite')
        files = [r[0] for r in c.execute(f'SELECT file_path FROM listing_media WHERE listing_id IN ({",".join("?" * len(CARS))})', tuple(CARS))]
        c.close()
        for f in files:
            if (config.MEDIA_DIR / f).exists():
                (dst / 'media' / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(config.MEDIA_DIR / f, dst / 'media' / f)
        print(f'run {run}: {dst} ready ({len(files)} photos)')


def client(port, account):
    os.environ['CARLOS_ACCOUNT'] = str(account)  # Api reads the account header when it is created
    return Api(f'http://127.0.0.1:{port}', load_token())


def queue():
    for run, port in RUNS.items():
        api, source = client(port, REQUESTER), client(port, ACCOUNT)  # source: the kept listings of account 5, read only
        asked = {r['url'] for r in api.call('GET', '/api/requests')  # open or already a pilot request (history kept by the reset)
                 if r['status'] in ('QUEUED', 'RUNNING') or (r['note'] or '').startswith('Pilot run')}
        for lid, name in CARS.items():
            url = source.call('GET', f'/api/listings/{lid}').get('url')
            if not url:
                print(f'run {run}: skipped {lid} {name} (the listing has no URL)'); continue
            if url in asked:
                continue
            try:
                api.call('POST', '/api/requests', {'url': url, 'note': f'Pilot run {run} (#167): {name}. Capture this listing '
                         'and research its model.'})
                print(f'run {run}: queued {lid} {name}')
            except ApiError as e:
                print(f'run {run}: not queued {lid} ({e}); run `python pilot.py queue` again later')
                break


def commands(d):
    claude = 'claude --chrome --allowedTools Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,mcp__claude-in-chrome -p --'
    for run, port in RUNS.items():
        print(f'# run {run}: server, then a worker (separate terminals)')
        print(f'CARLOS_DATA={d / run} CARLOS_PORT={port} python app.py')
        env = '~/.config/carlos/worker.env' if run == 'a' else '~/.config/carlos/worker-2.env'  # one registered worker per run
        print(f'set -a; . {env}; set +a; CAR_API=http://127.0.0.1:{port} WORKER_NAME=pilot-{run} '
              f'CLAUDE_CMD="{claude}" python worker.py\n')
    print('# when both runs are done: python pilot_compare.py ' + ' '.join(str(d / r / 'cars.sqlite') for r in RUNS))


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] not in ('setup', 'queue', 'commands'):
        raise SystemExit(__doc__)
    d = Path(args[args.index('--dir') + 1]).resolve() if '--dir' in args else config.DATA_DIR / 'backups' / 'pilot'
    {'setup': lambda: setup(d), 'queue': queue, 'commands': lambda: commands(d)}[args[0]]()
