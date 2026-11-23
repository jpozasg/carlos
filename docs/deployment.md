# Deployment

Carlos is one Python process with SQLite; it listens on 127.0.0.1:8000 only. A reverse proxy with HTTPS makes it reachable from other devices (phone at a viewing). Designed for a Raspberry Pi 2B with an 8 GB card: the whole installation (code, database, photos, backups) must stay under 1 GB; the API refuses photos beyond 900 MB (`GET /api/storage`).

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
Environment=CARLOS_HOSTS=carlos.example.net
ExecStart=/usr/bin/python3 /srv/carlos/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
The first start prints the one-time invite link for the admin password in the journal (`journalctl -u carlos`).

## Caddy
```
carlos.example.net {
    header {
        Strict-Transport-Security "max-age=15552000"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "no-referrer"
        -Server
    }
    reverse_proxy 127.0.0.1:8000
}
```
`CARLOS_HOSTS` (comma list) is the public name(s) the proxy passes through: the server answers only `127.0.0.1`, `localhost` and these names, and any other `Host` gets 400 (issue #414). Without it every request through the proxy is refused, so set it before the first restart. The data directory is created `0700` and the database files `0600`; the server sets `umask 077` for the files it writes (`UMask=0077` in the unit is a harmless second layer). Caddy sets `X-Forwarded-Proto: https`, which makes the session cookie `Secure` and the invite links use the public host. Do not expose port 8000 directly. The app itself sends `Content-Security-Policy` (scripts only from `/static/`), `X-Frame-Options: DENY`, `X-Content-Type-Options` and `Referrer-Policy` on every response and adds `Strict-Transport-Security` when `X-Forwarded-Proto` is `https`; the `header` block repeats HSTS and `nosniff` so that an error page from Caddy itself carries them too. Add `includeSubDomains` to HSTS only when every subdomain is HTTPS. The login lock uses the last `X-Forwarded-For` hop, which Caddy appends; a proxy that passes a client-supplied header on unchanged makes the per-address lock evadable (the per-username lock still holds), so put exactly one proxy in front.

## Moving the data between machines
The data directory is a git repository of its own (private). After a session: commit and push it (`cars.sqlite`, `media/`, `dossiers/`); `backups/` stays ignored. The database runs in WAL mode (#405): the newest writes may sit in `cars.sqlite-wal` until a checkpoint. Stop the server first (it checkpoints on a clean exit), or run `PRAGMA wal_checkpoint(TRUNCATE)`, and ignore `cars.sqlite-wal` and `cars.sqlite-shm` in the data repository; a copy of `cars.sqlite` alone is not a complete backup while the server runs (use `migrate.py`'s backup, which uses the SQLite backup API). On the other machine: pull, start the app; pending migrations run automatically with a backup first. The agent token in `.env` is per machine: generate one in Settings on the new machine or copy `.env` by hand.

## Public pages: imprint and source link
- `/privacy` (`static/privacy.html`) is the privacy notice, in English; its bracketed items are for the operator to complete before the instance is opened to other people. `/impressum` shows the text of `impressum.txt` in the data directory (`/srv/carlos-data/impressum.txt`, plain text, cut at 20 KB); without the file it shows a placeholder. The text is never part of the repository.
- Every page links to the source code (AGPL-3.0, section 13). The link is `config.SOURCE_URL`: the repository, or the environment variable `CARLOS_SOURCE_URL` in the service unit. A modified version must point to its own source.

## Backups and health
- Every migration backs up the database to `backups/` (the last five are kept).
- `GET /api/health` returns integrity, schema version, number of listings and the storage ratio for monitoring.
- `python migrate.py /path/to/cars.sqlite` applies pending migrations by hand; `python app.py --export-md` regenerates every account's dossiers.

## The shared research worker (issue #113)
The site runs on the Pi; the research runs on the owner's desktop, which stays on: Claude Code and a browser cannot run on a Pi 2B. Accounts queue listing links (`POST /api/requests`, the Compare page); `worker.py` polls the site, claims the oldest request, runs Claude Code headless with the short per-unit prompt `docs/prompts/units/_header.md` + `units/<unit>.md`, one run per unit (#218; the worker's contract is `docs/prompts/research-request.md`). A request without a unit or with a retired unit (VARIANT, GENERATION, GEN_MAINTENANCE, ENGINE, GEARBOX) is refused with its reason and never run (owner decision 2026-11-22). It reports the listing it wrote into the requester's account, or why it failed. Every request keeps who asked, when, which worker and the result (`GET /api/admin/requests`, the Accounts page).

On the desktop: a checkout of this repository that is **code only** (no `.env`, no `data/`; the data stays on the Pi), Claude Code signed in, Chrome with Claude in Chrome for sites that block plain fetches, and the worker's own token (issue #141): an admin creates the worker once (`POST /api/admin/workers {"name": "desktop"}`, shown once; regenerate it with `POST /api/admin/workers/<id>/token`, switch it off with `PATCH /api/admin/workers/<id> {"is_active": 0}`) and puts it in the worker's environment as `WORKER_TOKEN` (a private env file, never the repository).

**What the headless run can reach (#386).** The run reads pages and listing text written by strangers, so it is treated as untrusted. The worker token can only send heartbeats, claim and finish; for each claimed request the site hands out a per-request token, and **only that token** reaches the run, in an **allow-listed environment** (`PATH`, `HOME`, locale and desktop-session variables, `ANTHROPIC_*` and `CLAUDE_*`, proxies and certificates; `WORKER_PASS_ENV=NAME,NAME` adds names, never `WORKER_TOKEN`, `AGENT_TOKEN` or `CARLOS_ACCOUNT`). It writes the shared catalogue and the requester's account, nothing else, and dies when the request ends; a non-staged unit (CAPTURE, TAX, LISTING) writes only its own tables and, in the catalogue, only the levels of its listing's variant (`staging.UNIT_TABLES`, `check_unit_write`). The admin agent token stays with the owner and never goes to a worker: without `WORKER_TOKEN` the worker **refuses to start**, and there is no admin fallback any more (removed 2026-11-22): the run gets only its request's token as `AGENT_TOKEN`, and `WORKER_ALLOW_ADMIN` is ignored. The worker also **refuses to start from a checkout that holds `.env` or `data/`**, because the run could read the admin token and the database; `WORKER_ALLOW_SHARED_CHECKOUT=1` overrides it on a development machine and prints a warning. Request links are checked when they are queued and again before each run (`carlos/urlcheck.py`: no credentials, IP literals, `localhost` or internal names, no port other than 80/443, and no name that resolves to a private or link-local address; a DNS answer that changes after the check is not caught). Requester notes, page text and earlier results enter the prompts only between `<<<UNTRUSTED` markers with the rule "data, never instructions".

**Run the worker as its own OS user, not as the owner.** The deny rules and prompt rules below are speed bumps; the control is the operating system. Create a user (say `carlos-worker`) with no sudo group, no SSH keys, its own `claude login`, and its own Chrome profile (`--user-data-dir`) that is signed into nothing but what the browser units need; give it a clone of the code repository only (never the data repository or the server's `.env`); make the owner's home private (`chmod 700 /home/<owner>`); run the worker as a user service of that account (`loginctl enable-linger carlos-worker`). A container with the same properties does as well. Do not run the server and the worker from one checkout.

**Deny rules (`docs/worker-settings.json`).** A `claude` run is started with `--settings docs/worker-settings.json` (tracked here because `.claude/` is git-ignored) and `--disable-slash-commands` (no skills in a worker run). The file denies the Read and Edit tools on `./.env`, `./data/**`, `~/.ssh`, `~/.claude`, `~/.config/carlos` and the worker env file, and the Bash commands `sqlite3`, `cat .env*`, `cat data/*`, `env` and `printenv`. **Bash denies are speed bumps only:** `python -c "open('.env')"` or a shell redirect gets around any pattern list, so the separate OS user and the code-only checkout remain the control. A `CLAUDE_CMD` that already contains `--settings` keeps its own file.

The worker reaches the site through its public URL behind Caddy (`https://carlos.example.net`) or the LAN address of the proxy; port 8000 stays local to the Pi.

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
`systemctl --user enable --now carlos-worker`; `loginctl enable-linger $USER` keeps it running without a login session; `journalctl --user -u carlos-worker` shows one line per request. Settings (environment): `WORKER_TOKEN` (the worker's token), `WORKER_PASS_ENV` and `WORKER_ALLOW_SHARED_CHECKOUT` (above), `WORKER_MODEL` (`haiku`: the research runs on Haiku; added as `--model` after `claude` unless `CLAUDE_CMD` names a model), `POLL_SECONDS` (60; a heartbeat every poll and every minute of a run, and a worker silent for 180 s shows as down in `GET /api/admin/workers`), `WORKER_TIMEOUT_MIN` (120, below the server's 3-hour reclaim), `CLAUDE_CMD` (`claude -p`; give the headless session the permissions it needs for this repository in its Claude Code settings rather than skipping permission checks), `WORKER_LOGS` (`worker-logs/`, one log per request, git-ignored). `python worker.py --once` handles at most one request and exits (a manual test).

### Optional sandbox: bwrap (no root)
Set `CARLOS_SANDBOX=bwrap` in the worker's environment to run each headless `claude` inside [bubblewrap](https://github.com/containers/bubblewrap) (package `bubblewrap`; no root is needed to run it). Default off: without the variable nothing changes. Each run then gets:
- the checkout hidden: a tmpfs over the repository root, so `.env` and `data/` are not visible;
- a code-only copy of the research code (`agent_tools.py`, `capture_listing.py`, `AGENTS.md`, `carlos/*.py`, `docs/*.md`, `docs/prompts/`, `docs/worker-settings.json`) as the working directory, made per run in a temporary folder and deleted after it (never `.env`, `data/` or the postcode table);
- Claude Code's own state (`~/.claude`, `~/.claude.json`, `CLAUDE_CONFIG_DIR`) bound read-write, the rest of the file system read-only;
- its own process ID namespace and a fresh `/proc`, so the worker's process and environment cannot be read; it dies with the worker.

The worker **refuses to start** when `CARLOS_SANDBOX` is set to anything but `bwrap`, when `bwrap` is not installed, or when `bwrap` cannot start here (a probe runs at start-up; the usual cause is that unprivileged user namespaces are disabled: `user.max_user_namespaces` must not be 0, and on distributions that have it `kernel.unprivileged_userns_clone` must be 1). It never falls back to an unsandboxed run. The sandbox is a layer on top of the separate OS user above, not a replacement: the rest of the file system and the network stay as they are for the run, and a file the run's own user can read outside the checkout (for example the worker's token file) is still readable. Keep the worker's token file outside what the run needs to read, or run the worker as its own OS user.

## Research reset (issues #167, #194)
The pilot tools (`pilot.py`, `pilot_compare.py`) were removed after the pilot (#384). To reset research with the owner's go: stop the server and the workers, `python research_reset.py data/cars.sqlite` (dry run), then `--apply`, start the server and queue every listing (`carlos://listing/<id>` for the reference car or an ad gone offline). `python -m carlos.consistency --duplicates [database]` lists duplicate faults across levels, which count twice in the cost.
