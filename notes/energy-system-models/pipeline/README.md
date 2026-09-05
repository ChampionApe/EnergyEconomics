# Pipeline

Scripts that turn models and data into the note's figures and tables.
**Published to students**, so that they can reproduce them.

## Stages

    run_*.py     data/processed/ + model/  ->  results/             (expensive)
    build.py     results/                  ->  writing/generated/   (seconds)

`build.py` reads **only** `results/`. It imports no model code, unpickles
nothing, and solves nothing. Keeping that true is what makes rebuilding the note
cheap; breaking it usually happens by importing a model module for a constant or
an axis label. If a figure needs a number that is not in `results/`, have the
`run_*` stage write it out.

`build.py` writes figures, table fragments and quoted-number macros into
`writing/generated/`, next to the tex source, so the note compiles from
`writing/` alone. Everything under `writing/generated/` is overwritten on every
build.

## Contents

<!-- One line per script: what it produces. -->

- `run_dispatch.py` — solves the section 2 instances (base, carbon tax, cap
  sweep) and writes `results/dispatch_*.{csv,json}`. Seconds.
- `run_dispatch_t.py` — solves the section 3 instances (a year of hourly
  dispatch, VRE penetration sweeps, the linopy-vs-PyPSA cross-check) and
  writes `results/dispatch_t_*.{csv,json}`. Seconds at the default
  `--hours 168`; a few minutes at the note's `--hours 8784`.
- `run_storage.py` — section 4: base battery, no-storage counterfactual,
  the ramp-rate sweep on DK1's slow thermal plant, wind-value recovery
  sweep, and the perfect-foresight vs myopic comparison for section 9. Contiguous hours (storage needs them);
  `--hours 8784` for the note's figures.
- `run_heat.py` — section 5: coupled heat/power base case and the heat
  pump rollout sweep. Contiguous hours; `--hours 8784` for the note.
- `run_network.py` — section 6: zonal dispatch on the 12-bidding-zone network,
  congestion rents, wind smoothing, the Skagerrak expansion sweep with a
  per-zone welfare account (consumers, producers, owners' income net of
  losses) at every size, and the geography file behind the map and
  topology figures. Every solve charges the 2024 ETS average and runs on
  the network calibrated to 2024 (Norwegian inflow scaled to SSB's hydro
  production by a short secant search on the solved output; internal
  Nordic corridors derated to TYNDP's reference NTCs), plus a four-solve
  check of the calibration for Appendix C. `--raw-hydro`, `--raw-ntc`,
  `--hydro-factor F` and `--skip-calibration-check` switch the pieces.
  The note's figures use `--hours 1095` (chronological segments, like
  every other network section). Not cached: about fifteen minutes on
  Gurobi for the full chain.
- `run_greenfield.py` — section 7: screening data, CO2 budget sweep,
  scenario runs, and the small-vs-full cost check. Caches solved networks
  in `results/cache/`, keyed by case, size and aggregation scheme.
  `--resolution-check` adds the full-year reference solve.

  All four network scripts (`run_network`, `run_greenfield`, `run_weather`,
  `run_costs`) and `run_expansion` take `--hours` and `--aggregation`. The
  default, 336 chronological segments, solves in seconds to a minute; the
  note's figures use 1095 segments. See
  `model/network.py` for what the schemes do and how they were tested.
- `run_weather.py` — section 9: the greenfield re-solved per weather year
  2015–2024, all twelve zones on one consistent ERA5 year from
  `data/processed/weather_zones_{year}.csv` (requires run_greenfield.py
  first; cached — and the cache tag names the weather source, so changing
  the source cannot silently serve old solves).
- `run_costs.py` — section 9: the same greenfield re-solved on a
  pessimistic and an optimistic reading of the 2050 cost projection, plus
  the baseline (requires run_greenfield.py first; cached). The scenarios
  take technology-data's own 2025→2050 trend and realise half of it, or
  overshoot it by half again, uniformly across technologies — see
  `data/processed/cost_scenarios.csv`. It used to sweep the published
  vintages 2025–2050, which asked "what if it were 2035?" rather than "what
  if 2050 turns out dearer than projected?". Needs the cost files
  `data/prepare.py` builds, which are not shipped — their source's licence
  bars redistribution.
- `run_expansion.py` — section 8: the three-rung expansion ladder on the
  twelve-zone network (every zone extendable, then industrial hydrogen,
  then the grid), each rung swept over the CO2 budget. Cached;
  `--resolution-check` adds the full-year solve of the top rung.
- `run_taxcap.py` — section 9: the ladder's basic rung re-solved on each
  weather year under a fixed budget and under a fixed tax (requires
  run_expansion.py first). Tax versus cap, measured on this system.
- `build.py` — builds all figures (2.1–9.6), table 2.1 and the
  quoted-numbers macros (`*_values.tex`) into `writing/generated/`.
