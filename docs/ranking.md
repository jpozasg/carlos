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

### The questionnaire: twelve best–worst choices
Since issue #19 the weights come from **best–worst scaling** (MaxDiff), not from scenario questions. Each of twelve tasks shows three cars of the same model that are equal in everything except one advantage each, as a small table (three rows, three cars, the advantage highlighted). The person taps the car they would buy first, then the one they would buy last; "can't decide" skips a task without counting it.

**Why this method** (four independent reviews, 2026-11-05: survey methodology, form usability, German used-car market, a simulation red-team):
- Direct importance ratings come out flat ("everything matters") and suffer from acquiescence and scale-use bias; forcing a choice discriminates better ([Lee, Soutar & Louviere, *Best–worst scaling*](https://www.cambridge.org/core/books/bestworst-scaling/bestworst-scaling-an-alternative-to-ratings-data/756EDFCDC2DFF6C58A8198F8DB95C526); [Orme, Sawtooth](https://content.sawtoothsoftware.com/assets/f39e8184-8c93-4b3b-a9a3-735cc107907a)).
- Disguised (projective) questions reduce social-desirability bias only on socially sensitive topics ([Fisher 1993](https://academic.oup.com/jcr/article-abstract/20/2/303/1793106)); car priorities are not, so the earlier "life scenario" items added an interpretive leap (e.g. "invest a windfall" → monthly cost) without a benefit. Choices between concrete cars stay indirect (nobody is asked "how important is X") but every answer has an obvious meaning.
- Paired, realistic choices predict real behaviour well and people tolerate many simple repeated tasks ([Hainmueller, Hangartner & Yamamoto 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4345583); [Bansak et al. 2018](https://dspace.mit.edu/handle/1721.1/118642)).
- Burden: 3–5 items per set, each item shown 2–3 times ([Sawtooth MaxDiff design](https://sawtoothsoftware.com/help/lighthouse-studio/manual/maxdiff-designing-study.html)); pairwise AHP would need 36 judgments for nine criteria and constant-sum allocation breaks down beyond about six items.
- Weights depend on the ranges shown ([Fischer 1995](https://scholars.duke.edu/publication/771230)), so tasks show concrete magnitudes.

**Design.** The twelve sets are the four parallel classes of the 3×3 affine plane, so every criterion appears in exactly four tasks and every pair of criteria meets exactly once (`carlos/ranking.py` `TASKS`; a test enforces both). Task and car order are shuffled each time. Ordinary value → advantage (`static/js/quiz.js` `attributes`): running cost €330 → €290 a month (the note converts €40 a month to the account's period); price = the ideal budget → €1,500 less; 150,000 → 100,000 km; registered 13 → 9 years ago; 75 → 115 PS; "one known weak point (repair already in the running cost)" → "none known"; viewing "two small faults (price lowered to cover them)" → "nothing at all"; "turbo, direct injection, dual-clutch" → "no turbo, port injection, manual"; cost figures "half of them estimated" → "all documented". The magnitudes follow the German private used-car market for a 3–15 k€ budget (cars ~8–16 years old with 100–220 k km; a full TCO of €300–400 a month; one 100 k km step worth roughly 1–2 % of value per 10 k km; sources: AutoScout24 private-market data 2024, DAT-Report 2025, TÜV-Report 2026). The ordinary values already include the money effect (a weak point's repair is in the running cost, faults are compensated in the price), so choosing the other car measures the non-money preference that the criterion stands for.

**Simulation check** (red-team, 7 personas and 60 random priority profiles, noisy simulated respondents): rank correlation between true and derived weights 0.69 for the retired 12-scenario design, 0.79 for nine best–worst tasks, 0.84 for these twelve; the true best car among six random cars was picked 64 %, 76 % and 78 % of the time. A second round (18 tasks) added only +0.03; scaling the strongest weight to 5 or shrinkage added under 0.02. The scenario design also induced correlations between criteria purely through its wording (reliability–confidence r = +0.39, age–inspection r = −0.36), which tasks with one advantage per car avoid.

**Scoring.** Per criterion: `s = (times picked first − times picked last) ÷ times answered` (−1…+1), weight = `max(1, int(5 × (s + 1) / 2 + 0.5))` (first every time = 5, always in the middle = 3, last every time = 1: answers never switch a criterion off; only a hand-set 0 does). A criterion never answered gets 3 (neutral); no answers at all = all 3. This is an absolute scale, not "the strongest scaled to 5", so mild preferences stay mild. `GET /api/ranking` returns the `tally` (shown, first, last) per criterion, and the UI explains every weight with it ("shown 3×: bought first 2×, last 0×"). Stored answers: `{"t1": "power>age", …}` (first > last). Answers to retired questionnaires are ignored and reported as `retired_answers: true`, and the UI asks for the new choices.

## Objectivity rules for agents (the same for every car)
The score is only as fair as the data. These rules keep the inputs comparable:
1. **Same sources, same depth.** Reliability research follows `cost-research-protocol.md` step 2 for every car: ADAC Pannenstatistik/Gebrauchtwagen-Info, TÜV-Report, one buying guide, one engine-specific source. Do not add ten forum anecdotes for one car and nothing for the next: `reliability` counts points, so uneven research depth biases it.
2. **Severity by rule, not by mood.** `HIGH`: can cause engine/gearbox failure or a cost above about 1,500 €; `MEDIUM`: a repair of 300–1,500 € or a safety-relevant defect; `LOW-MEDIUM`: 100–300 €; `LOW`: cosmetic or under 100 €; `HIGH IF APPLICABLE`: a recall or batch problem to check by VIN. One row per distinct failure; no duplicates across levels.
3. **Statuses by rule.** `VERIFIED` only with an A/B source for this engine or variant; `ESTIMATED` whenever a figure was derived or taken from a C/D source, with the derivation in `notes`; `PENDING` never with a number.
4. **Source quality by rule.** A: official (manufacturer schedule, BMF calculator, KBA, fee tables). B: ADAC, TÜV, Haynes, dealer tool, comparison quote. C: aggregators, encyclopedias, consumption databases. D: forums, search snippets, single retailers.
5. **Engine data for `simplicity`** comes from the manufacturer or ADAC description (aspiration, injection, timing drive); unknown stays NULL (the criterion is then not scored for that car), never guessed.
6. **Every risk priced** (estimate when needed) so `cost_month` exists for every car; a car without a complete TCO has no `cost_month` and a lower coverage, which is honest rather than punitive.
7. **Listing contradictions**: the less favourable figure (mileage, CO2), logged as a `warning`.
