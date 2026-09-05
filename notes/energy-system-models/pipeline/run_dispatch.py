"""Solve the section 2 dispatch instances and write everything figures 2.1-2.3
and the technology table need into results/.

    python pipeline/run_dispatch.py                 the note's runs
    python pipeline/run_dispatch.py --co2-price 50  a different carbon price

Three experiments on one ten-generator instance (capacities below, load 5 GW):

    base       no carbon policy                     -> figure 2.1
    tax        carbon price of --co2-price EUR/t    -> figure 2.2
    cap sweep  emissions cap from just above the    -> figure 2.3
               feasibility floor up to unconstrained
               emissions; the dual of the cap is the
               endogenous carbon price at each level

The whole thing is ten generators and one period, so it solves in well under a
second — there is no size parameter and nothing to cache.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import dispatch

PROCESSED = NOTE / "data" / "processed"
RESULTS = NOTE / "results"

# The note's instance: capacity in MW per technology. For solar and wind this
# is the capacity *available in the period* — one period has no availability
# profile, so intermittency is deferred to section 3 and dispatch_t.py.
CAPACITY_MW = pd.Series(
    {
        "solar_pv": 500.0,
        "wind_onshore": 1500.0,
        "wind_offshore": 1000.0,
        "waste_chp": 350.0,
        "coal_chp": 1200.0,
        "wood_chips_chp": 700.0,
        "wood_pellets_chp": 250.0,
        "ccgt": 1500.0,
        "ocgt": 800.0,
        "oil_peak": 400.0,
    },
    name="capacity",
)

LOAD_MW = 5000.0


def run_base_and_tax(tech, co2_price):
    """The base dispatch and the same instance under a carbon tax, side by
    side in one per-generator table."""
    base = dispatch.solve(tech, CAPACITY_MW, LOAD_MW)
    tax = dispatch.solve(tech, CAPACITY_MW, LOAD_MW, co2_price=co2_price)

    generators = pd.DataFrame(
        {
            "label": tech.loc[CAPACITY_MW.index, "label"],
            "capacity_mw": CAPACITY_MW,
            "emission_rate_t_per_mwh": base["emission_rate"],
            "mc_base": base["marginal_cost"],
            "mc_tax": tax["marginal_cost"],
            "generation_base_mw": base["generation"],
            "generation_tax_mw": tax["generation"],
            "rent_base": base["rent"],
            "rent_tax": tax["rent"],
        }
    )
    summary = {
        "load_mw": LOAD_MW,
        "co2_price_eur_per_t": co2_price,
        "price_base_eur_per_mwh": base["price"],
        "price_tax_eur_per_mwh": tax["price"],
        "emissions_base_t": base["emissions"],
        "emissions_tax_t": tax["emissions"],
        "cost_base_eur": base["cost"],
        "cost_tax_eur": tax["cost"],
    }
    return generators, summary


def run_cap_sweep(tech, n_caps=200):
    """Re-solve under an emissions cap over a grid from the feasibility floor
    (cleanest way to serve the load at all) to unconstrained emissions. The
    dual of the cap traces the marginal abatement cost step function."""
    unconstrained = dispatch.solve(tech, CAPACITY_MW, LOAD_MW)["emissions"]

    # The floor: serve the load with as few tonnes as possible. That is itself
    # an LP — reuse the dispatch model with emission rates as the objective by
    # pricing carbon absurdly high, then read realised emissions.
    floor = dispatch.solve(tech, CAPACITY_MW, LOAD_MW, co2_price=1e6)["emissions"]

    rows = []
    for cap in np.linspace(floor * 1.001, unconstrained * 1.05, n_caps):
        sol = dispatch.solve(tech, CAPACITY_MW, LOAD_MW, co2_cap=cap)
        rows.append(
            {
                "cap_t": cap,
                "co2_shadow_price_eur_per_t": sol["co2_shadow_price"],
                "price_eur_per_mwh": sol["price"],
                "emissions_t": sol["emissions"],
                "cost_eur": sol["cost"],
            }
        )
    sweep = pd.DataFrame(rows)
    return sweep, {"emissions_floor_t": floor, "emissions_unconstrained_t": unconstrained}


def tech_table(tech):
    """The table printed in the note (table 2.1), with the derived marginal
    cost and emission rate columns, so build.py can typeset it from results/
    without touching data/ or model/."""
    out = tech.loc[CAPACITY_MW.index].copy()
    out["marginal_cost"] = dispatch.marginal_cost(tech).loc[CAPACITY_MW.index]
    out["emission_rate"] = dispatch.emission_rate(tech).loc[CAPACITY_MW.index]
    out["capacity_mw"] = CAPACITY_MW
    return out.reset_index()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--co2-price",
        type=float,
        default=85.0,
        help="carbon tax in EUR/tCO2 for the tax experiment (default 85)",
    )
    args = parser.parse_args()

    tech = dispatch.read_tech(PROCESSED / "technology_costs_small.csv")
    RESULTS.mkdir(parents=True, exist_ok=True)

    generators, summary = run_base_and_tax(tech, args.co2_price)
    sweep, sweep_meta = run_cap_sweep(tech)
    summary.update(sweep_meta)

    generators.to_csv(RESULTS / "dispatch_generators.csv", index_label="tech")
    sweep.to_csv(RESULTS / "dispatch_cap_sweep.csv", index=False)
    tech_table(tech).to_csv(RESULTS / "dispatch_tech_table.csv", index=False)
    (RESULTS / "dispatch_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(
        f"price {summary['price_base_eur_per_mwh']:.2f} -> "
        f"{summary['price_tax_eur_per_mwh']:.2f} EUR/MWh at "
        f"{args.co2_price:.0f} EUR/t; emissions "
        f"{summary['emissions_base_t']:.0f} -> {summary['emissions_tax_t']:.0f} t"
    )
    for name in [
        "dispatch_generators.csv",
        "dispatch_cap_sweep.csv",
        "dispatch_tech_table.csv",
        "dispatch_summary.json",
    ]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
