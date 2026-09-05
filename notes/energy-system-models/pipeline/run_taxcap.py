"""Tax versus cap under weather uncertainty, on the European model — the
experiment section 2 promised when it stated the equivalence and its
limits.

    python pipeline/run_taxcap.py                fast default (336 segments)
    python pipeline/run_taxcap.py --hours 1095   the note's figures

The basic rung of the expansion ladder (run_expansion.py, which must have
been run first) is re-solved on each weather year of the zonal archive
twice: under the reference CO2 budget, where emissions are fixed and the
carbon price is whatever the weather makes it; and under a carbon TAX equal
to the reference year's carbon price, where the price is fixed and
emissions are whatever the weather makes them. In the reference year the
two coincide, by section 2's equivalence. In every other year they do not,
and the two panels of the resulting figure are Weitzman's argument measured
on this system.

The experiment lives here rather than on the Danish model of section 7
because a territorial budget in an open economy hardly binds -- imports
count as carbon-free -- so its price carries no information. The
continental budget binds in every year.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))
sys.path.insert(0, str(NOTE / "pipeline"))

from model import expansion, network
from run_expansion import REFERENCE_FRACTION, RUNGS, load_shared, mix_row, solve_case
from run_greenfield import REFERENCE_WEATHER_YEAR, year_weather

RESULTS = NOTE / "results"
WEATHER_YEARS = list(range(2015, 2025))
RUNG = "basic"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=336)
    parser.add_argument("--aggregation", choices=network.AGGREGATION_SCHEMES,
                        default="segments")
    args = parser.parse_args()

    ladder_file = RESULTS / "expansion_ladder.csv"
    if not ladder_file.exists():
        raise SystemExit("run pipeline/run_expansion.py first — the reference "
                         "budget and carbon price come from its ladder")
    ladder = pd.read_csv(ladder_file)
    ref = ladder[(ladder["rung"] == RUNG)
                 & (ladder["budget_share"] == REFERENCE_FRACTION)].iloc[0]
    budget = float(ref["unconstrained_t"]) * REFERENCE_FRACTION
    tau = float(ref["co2_price_eur_t"])
    costs_full = load_shared()
    kwargs = RUNGS[RUNG]

    rows = []
    for year in WEATHER_YEARS:
        weather = year_weather(year)
        # The reference year's cap case is the ladder's own reference solve.
        cap_tag = (f"{RUNG}_cap{int(REFERENCE_FRACTION * 100)}"
                   if year == REFERENCE_WEATHER_YEAR
                   else f"{RUNG}_cap{int(REFERENCE_FRACTION * 100)}_w{year}")
        n_cap, sigma = solve_case(cap_tag, costs_full, args.hours,
                                  aggregation=args.aggregation, co2_budget=budget,
                                  weather=weather, **kwargs)
        n_tax, _ = solve_case(f"{RUNG}_tax_w{year}", costs_full, args.hours,
                              aggregation=args.aggregation, carbon_tax=tau,
                              weather=weather, **kwargs)
        cap = mix_row(n_cap, sigma, RUNG, REFERENCE_FRACTION)
        tax = mix_row(n_tax, None, RUNG, None)
        rows.append({
            "year": year,
            "cap_co2_price_eur_t": sigma,
            "cap_emissions_t": cap["emissions_t"],
            "cap_system_cost_eur": cap["system_cost_eur"],
            "tax_eur_t": tau,
            "tax_emissions_t": tax["emissions_t"],
            "tax_system_cost_eur": tax["system_cost_eur"],
        })
        print(f"{year}: cap -> sigma {sigma:.0f} EUR/t; tax {tau:.0f} EUR/t -> "
              f"{tax['emissions_t'] / 1e6:.1f} Mt against the cap's "
              f"{budget / 1e6:.1f} Mt")

    df = pd.DataFrame(rows).set_index("year")
    df.to_csv(RESULTS / "taxcap.csv")
    (RESULTS / "taxcap_summary.json").write_text(json.dumps({
        "rung": RUNG,
        "years": WEATHER_YEARS,
        "reference_year": REFERENCE_WEATHER_YEAR,
        "hours": args.hours,
        "budget_t": budget,
        "tax_eur_t": tau,
        "sigma_min": float(df["cap_co2_price_eur_t"].min()),
        "sigma_max": float(df["cap_co2_price_eur_t"].max()),
        "tax_emissions_min_t": float(df["tax_emissions_t"].min()),
        "tax_emissions_max_t": float(df["tax_emissions_t"].max()),
        "tax_emissions_spread_pct_of_budget": float(
            100.0 * (df["tax_emissions_t"].max() - df["tax_emissions_t"].min())
            / budget),
    }, indent=2), encoding="utf-8")
    print("wrote results/taxcap.csv, results/taxcap_summary.json")


if __name__ == "__main__":
    main()
