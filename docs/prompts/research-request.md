# Contract: research request (the shared worker)

This file has no prompt of its own any more (owner decision 2026-11-22: the single-run prompt for rows without a unit is retired). `worker.py` claims a request and:

- **refuses** it with its reason, without a run, when it has no unit (the old single run) or a retired one: `VARIANT`, `GENERATION`, `GEN_MAINTENANCE`, `ENGINE`, `GEARBOX`, `INSURANCE` (`carlos/research_units.refusal`; the server refuses them at the claim too);
- **runs** every other unit headless with Claude Code on the owner's desktop (issue #113): `worker.py` builds its prompt from `docs/prompts/units/_header.md` (shared rules and the placeholders `{UNIT}`, `{LISTING_ID}`, `{LEVEL_ID}`, `{PARENT_ID}`, `{MISSING}`, `{ATTEMPT}`, `{PREVIOUS_RESULT}`, `{URL}`, `{NOTE}`, `{ACCOUNT}`, `{REQUEST_ID}`, `{REPO}`, `{SCOPE}`; `{URL}`, `{NOTE}` and `{PREVIOUS_RESULT}` are fenced as untrusted data, #386) and `docs/prompts/units/<unit>.md`. The units: CAPTURE (#218), TAX, LISTING; RESEARCH_A and RESEARCH_B (`units/research.md`, #253); ARBITER (`units/arbiter.md`); MERGE runs no Claude (server code).
- **finishes** the run from its last result line: CAPTURE ends `CARLOS_RESULT listing_id=<id>`, every other unit `CARLOS_RESULT done: <summary>`, a failure `CARLOS_RESULT failed: <reason>`.

The run's environment is an allow-list that points every helper at the site: `CAR_API` (the site's URL) and `AGENT_TOKEN`, the token of this one request (issue #141). It writes the shared catalogue and account {ACCOUNT} only, and stops working when the request ends. There is no admin fallback (removed 2026-11-22): a run never gets an admin token or `CARLOS_ACCOUNT`, and `WORKER_ALLOW_ADMIN` is ignored. Everything written about the listing belongs to the requester's account.
