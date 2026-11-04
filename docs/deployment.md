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
