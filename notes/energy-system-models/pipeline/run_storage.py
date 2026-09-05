"""Solve the section 4 storage instances and write everything figures 4.1-4.4
(and section 9's foresight comparison) need into results/.

    python pipeline/run_storage.py                fast default (one week)
    python pipeline/run_storage.py --hours 8784   the note's figures (full year)

Storage couples the hours, so unlike run_dispatch_t.py the horizon is a
*contiguous* block starting 1 January — sampling every k-th hour would tear
the state-of-charge dynamics apart. Experiments:

    base        the section 3 DK1 fleet + a 1 GW / 4 h battery -> figs 4.1, 4.2
    no-storage  the same horizon without the battery         -> fig 4.2
    ramp        a ramp rate on DK1's slow thermal plant, tightened
                from none to 0.1 per hour, with and without
                the battery                                  -> fig 4.3
    recovery    wind scaled up (deep cannibalisation) with
                the battery swept from 0 to 8 GW             -> fig 4.4
    foresight   perfect foresight vs day-by-day myopic
                operation of the base battery                -> fig 9.6
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import dispatch, dispatch_t, storage
from run_dispatch import PROCESSED
from run_dispatch_t import IMPORTS, PROFILE_OF, YEAR, dk1_fleet, import_price

RESULTS = NOTE / "results"

BATTERY_MW = 1000.0
BATTERY_HOURS = 4.0
WIND_SCALE_RECOVERY = 1.5
RECOVERY_GRID_MW = [0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]

# The ramp sweep tightens one rate on DK1's slow thermal plant — the coal,
# wood and waste CHP boilers — and leaves the gas turbine and the import
# backstop free: a combined-cycle plant traverses its range within an hour,
# and the wires are the neighbours' problem. 1.0 is no limit; 0.9 is the
# rate the network sections give coal and biomass (PyPSA-Eur's value); the
# rest are stylised, to show what the wedge of section 4.3 does when it
# bites.
RAMP_TECHS = ["coal_chp", "wood_chips_chp", "wood_pellets_chp", "waste_chp"]
RAMP_GRID = [1.0, 0.9, 0.6, 0.3, 0.2, 0.1]
RAMP_CATALOGUE = 0.9


def load_instance(hours):
    profiles = pd.read_csv(
        PROCESSED / f"profiles_dk1_{YEAR}.csv", index_col="time", parse_dates=True
    )
    sample = profiles.iloc[:hours]
    load = sample["load_mw"].rename("load")
    availability = pd.DataFrame(
        {tech: sample[col] for tech, col in PROFILE_OF.items()}
    )
    return load, availability


def hourly_frame(n):
    """Everything figure 4.1 needs, hour by hour."""
    out = pd.DataFrame(
        {
            "price": n.buses_t.marginal_price["elec"],
            "soc_mwh": n.storage_units_t.state_of_charge["battery"],
            "storage_p_mw": n.storage_units_t.p["battery"],
        }
    )
    return out


def run_base(tech, capacity, load, availability, hourly_cost):
    with_storage = storage.build_network(
        tech, capacity, load, availability, storage_power_mw=BATTERY_MW,
        storage_hours=BATTERY_HOURS, hourly_cost=hourly_cost,
    )
    storage.solve(with_storage)
    without = storage.build_network(
        tech, capacity, load, availability, storage_power_mw=0.0,
        hourly_cost=hourly_cost,
    )
    storage.solve(without)

    prices = pd.DataFrame(
        {
            "with_storage": with_storage.buses_t.marginal_price["elec"],
            "without_storage": without.buses_t.marginal_price["elec"],
        }
    )
    # What the same battery costs to own per year, from section 7's cost
    # data (technology-data 2030: inverter plus cells, each annuitised) —
    # the yardstick the note's zero-profit result says the arbitrage
    # revenue should be measured against.
    from model import greenfield
    costs_full = pd.read_csv(
        PROCESSED / "technology_costs_full_2030.csv", index_col="technology"
    )
    annual_cost = greenfield.battery_capital_cost(
        costs_full, hours=BATTERY_HOURS
    ) * BATTERY_MW

    summary = {
        "battery_mw": BATTERY_MW,
        "battery_hours": BATTERY_HOURS,
        "efficiency_one_way": storage.EFFICIENCY_ONE_WAY,
        "battery_annual_cost_eur": annual_cost,
        "avg_price_with": float(prices["with_storage"].mean()),
        "avg_price_without": float(prices["without_storage"].mean()),
        "price_std_with": float(prices["with_storage"].std()),
        "price_std_without": float(prices["without_storage"].std()),
        "storage_revenue": storage.storage_revenue(with_storage),
        "system_cost_with": float(with_storage.objective),
        "system_cost_without": float(without.objective),
    }
    return hourly_frame(with_storage), prices, summary


def run_ramp_sweep(tech, capacity, load, availability, hourly_cost):
    """Section 4.3's wedge in numbers: the same year solved with and without
    the battery at each ramp rate in RAMP_GRID.

    Per rate: the system cost and price volatility with and without the
    battery, the battery's arbitrage revenue and system value, and the
    summed shadow value of the ramp constraints (storage.flexibility_cost).
    The cost of the rigidity itself is read off against the first row."""
    rows = []
    for rho in RAMP_GRID:
        ramp = None if rho >= 1.0 else {g: rho for g in RAMP_TECHS}
        row = {"rho": rho}
        for label, mw in (("with", BATTERY_MW), ("without", 0.0)):
            n = storage.build_network(
                tech, capacity, load, availability, storage_power_mw=mw,
                storage_hours=BATTERY_HOURS, hourly_cost=hourly_cost,
                ramp_rate=ramp,
            )
            storage.solve(n)
            price = n.buses_t.marginal_price["elec"]
            row[f"system_cost_{label}"] = float(n.objective)
            row[f"price_std_{label}"] = float(price.std())
            row[f"flexibility_cost_{label}"] = storage.flexibility_cost(n)
            if mw > 0:
                row["storage_revenue"] = storage.storage_revenue(n)
        row["battery_value"] = row["system_cost_without"] - row["system_cost_with"]
        rows.append(row)
    return pd.DataFrame(rows)


def run_recovery(tech, capacity_base, load, availability, hourly_cost):
    """Wind above its actual capacity — deep into cannibalisation — while
    the battery grows: how much of wind's market value does storage restore?

    The multiple is modest because the starting point is not: DK1 already has
    5.1 GW of wind, so 1.5x is 7.6 GW on a mean load of 2.7 GW."""
    capacity = capacity_base.copy()
    capacity[["wind_onshore", "wind_offshore"]] *= WIND_SCALE_RECOVERY
    wind = ["wind_onshore", "wind_offshore"]

    rows = []
    for mw in RECOVERY_GRID_MW:
        n = storage.build_network(
            tech, capacity, load, availability, storage_power_mw=mw,
            storage_hours=BATTERY_HOURS, hourly_cost=hourly_cost,
        )
        storage.solve(n)
        price = n.buses_t.marginal_price["elec"]
        gen = n.generators_t.p[wind]
        capture = float((gen.sum(axis=1) * price).sum() / gen.sum().sum())
        rows.append(
            {
                "storage_mw": mw,
                "wind_capture_price": capture,
                "avg_price": float(price.mean()),
                # Same base price as section 3's value factors: the
                # consumption-weighted average, not the time-average.
                "base_price": dispatch_t.base_price(price, load),
                "wind_value_factor": capture / dispatch_t.base_price(price, load),
                "wind_curtailed_share": 1.0
                - float(gen.sum().sum())
                / float(
                    (n.generators_t.p_max_pu[wind] * capacity[wind]).sum().sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def run_foresight(tech, capacity, load, availability, hourly_cost):
    """Perfect foresight versus myopia, for section 9.

    The same battery, the same year, two operators: one solves the whole
    horizon at once; the other sees one day at a time, carrying the state of
    charge from each midnight into the next day and expecting nothing of the
    future. The gap in system cost prices the value of foresight for a
    battery whose natural cycle is daily.
    """
    pf = storage.build_network(
        tech, capacity, load, availability, storage_power_mw=BATTERY_MW,
        storage_hours=BATTERY_HOURS, hourly_cost=hourly_cost,
    )
    storage.solve(pf)

    myopic = storage.build_network(
        tech, capacity, load, availability, storage_power_mw=BATTERY_MW,
        storage_hours=BATTERY_HOURS, cyclic=False, hourly_cost=hourly_cost,
    )
    soc = 0.0
    cost = 0.0
    days = [load.index[i : i + 24] for i in range(0, len(load), 24)]
    for window in days:
        myopic.storage_units.loc["battery", "state_of_charge_initial"] = soc
        myopic.optimize(
            snapshots=window, solver_name="highs", progress=False,
            solver_options={"output_flag": False},
        )
        soc = float(myopic.storage_units_t.state_of_charge.loc[window[-1], "battery"])
        # get_switchable_as_dense, not the static column: with the import
        # backstop priced by the hour, `generators.marginal_cost` is zero
        # for imports and the myopic bill would silently omit them.
        mc_t = myopic.get_switchable_as_dense(
            "Generator", "marginal_cost"
        ).loc[window]
        cost += float((myopic.generators_t.p.loc[window] * mc_t).sum().sum())

    pf_cost = float(pf.objective)
    return {
        "system_cost_perfect_foresight": pf_cost,
        "system_cost_myopic": cost,
        "value_of_foresight": cost - pf_cost,
        "windows": len(days),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=168,
        help="contiguous hours from 1 January (default 168; the note's "
        "figures use the full year, 8784)",
    )
    args = parser.parse_args()

    tech = dispatch.read_tech(PROCESSED / "technology_costs_small.csv")
    load, availability = load_instance(args.hours)
    capacity, tech = dk1_fleet(tech)
    hourly_cost = import_price(load.index)
    RESULTS.mkdir(parents=True, exist_ok=True)

    hourly, prices, summary = run_base(tech, capacity, load, availability,
                                       hourly_cost)
    ramp = run_ramp_sweep(tech, capacity, load, availability, hourly_cost)
    recovery = run_recovery(tech, capacity, load, availability, hourly_cost)
    foresight = run_foresight(tech, capacity, load, availability,
                              hourly_cost)
    summary["hours"] = len(load)
    summary["wind_scale_recovery"] = WIND_SCALE_RECOVERY
    summary["foresight"] = foresight
    summary["ramp"] = {
        "techs": RAMP_TECHS,
        "slow_thermal_mw": float(capacity[RAMP_TECHS].sum()),
        "import_mw": float(capacity[IMPORTS]),
        "catalogue_rho": RAMP_CATALOGUE,
    }

    hourly.to_csv(RESULTS / "storage_hours.csv", index_label="time")
    prices.to_csv(RESULTS / "storage_prices.csv", index_label="time")
    ramp.to_csv(RESULTS / "storage_ramp_sweep.csv", index=False)
    recovery.to_csv(RESULTS / "storage_recovery.csv", index=False)
    (RESULTS / "storage_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(
        f"{len(load)} hours: avg price {summary['avg_price_without']:.1f} -> "
        f"{summary['avg_price_with']:.1f} EUR/MWh with {BATTERY_MW:.0f} MW battery; "
        f"foresight worth {foresight['value_of_foresight']:.0f} EUR"
    )
    for name in ["storage_hours.csv", "storage_prices.csv",
                 "storage_ramp_sweep.csv", "storage_recovery.csv",
                 "storage_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
