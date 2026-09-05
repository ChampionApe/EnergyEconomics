"""Re-solve the section 7 greenfield across cost scenarios — the second half
of section 9's uncertainty question — and write what figure 9.4 needs into
results/.

    python pipeline/run_costs.py                 fast default (336 segments)
    python pipeline/run_costs.py --hours 1095    the note's figures

The weather sweep (run_weather.py) asks how much of a capacity expansion
answer is a statement about the weather. This asks how much of it is a
statement about *what the machines will cost*: the same network, the same
weather, the same demand and the same CO2 budget in tonnes, re-solved on a
pessimistic and an optimistic reading of the cost projection the reference
case uses.

This used to sweep technology-data's published vintages, 2025 to 2050, and
that asked the wrong question. A vintage is a projection of what a machine
costs in a *stated year*; sweeping them asks "what if it were 2035?" when
section 7 has already fixed the horizon at 2050. What section 9 wants to know
is what happens if 2050 turns out dearer or cheaper than projected, so the
horizon is held and the projection is varied instead:

    trend       = investment(2025) - investment(2050)
    pessimistic = investment(2050) + 0.5 * trend
    optimistic  = investment(2050) - 0.5 * trend

per technology, uniformly, built in data/prepare.py and recorded in
data/processed/cost_scenarios.csv. The pessimistic world realises only half
of the projected decline; the optimistic one overshoots it by half again.

An important caveat, which the note states rather than buries: these are two
constructed scenarios, not draws from a distribution. The spread between them
is a fair picture of how much the answer moves across plausible cost worlds;
it is not a confidence interval, and the two axes of section 9 should not be
read as if they were the same kind of object.

Solves are cached in results/cache/ under a tag that names the scenario, so
this does not collide with the weather sweep's cache.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import greenfield, network
from run_dispatch import PROCESSED
from run_greenfield import REFERENCE_TAX, mix_row, solve_case

RESULTS = NOTE / "results"

# Ordered dearest to cheapest, which is the order figure 9.4 plots them in
# and the order the prose reads them in.
COST_SCENARIOS = ["pessimistic", "baseline", "optimistic"]
REFERENCE_SCENARIO = "baseline"  # what sections 7 and 9 solve on


def costs_for(scenario: str) -> pd.DataFrame:
    """The cost table for one scenario. `baseline` is the very file section 7
    reads, not a copy of it, so the middle point of this sweep reproduces the
    reference case exactly rather than approximately."""
    suffix = "" if scenario == REFERENCE_SCENARIO else f"_{scenario}"
    path = PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}{suffix}.csv"
    if not path.exists():
        raise SystemExit(
            f"missing {path.name} — run `python data/prepare.py` to build the "
            f"cost scenarios the sweep re-solves over"
        )
    return pd.read_csv(path, index_col="technology")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=336,
        help="snapshots the year is reduced to (default 336; the note's "
        "figures use 1095)",
    )
    parser.add_argument(
        "--aggregation", choices=network.AGGREGATION_SCHEMES, default="segments",
        help="how the year is reduced to --hours snapshots (segments, the "
        "default, or stride; see model/network.py). Use the same as "
        "run_greenfield.py.",
    )
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    if not (RESULTS / "greenfield_summary.json").exists():
        raise SystemExit("run pipeline/run_greenfield.py first")

    scale = pd.read_csv(PROCESSED / "cost_scenarios.csv", comment="#",
                        index_col="technology")

    rows = {}
    for scenario in COST_SCENARIOS:
        costs = costs_for(scenario)
        n, _ = solve_case(
            f"costs_{scenario}", costs, args.hours, ets_price=REFERENCE_TAX,
            aggregation=args.aggregation,
        )
        rows[scenario] = mix_row(n, None, REFERENCE_TAX)
        print(f"{scenario} costs: Danish bill "
              f"{rows[scenario]['dk_system_cost'] / 1e9:.2f} bnEUR, "
              f"emissions {rows[scenario]['emissions_t'] / 1e6:.2f} Mt")

    mix = pd.DataFrame(rows).T
    mix.index.name = "scenario"
    mix.to_csv(RESULTS / "costs_mix.csv")

    # A couple of the scenarios' own numbers travel with the results so the
    # prose can quote what was actually varied without stage 3 reopening
    # data/processed/ -- build.py reads results/ and nothing else.
    def moved(tech: str) -> dict:
        if tech not in scale.index:
            return {}
        row = scale.loc[tech]
        return {
            "baseline_eur_per_kw": float(
                row[f"investment_{greenfield.FORWARD_HORIZON}_eur_per_kw"]),
            "pessimistic_eur_per_kw": float(row["investment_pessimistic_eur_per_kw"]),
            "optimistic_eur_per_kw": float(row["investment_optimistic_eur_per_kw"]),
        }

    (RESULTS / "costs_summary.json").write_text(
        json.dumps(
            {
                "scenarios": COST_SCENARIOS,
                "reference_scenario": REFERENCE_SCENARIO,
                "horizon": greenfield.FORWARD_HORIZON,
                "trend_base_year": int(scale["base_year"].iloc[0]),
                "trend_scale": float(scale["trend_scale"].iloc[0]),
                "hours": args.hours,
                "aggregation": args.aggregation,
                "carbon_price": REFERENCE_TAX,
                # Measured on the DANISH bill, not the solver's objective.
                # Eleven of the twelve zones are fixed in this section, so a
                # spread taken on the objective divides a Danish movement by
                # a European denominator and reports a tenth of a per cent
                # whatever happens.
                "cost_spread_pct": float(
                    100.0
                    * (mix["dk_system_cost"].max() - mix["dk_system_cost"].min())
                    / mix["dk_system_cost"].mean()
                ),
                "cost_spread_objective_pct": float(
                    100.0
                    * (mix["system_cost"].max() - mix["system_cost"].min())
                    / mix["system_cost"].mean()
                ),
                "scenario_examples": {
                    tech: moved(tech)
                    for tech in ["solar-utility", "onwind", "offwind",
                                 "battery storage"]
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for name in ["costs_mix.csv", "costs_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
