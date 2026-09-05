"""Stage 2 for section 1: evaluate the simple model and write results/.

    python pipeline/run_simple.py
    python pipeline/run_simple.py --points 2001   a finer grid

Nothing is solved except the optimum, which is one scalar root. The grids are
the note's own: fossil energy from zero to the point where consumption is back
to zero, and the same grid read as abatement.

Writes:

    results/simple_baseline.csv   E, C(E), M(E)          -> figure 1.1
    results/simple_mac.csv        A, MAC, D'(M)          -> figures 1.2, 1.3
    results/simple_summary.json   parameters, baseline, optimum
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model.economy import Economy

RESULTS = NOTE / "results"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=1001,
                        help="grid points on the energy axis (default 1001)")
    args = parser.parse_args()

    economy = Economy()
    baseline_energy = economy.baseline_energy()
    baseline_emissions = economy.baseline_emissions()

    # The grid runs to the point where consumption returns to zero, which for
    # an isoelastic F is (gamma/p_e)^(1/(1-alpha)) -- four times the baseline
    # at the note's parameters. That endpoint is what makes figure 1.1 close.
    zero_consumption_energy = (economy.productivity / economy.energy_price) \
        ** (1.0 / (1.0 - economy.output_elasticity))
    energy = np.linspace(0.0, zero_consumption_energy, args.points)

    baseline = pd.DataFrame({
        "energy": energy,
        "consumption": economy.consumption(energy),
        "emissions": economy.emissions(energy),
    })

    # The marginal abatement cost is unbounded at E = 0, so the grid for it
    # starts one step in. The curve still leaves the top of the frame -- at
    # the first point it is already an order of magnitude above the axis
    # limit -- so the figure is unchanged and no infinity has to be plotted.
    positive = energy[1:]
    mac = pd.DataFrame({
        "energy": positive,
        "abatement": economy.abatement(positive),
        "marginal_abatement_cost": economy.marginal_abatement_cost(positive),
        "marginal_damages": economy.marginal_damages(
            economy.emissions(positive)),
    })

    optimum = economy.optimum()
    summary = {
        "parameters": {
            "output_elasticity": economy.output_elasticity,
            "productivity": economy.productivity,
            "energy_price": economy.energy_price,
            "emission_intensity": economy.emission_intensity,
            "damage_curvature": economy.damage_curvature,
        },
        "baseline": {
            "energy": baseline_energy,
            "consumption": economy.baseline_consumption(),
            "emissions": baseline_emissions,
        },
        "optimum": optimum,
        "abatement_rate_at_optimum": optimum["abatement"] / baseline_emissions,
        "marginal_damages_at_baseline":
            economy.marginal_damages(baseline_emissions),
        # build.py sets its axes from these rather than from literals, so the
        # figures follow the parameters if the parameters ever change.
        "energy_grid_max": float(energy[-1]),
        "abatement_grid_min": float(mac["abatement"].min()),
    }

    RESULTS.mkdir(exist_ok=True)
    baseline.to_csv(RESULTS / "simple_baseline.csv", index=False)
    mac.to_csv(RESULTS / "simple_mac.csv", index=False)
    (RESULTS / "simple_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"baseline: E0 = {baseline_energy:.4f}, "
          f"C0 = {economy.baseline_consumption():.4f}, "
          f"M0 = {baseline_emissions:.4f}")
    print(f"optimum:  E* = {optimum['energy']:.4f}, "
          f"M* = {optimum['emissions']:.4f}, "
          f"A* = {optimum['abatement']:.4f}, "
          f"tau* = {optimum['carbon_price']:.4f}")
    print("wrote results/simple_baseline.csv, simple_mac.csv, "
          "simple_summary.json")


if __name__ == "__main__":
    main()
