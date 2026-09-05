# Abatement costs — code companion

The model and scripts behind the lecture note *A Simple Model of Abatement
Costs*.

**Nothing here is required reading.** The note is self-contained and asks you
to run nothing. This directory exists so that every figure in it can be
checked and rebuilt — by you, or by anyone else.

## Layout

    model/       the model: economy.py (section 1), technologies.py (section 2)
    pipeline/    run_simple.py, run_technical.py (the evaluations)
                 and build.py (the figures)
    results/     written by the run_* scripts, read by build.py

There is no `data/` directory and no downloads. Every number in this note is a
parameter of a stylised model, and the parameters live in `model/` beside the
equations that use them.

## Rebuild everything

    python pipeline/run_simple.py      # section 1: baseline, MAC curve, optimum
    python pipeline/run_technical.py   # section 2: the technology menu
    python pipeline/build.py           # results/ -> writing/generated/

Then compile `writing/main.tex`. The whole thing takes about a second.

Requirements: Python ≥ 3.11 with `numpy`, `scipy`, `pandas` and `matplotlib`.
No solver, no network connection.

## What each stage produces

| Stage | Reads | Writes |
|---|---|---|
| `pipeline/run_simple.py` | `model/economy.py` | `results/simple_*` |
| `pipeline/run_technical.py` | `model/` | `results/technical_*` |
| `pipeline/build.py` | `results/` **only** | `writing/generated/` |

The third stage's restriction is enforced at runtime rather than by
convention: it refuses to import model code, and reads every input through one
helper that refuses anything outside `results/`. If a figure needs a number
that is not there, stage 2 has to write it.

## The figures, and where they come from

| In the note | Built from |
|---|---|
| Fig. 1.1 baseline consumption and emissions | `results/simple_baseline.csv` |
| Fig. 1.2 the marginal abatement cost curve | `results/simple_mac.csv` |
| Fig. 1.3 marginal cost against marginal damage | `results/simple_mac.csv`, `simple_summary.json` |
| Fig. 2.1 what technology does to the cost of emitting | `results/technical_marginal_cost.csv` |
| Fig. 2.2 the MAC curve with and without technology | `results/simple_mac.csv`, `technical_mac.csv` |

## The notation bridge: code ↔ note

| In the note | In the code |
|---|---|
| $F(E) = \gamma E^{\alpha}$ | `Economy.output` |
| $C = F(E) - p_e E$ | `Economy.consumption` |
| $M = \phi E$ | `Economy.emissions` |
| $D(M)$, $D'(M)$ | `Economy.damages`, `Economy.marginal_damages` |
| $E^0, C^0, M^0$ | `Economy.baseline_energy`, `.baseline_consumption`, `.baseline_emissions` |
| $A = M^0 - M$ | `Economy.abatement` |
| $MAC = (F'(E) - p_e)/\phi$ | `Economy.marginal_abatement_cost` |
| $E^*, \tau^*$ | `Economy.optimum` |
| $\theta_i, c_i, \sigma_i$ | `Technology.potential`, `.average_cost`, `.cost_dispersion` |
| $a_i^*$, $f_i(a_i^*)$ | `Technology.utilisation`, `.unit_cost` |
| $\sum_i \theta_i a_i$, $\sum_i \theta_i f_i(a_i)$ | `TechnologyMenu.abated_share`, `.cost_share` |
| the right-hand side of eq. (7) | `TechnologyMenu.marginal_cost_of_emissions` |

## Suggested first experiments

- Section 1: raise $\gamma_D$ and watch $A^*$ and $\tau^*$ move along a fixed
  MAC curve. The curve does not shift — only the crossing does.
- Section 1: change $\phi$. It rescales both axes of figure 1.2, which is
  worth thinking about before running it.
- Section 2: give technology C a smaller $\sigma$ and see the step in
  figure 2.2 sharpen. In the limit the technology switches on at a point, and
  the MAC curve gets a flat stretch.
- Section 2: raise $\sum_i \theta_i$ towards one. `TechnologyMenu` refuses to
  go past it, and the footnote in the note's section 2 explains what happens
  on the other side.
