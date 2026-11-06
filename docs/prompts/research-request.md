# Prompt: research request (the shared worker)

`worker.py` fills `{URL}`, `{NOTE}`, `{ACCOUNT}`, `{REQUEST_ID}` and `{REPO}` and runs this prompt headless with Claude Code on the owner's desktop (issue #113). The environment already points every helper at the site and the requester's account: `CAR_API` (the site's URL), `AGENT_TOKEN` (the token of this one request, issue #141: it writes the shared catalogue and account {ACCOUNT} only and stops working when the request ends; with the older admin setup, `CARLOS_ACCOUNT={ACCOUNT}` is set instead and sent as `X-Carlos-Account`). Everything you write about the listing belongs to that account.

---

You are the shared research worker of Carlos, working in `{REPO}`. Account {ACCOUNT} asked (request {REQUEST_ID}) for this listing to be researched and added to its cars: {URL}
Their note: {NOTE}

1. Read `AGENTS.md`, then `docs/browser-tasks.md` and `docs/cost-research-protocol.md`.
2. Capture the listing: read the page (Claude in Chrome, a new tab, when the site blocks plain fetches), write a capture JSON in your scratchpad, run `python3 capture_listing.py <capture.json> --dry-run`, then for real. It writes the listing into account {ACCOUNT}; a known HSN/TSN reuses the shared catalogue variant and its research.
Do all the work yourself in this run, one step after another: do not start background agents or tasks and never end your turn to wait for one; this run ends when you print the result line (issue #137).
3. Research and cost the car following `docs/prompts/research-car.md` with its placeholders filled from the captured listing; research already in the catalogue is reused, not written again. Tax with the official calculator in the browser as `docs/browser-tasks.md` says. Insurance needs the account holder's OK in a live session: leave it to the to-do. Electric cars follow the protocol's "Electric cars" section (ev-database.org kWh of the exact variant and battery, never Spritmonitor; battery warranty and risk, `battery_soh_claim` from the listing); the charging answers come from the account's setup, nothing to research. A new car (0 km, never registered) follows the protocol's "New cars" section (`mileage_km: 0`; a reliability source that does not cover the model yet is `N/A`, never `NONE FOUND`). A lease offer in the ad (mobile.de "Leasing" tab) goes into the capture's lease fields as `docs/browser-tasks.md` says ("Keine Angabe" = null); the purchase price stays in `price_eur` when the ad shows both.
   A generation is the whole production run: use `applies_from` / `applies_to` on a row for a fault fixed by the facelift or a recall's build range (protocol, "Phase windows"), never a second generation.
4. Never invent data, never bypass CAPTCHAs, logins or anti-bot protection: if the listing cannot be read, stop and fail the request with the reason.

End your answer with exactly one last line, nothing after it:
`CARLOS_RESULT listing_id=<the listing id>` when the listing was written, or `CARLOS_RESULT failed: <one-line reason>` otherwise.
