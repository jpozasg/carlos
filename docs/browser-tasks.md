# Browser tasks: playbook for agents

How to gather data in the user's own Chrome (Claude in Chrome) for Carlos. Rules from `AGENTS.md` always apply. Keep this file updated after every browser session: what worked, what broke, what to avoid. Never write personal data (names, birth dates, licence dates, contact data, premiums paid, insurers) into this file or into the repository; account-specific results go into the database only.

## General
- **Getting started:** load the `chrome-browser` skill, call `tabs_context_mcp` (with `createIfEmpty`), work in your own new tab and close it at the end.
- **Separate Chrome profile (user decision 2026-11-03):**
  - Browser work runs only in a dedicated Chrome profile without the user's logins and cookies.
  - The extension was removed from the user's main profile.
  - At the start, `list_connected_browsers` should show exactly that one browser. If several are connected, ask the user which one; never pick one yourself.
  - A subagent or the headless worker cannot ask: if several browsers are connected and none is selected for its session, it stops and reports (the worker fails the request with "browser unavailable"). The main agent asks the owner, selects the chosen one, and the work is resumed or queued again (2026-11-06: Browser 1 chosen).
    - Cookie consent in this profile follows the usual rule: the most privacy-preserving option.
  - Never sign in to anything in it.
- **Site permissions ("Permission denied for this action on this domain"):** this often appears when a click moves the tab to another host.
  - **Before telling the user it cannot be done**, navigate the tab to that URL directly with the `navigate` tool and try again. Reaching a host through `navigate` is what works; arriving there by clicking a link is refused.
  - Only if direct navigation is also refused, stop and ask the user. The extension's settings page has no list to add hosts to; the user can only answer a prompt or change Chrome's site access for the extension.
  - After permission changes the tab group may be gone: call `tabs_context_mcp` with `createIfEmpty` and open a new tab.
- **Extension disconnects:** retry once; if it is still disconnected, ask the user to switch to Chrome and reconnect the extension. Do not loop.
- **Stop and hand over** on a CAPTCHA, a "verify you are human" box, a login, or a request for e-mail/phone. A Cloudflare widget that passes by itself ("Erfolg!") is fine; never click it.
- **Cookie banners:** choose the most privacy-preserving option ("Nur notwendige Cookies", "Ablehnen").
- **Reading pages:**
  - `get_page_text`, or `javascript_tool` returning `innerText` slices.
  - Outputs over ~1,000–1,500 characters are truncated, so read long texts in chunks (`slice(0,1000)`, `slice(1000,2000)`, …) and join them.
  - Outputs that contain URLs with query strings are blocked ("Cookie/query string data"). Strip URLs (`replace(/https?:\S+/g,'')`) or return only path parts.
- **Screenshots** sometimes time out on some tabs; fall back to `find` / `read_page` / JS.
- **Custom form widgets** (React/Vue):
  - Typing into fields works better than `form_input`.
  - Dropdowns: focus the field, press `ArrowDown` to open, check the value with `document.activeElement.value`, then `Tab` to confirm. Pressing `ArrowDown` again moves the selection, so check the value before confirming.
  - Clicking near an ⓘ icon opens info popups; close them with `Escape` or the ×.
  - Re-check radio buttons after changing a dependent field, because some fields reset.
- **Element refs** from `find` change when the page re-renders; call `find` again after each section.

## Listing capture (mobile.de and similar)
1. Open the plain listing URL `https://suchen.mobile.de/fahrzeuge/details.html?id=<id>`. Drop parameters such as `action=parkItem`, which would park/save the car in the user's account.
2. Extract with one JS call into `window.__cap`:
   - `dl` pairs: technical data;
   - equipment `li` items under "Ausstattung";
   - the description under "Fahrzeugbeschreibung laut Anbieter";
   - gallery image ids: `[data-testid^=thumbnail-] img`, `button[data-testid=slide] img`, path `…/images/<2 hex>/<uuid>`; similar-car images are excluded by these selectors;
   - the dealer box ("Über diesen Händler").

   Then read it back in chunks.
3. The header (title, subtitle, price, price rating) is easiest with `find`.
   - **Location and seller type:** the tab title reads "<Make> <Model> in <Place> für <Price> | mobile.de": take `<Place>` for `listings.location` (`document.title.match(/ in (.+?) für /)`). A dealer box ("Über diesen Händler") means a dealer, otherwise a private seller; store the dealer's name in `seller` only when the listing publishes it. Compare the place with the account's `search_center`/`search_radius` preferences and log a `warning` when it lies outside (sponsored results ignore the radius).
   - **Price drops:** a struck-through second price ("8.100 € … 8.999 €") is the previous asking price; mention it in the `found` log entry.
4. Photos: `https://img.classistatic.de/api/v1/mo-prod/images/<2 hex>/<uuid>?rule=mo-1024.jpg` (~230 KB) can be downloaded directly by `capture_listing.py`.
5. Structured facts for the ranking filters, the distance and the dossier (#169) go in `listing` as the ad states them (null when not shown, never guessed): `seller_type` DEALER/PRIVATE, `warranty` 1/0, `hu_until` YYYY-MM (HU/TÜV month), `service_history` YES (Scheckheft/invoices shown) / CLAIMED (only stated) / NO, `accident_free` YES (documented) / CLAIMED ("unfallfrei" stated) / NO, `postal_code` (the car's 5-digit postcode) and, for a **dealer ad, always** the dealer's rating: `seller_rating` (stars, e.g. 4.8) and `seller_reviews` (count) from the rating line (mobile.de "Händlerbewertung"); null for a private seller.
6. Write the capture JSON and run `python capture_listing.py <file> --dry-run`, then run it without `--dry-run`. Add listing-specific checklist items and warnings.

### A car without a link (issue #375)
The owner can give the facts in the session instead of a link (no ad, a car seen in person or told by phone). No worker is needed; the coordinating agent does it with the owner's data, acting for the account (`X-Carlos-Account`):
1. Ask only for what is missing: make, model, year or first registration, engine/fuel, power, gearbox, mileage, asking price, location/postcode, seller type, HSN/TSN if known, the seller's claims (accident, owners, HU, service history), equipment, photos (files). Never fill a gap by guessing: it stays null.
2. Create the shell (generation, engine, variant) as in `docs/prompts/units/capture.md` step 2, then write a capture JSON **without `url`** (`platform` defaults to `manual`, `capture_method` to "entered by the owner"; the source is `user_data`, quality D) and run `python capture_listing.py <file> --dry-run`, then for real. Photos come in as `{"file": ...}`.
3. Log a `user_data` entry with what the owner said, verbatim where it is a claim. Then queue the research with `POST /api/requests {"url": "carlos://listing/<id>"}`: the CAPTURE unit has no ad to read and goes on to the variant, generation, engine and tax research.

### Many listings at once (2026-11-03: 11 listings)
- Navigate + extract in one `browser_batch` per 5 listings. The extraction script stores each capture in the mobile.de origin's `localStorage.__caps` (keyed by listing id), so nothing is lost between navigations.
- Moving the data to disk without retyping it: outputs are cut at ~1,000 characters, so 50 KB would need ~56 chunked reads.
  1. Start a tiny one-shot receiver on `127.0.0.1:8765` in the scratchpad. It writes the POST body to a file and must not live in the repo.
  2. From the mobile.de tab, set `location.href = 'http://127.0.0.1:8000/#cap=' + encodeURIComponent(localStorage.__caps)`. The fragment is never sent to any server.
  3. On the 127.0.0.1 page, POST `decodeURIComponent(location.hash.slice(5))` to the receiver (`mode: 'no-cors'`, `text/plain`) and clear the hash with `history.replaceState`.
- **Do not** `fetch` 127.0.0.1 directly from the mobile.de page. Chrome shows a local-network permission prompt that freezes the tab; never accept it. Close the tab instead; `localStorage` survives.
- Build the capture JSONs with a script from the saved file. Non-breaking spaces (`\xa0`) appear in values such as `59\xa0kW`. Then run `capture_listing.py` with `--dry-run`, then for real.
- The listing links shared by the user may contain `action=parkItem`; always strip it.

## Reliability sources (#351)
Read by hand in the owner's Chrome, in a new tab, one page per engine or generation, never in bulk and never scripted. Stop at a CAPTCHA, Cloudflare check or login and report.
- **Autoscore:** `https://autoscore.pro/engine/<slug>` (no `/de/` prefix; about 120 engines, some not listed, e.g. BMW N45: record `rel.autoscore` `N/A`). Read the risk score (0-10) and the verdict verbatim; ignore the issue table and costs (own-use terms, not stored).
- **EngineScope:** `https://enginescope.gr/engine/<slug>/`. Record the link only; do not copy the score, band or "Total Risk Cost" until written permission is configured (`ENGINESCOPE_PERMISSION`).
- **ADAC Pannenstatistik:** `https://www.adac.de/rund-ums-fahrzeug/unfall-schaden-panne/adac-pannenstatistik/`; the table is drawn by JavaScript, so read it in Chrome: the series, then the breakdown figure and the band (1 best to 5 worst) per registration year.
- **ADAC Gebrauchtwagen-Info:** a public PDF per generation and fuel; search `site:assets.adac.de GWInfo <make> <model>` (no index).
- **TÜV-Report:** the yearly table from the owner's purchased copy, not a web scrape.

## Electric car consumption: ev-database.org
- ev-database.org opens with a plain fetch (WebFetch) or in the browser, no bot check; robots.txt allows it. Find the exact variant and battery (e.g. `https://ev-database.org/car/1164/Renault-Zoe-ZE50-R110`) and read the "Vehicle Consumption" line of the real-world section (Wh/km). If WebFetch does not return that line, read the page in the browser.
- spritmonitor.de is not used: it shows a Cloudflare "Verify you are human" check in the agent's tab (never click it) and plain fetches return 403.

## Tax: BMF Kfz-Steuer-Rechner
- URL: https://www.bundesfinanzministerium.de/Web/DE/Service/Apps_Rechner/KfzRechner/KfzRechner.html (consent banner: "Ablehnen").
- **Fahrzeugart** selects the registration period: "PKW EZ bis 04.11.2008", "… 05.11.2008 bis 30.06.2009", "… 01.07.2009 bis 31.12.2011", "… 01.01.2012 bis 31.12.2013", "… 01.01.2014 bis 31.12.2020", "… ab 01.01.2021". The fields depend on it:
  - up to 04.11.2008: Antriebsart (Diesel/Otto), Emissionsklasse ("Euro 3 bis 6 (einschließlich D3 und D4)", "Euro 2", …), Hubraum;
  - from 07/2009: Antriebsart (Diesel/Otto/Wankel), Hubraum, CO2.
- **Element refs differ** between periods; `find` them after choosing the period. `form_input` works on this page.
- **Reload the page** before each new calculation: changing one field and pressing "Berechnen" again can leave the old result on screen.
- **Fast path (JS, one car per reload):**
  - Field ids: `ct1` period (set `selectedIndex`: 1 = bis 04.11.2008, 3 = 07/2009–2011, 4 = 2012–2013, 5 = 2014–2020, 6 = ab 2021), `ct3` fuel (`Otto` for the old period, `OttoWankel`/`Diesel` for later ones), `ct4` emissions class (`Euro3bis6`, old period only), `ct6` displacement, `ct7` CO2.
  - Dispatch `input` + `change` after each value, wait ~1 s after `ct1`, then click `[name=submitButton]`. The result follows "Die Kfz-Steuer für das Fahrzeug beträgt:".
  - Reload before the next car; batch reload + calculate pairs in `browser_batch`.
- **Record** as described in AGENTS.md (`source_type='tax_official_calculator'`).

## Insurance: no browser task
- Insurance quotes are not read in the browser by any agent (owner decision 2026-11-22, after a legal gap analysis: the comparison site's robots.txt disallows all automated access and its terms ban commercial use). The owner enters a dated quote by hand per listing in the dossier's Costs tab (`POST /api/ui/listing_quotes`).
- The automated CHECK24 unit and its field notes are kept only on the branch `legacy/insurance-automation` (`docs/legacy/insurance-automation.md`).
