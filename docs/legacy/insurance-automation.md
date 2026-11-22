# Legacy: automated insurance quotes (removed 2026-11-22)

The worker used to fill in a comparison site's insurance form for each car (the INSURANCE research unit, issues #218, #245, #399). Owner decision of 2026-11-22: CHECK24 disallows automated access in its robots.txt and bans commercial use in its terms, so the automation was removed from `main`.

- **Where the code is:** branch `legacy/insurance-automation` (the last commit of `main` before the removal). It is kept, not deleted; nothing on `main` runs it.
- **What replaced it:** the owner enters a dated insurance quote per listing by hand in the dossier's Costs tab (`POST /api/ui/listing_quotes`, a `listing_quotes` row). The reference car keeps the premium the owner pays (`USER DATA`).
- **Data:** `insurance_data` and `listing_quotes` rows already written stay as they are. The insurance profile keys in `project_preferences` and the columns in `project_parameters` are no longer read by any code; they are not deleted.
- **Re-enabling it would be a new decision** and needs a lawyer's answer first (see the source-terms register, `.claude/skills/source-terms-register/references/register.md`).
