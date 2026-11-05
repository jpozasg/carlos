# Carlos

**The real cost of a car, compared with the one you already own (if you have one).**

Carlos is a small self-hosted web app for people choosing a car, new or used. If you already own one, you register it as the *reference*; an agent (or you) researches the cars you are interested in, and Carlos shows what each one would really cost over the years you plan to keep it: fuel, insurance, road tax, maintenance, expected repairs, tyres, purchase and sale costs and depreciation. A questionnaire turns what matters to you into ranking weights, and every number can be traced back to its source.

It was built and tested with German data (the official BMF road-tax calculator, CHECK24 insurance quotes, HSN/TSN type codes, Bavarian registration and inspection fees), but nothing in the method is German: anywhere else, swap those regional sources for the local ones (`docs/cost-research-protocol.md`, `agent_tools.py` shared sources) and the same calculation works.

**Why "Carlos"?** It is a typical Spanish name, and read with a bit of German, *Car-los* means *car-less* (*-los* = without). It was written by a Spaniard who does not have a car, to find the right one.

- Python standard library only (runs on a Raspberry Pi 2B), SQLite, no build step.
- Accounts: every person has their own private cars, models, parameters and dossiers.
- Ten switchable looks (instrument cluster by default, friendly, garage night, seventies brochure, olive workshop, terminal, cute, circuit board, arcade, Hyrule), light and dark where the look allows. Design decisions: `docs/design.md`.
- English, Spanish, German and Polish UI.
- Designed to be filled by AI agents through a write API with strict rules (sources, no invented data, same method for every car). See `AGENTS.md`.

## Getting started
1. Requirements: Python 3.9 or newer. Nothing to install.
2. Clone the code. The data (database, photos, dossiers, backups) lives in a separate directory, `data/` next to the code by default or the path in the environment variable `CARLOS_DATA`. Keep it in its own private repository if you want to move it between machines; the code repository never contains it.
3. Run `python app.py`. On first start it creates the database from `schema.sql`, generates the admin's agent token into `.env`, and prints a one-time link to set the admin password.
4. Open the link, set the password, then open http://127.0.0.1:8000 and sign in. Create further accounts under *Accounts*.
5. Put Carlos behind a reverse proxy with HTTPS for access from other devices (`docs/deployment.md`). The server itself only listens on 127.0.0.1.

## What you see
| Page | What it does |
|---|---|
| **Compare** | Overview table (rank, score, price, km, age, cost per month, total, difference against your car, warnings), cost composition bars with selectable components, break-even chart "keep your car or switch", detail table of every figure, photo cards. Sort, filter by budget or withdrawn, select the cars, export CSV. |
| **Ranking** | Eight quick choices between four cars set the weights of eight criteria; sliders can still override them. Reliability is a score out of 36 (higher is better): four parts (engine, gearbox & clutch, chassis & brakes, electrics) each start at 9 and lose the points of their 3 worst known weak points; a recall costs its points until the viewing checklist shows it was done. The ranked list shows how much each criterion contributed; the formula and every criterion's basis are on the page. |
| **Dossier** (click a car) | Photos, listing facts and seller claims, the ranking explanation with the evidence behind it, the maintenance plan and repair risks (each row tagged with the level it comes from: variant, engine or generation), checklist, valuations, own costs, watch points, listing archive, log, sources. *Viewing mode* on a phone: tick the checklist, add notes and photos while looking at the car. |
| **Models** | Make → model → generation → engine → variant with filters; each variant shows its listings and inherits the rows of its engine and generation. |
| **Sources** | Every source with its quality A–D, what it supports and its limitations. |
| **Settings** | The assumptions (km per year, years, fuel prices, budget), the insurance profile, theme, light/dark mode, language, password, agent token (admins). |
| **Accounts** (admin) | Create accounts and invite links, deactivate, change roles. |

## How the numbers are built
Per listing, over the period (km per year × years from Settings):
- **Fuel:** real-world consumption of the exact variant (the same source for every car, the reference included) × km × fuel price (petrol or diesel; a full hybrid as petrol). Electric cars: real-world kWh/100 km (Spritmonitor, the same source for every electric car) × km × the electricity price from the charging answers (home and public price weighted by the share charged at home, +10 % loss at a household socket). Plug-in hybrids: not costed yet, fuel stays unknown.
- **Insurance:** the latest comparison quote for the variant (median of the five cheapest reasonable offers); for the reference car, the premium you actually pay.
- **Tax:** the latest known annual amount, preferably from the official calculator. Electric cars first registered by 2030-12-31 pay nothing for 10 years (until 2035-12-31 at the latest): tax counts only the months of the period after that, and is a known 0 when the whole period is exempt.
- **Maintenance:** item schedules costed job by job as an expected value (period ÷ interval, whichever of km and months is reached first). A job due at purchase (e.g. a timing belt overdue by age) is a certain maintenance cost listed by name, and restarts its schedule. DIY jobs count parts only; DIY hours are shown, never priced.
- **Repairs:** certain one-off repairs of the listing (present faults, listed by name) plus the expected cost of each known risk (probability × share of its km window driven in the period). Every risk must carry a price; an unpriced risk, no risk research or no mileage makes the component unknown.
- **Tyres:** wear (km ÷ tread life × set price with fitting) plus listing-specific tyre costs.
- **Purchase/sale:** registration, plates, pre-purchase check; deregistration for the reference; for an electric car, the wallbox you said you would install (Charging setup).
- **Depreciation:** asking price − resale at the end (candidates); sale today − resale at the end (reference).

A total is only called a TCO when no component is missing; otherwise it is a partial subtotal and the missing parts are listed. Unknown is always NULL, never 0. The break-even view spreads running costs over the months and shows the payback month of switching. Details: `docs/data-model.md`, `docs/ranking.md`.

## Three levels of model knowledge
A car model is described at three levels: the **generation** (make, model, generation, years on sale, facelift), the **engine** (code, fuel, displacement, power, aspiration, injection, timing drive) and the **variant** (generation + engine + trim, gearbox, body, HSN/TSN). Maintenance schedules, repair risks, watch points, consumption, tax, insurance and tyre data attach to exactly one level, and a listing inherits the rows of its variant, its engine and its generation. An engine's oil interval is recorded once for every car that uses that engine.

## Accounts and security
Every account owns its listings, parameters, preferences, private rows (insurance premiums, own observations) and dossiers; the research on generations, engines and variants is a shared catalogue, written by admins (the shared research worker) and visible to an account only for the cars it has listings for. Admins create accounts and hand over a one-time invite link (72 h) on which the person sets a password. Sessions are cookies (30 days, HttpOnly, SameSite=Strict, Secure behind HTTPS); ten wrong passwords lock a username for five minutes. Agent tokens for the write API are for admin accounts only; a normal account signs in and asks for research through the request queue. Passwords are stored with scrypt, tokens and sessions as SHA-256 hashes. Photos are served only to their owner.

## Development
- Tests: `python -m unittest -v` (a synthetic database is built from `schema.sql`; no real data is touched).
- Integrity of a real database: `python -c "import sqlite3; c=sqlite3.connect('data/cars.sqlite'); print(c.execute('PRAGMA integrity_check').fetchone(), c.execute('PRAGMA foreign_key_check').fetchall())"` → `('ok',) []`.
- Schema changes go through `migrations/NNN_*.sql` numbered above the baseline version in the header of `schema.sql` (applied at startup with a backup, foreign keys checked before the commit), then `python migrate.py --schema` regenerates `schema.sql`. A new database is created from `schema.sql` directly, so the repository only needs the migrations written after the baseline.
- Layout: `app.py` entry point; `carlos/` package (`server.py` HTTP and routing, `auth.py` accounts, `costs.py` calculation, `ranking.py`, `agent.py` write API, `todo.py`, `models.py`, `db.py`, `config.py`); `markdown_export.py` dossiers; `migrate.py`; `agent_tools.py` and `capture_listing.py` for agents; `static/` the front end (`docs/frontend.md`); `tests/`; `docs/`.
- Contributing: `CONTRIBUTING.md`. Licence: AGPL-3.0 (`LICENSE`).
