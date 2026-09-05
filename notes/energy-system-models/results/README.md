# Results

Generated. Nothing here is written by hand: the `pipeline/run_*.py` scripts
write it, `pipeline/build.py` reads it, and nothing else touches it. Committed, so the note can be rebuilt without re-running a
single solve. Each script owns the files that carry its prefix.

| Prefix | Written by | Note section | What it holds |
|---|---|---|---|
| `dispatch_*` | `run_dispatch.py` | §2 | the ten-generator dispatch: merit order, carbon tax, cap sweep, and the technology table |
| `dispatch_t_*` | `run_dispatch_t.py` | §3 | hourly dispatch on the 2024 DK1 profiles: hours, residual load, duration curves, the penetration sweep, and the validation week |
| `storage_*` | `run_storage.py` | §4 (and fig. 9.6) | battery arbitrage, the ramp sweep and the recovery experiment |
| `heat_*` | `run_heat.py` | §5 | heat pump dispatch and the rollout sweep |
| `network_*` | `run_network.py` | §6 | zonal prices, congestion rents, the calibration and validation, the expansion accounts |
| `greenfield_*` | `run_greenfield.py` | §7 | screening curves, cost recovery, scarcity rents, the optimal mix and its scenarios |
| `expansion_*` | `run_expansion.py` | §8 | the three-rung expansion ladder on the twelve-zone network |
| `weather_*` | `run_weather.py` | §9 | the §7 reference case re-solved on each weather year |
| `costs_*` | `run_costs.py` | §9 | the same under pessimistic and optimistic cost readings |
| `taxcap*` | `run_taxcap.py` | §9 | tax versus cap across weather years |

Every `*_summary.json` holds the scalars its section quotes in prose;
`build.py` turns them into the macros the note reads, so the note quotes
nothing that is not in one of these files.

The `*_resolution_check.json` files hold the full-year solves that the
segment-based §7 and §8 instances are checked against. They take hours on a
commercial solver and are not something to re-run casually.

This directory is the interface between the compute stage and the build
stage. Anything a figure or table needs must exist here as a file;
`build.py` may not reach back into the models to compute it. It reads only
this directory and writes the note-facing output to `../writing/generated/`.

`cache/` holds solved model instances and intermediate artefacts, named
`{experiment}_{case}_{hours}[_{aggregation}].nc` (stride sampling keeps the
bare name). It is large binaries and is never published — it is in the
manifest's `forbidden_sources`. Without it every `run_*.py` simply solves
fresh, which at the default instance size takes seconds.
