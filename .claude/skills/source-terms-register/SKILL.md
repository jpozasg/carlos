---
name: source-terms-register
description: Use before adding or changing ANY external source, scraper-like step, browser task or automation (listing sites, CHECK24 or other comparison portals, Autoscore, EngineScope, ADAC, TUeV-Report, autokostencheck, ev-database, BMF tax calculator, postcode data, any new site), and for a change that stores, shows or shares personal data or third-party content (seller data, listing text or photos, the insurance profile, cookies/localStorage, retention, export/erasure, public deployment, licences). Not for ordinary UI or calculation work. Keeps a register of what each site is read for and under which terms (NOT VERIFIED where the repo records none) and turns open points into a question list for a lawyer.
---

# source-terms-register

Carlos reads third-party sites and stores parts of them in a shared catalogue that several accounts see. Whether that is allowed depends on each site's terms, robots.txt, database and copyright rights, and on GDPR. Nobody has verified most of it. This skill keeps the register honest: facts already in the repo are recorded, everything else is `NOT VERIFIED`, and open points become questions for a lawyer.

## Hard rules
- **Output is a QUESTION LIST for a lawyer, never a verdict or legal advice.** Never write "this is legal / illegal / compliant". Write "Open question for a lawyer: ...", with the facts and the file that shows them. Say what was and was not checked.
- **Never invent terms.** A site's terms, robots.txt status, permission or licence is recorded only from the repo docs or from a page the agent actually read in this session (then give URL and date). Otherwise write `NOT VERIFIED`.
- Never bypass CAPTCHAs, logins, Cloudflare or anti-bot checks. The reliability sources (Autoscore, EngineScope, ADAC Pannenstatistik and Gebrauchtwagen-Info, TUeV-Report) are read by hand in the owner's browser: new tab, one page per engine or generation, never in bulk (AGENTS.md "Reliability"). Every other source is accessed the way its register row records (plain fetch or browser, single pages). A bulk or scripted extraction needs the owner's explicit decision, recorded in the row.
- Quality grade follows AGENTS.md (A official, B ADAC/TUeV/Haynes/dealer tool/comparison quote, C aggregators and databases, D forums and single retailers). A grade says how reliable, not whether it is permitted.
- Terms read for the owner stay the owner's decision: permissions (e.g. `config.ENGINESCOPE_PERMISSION`) are set by the owner only, never by an agent.

## When a source, browser step or automation is added or changed
1. Open `references/register.md`. Find the site's row (sources named in the protocol but without a row of their own are in the last block of the table); if there is none, add one from the template below **before** the step ships (the PR includes the register row).
2. Fill the row only with facts from the repo or from a page read now. Everything else `NOT VERIFIED`. Put the open question in the row's "Question for a lawyer" cell.
3. Decide the access mode: by hand in the owner's browser (user-initiated, one page) is the default for a new site; automated or batched needs the owner's explicit decision recorded in the row (date, who). Say which Chrome profile: browser work runs in the dedicated profile without the owner's logins (`docs/browser-tasks.md`, "General").
4. Decide what is stored and what other accounts see (the shared catalogue is visible to every account through its listings): link only / figure only / verbatim text / photos. Store the minimum the calculation needs; prefer a link plus the figure over copying text, tables or issue lists.
5. Check privacy: no VIN or plate, no seller personal data beyond what the ad publishes (and no private seller names or addresses if avoidable), nothing of the account holder in files, notes or commits, `quote_profile` without names, dates of birth, postal codes or contact data.
6. Register the data source in the API (`src(...)`: URL, access date, quality, `supports`, `limitations` stating the terms status in English).
7. Answer the checklist in `references/compliance-checklist.md` for any feature that touches personal data, accounts, photos, cookies/storage, retention or deployment (done / not applicable and why / open and filed as an issue).
8. If anything is open, produce the question list (format below) and tell the owner; do not block work that does not depend on it.

## Register row template
| Field | Content |
|---|---|
| Site | name and domain |
| What Carlos reads | exact data points (fields, tables, PDFs) |
| How | by hand in the owner's browser / plain fetch / automated by the worker; batch or single |
| Terms | URL and date read, or `NOT VERIFIED`; relevant clauses quoted briefly |
| robots.txt | status and date, or `NOT VERIFIED` |
| Stored | table and columns; verbatim text, figure, link, photos |
| Shown to other accounts | yes / no / link only (through the shared catalogue) |
| Permission | written permission held, own-use terms, none, or `NOT VERIFIED`; who decided and when |
| Quality | A-D |
| Review date | next date to re-read the terms (default 12 months), or `NOT SET` |
| Question for a lawyer | the open point, or none |

## Question list format (what you hand to the owner)
```
Question for a lawyer N: <one sentence, neutral>
Facts: <what Carlos does, quoted from the repo: file and section or function (line numbers drift)>
Why it matters: <right or duty at stake, named, not concluded>
Options the owner could consider: <technical changes, e.g. link only, ask for permission, switch off>
Not checked: <what is unknown>
```
Group by topic (third-party terms and database rights, GDPR and processors, imprint and consumer law, accessibility, licences). Mark urgency only by consequence ("public instance", "any non-owner account"), not by guessing legal outcomes.

## Use with the installed skills
- `legal-audit` (waldo): GDPR/DSGVO, DPA, privacy policy, Impressum, cookies/TDDDG. Run it for any privacy-relevant feature or before opening the instance to other people; paste its findings into the question list and keep its "not legal advice" framing. It answers in German, its greps miss `.js` and `.py`, and its Impressum and privacy templates need the owner's name and address: keep them as placeholders, never put owner data in this repository (`docs/skills.md`).
- `bfsg-check` (waldo): accessibility (BFSG/WCAG 2.1 AA), low fit, use it as a checklist. Run it only if the owner asks or the service is offered commercially; whether the BFSG applies to this service at all is a question for a lawyer.
- `carlos-threat-model`: when the step handles tokens, logins or untrusted page text; `research-audit`: when a new source changes the research prompts or contract.
- Ask first in the live session (owner-only consent): entering personal data, logins, purchases, accepting a site's terms, contacting a site for permission, sending the EngineScope permission e-mail.

## Files
- `references/register.md`: the register, pre-filled from repo facts only (each fact names the repo file that records it).
- `references/compliance-checklist.md`: checkboxes for the privacy and licence topics a change can touch (GDPR, cookies and storage, imprint, third parties, accessibility, AGPL, security of processing). Each item states what the code or docs show today and ends in a question for a lawyer where a legal judgement is needed; it concludes nothing.
