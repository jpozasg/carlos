# Ranking: formula and objectivity rules

The ranking answers one question: *given what matters to this account, which car for sale looks best?* It is a weighted score 0–100 among the candidates (listings that are not the reference car and not withdrawn). The reference car is never ranked.

## Criteria (no metric counts twice)
| Key | Better | Value | Why it is separate |
|---|---|---|---|
| `cost_month` | lower | complete TCO ÷ months of the period: fuel, insurance, tax, maintenance, repairs (certain + expected), tyres, purchase/sale, depreciation | the one money figure; fuel, insurance and tax are **only** here |
| `cash_now` | lower | asking price + purchase costs of the car | liquidity: what leaves the bank account now (depreciation inside `cost_month` uses price − resale, a different thing) |
| `mileage` | lower | km on the odometer | wear not captured by costs |
| `age` | lower | years since first registration | wear and age-related risk not captured by costs |
| `reliability` | lower | severity points of the documented watch points (variant + engine + generation): HIGH 3, HIGH IF APPLICABLE 1.5, MEDIUM 2, LOW-MEDIUM 1, LOW 0.5 | the hassle of known weak points; their expected money cost is already in `cost_month` |
| `inspection` | lower | checklist items marked PROBLEM; unknown until something was checked | findings on the actual car |
| `power` | higher | PS | driving |
| `simplicity` | higher | naturally aspirated +1, port injection +1, timing chain +1 (dry belt +0.5, wet belt 0), manual gearbox +1; unknown while any field is unknown | the user's preference for simple mechanics, from engine data |
| `confidence` | higher | average evidence quality of the rows behind the costs: status VERIFIED/official/primary 1, ESTIMATED 0.5, other 0; source quality A 1, B 0.8, C 0.5, D 0.3, none 0.3 | how much to trust `cost_month` |

Price, consumption, insurance and tax are still shown as information but are not criteria: they are inside `cost_month` (and `cash_now` for the price).

## Formula
For each criterion with weight > 0 and at least two candidates with a value: `score = (value − worst) / (best − worst)` (0–1, best = 1, all equal = 1). Car score = `Σ weight × score / Σ weight of the criteria this car has a value for`, × 100. **Coverage** = Σ weight of the criteria with a value ÷ Σ all weights: a car with missing data is scored on what is known and shows a lower coverage; missing data never counts as 0. `GET /api/tco` returns per car `score`, `rank`, `coverage`, `score_parts` and `explain` (value, bounds, weight, score, contribution, why a criterion is missing).

## Weights
Weights are integers 0–5 per criterion. They come from the questionnaire (`ranking_answers`), or are set by hand (`ranking_weights`); the API then reports `manual: true` and keeps the derived weights for comparison; `ranking_weights: null` returns to the answers.

### The questionnaire (indirect, scenario-based)
Twelve everyday situations instead of "how important is X" (issue #13): the person answers what they would do, not what they think they should value, and Carlos infers the priorities from the pattern. While answering, no points are shown; afterwards the Ranking page and the setup wizard show every criterion's weight with the answers that produced it ("because you said …"), so the inference is never hidden.

Rules that keep it sound:
- every answer adds points to one or more criteria (or none: a neutral answer);
- every criterion is fed by at least two questions (a test enforces it), so no single answer decides it;
- per criterion, the points earned are divided by the most it could have earned from the questions answered (share 0–1); the largest share becomes 5 and the others scale with it (`round(5 × share / top share)`). Only the relative weights matter to the score, so scaling the strongest preference to 5 loses nothing;
- no answers at all: every criterion gets 3 (neutral); answers to retired questions are ignored when read.

The mapping (ids in `carlos/ranking.py`, texts in `static/i18n/*.json`):

| Question | Answers → points |
|---|---|
| `windfall` An unexpected €1,000 lands in your account. What happens to it? | `cushion` cash_now 2, reliability 1 · `car_fund` mileage 1, age 1 · `invest` cost_month 2 · `treat` power 1 |
| `no_start` Monday, 7:40. Your car won't start. What goes through your head? | `toolbox` simplicity 2 · `call` reliability 1 · `nightmare` reliability 3, confidence 1 · `shrug` nothing |
| `listing_eye` You open a car listing. Where does your eye go first? | `price` cash_now 2 · `km_year` mileage 2, age 1 · `history` confidence 1, reliability 1, inspection 1 · `engine` simplicity 1, power 1 |
| `twins` Two cars, same model, same condition. One is €1,500 cheaper but has 60,000 km more. Which do you take? | `cheaper` cash_now 3 · `fewer_km` mileage 3 · `per_month` cost_month 3 |
| `old_gem` A 15-year-old car in excellent condition, one careful owner. Your gut says… | `condition` inspection 2 · `if_cheap` cash_now 1, age 1 · `no_old` age 3 |
| `motorway` Joining the motorway behind a lorry, traffic coming fast. You want the car to… | `surge` power 3 · `manage` power 1 · `patient` cost_month 1 |
| `gadgets` Turbo, direct injection, dual-clutch gearbox, start-stop. Your first thought? | `progress` power 1 · `breakable` simplicity 3, reliability 1 · `indifferent` nothing |
| `oil_stain` The seller is friendly and the car is spotless, but there's a fresh drop of oil under the engine. You… | `walk` inspection 3, reliability 1 · `haggle` inspection 1, cash_now 1 · `workshop` inspection 2, confidence 1 · `normal` nothing |
| `friend_tip` A friend swears by their car's model. Opinions online are mixed. You… | `statistics` confidence 2, reliability 1 · `trust` nothing · `see_one` inspection 2 |
| `budget_shape` Which sentence fits your finances best? | `monthly_tight` cost_month 3 · `savings_thin` cash_now 3 · `relaxed` nothing |
| `five_years` Five years from now, you'd be happiest if this car… | `no_surprises` reliability 2, mileage 1, age 1 · `resell` cost_month 2, mileage 1 · `used_up` cash_now 1, cost_month 1 · `still_fun` power 2 |
| `two_quotes` Car A is estimated at €230 a month, but half of the figures are guesses. Car B comes to €250 a month, every figure documented. You… | `cheaper_guess` cost_month 2 · `documented` confidence 2, cost_month 1 · `dig_deeper` confidence 1, inspection 1 |

Why these answers point where they do, in short: the emergency fund, the price-first glance, the cheaper twin, thin savings and "drive it into the ground" read as cash sensitivity (`cash_now`); investing, "cheaper per month", a tight monthly budget, resale and "B, documented" read as cost over time (`cost_month`); fearing a breakdown, service history, distrust of complex technology, statistics and "no surprises" read as reliability; "bonnet up" (DIY) and distrust of turbo/direct injection read as a wish for simple mechanics; leaving at an oil drop, a workshop check and "condition beats age" read as weight on what a viewing finds (`inspection`); low kilometres, "old is old" and resale read as `mileage`/`age`; enjoyment answers read as `power`; statistics, documented figures and "want the missing figures" read as `confidence`. The weights were checked against archetypes (tight budget, enthusiast, peace of mind, DIY tinkerer, rational TCO) before release; `tests/test_app.py` keeps the structural rules.

## Objectivity rules for agents (the same for every car)
The score is only as fair as the data. These rules keep the inputs comparable:
1. **Same sources, same depth.** Reliability research follows `cost-research-protocol.md` step 2 for every car: ADAC Pannenstatistik/Gebrauchtwagen-Info, TÜV-Report, one buying guide, one engine-specific source. Do not add ten forum anecdotes for one car and nothing for the next: `reliability` counts points, so uneven research depth biases it.
2. **Severity by rule, not by mood.** `HIGH`: can cause engine/gearbox failure or a cost above about 1,500 €; `MEDIUM`: a repair of 300–1,500 € or a safety-relevant defect; `LOW-MEDIUM`: 100–300 €; `LOW`: cosmetic or under 100 €; `HIGH IF APPLICABLE`: a recall or batch problem to check by VIN. One row per distinct failure; no duplicates across levels.
3. **Statuses by rule.** `VERIFIED` only with an A/B source for this engine or variant; `ESTIMATED` whenever a figure was derived or taken from a C/D source, with the derivation in `notes`; `PENDING` never with a number.
4. **Source quality by rule.** A: official (manufacturer schedule, BMF calculator, KBA, fee tables). B: ADAC, TÜV, Haynes, dealer tool, comparison quote. C: aggregators, encyclopedias, consumption databases. D: forums, search snippets, single retailers.
5. **Engine data for `simplicity`** comes from the manufacturer or ADAC description (aspiration, injection, timing drive); unknown stays NULL (the criterion is then not scored for that car), never guessed.
6. **Every risk priced** (estimate when needed) so `cost_month` exists for every car; a car without a complete TCO has no `cost_month` and a lower coverage, which is honest rather than punitive.
7. **Listing contradictions**: the less favourable figure (mileage, CO2), logged as a `warning`.
