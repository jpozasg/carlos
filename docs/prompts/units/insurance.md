## Unit INSURANCE (listing id = {LISTING_ID})
Owns the insurance quote of this car: one `listing_quotes` row (status `QUOTE`). Last stage of a listing request, only for accounts that switched on "Insurance quotes by the worker" in Settings (preference `insurance_worker_quotes`). Read `docs/browser-tasks.md` ("Insurance: CHECK24") and the protocol's step 11 first.
Browser: Claude in Chrome, a new tab of your own, closed at the end. Nothing else is done in the browser.

Steps:
1. **Consent and profile.** `GET /api/preferences` (the requester's account): if `insurance_worker_quotes` is absent, end `CARLOS_RESULT failed: consent withdrawn`. Then `GET /api/parameters`: `postal_code`, `sf_class`, `insurance_cover`, `insurance_deductible_eur`, `annual_km`, `purchase_mode` must be set, and the preferences `insurance_holder_*`, `insurance_claims_3y`, `insurance_usage`, `insurance_parking`, `insurance_start_date`. If something is missing or this is the account's reference car, do not start the browser: end `CARLOS_RESULT done: skipped, <reason>`.
2. **The car.** `GET /api/listings/{LISTING_ID}`: HSN/TSN and first registration. Without HSN/TSN end `CARLOS_RESULT failed: no HSN/TSN`.
3. **The form.** Open `https://kfz.check24.de/auto/rechner/web/rechner#/situationSection` in a new tab. Cookie banner: "Nur notwendige Cookies". CHECK24's mandatory broker-information checkbox may be ticked. **Re-enter every section of the form from this account's profile** (Situation, Ihr Auto, Nutzung, Versicherungsnehmer, Fahrer, Vorversicherung, SF-Rabatt, Rabatte, Tarifoptionen), also those that are already filled: the form remembers earlier sessions, and one account's data must never carry into another's quote. Check the matched model after HSN/TSN and retype a TSN that was ignored.
4. **Read the result list.** Take the 5 cheapest reasonable offers (members-only tariffs excluded) for the profile's cover and excess: `annual_premium_eur` = their median, `premium_min_eur` = the cheapest, `insurer` and `tariff` of the cheapest.
5. **Write** (source of type `comparison_site`, quality B):
```python
s = src(title='CHECK24 Kfz-Versicherungsvergleich', url='https://kfz.check24.de/', quality='B', source_type='comparison_site',
        supports='Insurance quote for one car and one profile', limitations='Quote of one day for the saved profile; offers change; not an offer to contract')
post('listing_quotes', {'listing_id': {LISTING_ID}, 'annual_premium_eur': <median>, 'premium_min_eur': <cheapest>, 'premium_status': 'QUOTE',
     'insurer': '<cheapest insurer>', 'tariff': '<its tariff>', 'quote_date': DAY, 'source_id': s,
     'quote_profile': {'cover': ..., 'excess_eur': ..., 'sf_class': ..., 'annual_km': ..., 'usage': ..., 'parking': ..., 'purchase_mode': ...,
                       'workshop_binding': ..., 'start_date': '<date the form accepted>', 'extra_drivers': <n>, 'hsn': ..., 'tsn': ..., 'first_registration': ...}})
```
`quote_profile` is a JSON object and never holds names, birth or licence dates, the postal code, occupation, previous insurer, email, phone, reference numbers or screenshots. Add a `log(...)` entry (kind `verification`) naming the quote.

Forbidden: choosing a tariff or pressing "weiter" towards an application, requesting an eVB, logging in, the "Sophie" chat ("Neu angeschafftes Auto versichern" on the landing page), solving or bypassing a CAPTCHA or Cloudflare check (on a block end `CARLOS_RESULT failed: blocked by <site>`), any other use of the browser. If no browser is available (none, or several and none selected: never pick one) end `CARLOS_RESULT failed: browser unavailable (<what the tool said>)`.
Last line: `CARLOS_RESULT done: <insurer/tariff, median premium>` or `CARLOS_RESULT failed: <reason>`.
