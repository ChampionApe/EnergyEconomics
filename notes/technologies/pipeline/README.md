# Pipeline

Stages 2 and 3.

    run_costs.py   data/processed/ -> results/
    build.py       results/ -> writing/generated/

## `run_costs.py`

Everything the note prints is computed here: annuity factors, levelised costs
over a grid of utilisations and of discount rates, the lower envelope of the
dispatchable technologies, the cost decomposition, the projection paths, the
ordinary least squares fit behind the experience curve, and §6's regional
re-pricing.

That last one is worth a sentence, because it is the section most likely to be
misread. `write_geography()` does not import anybody's regional cost estimate.
It takes the note's own investment costs, lifetimes and fixed O\&M, changes
four inputs per region, and runs them back through `levelised_cost()`. That is
what makes the columns comparable: one boundary, one currency year, one
annuity factor. The inputs themselves are assumptions, written down in
`data/prepare.py` and labelled as such everywhere they surface.

The two functions worth reading are `annuity()` and `levelised_cost()`. They
are four lines each and they are the whole of the note's §4.

Three module constants are assumptions rather than data, and the note says so:
`DISCOUNT_RATE` (7% real), `CARBON_PRICE` (80 EUR/t, used for two illustrative
numbers) and `ELECTRICITY_PRICE` (60 EUR/MWh, the heat pump's fuel price).

Two exclusions are deliberate. Stores get no levelised cost, because they
produce no energy of their own. The lower envelope is computed over the
thermal dispatchables only — reservoir hydro is dispatchable and cheap, but
you cannot decide to have a valley.

## `build.py`

**Reads only `results/`.** It imports nothing from `data/`, computes no cost
and fits no curve. The restriction is enforced by routing every input through
`read()`, which refuses anything outside `results/` and prints what it opened
at the end of the run. If a figure needs a number that is not there, the fix
is to have `run_costs.py` write it.

It emits six figures, six table fragments, and `numbers.tex` — a file of
LaTeX macros holding every number the note quotes in prose. That last one is
what stops the text drifting away from the figure it describes.

Set `FIGURE_PNG=/some/dir` to also write PNG copies of each figure, which is
convenient when checking layout without opening a PDF.

One trap worth knowing: LaTeX command names may contain letters only, so
generated macro names have their digits spelled out (`\numNuclearAtZeroThree`,
not `\numNuclearAt03`). Getting that wrong produces an error three files away
from the cause.
