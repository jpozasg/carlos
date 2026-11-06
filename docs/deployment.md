# Deployment

Carlos is one Python process with SQLite; it listens on 127.0.0.1:8000 only. A reverse proxy with HTTPS makes it reachable from other devices (phone at a viewing). Designed for a Raspberry Pi 2B with an 8 GB card: the whole installation (code, database, photos, backups) must stay under 500 MB; the API refuses photos beyond 450 MB (`GET /api/storage`).

## Layout
```
/srv/carlos/            code (public repository)
/srv/carlos/.env        AGENT_TOKEN of the first admin (generated on first start, mode 600, never committed)
/srv/carlos-data/       data (private repository): cars.sqlite, media/, dossiers/, backups/
```
Set `CARLOS_DATA=/srv/carlos-data` in the service environment, or keep the default `data/` folder next to the code (git-ignored).

## systemd
```
[Unit]
Description=Carlos
After=network.target

[Service]
User=carlos
WorkingDirectory=/srv/carlos
Environment=CARLOS_DATA=/srv/carlos-data
ExecStart=/usr/bin/python3 /srv/carlos/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
The first start prints the one-time invite link for the admin password in the journal (`journalctl -u carlos`).

## Caddy
```
carlos.example.net {
    reverse_proxy 127.0.0.1:8000
}
```
Caddy sets `X-Forwarded-Proto: https`, which makes the session cookie `Secure` and the invite links use the public host. Do not expose port 8000 directly.

## Moving the data between machines
The data directory is a git repository of its own (private). After a session: commit and push it (`cars.sqlite`, `media/`, `dossiers/`); `backups/` stays ignored. On the other machine: pull, start the app; pending migrations run automatically with a backup first. The agent token in `.env` is per machine: generate one in Settings on the new machine or copy `.env` by hand.

## Backups and health
- Every migration backs up the database to `backups/` (the last five are kept).
- `GET /api/health` returns integrity, schema version, number of listings and the storage ratio for monitoring.
- `python migrate.py /path/to/cars.sqlite` applies pending migrations by hand; `python app.py --export-md` regenerates every account's dossiers.

## The shared research worker (issue #113)
The site runs on the Pi; the research runs on the owner's desktop, which stays on: Claude Code and a browser cannot run on a Pi 2B. Accounts queue listing links (`POST /api/requests`, the Compare page); `worker.py` polls the site, claims the oldest request, runs Claude Code headless with `docs/prompts/research-request.md` and reports the listing it wrote into the requester's account, or why it failed. Every request keeps who asked, when, which worker and the result (`GET /api/admin/requests`, the Accounts page).

On the desktop: a checkout of this repository (code only; the data stays on the Pi), Claude Code signed in, Chrome with Claude in Chrome for sites that block plain fetches, and the worker's own token (issue #141): an admin creates the worker once (`POST /api/admin/workers {"name": "desktop"}`, shown once; regenerate it with `POST /api/admin/workers/<id>/token`, switch it off with `PATCH /api/admin/workers/<id> {"is_active": 0}`) and puts it in the desktop's environment as `WORKER_TOKEN` (a private env file, never the repository). The worker token can only send heartbeats, claim and finish; for each claimed request the site hands out a per-request token, and only that one reaches the headless research run: it writes the shared catalogue and the requester's account, nothing else, and dies when the request ends. The admin agent token stays with the owner and never goes to a worker (without `WORKER_TOKEN` the worker still runs with `AGENT_TOKEN`, an admin token, the old way). The worker reaches the site through its public URL behind Caddy (`https://carlos.example.net`) or the LAN address of the proxy; port 8000 stays local to the Pi.

```
# ~/.config/systemd/user/carlos-worker.service
[Unit]
Description=Carlos research worker
After=network-online.target

[Service]
WorkingDirectory=%h/carlos
Environment=CAR_API=https://carlos.example.net
EnvironmentFile=%h/.config/carlos-worker.env   # WORKER_TOKEN=…
ExecStart=/usr/bin/python3 %h/carlos/worker.py
Restart=always
RestartSec=60

[Install]
WantedBy=default.target
```
`systemctl --user enable --now carlos-worker`; `loginctl enable-linger $USER` keeps it running without a login session; `journalctl --user -u carlos-worker` shows one line per request. Settings (environment): `WORKER_TOKEN` (the worker's token), `WORKER_MODEL` (`sonnet`: the research runs on Sonnet; added as `--model` after `claude` unless `CLAUDE_CMD` names a model), `POLL_SECONDS` (60; a heartbeat every poll and every minute of a run, and a worker silent for 180 s shows as down in `GET /api/admin/workers`), `WORKER_TIMEOUT_MIN` (120, below the server's 3-hour reclaim), `CLAUDE_CMD` (`claude -p`; give the headless session the permissions it needs for this repository in its Claude Code settings rather than skipping permission checks), `WORKER_LOGS` (`worker-logs/`, one log per request, git-ignored). `python worker.py --once` handles at most one request and exits (a manual test).

## Research pilot and reset (issues #167, #194)
Before the full re-research, two independent runs research the same known cars on two reset copies and are compared; only when they agree (same faults on the same levels, bands at most one step apart, prices within ±30 %, no worker failures) does the real reset run.
1. `python pilot.py setup` — two reset copies of the database in `data/backups/pilot/a` and `b` (ignored by the data repository), with the pilot cars' photos; the real database is only read.
2. `python pilot.py commands` — prints the commands for two servers (ports 8021, 8022) and one worker per run (`~/.config/carlos/worker.env` for run a, `worker-2.env` for run b); start them in separate terminals.
3. `python pilot.py queue` — queues the pilot cars on both servers (admin token: `AGENT_TOKEN` or `.env`); at most 5 requests wait per account, so run it again when the first ones are done.
4. `python pilot_compare.py data/backups/pilot/a/cars.sqlite data/backups/pilot/b/cars.sqlite` — the comparison report. Fix the prompt or the rules, then repeat from step 1.
5. Only then, with the owner's go: stop the server and the workers, `python research_reset.py data/cars.sqlite` (dry run), then `--apply`, start the server and queue every listing (`carlos://listing/<id>` for the reference car or an ad gone offline).
