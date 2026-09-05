# Results

Written by `pipeline/run_costs.py`, read by `pipeline/build.py`, and by
nothing else. Committed, so the note can be rebuilt without re-running stage 2.

| File | What it holds |
|---|---|
| `technology_costs.csv` | one row per technology: costs, derived marginal cost and emission rate, reference levelised cost |
| `fuel_assumptions.csv` | fuel prices and carbon contents, published and as used |
| `decomposition.csv` | cost per MWh at the reference duty, split into the categories that have a per-MWh form |
| `geography.csv` | §6: the note's own technologies re-priced under each region's inputs |
| `geography_waterfall.csv` | §6: the same, one input changed at a time |
| `geography_assumptions.csv` | §6's regional inputs, carried through from `data/processed/` so stage 3 need not read it |
| `lcoe_capacityfactor.csv` | levelised cost over a grid of utilisations |
| `lcoe_envelope.csv` | which dispatchable technology is cheapest at each duty |
| `lcoe_discountrate.csv` | levelised cost over a grid of discount rates |
| `cost_projections.csv` | the pinned catalogue's 2025–2050 path, indexed |
| `cost_vintages.csv` | the same 2030 projection across seven releases |
| `learning.csv`, `learning_fit.csv` | solar prices and capacity; the fitted curve |
| `summary.json` | every scalar the note quotes in prose |

`summary.json` is the important one: `build.py` turns it into
`writing/generated/numbers.tex`, and the note quotes nothing that is not in it.
