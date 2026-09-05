# Models

Model implementations for the lecture note. **Published to students.**

Everything here is read by people learning from it, so it is written to be read:
named for what it does, documented at the level a reader needs to run and modify
it, no dead parameters or commented-out alternatives. Work that is not at that
standard belongs in `../scratch/` until it is.

Instance size is a parameter, not a constant. The published default must solve
in seconds — see the note's `CLAUDE.md`.

## Contents

<!-- One line per module: what it implements and which figures depend on it. -->

- `dispatch.py` — single-period economic dispatch as an explicit linopy LP
  (section 2); carbon tax via marginal cost, emissions cap as a constraint.
  Figures 2.1–2.3 and table 2.1 depend on it.
- `dispatch_t.py` — multi-period dispatch with availability profiles
  (section 3); periods stay independent. Also defines capacity factor,
  capture price and value factor. Figures 3.1–3.4 depend on it.
- `storage.py` — the section 3 instance plus a battery `StorageUnit`
  (section 4); first PyPSA model. Figures 4.1–4.3 and 8.4 depend on it.
- `heat.py` — power + heat buses, heat pump as a `Link` with hourly COP,
  gas boiler (section 5). Figures 5.1–5.3 depend on it.
- `network.py` — loads, aggregates and solves the 12-bidding-zone PyPSA-Eur
  network from `data/processed/`, computes congestion rents, swaps weather
  years (sections 6–9). The time aggregation lives here too: `aggregate()`
  reduces the year to `hours` snapshots either by chronological
  segmentation (tsam; the default) or by keeping every k-th hour, and the
  module comment records how the two were tested against full-year
  solves. Figures 6.1–6.4 depend on it.
- `greenfield.py` — capacity expansion on the network: Danish zones
  extendable, annuitised capital costs, CO2 budget with its dual as the
  carbon price (sections 7–8). Figures 7.1–7.4 and 8.1–8.3 depend on it.
