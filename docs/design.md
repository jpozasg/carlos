# Design

The visual decisions behind the Carlos front end, so the next change (by a person or an agent) extends the same world instead of starting a new one. Mode: **Operate** (a tool the person is inside while deciding about a car), with one committed moment per page where the brand shows.

## Subject, audience, job
A personal tool for deciding whether to swap the car you own for one of the used cars you follow, on the German market. One owner plus a few friends. The job: see within seconds whether switching pays, then dig into the evidence behind every number. The joke in the name (a Spaniard without a car) sets the tone: friendly, slightly playful, never flippant about money.

## Palette (default theme, "instrument cluster")
An instrument cluster at night, chosen by the owner as the main look.
- Near-black `#0B0D10` page, dark surfaces `#13161B`, light ink `#F2F3F5`.
- Amber `#F5A524` as the accent: selection, the current tab, focus, the ruler markers. Amber carries dark text, never white.
- Teal `#2FD4A8` for "costs less" and good states; red `#FF5C5C` for "costs more". Status colours stay reserved for status.
- The big readouts (versus number, spec plate figures, cost per month) use a monospace readout face on purpose: it is the cluster's digital display, not a costume.
- The "friendly" light theme uses road colours instead: concrete `#F2F2EF`, asphalt ink, road-marking yellow, teal-green links.
Other themes replace these tokens wholesale (`static/css/tokens.css`); layout and components never change with the theme.

## Type
One family: **Bricolage Grotesque** (SIL OFL, self-hosted in `static/fonts/`, variable weight and optical size). Large sizes use the wide optical size for the versus number and page titles; small sizes stay neutral for labels and data. Numbers use tabular figures. Scale in rem with a 1.15 ratio; no fluid headings. No all-caps labels, no eyebrows above headings, no arrows appended to links, no monospace as a costume.

## Layout concepts
- **Compare** opens with the **versus strip**: your car on the left, the best buy right now on the right, one number between them: how much less (or more) per month. That is the page's memorable element; everything under it is quiet.
- Below it the **cost ruler** (default view): every car is a row with a marker on one shared euro-per-month axis; your car is the dashed line across all rows. Left of the line costs less, right costs more. Filled marker = complete cost of ownership; hollow = partial subtotal. The table, costs, break-even, details and cards stay as views.
- **Dossier** opens with the photo and, beside it, the **Your Carlos score** card (two field strips, score 0–100 and total cost per month from most expensive to cheapest: every compared car a dot, this car the marker in the rating colour, the owner's car a dashed tick; the rating word, rank and coverage) above the **spec plate** (the cost per month first, the key figures, reliability per part), and the verdict as a stamp when one exists. Sections below in two columns on desktop, as tiles in the spec plate's colours.
- **Ranking**: the questionnaire as question cards, the result list with per-criterion contribution bars.
- **Models**: the tree make → model → generation → engine → variant.

## Motion
One authored moment: on the compare page the ruler markers slide from your car's line to their place (400 ms, ease-out) once per load. Everything else is state feedback at 150–200 ms. `prefers-reduced-motion` disables the slide.

## Writing
Sentence case, plain verbs, the product's own words (a listing, a dossier, your car). Buttons name the action. Empty states say what to do next. Unknown values are "pending", never 0.
