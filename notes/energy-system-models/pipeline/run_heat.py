"""Solve the section 5 heat coupling instances and write everything figures
5.1-5.3 need into results/.

    python pipeline/run_heat.py                fast default (one week)
    python pipeline/run_heat.py --hours 8784   the note's figures (full year)

The electricity side is the section 3 instance; the heat side is a stylised
DK1-scale district heating load (annual total set below) served by a gas
boiler and an air-sourced heat pump. Experiments:

    base      heat pump at 800 MW electric               -> figs 5.1, 5.2
    rollout   heat pump capacity swept from 0 to 2 GW    -> fig 5.3

Hours are contiguous from 1 January (the COP-load correlation is the point,
and it lives in the seasons).
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import dispatch, heat
from run_dispatch import PROCESSED
from run_dispatch_t import PROFILE_OF, YEAR, dk1_fleet, import_price

RESULTS = NOTE / "results"

HEAT_ANNUAL_TWH = 20.0     # DK1-scale district heating, stylised
HP_BASE_MW_EL = 800.0
ROLLOUT_GRID_MW = [0.0, 200.0, 400.0, 800.0, 1200.0, 1600.0, 2000.0]
# The rollout is swept twice: without a carbon price and at section 2's
# teaching tax (\DispatchTax), so the complementarity claim — that
# electrification pays off jointly with clean marginal power — is a shown
# result rather than an asserted one.
DISPATCH_TAX = 85.0

# Emission rates per MWh electric for the power fleet, and per MWh heat for
# the boiler, used to aggregate total emissions across both sectors.


def load_instance(hours):
    profiles = pd.read_csv(
        PROCESSED / f"profiles_dk1_{YEAR}.csv", index_col="time", parse_dates=True
    )
    temperature = pd.read_csv(
        PROCESSED / f"temperature_dk_{YEAR}.csv", index_col="time", parse_dates=True
    )["temperature_c"]
    sample = profiles.iloc[:hours]
    # The EDS profiles cover the Danish-local-time year, so their UTC index
    # starts an hour before the temperature series; align by nearest hour.
    temperature = temperature.reindex(sample.index, method="nearest")

    load = sample["load_mw"].rename("load")
    availability = pd.DataFrame(
        {tech: sample[col] for tech, col in PROFILE_OF.items()}
    )
    cop = heat.cop_series(temperature)
    # Scale the annual total by the sampled share of the year so short runs
    # keep the right heat-to-power proportions.
    heat_load = heat.heat_demand(
        temperature, HEAT_ANNUAL_TWH * len(sample) / len(profiles)
    )
    return load, availability, temperature, cop, heat_load


def emissions(n, tech, capacity):
    """Total CO2 across both sectors: power fleet plus gas boiler."""
    e_el = dispatch.emission_rate(tech)
    gen = n.generators_t.p
    power = sum(
        float(gen[g].sum()) * float(e_el[g])
        for g in capacity.index
        if g in gen.columns
    )
    boiler = float(gen["gas_boiler"].sum()) * (
        heat.GAS_CO2_T_PER_MWH_TH / heat.BOILER_EFFICIENCY
    )
    return power + boiler


def run_base(tech, capacity, load, availability, temperature, cop,
             heat_load, hourly_cost):
    n = heat.build_network(
        tech, capacity, load, availability, heat_load, cop,
        hp_power_mw_el=HP_BASE_MW_EL, hourly_cost=hourly_cost,
    )
    heat.solve(n)

    hourly = pd.DataFrame(
        {
            "temperature_c": temperature,
            "cop": cop,
            "heat_demand_mw": heat_load,
            "elec_price": n.buses_t.marginal_price["elec"],
            "heat_price": n.buses_t.marginal_price["heat"],
            "hp_heat_mw": -n.links_t.p1["heat_pump"],
            "hp_elec_mw": n.links_t.p0["heat_pump"],
            "boiler_mw": n.generators_t.p["gas_boiler"],
        }
    )
    return n, hourly


def run_rollout(tech, capacity, load, availability, cop, heat_load,
                hourly_cost, co2_price=0.0):
    rows = []
    for mw in ROLLOUT_GRID_MW:
        n = heat.build_network(
            tech, capacity, load, availability, heat_load, cop,
            hp_power_mw_el=mw, co2_price=co2_price,
            hourly_cost=hourly_cost,
        )
        heat.solve(n)
        price = n.buses_t.marginal_price["elec"]
        hp_heat = -n.links_t.p1["heat_pump"].sum() if mw > 0 else 0.0
        rows.append(
            {
                "tau_eur_t": co2_price,
                "hp_mw_el": mw,
                "avg_elec_price": float(price.mean()),
                "avg_heat_price": float(n.buses_t.marginal_price["heat"].mean()),
                "hp_heat_share": float(hp_heat / heat_load.sum()),
                "emissions_t": emissions(n, tech, capacity),
                "system_cost": float(n.objective),
            }
        )
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=168,
        help="contiguous hours from 1 January (default 168; the note's "
        "figures use the full year, 8784)",
    )
    args = parser.parse_args()

    tech = dispatch.read_tech(PROCESSED / "technology_costs_small.csv")
    load, availability, temperature, cop, heat_load = load_instance(args.hours)
    capacity, tech = dk1_fleet(tech)
    hourly_cost = import_price(load.index)
    RESULTS.mkdir(parents=True, exist_ok=True)

    n, hourly = run_base(tech, capacity, load, availability, temperature,
                         cop, heat_load, hourly_cost)
    rollout = pd.concat(
        [
            run_rollout(tech, capacity, load, availability, cop, heat_load,
                        hourly_cost),
            run_rollout(tech, capacity, load, availability, cop, heat_load,
                        hourly_cost, co2_price=DISPATCH_TAX),
        ],
        ignore_index=True,
    )

    summary = {
        "hours": len(load),
        "heat_annual_twh": HEAT_ANNUAL_TWH,
        "hp_base_mw_el": HP_BASE_MW_EL,
        "rollout_tax_eur_t": DISPATCH_TAX,
        "sink_temperature_c": heat.SINK_TEMPERATURE_C,
        "cop_mean": float(cop.mean()),
        "cop_min": float(cop.min()),
        "cop_max": float(cop.max()),
        "hp_heat_share_base": float(
            (-n.links_t.p1["heat_pump"].sum()) / heat_load.sum()
        ),
        "emissions_base_t": emissions(n, tech, capacity),
    }

    hourly.to_csv(RESULTS / "heat_hours.csv", index_label="time")
    rollout.to_csv(RESULTS / "heat_rollout.csv", index=False)
    (RESULTS / "heat_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(
        f"{len(load)} hours: COP {summary['cop_min']:.1f}-{summary['cop_max']:.1f} "
        f"(mean {summary['cop_mean']:.1f}); HP serves "
        f"{100 * summary['hp_heat_share_base']:.0f}% of heat at "
        f"{HP_BASE_MW_EL:.0f} MW_el"
    )
    for name in ["heat_hours.csv", "heat_rollout.csv", "heat_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
