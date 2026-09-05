"""Re-solve the section 7 reference case across weather years — the
uncertainty section's sweep — and write everything its weather figures
need into results/.

    python pipeline/run_weather.py                fast default (336 segments)
    python pipeline/run_weather.py --hours 1095   the note's figures

One capacity expansion per weather year 2015-2024: the same network, the same
costs, the same demand, the same common carbon price (the reference from
run_greenfield.py, which must have been run first) — only the weather
changes. The spread of the resulting optimal mixes and system costs is the
section's point: a single-year answer carries spurious precision.

The weather comes from data/processed/weather_zones_{year}.csv, which covers
all twelve bidding zones on one consistent ERA5 year. That matters more than
it sounds: a sweep that swapped the Danish zones only would pair a becalmed
Denmark with an unrelated German year and could always import. Correlated
calm is exactly the risk a capacity expansion model is being asked about.
Section 7's reference case is solved on the same archive's reference year,
so the reference column of this sweep IS the reference case: it is served
from the same cached solve rather than re-solved.

(The tax-versus-cap experiment lives in run_taxcap.py, on the European
model, where a cap actually binds. The perfect-foresight figure comes from
run_storage.py.)
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import network
from run_greenfield import (REFERENCE_TAX, REFERENCE_WEATHER_YEAR, load_shared,
                            mix_row, solve_case, tax_tag, year_weather)

RESULTS = NOTE / "results"
WEATHER_YEARS = list(range(2015, 2025))


def case_tag(year: int) -> str:
    """The reference year is section 7's reference case, not a copy of it:
    reuse its cache tag so the two are one solve."""
    if year == REFERENCE_WEATHER_YEAR:
        return tax_tag(REFERENCE_TAX)
    return f"weather_era5_{year}"


def price_duration(n, zone: str = "DK1") -> pd.Series:
    """The zone's price duration curve in HOURS: each snapshot repeated for
    the hours it stands for, then sorted."""
    hourly = network.expand_to_hours(n, n.buses_t.marginal_price[[zone]])
    return hourly[zone].sort_values(ascending=False).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=336,
        help="snapshots each year is reduced to (default 336; the note's "
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
    costs_full = load_shared()

    rows = {}
    duration = {}
    for year in WEATHER_YEARS:
        n, _ = solve_case(
            case_tag(year), costs_full, args.hours,
            weather=year_weather(year), ets_price=REFERENCE_TAX,
            aggregation=args.aggregation,
        )
        rows[year] = mix_row(n, None, REFERENCE_TAX)
        duration[year] = price_duration(n)
        print(f"{year}: Danish bill {rows[year]['dk_system_cost'] / 1e9:.2f} bnEUR, "
              f"emissions {rows[year]['emissions_t'] / 1e6:.2f} Mt")

    mix = pd.DataFrame(rows).T
    mix.index.name = "year"
    duration = pd.DataFrame(duration)
    duration.index = (duration.index + 0.5) / len(duration) * 100.0

    mix.to_csv(RESULTS / "weather_mix.csv")
    duration.to_csv(RESULTS / "weather_price_duration.csv", index_label="pct_of_hours")
    (RESULTS / "weather_summary.json").write_text(json.dumps({
        "years": WEATHER_YEARS,
        "reference_year": REFERENCE_WEATHER_YEAR,
        "hours": args.hours,
        "aggregation": args.aggregation,
        "carbon_price": REFERENCE_TAX,
        # Measured on the DANISH bill, not the solver's objective.
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
        "emissions_spread_pct": float(
            100.0 * (mix["emissions_t"].max() - mix["emissions_t"].min())
            / mix["emissions_t"].mean()) if mix["emissions_t"].mean() > 0 else 0.0,
    }, indent=2), encoding="utf-8")
    for name in ["weather_mix.csv", "weather_price_duration.csv", "weather_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
