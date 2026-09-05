"""Stage 2 for section 2: the model with technical abatement.

    python pipeline/run_technical.py
    python pipeline/run_technical.py --max-carbon-price 20

The sweep variable is the marginal damage $D'(M)$ — the carbon price every
technology responds to. Fixing it turns section 2's system of equations into
a sequence of explicit evaluations, so nothing here is solved either, apart
from the one fixed point that closes the model at the end.

Writes:

    results/technical_menu.csv           theta_i, c_i, sigma_i per technology
    results/technical_marginal_cost.csv  the marginal cost of emissions -> fig 2.1
    results/technical_mac.csv            the abatement cost curve       -> fig 2.2
    results/technical_summary.json       the menu, and the optimum with technology
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model.economy import Economy
from model.technologies import NOTE_MENU, abatement_with_technology

RESULTS = NOTE / "results"


def optimum_with_technology(economy, menu, upper_carbon_price):
    """The carbon price at which marginal damage equals its own consequence.

    Along the sweep the carbon price and the emissions it produces move in
    opposite directions, so `price - D'(M(price))` crosses zero exactly once
    between a zero price (where emissions are at the baseline, and marginal
    damage is positive) and a high one. Brent's method on that difference is
    the whole calculation.
    """
    def excess(price):
        path = abatement_with_technology(economy, menu, np.array([price]))
        return price - economy.marginal_damages(path["emissions"][0])

    price = optimize.brentq(excess, 0.0, upper_carbon_price)
    path = abatement_with_technology(economy, menu, np.array([price]))
    return {
        "carbon_price": price,
        "energy": float(path["energy"][0]),
        "emissions": float(path["emissions"][0]),
        "abatement": float(path["abatement"][0]),
        "abated_share": float(path["abated_share"][0]),
        "cost_share": float(path["cost_share"][0]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=1001,
                        help="grid points on the carbon-price axis")
    parser.add_argument("--max-carbon-price", type=float, default=10.0,
                        help="top of the carbon-price grid; the default is "
                             "twice the most expensive technology's average "
                             "cost, so every technology is fully deployed")
    args = parser.parse_args()

    economy, menu = Economy(), NOTE_MENU
    marginal_damages = np.linspace(0.0, args.max_carbon_price, args.points)
    path = abatement_with_technology(economy, menu, marginal_damages)

    technologies = pd.DataFrame([
        {"technology": t.name, "potential": t.potential,
         "average_cost": t.average_cost, "cost_dispersion": t.cost_dispersion}
        for t in menu])

    # Figure 2.1 compares the marginal cost of emitting with and without the
    # menu. Without it, the cost of emitting a tonne is the damage it does;
    # the two columns beside it are the decomposition of the "with" line into
    # damages borne on unabated emissions and the cost of the abatement.
    marginal_cost = pd.DataFrame({
        "marginal_damages": marginal_damages,
        "abated_share": path["abated_share"],
        "cost_share": path["cost_share"],
        "without_abatement": marginal_damages,
        "with_abatement": path["marginal_cost_of_emissions"],
    })

    mac = pd.DataFrame({
        "abatement": path["abatement"],
        "marginal_abatement_cost": path["marginal_abatement_cost"],
        "energy": path["energy"],
        "emissions": path["emissions"],
    })

    optimum = optimum_with_technology(economy, menu, args.max_carbon_price)
    summary = {
        "total_potential": menu.total_potential,
        "technologies": {t.name: {"potential": t.potential,
                                  "average_cost": t.average_cost,
                                  "cost_dispersion": t.cost_dispersion}
                         for t in menu},
        "optimum": optimum,
        "carbon_price_grid_max": float(args.max_carbon_price),
        # Where figure 2.2's horizontal axis has to stop: past this point the
        # menu is exhausted and the two curves both go vertical.
        "max_abatement": float(mac["abatement"].max()),
    }

    RESULTS.mkdir(exist_ok=True)
    technologies.to_csv(RESULTS / "technical_menu.csv", index=False)
    marginal_cost.to_csv(RESULTS / "technical_marginal_cost.csv", index=False)
    mac.to_csv(RESULTS / "technical_mac.csv", index=False)
    (RESULTS / "technical_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"menu potential: {menu.total_potential:.2f} of emissions")
    print(f"optimum:  tau* = {optimum['carbon_price']:.4f}, "
          f"M* = {optimum['emissions']:.4f}, "
          f"A* = {optimum['abatement']:.4f}, "
          f"technically abated share = {optimum['abated_share']:.3f}")
    print("wrote results/technical_menu.csv, technical_marginal_cost.csv, "
          "technical_mac.csv, technical_summary.json")


if __name__ == "__main__":
    main()
