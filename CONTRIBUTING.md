# Contributing

Carlos is AGPL-3.0: if you change it and run it for others, publish your changes under the same licence.

- Open an issue that says why, branch from `main` (`<type>/<issue>-<slug>`), open a pull request that closes the issue. Agents and people follow the same workflow (`AGENTS.md`).
- Python standard library only (the target is a Raspberry Pi 2B); the front end has no build step and no dependencies.
- Schema changes only through a new `migrations/NNN_*.sql`; never edit an applied migration; regenerate `schema.sql` with `python migrate.py --schema`.
- Run `python -m unittest` before every pull request. Tests use a synthetic database (`tests/fixture.py`); never commit real data, photos, tokens or personal data to this repository.
- Free text in the database, the code and the documentation is English. The UI is translated through `static/i18n/*.json`.
- Every theme must keep the same markup, data and API calls as the others: themes are tokens and decoration only.
