# Results

Written by `pipeline/run_simple.py` and `pipeline/run_technical.py`, read by
`pipeline/build.py`, and by nothing else. Committed, so the note can be
rebuilt without re-running stage 2.

| File | What it holds |
|---|---|
| `simple_baseline.csv` | section 1 on the energy grid: $E$, $C(E)$, $M(E)$ |
| `simple_mac.csv` | the same grid read as abatement: $A$, $MAC$, $D'(M)$ |
| `simple_summary.json` | the parameters, the baseline $(E^0, C^0, M^0)$, the optimum $(E^*, C^*, M^*, A^*, \tau^*)$, and the grid endpoints the figures set their axes from |
| `technical_menu.csv` | one row per technology: $\theta_i$, $c_i$, $\sigma_i$ |
| `technical_marginal_cost.csv` | the marginal cost of emitting on the carbon-price grid, with and without the menu, plus the two terms the "with" column decomposes into ($\sum_i\theta_i a_i$ and $\sum_i\theta_i f_i(a_i)$) |
| `technical_mac.csv` | the abatement cost curve with technology: $A$, $MAC$, and the $E$ and $M$ behind them |
| `technical_summary.json` | the menu, its total potential, and the optimum once the menu is available |

The two summary files are the ones that matter beyond the figures:
`build.py` turns them into `writing/generated/numbers.tex`, so that a number
the prose quotes cannot drift away from the figure beside it.

Nothing here is expensive. The whole of stage 2 is a grid evaluation and two
scalar root-finds; delete the directory and it comes back in a second.
