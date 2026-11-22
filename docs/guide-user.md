# Carlos: user guide

For the owner of a Carlos site and for the people you invite to it.

## 1. What Carlos does

Carlos answers one question: **what does a used car really cost you, compared with the car you already own?**

The price on a listing is only the start. Carlos adds up the costs over the years you plan to keep the car:

- **Fuel** or electricity, from the kilometres you drive.
- **Insurance**, from a quote you enter.
- **Road tax**.
- **Maintenance**: the services and parts the manufacturer asks for.
- **Repairs**: faults that are known for this model, and faults this particular car already has.
- **Tyres**.
- **Purchase and sale costs**: registration, a pre-purchase check, and what you get when you sell.
- **Depreciation**: how much value the car loses.

Carlos then ranks the cars for sale by what matters to you, and shows every number with its source.

Carlos does not decide for you. It shows the figures, what is still missing, and how sure each figure is.

## 2. Signing in

- The owner creates your account and sends you an invite link. The link works for 72 hours.
- Open the link and choose a password. It must have at least 8 characters.
- Sign in with your username and password. Your session lasts 30 days on one device.
- Ten wrong passwords lock the sign-in from one address for five minutes. Twenty wrong passwords for one username lock that username for five minutes.
- You can change your password in Settings. This also signs you out everywhere else.

Each account has its own cars, settings, notes and photos. Nobody else sees them, except the admin (see section 12).

## 3. Setup

The setup starts the first time you open Carlos. You can leave it with "Set up later", and you can reopen it from Settings with "Set up again". Each step saves when you press the button at its end. You can go back and change any answer later.

| Step | What you answer | What it changes |
|---|---|---|
| **Driving** | Kilometres per year, years you keep a car, where you drive most (town, mixed, motorway), the car you have now | Every running cost is worked out for this distance and this many years. Mostly town driving uses the stricter service intervals for heavy use. |
| **Money** | Ideal budget, maximum budget, cash or financing, petrol and diesel prices with their dates | Cars above the ideal budget are marked. Cars above the maximum can be hidden. Fuel prices give the fuel cost. Cash or financing is saved and shown in the summary; it does not change the figures yet. |
| **Search** (postal code, town, distance, fuel, gearbox) | Your postal code, the town you search from, the radius, the fuel and gearbox you prefer | The postal code sets the distance to each car, for viewing it. The town, radius, fuel and gearbox are saved as your preferences for the agents who look for cars; they do not change the cost figures. |
| **Workshop** (optional) | Which jobs you do yourself: oil, spark plugs, service, brakes, battery, bulbs, wipers, coolant, timing belt, clutch | Your own jobs count only the parts. Your hours are shown, but never given a price. Jobs you leave to a workshop count the workshop price. Untick everything if a workshop does all the work. |
| **Charging** (optional, electric cars only) | Charging at home (none, socket, wallbox, wallbox planned), share charged at home, wallbox cost, electricity price at home and in public | Sets the electricity cost of an electric car. A normal socket loses about 10 % more energy than a wallbox. |
| **Priorities** | Eight quick choices: from four cars, you pick the best and the worst, eight times | Sets how much each criterion weighs in the ranking (see section 6). |
| **Summary** | Nothing new. Your answers, and your priorities | Shows what is saved. "Pending" means you have not answered. |

You can skip the two optional steps. Skipping posts nothing, so earlier answers stay.

## 4. Adding a car

### By listing link

1. Open **Compare**. At the top, open **Add a car**.
2. Paste the link of the listing. You can add a short note for yourself.
3. Press **Request research**.

The research worker reads the listing, checks the car, and adds it to your cars. The request appears in the list at the top of Compare, with its status (section 9). When the car is in, it shows on Compare and has its own dossier.

Carlos accepts only used cars for sale. New cars, leases and car subscriptions are refused (section 11).

### By hand

Carlos has no form for a new car. An admin or an agent enters a car by hand through the write API, with the same facts as a listing:

- the listing link and the platform, and the listing's own number, if it has one;
- the asking price and the date you saw it;
- the mileage, the first registration, the location;
- the car's make, model, generation, engine and trim, and its HSN and TSN if you have them;
- the seller's claims, marked as claims (for example "belt new").

Ask the admin to add it. Photos can be added later, in the dossier (section 7).

If a listing site blocks automatic reading, the request can still be made. The car is then read from a page in a browser, or from a page you saved.

## 5. Compare

Compare is the main page. It starts with **At a glance**. Six views sit above the list:

| View | What it shows |
|---|---|
| **At a glance** | Each car's cost per month on one common scale, with your car as the reference line. |
| **Table** | The overview table (see below). |
| **Costs** | The cost of each part, stacked for each car. Choose which parts to show. |
| **Break-even** | Keep your car or switch: the money month by month, and the month when switching pays off. |
| **Details** | Every figure of every selected car, in one table. The full data view. |
| **Cards** | One card per car, with photo, cost, and what is still missing. |

### The overview table

- **Check box**: put the car in or out of the comparison. Your own car is always in.
- **#**: the rank from the Ranking page. A car with no rank has no score yet.
- **Car**: click it to open the dossier.
- **Score**: 0 to 100, higher is better. A question mark means the score is provisional (section 6).
- **Asking price**: the price in the listing. This is an asking price, not a sale price. Your own car says "Owned".
- **Km**, **Age**: from the listing.
- **Per month**: the running cost per month, over your ownership period.
- **Total (years)**: the total cost over your ownership period. If it says "partial", some parts are still missing, so this is only a subtotal.
- **Difference**: the cost of this car minus the cost of your car. An up arrow means this car costs more than yours. A down arrow means it costs less. It is shown only when both totals are complete.
- **Status**: budget tags, price changes, cars not checked for a long time, and withdrawn cars.

### What "pending" and "partial" mean

- **Pending** means the amount is not known yet. It is never shown as zero. Carlos does not guess.
- **Partial** (or "subtotal, partial") means at least one part is missing. The total only adds up the parts it knows. The missing parts are named in the dossier.
- A **complete** total means all eight parts are known. Only complete totals are called total cost of ownership, and only complete totals are compared with your car.

### Why the order can differ from the cost

The rank does not follow the cost alone. It follows your priorities: cost per month, cash needed now, mileage, age, reliability, viewing findings, power and how sure the data is. A car can cost less per month and still rank lower, for example because of its age or its reliability.

The sort options work on one column at a time. "Known cost per month" puts cars with a partial cost after the cars with a complete one, so a partial figure never looks like the cheapest car.

Missing data lowers the coverage of a score; it never counts as zero.

### Other controls on Compare

- **Sort** and the arrow next to it change the order.
- **Pin your car** keeps your car at the top.
- **Hide cars over budget** and **Hide withdrawn cars** remove cars from every view. The page says how many cars are hidden.
- **Select** chooses the cars for Costs, Break-even and Details. Quick picks: all, none, the best five, cars within budget, and shortlisted cars.
- **Export CSV** saves the table as a file.
- Filters in Settings (section 10) can also leave a car out of the ranking.

## 6. The Ranking page

Ranking turns your priorities into a score from 0 to 100.

- The questionnaire asks eight quick questions. Each question shows four cars. You pick the best and the worst. The answers set the weight of each criterion.
- You can change the weights by hand with the sliders. The page explains the formula and where each number comes from.
- The nine criteria are: total cost per month, price against budget, mileage, age, reliability (external ratings), viewing findings, power, safety, and distance to view.
- **Reliability** comes from published ratings: the engine rating, the defect share of the technical inspection (TÜV) and the breakdown statistics (ADAC). If one source is missing, the page says "2 of 3 sources". A missing source is never counted as zero.
- A score with a **?** is **provisional**. Less than half of what you weight is known for that car yet. The score firms up when the research fills in.

Your own car is scored the same way, so you can see how it compares. It has no rank.

## 7. The dossier

Click a car to open its dossier. The photos, the score and the key facts stay at the top. Below them are six tabs.

| Tab | What you find there |
|---|---|
| **Overview** | What the car is, its listing facts, the seller's claims, the reasons for its rank, and what is still missing. |
| **Costs** | The eight parts, each with its amount, its basis and its source. Here you also enter an insurance quote (section 8). |
| **Maintenance & repairs** | The service plan for the next years, the repairs to expect, and the repairs this car needs now. |
| **Reliability** | The published ratings, the faults known for this model, and the recalls. |
| **Viewing** | The seller's claims to ask about, the checklist, and viewing mode. |
| **Log & sources** | The listing as it was when captured, your log, and every source used. |

### Your decision

The top of the dossier has four buttons: **Shortlist**, **Plan a viewing**, **Reject**, and an undo. Rejecting takes the car out of the ranking. You can add a reason. You can undo any decision.

### Checklist

The checklist is the list of things to check at the viewing. Each item shows one of four states:

- **OK**: checked and fine.
- **Problem**: checked and something is wrong.
- **N/A**: does not apply to this car.
- **Pending**: not checked yet.

Tap an item to change it. Only that item is saved, and a failed save is shown on that item.

### Viewing mode on a phone

Press **Viewing mode** at the top of the dossier. The viewing tab opens and the top of the page folds to a thin strip, so the checklist starts high on the screen. While you look at the car you can:

- tick the checklist,
- write notes,
- take photos with the camera or pick them from the gallery.

Everything is saved at once. Press **Back to my account** to leave viewing mode.

### Notes stay as you wrote them

Your notes and your checklist remarks are kept exactly as you typed them. Carlos does not rewrite or translate them. If you write in a language other than English, the admin or an agent may add an English translation next to your note. The original stays.

### Photos

- **Add**: press the photo button and pick photos from the gallery, or take new ones.
- **Remove**: each photo has a Remove button. Press it and confirm. The photo leaves the dossier at once. Use this for a photo that shows a licence plate or a VIN.
- **Removed photos**: the removed ones are listed below the photos, with **Restore** and **Delete for good**.
- **Delete for good**: asks you to confirm again. The file is erased from the server and cannot be recovered.

Carlos removes a photo only when you ask it to. Nothing is deleted on its own.

### Log & sources

- **Listing archive**: earlier captures of the listing, so you can see what the ad said before.
- **Log**: a dated list of what happened to the car: found, verified, price changed, decision, your viewing notes, warnings, photos.
- **Sources**: every source used for this car, with its quality from A (official) to D (forum or search snippet), what it supports and what its limits are.

## 8. Insurance

Carlos never gets an insurance quote by itself. It does not start an application, log in to an insurer, or fill in a form. You get the quote yourself and type it in.

How to do it:

1. Open a comparison site or an insurer's calculator in your own browser. Enter the car and your own details there.
2. Copy the premium for the cover you want, per year or per month.
3. Open the dossier of that car, go to **Costs**, and find the insurance block. Press **Enter an insurance quote**.
4. Fill in the premium and whether it is per year or per month. Add the insurer, tariff, cover, deductible, SF class and quote date if you have them. Only the premium is required.
5. Press **Save quote**.

A newer quote replaces the older one in the cost. A quote is marked expired after 60 days. Carlos still uses an expired quote in the cost until you enter a newer one.

Your own car has no quote form. The premium you pay for it is kept as your own data, entered by the admin or an agent.

Insurance premiums are private to your account. The admin can still see them (section 12).

## 9. Requests and their statuses

Each request you send is listed at the top of Compare, with its status. The list keeps the last ten requests.

| Status | Meaning |
|---|---|
| **Queued** | Waiting for the worker. You can cancel the request while it is queued. |
| **Being researched** | The worker is working on it now. |
| **Waiting** | Waiting for another request to finish the same part. |
| **Done** | The car is in your cars. The request links to its dossier. |
| **Already existed** | Part of the research was already in the shared catalogue, so nothing new was needed for it. |
| **Failed** | The worker could not finish. The result says why. You can send the link again. |
| **Cancelled** | You cancelled it while it was queued. |

A request shows its steps as well: capture, variant, generation, maintenance, engine, gearbox, research, tax and listing. Each step is marked done, in progress, waiting, pending or failed. Failed steps say how many items are missing.

The admin sees the whole queue: who asked, when, and what came of it.

## 10. Settings

Settings is the page for your numbers and your preferences. Changes are shown in a preview before you save, and you can discard them.

- **Calculation**: kilometres per year, years you keep the car, fuel and diesel prices and their dates, ideal and maximum budget, whether to hide cars over the maximum, postal code, cash or financing, charging at home, electricity prices, and the wallbox cost. The "derived" line shows the total distance for your period.
- **Filters**: leave out cars that do not fit. You can filter by seller (dealer or private), warranty, service history, accident-free history, and months left on the technical inspection (HU). A car that fails a filter is not ranked. A car with unknown data does not pass the filter.
- **Appearance**: the look of the site has one style, with three modes: **Auto** (follows your device), **Light** and **Dark**.
- **Language**: English, Spanish, German or Polish. Carlos translates its own labels and buttons. Your notes, listing texts and source texts stay in the language they were written in.
- **Password**: change your own password.
- **Download my data**: saves your own data as a JSON file (section 12).
- **Agent token**: only for admin accounts. It lets an agent write data. Keep it private.

## 11. What Carlos does not do

- It does **not** get insurance quotes by itself. You enter them (section 8).
- It does **not** cover **new cars**, **leases** or **car subscriptions**. It compares second-hand cars for sale only. A lease-only ad is refused. A used ad that also offers a lease is recorded as a purchase.
- It does **not** yet work out the energy cost of a plug-in hybrid. The car is recorded, but its fuel cost stays pending.
- It does **not** check seller claims. A claim stays a claim until you check it, for example with an invoice.
- It does **not** check recalls by VIN. Ask a brand dealer for an open-recall check.
- It does **not** tell you what to pay. A listing price is an asking price, not a sale price.
- It does **not** give tax or insurance advice. The tax figure comes from the official calculator, and the rest is your own decision.
- It does **not** delete anything on its own. Old data is archived, not deleted.

## 12. Your data, privacy and erasing

- **Who sees your data.** Only you, and the admin. The admin can see every account, including your notes and viewing data. The admin is the person who runs this Carlos site. If that is not acceptable to you, do not put private data into it.
- **Shared catalogue.** Research on car models (generations, engines, variants) is shared by everyone. It contains no personal data. Your cars, notes, photos, insurance quotes and settings are never part of it.
- **Download my data.** In Settings, press **Download my data (JSON)**. The file holds your cars, notes, photo records, quotes and settings. It does not hold your password, your sessions or the change log.
- **Erase your account.** Only the admin can do this, on the Accounts page. The admin types your username to confirm. Carlos first writes an export file of your data to the server's data directory, then erases your cars, notes, photos and settings. Shared catalogue data stays. Ask the admin before you rely on this: the erasure cannot be undone from the app.
- **Photos you delete for good** are erased from the server at once.

## 13. Quick reference

- Compare: the cars, the ranking and the total costs. Start here.
- Dossier: one car, its costs, its checklist and its photos.
- Ranking: your priorities and the score.
- Settings: your numbers, filters, look, language and data.
- Requests: the status of the cars you asked for.
