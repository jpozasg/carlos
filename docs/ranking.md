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
Weights are integers 0–5 per criterion. They come from the questionnaire (`ranking_answers`, eight fixed questions with fixed answers, `GET /api/ranking` lists ids; the UI translates them): each answer adds points to criteria, the sum is clamped to 5. The user may still edit weights by hand (`ranking_weights`); the API then reports `manual: true` and keeps the derived weights for comparison; `ranking_weights: null` returns to the answers.

| Question | Answers → points |
|---|---|
| `cash` how tight is the cash for buying | `tight` cash_now 4 · `some_room` cash_now 2 · `long_run` cash_now 1, cost_month 1 |
| `running` how much the monthly running costs matter | `decisive` cost_month 4 · `important` 2 · `secondary` 1 |
| `trouble` attitude to unplanned repairs | `peace` reliability 4, confidence 1 · `some_risk` reliability 2 · `diy` reliability 1 |
| `wear` mileage and age beyond their cost effect | `fresh` mileage 3, age 2 · `somewhat` mileage 2, age 1 · `costs_only` nothing |
| `drive` performance | `lively` power 3 · `enough` power 1 · `irrelevant` nothing |
| `simple` simple mechanics | `strongly` simplicity 3 · `nice` simplicity 1 · `no_preference` nothing |
| `viewing` findings at viewings | `decisive` inspection 4 · `important` 2 · `not_yet` 1 |
| `evidence` well-documented data over estimates | `prefer_backed` confidence 3 · `a_little` 1 · `ignore` nothing |

## Objectivity rules for agents (the same for every car)
The score is only as fair as the data. These rules keep the inputs comparable:
1. **Same sources, same depth.** Reliability research follows `cost-research-protocol.md` step 2 for every car: ADAC Pannenstatistik/Gebrauchtwagen-Info, TÜV-Report, one buying guide, one engine-specific source. Do not add ten forum anecdotes for one car and nothing for the next: `reliability` counts points, so uneven research depth biases it.
2. **Severity by rule, not by mood.** `HIGH`: can cause engine/gearbox failure or a cost above about 1,500 €; `MEDIUM`: a repair of 300–1,500 € or a safety-relevant defect; `LOW-MEDIUM`: 100–300 €; `LOW`: cosmetic or under 100 €; `HIGH IF APPLICABLE`: a recall or batch problem to check by VIN. One row per distinct failure; no duplicates across levels.
3. **Statuses by rule.** `VERIFIED` only with an A/B source for this engine or variant; `ESTIMATED` whenever a figure was derived or taken from a C/D source, with the derivation in `notes`; `PENDING` never with a number.
4. **Source quality by rule.** A: official (manufacturer schedule, BMF calculator, KBA, fee tables). B: ADAC, TÜV, Haynes, dealer tool, comparison quote. C: aggregators, encyclopedias, consumption databases. D: forums, search snippets, single retailers.
5. **Engine data for `simplicity`** comes from the manufacturer or ADAC description (aspiration, injection, timing drive); unknown stays NULL (the criterion is then not scored for that car), never guessed.
6. **Every risk priced** (estimate when needed) so `cost_month` exists for every car; a car without a complete TCO has no `cost_month` and a lower coverage, which is honest rather than punitive.
7. **Listing contradictions**: the less favourable figure (mileage, CO2), logged as a `warning`.
