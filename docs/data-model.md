# Data model

SQLite, one file (`cars.sqlite` in the data directory). `schema.sql` is the executable reference and the baseline for new databases; changes go through `migrations/NNN_*.sql`. Every row of a top-level table belongs to one account (`owner_id`); child rows belong through their parent. The API shows and accepts only the rows of the account behind the session or token (per-owner views, `carlos/auth.py`).

## Accounts
| Table | Purpose |
|---|---|
| `users` | `username`, `password_hash` (scrypt), `role` admin/user, `is_active`, `api_token_hash` (SHA-256 of the agent token), `created_at`. |
| `sessions` | cookie sessions: `id` = SHA-256 of the cookie value, `user_id`, `expires_at`. |
| `invites` | one-time links to set a password: `id` = SHA-256 of the token, `user_id`, `created_by`, `expires_at`, `used_at`. |
| `project_parameters` | one row per account (`owner_id` unique): `annual_km`, `ownership_years`, `fuel_price_eur_l` + `fuel_price_date`, `diesel_price_eur_l` + date, `budget_ideal_eur`, `budget_max_eur`, the insurance profile (`postal_code`, `drivers_count`, `driver_age`, `sf_class`, `insurance_cover`, `insurance_deductible_eur`), `purchase_mode`, `ranking_answers` (JSON), `ranking_weights` (JSON or NULL = derived from the answers). |
| `project_preferences` | free preferences per account (`owner_id`, `preference_key`, `preference_value`, `unit`, `status`, `notes`): search area, preferred fuel/engine/gearbox, DIY skills, usage profile. Agents read them before asking the user again. Keys the setup wizard writes (plain English values): `search_center`, `search_radius` (km or `Any`), `preferred_fuel`, `preferred_transmission`, `driving_mix`, `current_car`, `diy_jobs` (comma list, `none` when a workshop does everything), insurance profile for comparison quotes: policyholder `insurance_holder_gender` (`female`/`male`/`diverse`), `insurance_holder_birth_date`, `insurance_holder_licence_date` (ISO dates), `insurance_holder_licence_country` (`germany`/`eu`/`other`), `insurance_holder_marital` (`single`/`married`/`partnership`/`divorced`/`widowed`), `insurance_holder_occupation` (`employee`/`worker`/`public_service`/`civil_servant`/`self_employed`/`student`/`trainee`/`retired`/`homemaker`/`not_working`), `insurance_holder_bf17`, `insurance_holder_other_car` (`yes`/`no`), `insurance_holder_points`; `insurance_drivers` (JSON array of further regular drivers, each with `relationship` `partner`/`child`/`other`, `household` `yes`/`no` and the same person fields except licence country); `insurance_main_user` and `insurance_keeper` (Policyholder / Driver 2 / Someone else); policy `insurance_start_date`, `insurance_claims_3y`, `insurance_previous_insurer`, `insurance_previous_years`, `insurance_cancelled`, `insurance_usage`, `insurance_parking`, `insurance_seasonal_plate`, `insurance_workshop_binding`, `insurance_discounts` (comma list of `homeowner`, `children` (under 17), `transit_pass`, `bahncard`, `club`, `liability`, `household`, `legal`, `accident`, `other_policy`, or `none`); `insurance_usage` (Private (including commuting) / Business only / Private and business, as CHECK24 asks), `insurance_club_name`, `insurance_liability_insurer`, `current_premium_eur_year` (the wizard also sets the parameters `drivers_count` and `driver_age` from the people entered); this personal data lives only in the account's database rows, never in notes, logs, dossiers or `insurance_data.quote_profile` (which records the profile without birth dates); `onboarding_done` (date, or `skipped`). Older free-text keys (`diy_skills`, `usage_profile`, `preferred_engine`, …) are kept and shown as notes. |

## Three levels of model knowledge
| Table | Level | Columns |
|---|---|---|
| `generations` | generation | `make`, `model`, `name` (generation code or name), `start_year`, `end_year`, `facelift_year`, `status`, `notes`, `owner_id`. |
| `engines` | engine | `code` (manufacturer engine code), `family`, `description`, `fuel_type`, `displacement_cc`, `cylinders`, `power_kw`, `power_ps`, `aspiration` (NATURALLY ASPIRATED / TURBO / SUPERCHARGED), `injection` (PORT / DIRECT / DUAL / CARBURETTOR), `timing_drive` (CHAIN / BELT / WET BELT / GEAR), `status`, `notes`, `owner_id`. |
| `vehicles` | variant | `generation_id`, `engine_id`, `trim`, `transmission`, `body_style`, `model_year`, `emissions_standard`, `co2_g_km`, `hsn`, `tsn`, `technical_status`, `notes`, `owner_id`. |

**Knowledge tables** attach to exactly one level through `vehicle_id`, `engine_id` or `generation_id` (a CHECK constraint enforces it). A listing resolves its data from its variant, its engine and its generation together (`carlos/db.py: for_variant`). The `level` of every row is returned by the API.

| Table | What a row is | Key columns |
|---|---|---|
| `maintenance_items` | a scheduled job (`schedule='ITEM'`; old `PACKAGE` rows are history, `active=0`) | `item`, `interval_km`, `interval_months`, `diy` (0/1), `diy_parts_cost_eur`, `diy_hours`, `reference_cost_eur` (workshop price of the whole job), `labor_included`, `status`, `source_id`, `notes`, `active` |
| `repair_risks` | a failure that may happen in a km window | `component`, `km_from`, `km_to`, `probability` (0–1 over the window, with the reason in `evidence`/`notes`), `parts_eur`, `labor_eur`, `diy`, `diy_hours`, `status`, `evidence`, `source_id`, `notes` |
| `reliability_items` | a documented watch point (not a proven defect) | `component`, `issue`, `evidence`, `severity` (HIGH / HIGH IF APPLICABLE / MEDIUM / LOW-MEDIUM / LOW), `frequency_status`, `source_id`, `inspection_action` (becomes a checklist item of every listing) |
| `observations` | a measured figure, above all consumption | `category`, `metric` (`Autokostencheck average` is the primary consumption; `Owner measured average` a cross-check), `value_num`, `value_text`, `unit`, `sample_count`, `min_value`, `max_value`, `status`, `evidence_quality`, `observed_date`, `source_id`, `notes` |
| `tax_data` | annual road tax | `annual_tax_eur`, `status`, `basis` (every input of the calculator), `source_id`, `notes` |
| `insurance_data` | a quote or the premium paid | `hsn`, `tsn`, `year`, the three Typklassen, `annual_premium_eur` (median of the 5 cheapest reasonable offers), `premium_min_eur`, `insurer`, `tariff`, `premium_status` (QUOTE / USER DATA / PENDING), `quote_date`, `quote_profile` (JSON, no personal data), `source_id`, `notes` |
| `tyre_data` | the tyre set of the variant | `tyre_type`, `size`, `price_per_tyre_eur`, `tyres_per_set`, `life_km`, `fitting_per_set_eur`, `status`, `source_id`, `notes` |

`sources` (`title`, `url`, `source_type`, `quality` A–D, `accessed_date`, `supports`, `limitations`, `owner_id`) may attach to one level or to none (shared sources such as fee tables).

## Listings (a specific car)
| Table | Purpose |
|---|---|
| `listings` | one row per car: `vehicle_id` (variant), `source_id` (the listing itself as a source), `platform`, `listing_id` (the platform's id), `url`, `price_eur`, `mileage_km`, `first_registration`, `seller`, `location`, `seller_address` (only what the listing publishes), the seller claims (`accident_free_claim`, `owners_claim`, `hu_claim`, `service_history_claim`), `equipment`, `listing_date`, `last_checked`, `listing_status` (UNDER REVIEW / OWNED / WITHDRAWN), `is_reference` (the car you own), `verdict`, `notes`, `owner_id`. |
| `listing_snapshots` | captures of the listing as published: `captured_at`, `title`, `price_eur`, `mileage_km`, `description` (verbatim, original language), `attributes_json` (every feature as shown), `source_id`. Never overwritten; a new capture per visit. The price history comes from here. |
| `listing_media` | archived photos in `media/<listing id>/<sha256>.<ext>` (max 1.5 MB each, deduplicated by hash). |
| `valuations` | `kind` `sale_today` (reference only) or `resale_end`, `horizon_years`, `low_eur`, `expected_eur`, `high_eur`, `status`, `valued_date`, `source_id`. |
| `unit_costs` | certain one-off costs of this car: `category` repairs / tyres / purchase_sale, `item`, `parts_eur`, `labor_eur`, `diy_hours`, `status`, `source_id`. |
| `maintenance_resets` | a scheduled job done at the start of ownership (`basis` CERTAIN REPAIR / SELLER CLAIM / DOCUMENTED): the schedule restarts for this listing. |
| `inspection_items` | the checklist: `item`, `status` PENDING / OK / PROBLEM / N/A, `checked_date`, `notes`. |
| `listing_events` | the log, the agent's memory: `event_date`, `kind` (found, verification, correction, price, decision, user_data, warning, archive, photos, viewing), `text` (English), `source_id`. |
| `change_log` | audit trail of every write through the API (`table_name`, `row_id`, `action`, `old_json`, `new_json`, `user_id`). |

## Conventions
- **NULL means unknown, never 0.** A missing price, interval or figure stays NULL; the calculation then reports the component as unknown.
- **Every external data point cites a source** (`source_id`) with URL, access date, quality A–D, what it supports and its limitations.
- **Statuses** are English upper-case codes: `VERIFIED` (official or primary source for this engine/variant), `ESTIMATED` (derived, with the derivation in `notes`), `PENDING` (unknown; never with a number), `OBSERVED`, `USER DATA`, `QUOTE`, `OFFICIAL FEE LEVEL`, `PRIMARY`.
- **Free text is English** (notes, log, verdicts, checklist items, descriptions of reliability items, `sources.supports`/`limitations`). Verbatim third-party content (`listing_snapshots.description`, `attributes_json`) keeps its original language.
- **Generations always record** start and end of sale and the facelift year; **engines** record aspiration, injection and timing drive (they feed the simplicity criterion of the ranking).
- **Never duplicate** a knowledge row on two levels. Re-scope a row with one PATCH that sets the old level column to null and the new one to the id.
- **No DELETE** through the API: archive listings with `listing_status='WITHDRAWN'`, deactivate schedules with `active=0`, neutralise a wrong risk with `probability=0` and a note.
