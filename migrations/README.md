# Migrations

`NNN_<slug>.sql`, applied in order at startup when `NNN` is above the database's `PRAGMA user_version`, each in one transaction after a backup, with `PRAGMA foreign_key_check` before the commit. A new database is created from `schema.sql` at the baseline version written in its header, so only migrations above that baseline live here. Applied migrations are history: never edit them; write a new one. Regenerate `schema.sql` afterwards with `python migrate.py --schema`.

Note on 046: it deletes specific owner rows by id (`insurance_data` 74, `listing_quotes` 49 and 50). It is owner-specific, applied once on the owner's database, and must not run on any other installation without first checking those ids.
