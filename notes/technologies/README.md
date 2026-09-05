# Generation technologies — code companion

The scripts and data behind the lecture note *Generation Technologies*.

**Nothing here is required reading.** The note is self-contained and asks you
to run nothing. This directory exists so that every number and every figure in
it can be checked and rebuilt — by you, or by anyone else.

## Layout

    data/        prepare.py (downloads and reshaping) and the processed inputs
    pipeline/    run_costs.py (the computations) and build.py (figures, tables)
    results/     written by run_costs.py, read by build.py

There is no `model/` directory and there are no notebooks. This note solves
nothing; three scripts is the right amount of machinery for what it does.

## Rebuild everything

    python data/prepare.py         # fetches published cost data at pinned versions
    python pipeline/run_costs.py   # annuities, levelised costs, learning fit
    python pipeline/build.py       # results -> writing/generated/

Then compile `writing/main.tex`. The processed data is committed, so the first
step is only needed if you want to verify the fetch — and re-running it should
reproduce the processed files byte for byte, because every source is pinned.

Requirements: Python ≥ 3.11 with `pandas`, `numpy` and `matplotlib`. Step 1
needs a network connection; steps 2 and 3 do not.

## What each stage produces

| Stage | Reads | Writes |
|---|---|---|
| `data/prepare.py` | `data/raw/` (fetching it first if absent) | `data/processed/` |
| `pipeline/run_costs.py` | `data/processed/` | `results/` |
| `pipeline/build.py` | `results/` **only** | `writing/generated/` |

The third stage's restriction is enforced at runtime, not by convention: it
reads every input through one helper that refuses anything outside `results/`.
If a figure needs a number that is not there, stage 2 has to write it.

## The figures and tables, and where they come from

| In the note | Built by |
|---|---|
| Fig. 3.1 cost decomposition | `results/decomposition.csv` |
| Fig. 4.1 levelised cost vs utilisation | `results/lcoe_capacityfactor.csv`, `lcoe_envelope.csv` |
| Fig. 4.2 levelised cost vs discount rate | `results/lcoe_discountrate.csv` |
| Fig. 5.1 realised and projected costs | `results/learning.csv`, `cost_projections.csv` |
| Fig. 5.2 the catalogue across releases | `results/cost_vintages.csv` |
| Fig. 5.3 the solar experience curve | `results/learning_fit.csv` |
| Fig. 6.1 the geography waterfall | `results/geography_waterfall.csv` |
| Tables 1–3, 5 | `results/technology_costs.csv`, `fuel_assumptions.csv` |
| Table 4, regional inputs and results | `results/geography.csv` |
| Every number quoted in the prose | `results/summary.json` → `writing/generated/numbers.tex` |

That last row is the one worth knowing about. The note quotes no number
directly: each is a macro written by `build.py` from `summary.json`, so the
text cannot drift away from the figure beside it.

## Sources

Both are fetched at a pinned version by `data/prepare.py`:

- **PyPSA `technology-data`** at tag `v0.13.2` — compiled cost and technical
  assumptions, largely from the Danish Energy Agency catalogue, in 2020 euros.
- **Our World in Data** — world solar PV module prices and cumulative
  installed capacity (CC-BY 4.0).

`data/README.md` records what is done to each, and Appendix D of the note
records which numbers are sourced and which are assumptions.

The note's §6 compares regions and fetches nothing at all: its regional
inputs are hand-authored assumptions in `prepare.py`, and every cost it
prints is computed here from them. `data/README.md` explains why.
