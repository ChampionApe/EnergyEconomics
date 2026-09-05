# Data

    raw/         as downloaded. NEVER PUBLISHED.
    processed/   derived by prepare.py. Published, so students can reproduce.
    prepare.py   raw/ -> processed/

`raw/` is in the manifest's `forbidden_sources`: no rule can publish out of it.
Treat it as read-only — never edit a file in place, or the pipeline stops being
reproducible from the original download.

`prepare.py` must be deterministic and re-runnable. It never reads `results/`.

## Provenance

<!-- One entry per dataset: source, URL, date retrieved, licence, and whether
     the processed form may be published. Settle the licence question before
     building a figure on a dataset — if the processed data cannot be shared,
     students cannot reproduce the figure and the note needs a different
     example. -->

| Dataset | Source | Retrieved | Licence | Processed form publishable? |
|---|---|---|---|---|
| `processed/technology_costs_small.csv` | **Generated** by `prepare.py` from `PyPSA/technology-data` at pinned tag `v0.13.2`, vintage 2025, plus the fuel prices and carbon contents in `fuel_assumptions.csv` | generated 2026-08-28 | derived | Yes — printed in the note as table 2.1 |
| `processed/fuel_assumptions.csv` | **Generated** by `prepare.py`: fuel prices and carbon contents, carrying both technology-data's published value and the note's own. Read by every tier of the note's data | generated 2026-08-28 | derived | Yes |
| `processed/battery_assumptions.csv` | **Generated** by `prepare.py`: battery investment costs per vintage, technology-data's published value beside the note's. The note caps every vintage's 4-hour turnkey system cost at 165 €/kWh — BNEF's 2025 European average (177 $/kWh, *Energy Storage System Cost Survey 2025*, Dec 2025, press-release figures; ~1.07 USD/EUR), keeping technology-data's inverter/cells split; binds for the 2025 and 2030 vintages only. Shared verbatim with the technologies note | generated 2026-08-29 | derived (BNEF figure from press release) | Yes |
| `processed/offshore_assumptions.csv` | **Generated** by `prepare.py`: offshore wind investment cost per vintage, technology-data's published `offwind` beside the note's. technology-data subtracts the installation half of grid connection from the Danish Energy Agency catalogue total because PyPSA-Eur adds distance-specific cabling back per farm; this note adds no cabling, so the DEA total is restored (+7.8%). Sheet '21 Offshore turbines' of the DEA technology catalogue at the pinned tag. Shared verbatim with the technologies note | generated 2026-09-01 | derived | Yes |
| `processed/offshore_cost_premium.csv` | **Generated** by `prepare.py`: a per-zone multiplier on offshore capital cost, since the DEA number is Danish and Denmark is the cheapest offshore in Europe. `premium(z) = LCOE(country)/LCOE(DK) x CF(z)/CF(DK)`, from IRENA's 2024 country costs; the capacity-factor term prevents double-counting the resource, which each zone's profile already carries. Zones with no published country figure take the European average — the weakest number in the file, and it prices SE4 | generated 2026-09-01 | derived | Yes |
| `processed/cost_scenarios.csv` + `technology_costs_full_2050_{pessimistic,optimistic}.csv` | **Generated** by `prepare.py`: section 8's cost axis. Per technology, the 2025→2050 trend in the *used* investment cost, and the two tables built from it by adding and subtracting half of that trend (clipped at zero). Constructed scenarios at a fixed 2050 horizon, not a sweep over published vintages, and not a distribution — the half is a choice | generated 2026-09-01 | derived | Yes |
| `processed/profiles_{dk1,dk2}_{2019..2024}.{csv,json}` | Energi Data Service, dataset `ProductionConsumptionSettlement`, DK1 and DK2, calendar years 2019–2024 (hourly gross consumption; onshore/offshore wind and solar production summed over size classes, normalised by annual maximum) | 2026-08-26 | CC-BY 4.0, no key | Yes — with attribution; students can also re-run `prepare.py` |
| `processed/temperature_dk_2024.csv` | Open-Meteo historical archive (ERA5-derived), hourly 2 m temperature, Aarhus | 2026-08-26 | CC-BY 4.0, no key | Yes — with attribution |
| `processed/weather_zones_{2015..2024}.csv` + `weather_zones.json` | Open-Meteo historical archive (ERA5-derived), hourly 100 m wind speed and surface shortwave radiation at each of the 12 bidding zones' bus coordinates, 2015-2024. Converted to per-unit availability by a stylised power curve (3/12/25 m/s) and a 1000 W/m2 reference; only the shape is used, since `model/network.py` rescales each series to preserve the network's own capacity factor. The basis of section 8's weather sweep | 2026-08-27 | CC-BY 4.0, no key | Yes - with attribution |
| `processed/spot_2024.csv` | Energi Data Service, dataset `Elspotprices`: actual hourly day-ahead prices (EUR) for DK1, DK2, DE, NO2, SE3, SE4 — the model-vs-market comparisons of §3 and §6 | 2026-08-26 | CC-BY 4.0, no key | Yes — with attribution |
| `processed/exchange_{dk1,dk2}_2024.csv` | Energi Data Service, `ProductionConsumptionSettlement` exchange columns: hourly cross-border flows of the Danish zones (positive = import) — realised congestion rents in §6 | 2026-08-28 | CC-BY 4.0, no key | Yes — with attribution |
| `processed/technology_costs_full_2030.csv` | `PyPSA/technology-data`, compiled `outputs/costs_2030.csv` **fetched at pinned tag `v0.13.2`**, subset reshaped | 2026-08-26 | outputs carry no single stated licence | **No** — `technology_costs_full_*.csv` is in the manifest's `forbidden_names`; students obtain it by running `prepare.py` (pinned fetch, byte-identical) |
| `processed/transmission_costs.csv` | **Generated** by `prepare.py` from `PyPSA/technology-data` at the pinned tag: the investment cost, lifetime and fixed O&M of overhead AC, overhead and submarine DC, and the DC converter station pair — the numbers section 6's introduction to transmission grids quotes | generated 2026-09-04 | derived | Yes |
| `processed/transmission_ntc_reference.csv` | **Generated** by `prepare.py` from the TYNDP 2024 'Electricity and Hydrogen Reference Grid & Investment Candidates' workbook, sheet '1. Elec Ref Grid': reference-grid transfer capacities between the twelve zones, both directions. Section 6 derates the network's internal Nordic corridors (thermal ratings) to the larger direction; never uprates | 2026-09-04 | CC-BY 4.0 | Yes |
| `processed/hydro_calibration.csv` | **Generated** by `prepare.py`: the network's Norwegian hydro energy (reservoir inflow, run-of-river) beside Statistics Norway's 2024 hydro production (139,984 GWh) and net export (18,439 GWh) and NVE's normal annual production (137.6 TWh, reference 1991–2020, energifaktanorge.no). `model/network.py` scales every section's reservoir inflow to the normal level on load; section 6 scales further so the solved output equals the 2024 production | 2026-09-04 | SSB: open (CC-BY 4.0) | Yes |
| `processed/bidding_zones.json` | **Generated** by `prepare.py` from **Natural Earth** 50m admin-0 countries and 10m admin-1 subdivisions (`naciscdn.org/naturalearth`), assembled into Europe's bidding zones (Norway, Sweden, Denmark and Italy from counties/regions; Germany+Luxembourg and the island of Ireland merged) and projected to ETRS89-LCC (EPSG:3034), simplified to 2.5 km; plus the network's zone coordinates in the same projection. The county-to-zone mapping is approximate — a classroom map, not a legal one. Needs `geopandas` to regenerate | 2026-09-04 | Natural Earth: public domain | Yes |
| `processed/network_eur_bz_2024.nc` + `network_zones.json` + `network_eur_bz_2024_fleet.csv` | **PyPSA-Eur v2026.08.0**, electricity-only, countries DK/DE/SE/NO, clustered to the 12 actual bidding zones, 2024 weather/demand year; trimmed and renamed by `scratch/pypsa-eur/export_network.py` (procedure in `scratch/pypsa-eur/README.md`, summarised in the note's Appendix C). Not produced by `prepare.py` — vendored directly | run 2026-08-28 | PyPSA-Eur: code MIT, data CC-BY-4.0/CC0 (REUSE) | Yes — with attribution |

### The forward-looking tables (sections 7–9)

All **generated** by `prepare.py`, all from the ENTSO-E/ENTSOG **TYNDP 2024
Scenarios** workbooks (CC-BY 4.0) unless a row says otherwise, and every one
carries its source sheet and every allocation that is ours rather than the
source's in a comment header at the top of the file. Where a TYNDP node covers
several of our zones the split is recorded in the file. Publishable: yes, all.

| Dataset | What it is | From |
|---|---|---|
| `processed/fuel_assumptions_2050.csv` | fuel prices at the 2050 horizon beside today's; carbon contents unchanged | Supply Inputs, sheet 3.1 (IEA WEO 2022 APS underneath) |
| `processed/demand_zones_2050.csv` | annual electricity demand per zone at 2050 (market plus prosumer), averaged over the three climate years the workbooks carry; only the total is used | Demand Profiles, Distributed Energy 2050 |
| `processed/ev_assumptions.csv` | annual EV electricity per zone at 2050, added to the load, never carved out | EV Modelling Inputs |
| `processed/h2_assumptions.csv` | annual industrial hydrogen demand per zone (heating excluded) | Demand Profiles, H2 zone 2, Distributed Energy 2050 |
| `processed/h2_imports.csv` | hydrogen import supply steps (Germany only in this scenario) | Hydrogen inputs, import generators |
| `processed/h2_storage_potential.csv` | underground hydrogen storage ceiling per zone; country totals sourced, the split to zones is ours | Hydrogen inputs, H2 storages |
| `processed/potentials_zones.csv` | buildable potential per zone and technology: the smaller of TYNDP's high trajectory and the network's land-availability potential | Supply Inputs, sheets 1.1–1.3, and the shipped network's `p_nom_max` |
| `processed/biomethane_potential.csv` | one system-wide biomethane ceiling; the EU total's allocation to these zones is ours | Supply Inputs, sheet 3.5 (Guidehouse underneath) |
| `processed/transmission_candidates.csv` | transmission increments the section 8 model may buy, at TYNDP's capex, with committed projects as fixed capacity | Reference Grid & Investment Candidates, sheet 3 |

## One set of plant characteristics, everywhere

The note's data comes in three tiers, and until August 2026 they disagreed:

| Tier | Used by | What went wrong |
|---|---|---|
| the small table | §§2–5 | hand-authored, and drifted |
| the shipped PyPSA-Eur network | §§6–8 | carried the workflow's own fuel prices |
| technology-data | §7–§8 candidates | gas price hard-coded to match the small table |

A combined-cycle plant cost 64 €/MWh to run in §2 and 44 €/MWh in §6, and
nothing in the pipeline noticed. That is now fixed, in three places:

1. **`fuel_assumptions.csv` is the single source of fuel prices and carbon
   contents.** Generated by `prepare.py`, it carries technology-data's own
   published value alongside the note's assumption, so every override is
   visible rather than buried. **This block is shared verbatim with the
   technologies note** — duplicated rather than imported, because the two
   notes publish independently and neither may depend on the other's
   directories. What they share is a source and a set of assumptions, not a
   file. If you change it here, change it there.
2. **`technology_costs_small.csv` is generated, not hand-authored.** Every
   parameter is read from technology-data at the pinned tag, vintage 2025 —
   the same vintage the technologies note's catalogue reports — so a machine
   named in table 2.1 is the *same machine, with the same numbers*, as the one
   named in the technologies note. Never edit it by hand.
3. **The shipped network is re-priced on load** (`model/network.py`,
   `reprice()`). Each thermal generator keeps its own PyPSA-Eur efficiency —
   that heterogeneity is real and worth having — and gets the note's fuel
   price and variable operating cost. Carrier emission factors are refreshed
   at the same time, which also repairs a PyPSA-Eur default that had assigned
   municipal waste the emission factor of fuel oil.

Sections 7–9 read the **2050** vintage for investment costs, because they
ask what it costs to build for 2050 and every other forward input they read
— fuel prices, demand, potentials, hydrogen and EV demand — is at that same
horizon. `run_greenfield.costs_check()` writes `results/costs_check.csv`
comparing the 2025 vintage the small table of §§2–5 uses against the one
§7 prices investment on; the residual difference is under 2% on efficiency.

§8's cost axis does **not** sweep the vintages. It holds the horizon at 2050
and varies the projection instead: `cost_scenarios.csv` records, per
technology, the 2025→2050 trend and the pessimistic and optimistic tables
built from it (half the trend in each direction, clipped at zero). The
scenario tables are `technology_costs_full_2050_{pessimistic,optimistic}.csv`.

**What is an assumption:** the fuel prices, the carbon content of waste, and
the battery investment costs. Prices are stylised 2025 forward levels rather
than technology-data's own, which are inherited from a 2013 study and sit
well below what European plants have paid recently. Waste is counted at
0.15 tCO2/MWh_th — its fossil (plastics) fraction — rather than as
carbon-free. Battery costs are capped at BNEF's 2025 European turnkey level
because technology-data's trajectory has fallen behind the world market (its
2040 vintage costs roughly what systems sold for in 2025). All are flagged:
the first two in `fuel_assumptions.csv`'s `*_is_assumption` columns, the
battery cap in `battery_assumptions.csv`'s `is_override` column, and the
offshore capital cost in `offshore_assumptions.csv`, which records
technology-data's published `offwind` beside the Danish Energy Agency total
the note restores to it. The scale of the scenarios in `cost_scenarios.csv`
is an assumption too, and the most visible one: half the projected trend is
a choice, not an estimate.
