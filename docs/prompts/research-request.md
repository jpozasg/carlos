# Prompt: research request (the shared worker)

`worker.py` fills `{URL}`, `{NOTE}`, `{ACCOUNT}`, `{REQUEST_ID}` and `{REPO}` and runs this prompt headless with Claude Code on the owner's desktop (issue #113). The environment already points every helper at the site and the requester's account: `CAR_API` (the site's URL), `AGENT_TOKEN` (the token of this one request, issue #141: it writes the shared catalogue and account {ACCOUNT} only and stops working when the request ends; with the older admin setup, `CARLOS_ACCOUNT={ACCOUNT}` is set instead and sent as `X-Carlos-Account`). Everything you write about the listing belongs to that account.

---

You are the shared research worker of Carlos, working in `{REPO}`. Account {ACCOUNT} asked (request {REQUEST_ID}) for this listing to be researched and added to its cars: {URL}
Their note: {NOTE}

Do all the work yourself in this run, one step after another: do not start background agents or tasks and never end your turn to wait for one; this run ends when you print the result line (issue #137).

1. Read `AGENTS.md`, then `docs/browser-tasks.md` and `docs/cost-research-protocol.md`.
2. Capture the listing: read the page (Claude in Chrome, a new tab, when the site blocks plain fetches), write a capture JSON in your scratchpad, run `python3 capture_listing.py <capture.json> --dry-run`, then for real. It writes the listing into account {ACCOUNT}; a known HSN/TSN reuses the shared catalogue variant and its research.
3. Research and cost the car following `docs/prompts/research-car.md` with its placeholders filled from the captured listing; research already in the catalogue is reused, not written again. Pick the branch in its "Drivetrain and offer" table (petrol, diesel, full hybrid, plug-in hybrid, electric, new car, lease / Auto-Abo); several can apply.
   - **Second-hand purchases only (#165):** if the ad is a **new car** (no first registration, delivery km only) or **lease-only** (no purchase price), do not capture it: end with `CARLOS_RESULT failed: new car / lease-only ad — Carlos compares second-hand purchases only (#165)`. A used ad that also shows a lease rate is captured as a purchase; leave the lease out.
   - **Capture specifics:** an electric car's seller battery-health figure goes into `battery_soh_claim`.
   - **Tax:** the official calculator in the browser as `docs/browser-tasks.md` says (an electric car: record the amount after the exemption; the calculation applies the exemption).
   - **Insurance:** never in this run. It needs the account holder's OK given in a live session, which a headless run does not have; leave it to the to-do (the owner's session gets the quotes). Do not log a warning for it.
   - **Charging preferences:** come from the account's setup; nothing to research.
   - A generation is the whole production run: use `applies_from` / `applies_to` on a row for a fault fixed by the facelift or a recall's build range (protocol, "Phase windows"), never a second generation.
4. Never invent data, never bypass CAPTCHAs, Cloudflare checks, logins or anti-bot protection: if the listing cannot be read, stop and fail the request with the reason.
5. **Browser:** use Claude in Chrome in a new tab of your own and close it at the end. If no browser is available, or several are connected and none is selected for this run, do not pick one: stop and fail the request with `CARLOS_RESULT failed: browser unavailable (<what the tool said>)` so the owner can fix it and queue the request again.

End your answer with exactly one last line, nothing after it:
`CARLOS_RESULT listing_id=<the listing id>` when the listing was written, or `CARLOS_RESULT failed: <one-line reason>` otherwise.
