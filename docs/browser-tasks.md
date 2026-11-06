# Browser tasks: playbook for agents

How to gather data in the user's own Chrome (Claude in Chrome) for Carlos. Rules from `AGENTS.md` always apply. Keep this file updated after every browser session: what worked, what broke, what to avoid. Never write personal data (names, birth dates, licence dates, contact data, premiums paid, insurers) into this file or into the repository; account-specific results go into the database only.

## General
- **Getting started:** load the `chrome-browser` skill, call `tabs_context_mcp` (with `createIfEmpty`), work in your own new tab and close it at the end.
- **Separate Chrome profile (user decision 2026-11-03):**
  - Browser work runs only in a dedicated Chrome profile without the user's logins and cookies.
  - The extension was removed from the user's main profile.
  - At the start, `list_connected_browsers` should show exactly that one browser. If several are connected, ask the user which one; never pick one yourself.
  - **To verify the profile,** open `https://www.check24.de/kfz-versicherung/`. A fresh profile shows the cookie banner, whereas the old profile had consent stored and showed none.
  - Cookie consent in this profile follows the usual rule: the most privacy-preserving option.
  - Never sign in to anything in it.
- **Site permissions ("Permission denied for this action on this domain"):** this often appears when a click moves the tab to another host, e.g. `www.check24.de` → `kfz.check24.de`.
  - **Before telling the user it cannot be done**, navigate the tab to that URL directly with the `navigate` tool and try again. Reaching a host through `navigate` is what works; arriving there by clicking a link is refused.
  - Seen 2026-11-03 twice: the click route was refused, `navigate` to `https://kfz.check24.de/auto/rechner/web/rechner#/situationSection` worked.
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
5. Write the capture JSON and run `python capture_listing.py <file> --dry-run`, then run it without `--dry-run`. Add listing-specific checklist items and warnings.

### Leasing offers (issue #127)
- The price box has tabs "Finanzierung" and "Leasing" (checked 2026-11-05 on a used VW Golf Variant: purchase 20,980 € **and** lease from 223 €/month). Click the **Leasing** tab (read only; never "Leasingangebot anfragen"), then read the tab panel: `[...document.querySelectorAll('[role=tabpanel]')].map(e => e.innerText)`.
- The panel states the rate ("224 € mtl. inkl. MwSt."), "Laufzeit" (48 Monate), "Fahrleistung" (10.000 km pro Jahr), "Anzahlung" (0 €), the "Leasing-Gesamtbetrag", and under "Zusätzliche Informationen": "Bereitstellungskosten", "Zulassungskosten", "Mehr-Kilometer-Kosten", "Minder-Kilometer-Vergütung" — often "Keine Angabe": leave those NULL. Term and km are adjustable ("ändern"): record the default offer as shown; never request an offer.
- Map to the capture's `listing` object: `lease_kind` (`km` unless the ad says Restwert → `residual`, or Auto-Abo/all-inclusive → `abo`), `lease_monthly_eur`, `lease_term_months`, `lease_km_per_year`, `lease_down_payment_eur`, `lease_fees_eur` (Bereitstellung + Zulassung when both are stated; NULL if either is "Keine Angabe"), `lease_extra_km_eur`, `lease_fewer_km_eur` (€/km; convert ct), `lease_includes` (only what the ad says the rate includes, e.g. "inkl. Versicherung" → `insurance`). Put the lessor's name and the panel text in `attributes` verbatim.

### Many listings at once (2026-11-03: 11 listings)
- Navigate + extract in one `browser_batch` per 5 listings. The extraction script stores each capture in the mobile.de origin's `localStorage.__caps` (keyed by listing id), so nothing is lost between navigations.
- Moving the data to disk without retyping it: outputs are cut at ~1,000 characters, so 50 KB would need ~56 chunked reads.
  1. Start a tiny one-shot receiver on `127.0.0.1:8765` in the scratchpad. It writes the POST body to a file and must not live in the repo.
  2. From the mobile.de tab, set `location.href = 'http://127.0.0.1:8000/#cap=' + encodeURIComponent(localStorage.__caps)`. The fragment is never sent to any server.
  3. On the 127.0.0.1 page, POST `decodeURIComponent(location.hash.slice(5))` to the receiver (`mode: 'no-cors'`, `text/plain`) and clear the hash with `history.replaceState`.
- **Do not** `fetch` 127.0.0.1 directly from the mobile.de page. Chrome shows a local-network permission prompt that freezes the tab; never accept it. Close the tab instead; `localStorage` survives.
- Build the capture JSONs with a script from the saved file. Non-breaking spaces (`\xa0`) appear in values such as `59\xa0kW`. Then run `capture_listing.py` with `--dry-run`, then for real.
- The listing links shared by the user may contain `action=parkItem`; always strip it.

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

## Insurance: CHECK24 Kfz-Versicherungsvergleich
- **Consent first:** the user's explicit OK for entering personal data is required in each session (AGENTS.md). The profile and the answers below are recorded in `insurance_data.quote_profile` without birth dates or names.
- **Entry:** navigate directly to `https://kfz.check24.de/auto/rechner/web/rechner#/situationSection` (see "Site permissions"); if a "Sie waren eine zeitlang inaktiv" page appears, it reloads by itself. Do not click through from www.check24.de ("jetzt Tarif finden"), which ends in "Permission denied". If the cookie banner appears, choose "Nur notwendige Cookies".
  - **Do not** use "Neu angeschafftes Auto versichern" on the landing page: it opens the "Sophie" AI chat, which requires a login.
- **Read the profile first:** `GET /api/parameters` (postal code, SF class, cover, excess, purchase mode, annual km) and `GET /api/preferences` (the `insurance_*` keys in `data-model.md`), all set in the setup wizard's Drivers and Insurance steps. Map them to the CHECK24 sections: Situation ← `insurance_start_date`; Ihr Auto ← the listing's HSN/TSN and first registration, `purchase_mode` (cash = Eigenfinanziert); Nutzung ← `insurance_usage`, `annual_km`, `insurance_parking`, `insurance_seasonal_plate`; Versicherungsnehmer ← `insurance_holder_*` and `postal_code`; Fahrer ← `insurance_drivers` (`relationship` partner → Ehe-/Lebenspartner, child → Kind, other or a partner with `household` no → Sonstiger Fahrer); Vorversicherung ← `insurance_previous_insurer`, `insurance_previous_years`, `insurance_cancelled`; SF-Rabatt ← `insurance_claims_3y`, `sf_class`, `insurance_holder_other_car`; Rabatte ← `insurance_discounts`, `insurance_club_name`, `insurance_liability_insurer`; Tarifoptionen ← `insurance_cover`, `insurance_deductible_eur`, `insurance_workshop_binding`. Ask only for what is still missing.
- **A leased car** (a listing whose lease is the offer being costed, #127): on "Ihr Auto" choose **"Geleast"** instead of "Eigenfinanziert", and quote **Vollkasko** whatever the profile's cover (lessors require it); write "leased, Vollkasko" in `quote_profile`. No quote is needed when the rate includes insurance (`lease_includes`).
- **Form sections and the answers used** (profile of 2026-11-03):
  1. **Situation:** "Neu angeschafftes Auto"; "Tarifvergleich mit über 330 Tarifen"; Versicherungsbeginn 01.12.2026.
  2. **Ihr Auto:** HSN + TSN (the matched model is shown; check it); first registration TT.MM.JJJJ (1st of the month when only the month is known); "Eigenfinanziert".
  3. **Nutzung:** "nur privat"; 15.000 km; "Straße (öffentlich)"; no seasonal plate.
  4. **Versicherungsnehmer:** gender, birth date, licence date (TT.MM.JJJJ) and country, Familienstand, Beruf, PLZ, accompanied driving (BF17), points, access to another car. Ask the user; never guess personal data.
  5. **Fahrer:** "Versicherungsnehmer und weitere Fahrer" → "ja" → "Fahrer hinzufügen" → relationship: "Ehe-/Lebenspartner", "Kind" or "Sonstiger Fahrer". A partner in a separate household = "Sonstiger Fahrer". Then gender, birth date, status, household, BF17, points, other car.
  6. **Vorversicherung:** "ja", the previous insurer (autocomplete), duration, not cancelled.
  7. **SF-Rabatt:** claims in 3 years, SF class (dropdown: "SF 1" vs "SF 1/2"), other car insured "nein" when the new car replaces the old one.
  8. **Rabatte:** Kombi chips (e.g. Privathaftpflicht), children, home ownership, transit pass, BahnCard, Automobilclub "ja" → club (ADAC).
     - The required broker-information checkbox (§ 15 VersVermV / § 60 VVG) may be ticked by the agent without asking (standing user decision 2026-11-05). It is only the acknowledgement of the broker information; it never covers choosing a tariff ("weiter"), an application, an eVB or a login.
     - Then "Ergebnis anzeigen".
- **Results page:**
  - A "Tarifoptionen" dialog (Teilkasko, SB 150 €, Werkstattauswahl "durch Versicherer", jährlich) → "übernehmen".
  - The list is numbered ("1. Günstigster Tarif …"). Read it as collapsed `innerText` and strip the feature words; insurer names are logo `alt` texts, so use `find` on the card.
  - Record the median of the first 5 prices plus the cheapest offer (insurer, tariff).
- **Next car:** "Angaben ändern" → "ändern" in "Ihr Auto" → new HSN/TSN and first registration; the other sections stay filled.
- **Never** click "weiter" on a tariff (that starts an application), request an eVB, a callback, or log in.

- **Later runs ask more:** with "Privathaftpflicht" ticked in Kombi-Rabatte, later runs require "Priv. Haftpflichtversicherung bei" (CosmosDirekt, DEVK, HDI, Sonstige). Ask the user. (The 208 was re-run with it and gave identical prices.)
- **Form state is lost** when the extension reconnects or the tab group changes. All sections must be entered again, then switch only the car via "Angaben ändern".
- **Check the matched model and years** after typing HSN/TSN. Candidate TSNs from dieversicherer.de can belong to another generation (e.g. 5013/AGI is the 2015–2018 Auris 1.33, not the 2011 one). If no TSN matches exactly, use the closest one of the right generation and record it as assumed.
- The "Marke & Modell" search did not respond reliably; HSN/TSN entry works.

### Quoting many cars in one session (2026-11-03, 11 cars)
- **Per car:**
  1. `Angaben ändern` (a JS click works; it navigates).
  2. `find` the "ändern" button of "Ihr Auto" and click it.
  3. Type over HSN and TSN, then Tab, and read the matched model from the text after "Fahrzeug ändern".
  4. `find` the "Erstzulassung des Autos" input, select all and type the date.
  5. Click "Ergebnis anzeigen".

  The other sections keep their answers.
- **Results:**
  - The "Tarifoptionen" dialog reappears every time. Confirm it with a JS click on the button whose text is exactly "übernehmen", only if it is present; never click blind coordinates on the results page (a tariff's "weiter" starts an application).
  - Read the cards by walking up from each insurer logo (`img[alt]`) to the container that shows a "… €" price and "jährlich".
  - Sort the prices yourself. Featured cards ("Preis-Leistungs-Empfehlung", WGV/DEVK, ADAC "(Mitglieder)") appear out of order; members-only tariffs are excluded.
- **Pitfalls:**
  - **Window resizes:** the screenshot coordinate frame changes (750 ↔ 1512 px). After a resize, take a new screenshot before clicking, and verify field values with JS (`input.value`).
  - **Screenshot timeouts:** `Page.captureScreenshot` can time out while the page still answers JS. Read the form with `innerText` and continue; screenshots usually work again after the next section.
  - **A "weiter" click that does not advance:** check the inputs with JS, then click the section's "weiter" button with JS.
  - The second driver section asks no licence date or country.
  - No broker-information checkbox appeared before "Ergebnis anzeigen" in this run.

### Run of 2026-11-05 (test account, 3 cars) — what changed
- The "Fahrer" section also asks **Hauptnutzer** and **Halter** (`insurance_main_user`, `insurance_keeper`); each further driver also gets **Familienstand** and **Beruflicher Status**.
- CHECK24 offers only männlich/weiblich; for `diverse` ask the user which to enter.
- Occupation list: Angestellte/r, Arbeiter/in, Angestellte/r öffentlicher Dienst, Rentner/in, Selbstständige/r, z.Z. ohne Berufstätigkeit, Auszubildende/r, Hausfrau/-mann, Beamter/Beamtin, Student/in (the setup's codes map one to one). The Rabatte section also asks Beruf/Branche/Arbeitsweise/Arbeitgeber; "sonstige" is the default.
- Nutzung: "nur privat (inkl. Arbeitsweg)" covers commuting. Kombi chips: Motorrad, Privathaftpflicht, Hausrat, Glas, Rechtsschutz, Unfall, Kranken, Leben, Rente. Children: "unter 17 Jahren".
- After "Angaben ändern" → "ändern" and a new HSN/TSN, the Erstzulassung field is **cleared**: enter it again before "Ergebnis anzeigen".
- A click on "Ergebnis anzeigen" right after ticking the broker checkbox may be ignored; click it again.

Quote results are recorded in `insurance_data` only (one row per quote, no personal data); they do not belong in this file.

### Run of 2026-11-05 (16 cars, one session) — what changed
- **Start date:** CHECK24 refuses a start date about two months ahead for a "Neu angeschafftes Auto" ("Bitte überprüfen Sie Ihre Eingabe"); use the next 1st of the month it accepts and record the profile's date as a note in `quote_profile`.
- **Fast loop per car (two batches):** JS click on the link "Angaben ändern" → `find` the "ändern" button of "Ihr Auto" → `find` HSN/TSN inputs, triple-click and type each, Tab → read the matched model after "Fahrzeug ändern" → `find` the Erstzulassung input (its ref changes between 440/441/442), type → `find` "Ergebnis anzeigen", click → JS click "übernehmen" if present → read the numbered list ("1." … with its price line) and the insurer from the `img[alt]` inside the same card. Focusing inputs by JS and typing did **not** work (the "ändern" click by JS did not open the section).
- **Check the TSN echo every time:** a typed TSN was once ignored (the old TSN stayed and matched another model); retype it.
- **Recording:** `insurance_data.quote_profile` must be a JSON object (a plain string is refused as "malformed JSON").
- **autokostencheck:** the "Gemeldeter Durchschnitt … Grundlage sind N … Meldungen" block is sometimes rendered by JavaScript; plain fetches then show only the stored "Praxisverbrauch". Read it in the browser instead of falling back to another figure.
