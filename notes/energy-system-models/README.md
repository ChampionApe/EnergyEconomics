# Energy system models — code companion

Every model, script and dataset behind the lecture note *Energy System
Models* (`energy-system-models.pdf`).

**The division of labour is deliberate.** The note explains the economics and
never mentions code. This file, and the notebooks it points to, are where the
code lives — how to install it, how to run it, how it maps onto the note's
notation, and how to reproduce every figure and table. Nothing here is
required reading for the note, and nothing in the note requires you to run
anything.

## Start with the notebooks

If you want to *use* the models rather than read about them, the notebooks in
[`notebooks/`](notebooks/) are the way in. They run top to bottom on a laptop,
and each one ends with things to try.

| Notebook | Note section | What you do |
|---|---|---|
| [`00-start-here.ipynb`](notebooks/00-start-here.ipynb) | — | Check the install; solve the smallest model; read a price off a dual |
| [`01-dispatch-and-the-price.ipynb`](notebooks/01-dispatch-and-the-price.ipynb) | §2 | Draw a merit order; carbon tax vs cap; build the abatement cost curve |
| [`02-intermittency.ipynb`](notebooks/02-intermittency.ipynb) | §3 | Capacity factors, capture prices, cannibalisation, the ratio trap |
| [`03-storage.ipynb`](notebooks/03-storage.ipynb) | §4 | Battery arbitrage, ramping, what storage does to the price |
| [`04-heat.ipynb`](notebooks/04-heat.ipynb) | §5 | A heat pump's moving COP; two prices, one exchange rate |
| [`05-transmission.ipynb`](notebooks/05-transmission.ipynb) | §6 | Zonal prices, congestion rent, a bigger cable |
| [`06-investment.ipynb`](notebooks/06-investment.ipynb) | §7 | Screening curves, what Denmark should build, a CO2 budget |
| [`07-expansion.ipynb`](notebooks/07-expansion.ipynb) | §8 | Every zone extendable, one budget, the ladder |
| [`08-uncertainty.ipynb`](notebooks/08-uncertainty.ipynb) | §9 | Weather years, cost scenarios, tax versus cap |
| [`09-reproducing-the-figures.ipynb`](notebooks/09-reproducing-the-figures.ipynb) | all | The three-stage pipeline, and how to rebuild any figure |

Notebooks 00–04 run in seconds and need nothing beyond the install below.
Notebooks 05–09 solve the twelve-zone network and take a few minutes each;
they also need the technology-cost tables, one download step described
under *Install*.

Launch them with `jupyter lab` from anywhere in the repository — the first
cell finds the note's directory on its own.

## Install

Python ≥ 3.11 with

    pip install pypsa tsam matplotlib pandas openpyxl

`pypsa` brings `linopy` (the optimisation layer) and `highspy` (the HiGHS
solver) with it, so this is a complete, free, no-registration toolchain.
`tsam` is the time-series aggregation package the network models of §6–9
use to cut the year into segments (see `model/network.py`). Only
`data/prepare.py`'s map step (the bidding-zone polygons behind §6's two
geography figures) needs `geopandas` on top; the processed file it writes
is shipped, so running the models and the pipeline does not.

HiGHS solves everything. If you have a Gurobi licence (free for students;
`INSTALL.md` at the repository root says how), set `ESM_SOLVER=gurobi` and
the network models of §6–§9 use it instead — same solution, same prices,
several times faster at the full instance sizes.

## Layout

    notebooks/   instructional notebooks — start here
    model/       the models, one module per section of the note
    pipeline/    scripts that solve them and build the note's figures
    data/        prepare.py (downloads + reshaping) and processed inputs
    results/     written by the pipeline (see results/README.md); figures land
                 in writing/generated/

The processed data ships with the repository, with one exception. The
technology-cost tables the network models of §6–§9 read
(`technology_costs_full_*.csv`) are our reshaped subset of PyPSA's
technology-data, whose compiled outputs carry no single stated licence, so
they are not redistributed from here. Build them once, from this directory:

    python data/prepare.py --costs-only

Six small downloads at a pinned version, a few seconds, byte-identical to
what the note was built on. Everything for §2–§5 runs without this step;
notebooks 05–09 need it.

Re-running `python data/prepare.py` without the flag re-fetches every raw
source (Energi Data Service, Open-Meteo, TYNDP, technology-data) and
reproduces the processed files byte-for-byte; it is slow and you will not
need it. `data/processed/network_eur_bz_2024.nc` — the 12-bidding-zone
DK/DE/SE/NO network of §6–§9 — is not produced by it at all: derived once
from PyPSA-Eur (the note's Appendix C documents how) and vendored; you load
it, you don't rebuild it.

## Reproduce the note's figures

Each `run_*.py` solves in seconds at its default instance size; the value in
the second column reproduces the note's own figures exactly (minutes, not
hours). Then `python pipeline/build.py` turns results into figures.

| Note section | Command for the note's figures | Figures |
|---|---|---|
| §2 Dispatch | `python pipeline/run_dispatch.py` | 2.1–2.4, table 2.1 |
| §3 Intermittency | `python pipeline/run_dispatch_t.py --hours 8784` | 3.1–3.8 |
| §4 Storage | `python pipeline/run_storage.py --hours 8784` | 4.1–4.4, 9.6 |
| §5 Heat | `python pipeline/run_heat.py --hours 8784` | 5.1–5.3 |
| §6 Transmission | `python pipeline/run_network.py --hours 1095` | 6.1–6.8 |
| §7 Investment | `python pipeline/run_greenfield.py --hours 1095` | 7.1–7.6 |
| §8 Expansion at European scale | `python pipeline/run_expansion.py --hours 1095` | 8.1–8.4 |
| §9 Uncertainty | `python pipeline/run_weather.py --hours 1095` and `python pipeline/run_costs.py --hours 1095` (both after §7's run), then `python pipeline/run_taxcap.py --hours 1095` (after §8's run) | 9.1–9.5 |

`--hours` is the instance-size parameter throughout. For the dispatch-only
models it samples every k-th hour of the year (so even a small run sees all
four seasons); for storage and heat it is a contiguous block from 1 January,
because state of charge and heating seasons cannot be sampled apart.
Expensive solves (§7–§9) are cached in `results/cache/` — delete the cache to
force fresh solves.

## The notation bridge: code ↔ note

**Layer 1 — explicit linopy (§2–§3).** `model/dispatch.py` and
`model/dispatch_t.py` write the LP constraint by constraint, and every
constraint's name is the LaTeX label of the equation it implements:

| In the code | In the note | Dual read off it |
|---|---|---|
| variable `q` | dispatch $q_g$ resp. $q_{g,h}$ | — |
| constraint `balance` | eq:dispatch:balance / eq:intermittency:balance | $\lambda$, the price |
| constraint `capacity` | eq:dispatch:capacity / eq:intermittency:capacity | $\mu_g$, the scarcity rent |
| constraint `cap` | eq:dispatch:cap | $\sigma$, the carbon price |
| `marginal_cost(tech)` | $c_g = p^F_g/\eta_g + o_g$ (eq:dispatch:mc) | — |
| `emission_rate(tech)` | $e_g = \varphi_g/\eta_g$ | — |
| `capacity_factor`, `capture_price`, `value_factor` | eq:intermittency:cf / :capture / :vf | — |

Sign convention: solvers report the dual of a binding ≤-constraint in a
minimisation as non-positive; the code flips the sign once so that what you
read matches the note's non-negative multipliers.

**Layer 2 — PyPSA (§3 onwards).** PyPSA components expand into exactly the
constraints of the note; §3 of the note verifies this numerically (the two
idioms give bit-identical prices). The dictionary:

| In the equations | In PyPSA |
|---|---|
| market clearing at a bus, eq:intermittency:balance | `Bus` + `Load` with `p_set` |
| its dual $\lambda_h$ | `n.buses_t.marginal_price` |
| capacity limit, $\gamma = 1$ | `Generator` with `p_nom`, `marginal_cost` |
| availability profile $\gamma_{g,h}$ | the same `Generator` with time-varying `p_max_pu` |
| storage balance, eq:storage:soc | `StorageUnit` (`p_nom`, `max_hours`, efficiencies) |
| its state $soc_h$ | `n.storage_units_t.state_of_charge` |
| heat pump conversion, eq:heat:cop | `Link` from elec to heat bus, `efficiency` = hourly COP |
| an interconnector | `Link` with `p_min_pu=-1` between zone buses |
| congestion rent, eq:transmission:rent | flow (`n.links_t.p0`) × zonal price spread |
| extendable capacity (§7) | `p_nom_extendable=True` with `capital_cost` |
| annualised capital cost, eq:investment:annuity | `capital_cost` = (annuity + FOM) × investment |
| CO2 budget and its dual $\sigma$ | an extra constraint added in `model/greenfield.py`; dual read from the model |

A minimal PyPSA rendition of §3's model, to fix ideas:

```python
import pypsa

n = pypsa.Network()
n.set_snapshots(load.index)
n.add("Bus", "elec")
n.add("Load", "demand", bus="elec", p_set=load)
n.add("Generator", "ccgt", bus="elec", p_nom=1500, marginal_cost=64.3)
n.add("Generator", "wind_onshore", bus="elec", p_nom=1500,
      marginal_cost=1.3, p_max_pu=availability["wind_onshore"])
n.optimize(solver_name="highs")
n.buses_t.marginal_price          # the price path, lambda_h
```

Nothing is hidden: `n.optimize()` builds the same linopy problem §2–§3 write
by hand and passes it to the same solver.

## Suggested first experiments

- §2: raise the load in `pipeline/run_dispatch.py` until the oil peaker sets
  the price; find the carbon tax at which coal exits the dispatch, and check
  both against table 2.1 by hand.
- §3: change `--hours` and watch which figures are robust to instance size.
- §4: give the battery 8 hours instead of 4 and see what happens to wind's
  capture price in the recovery experiment.
- §7: change the discount rate in `model/greenfield.py` and reconcile the
  new mix with the annuity formula of the note's Appendix B.

The marginal costs and emission rates the note prints are computed by the
model from the same file (`data/processed/technology_costs_small.csv`) at
run time — the table you read and the model you run cannot disagree.
