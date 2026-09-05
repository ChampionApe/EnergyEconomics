"""Solve the section 3 instances and write everything figures 3.1-3.8 need
into results/.

    python pipeline/run_dispatch_t.py                fast default (168 hours)
    python pipeline/run_dispatch_t.py --hours 8784   the note's figures

The instance is the section 2 fleet (same capacities, same technology table)
facing the actual hourly DK1 load of 2024 (mean 2.7 GW, peak 4.2 GW — the
dispatchable half of the fleet alone covers the peak, so the LP stays feasible
even in dark, windless hours), with solar and wind on their DK1 availability
profiles. `--hours` samples
every k-th hour of the year rather than a contiguous block, so even the small
default sees all four seasons; each experiment then runs:

    base          one year of hourly dispatch          -> figs 3.1-3.4
    penetration   wind and solar capacity scaled up    -> figs 3.5-3.6
                  and down, one family at a time
    cross-check   the identical base instance built in
                  PyPSA; prices and objective compared

The cross-check is the point where the note switches idiom: the explicit
linopy model and the PyPSA network must agree to solver tolerance, and the
achieved agreement is written into results/ so the note can quote it.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import dispatch, dispatch_t
from run_dispatch import PROCESSED

RESULTS = NOTE / "results"
YEAR = 2024

# The 2024 market embedded the EU ETS at roughly this average allowance
# price (EUR/t). The base year is solved a second time with it, so the
# validation figure can show what part of the model-market price gap is
# just the carbon price the plain merit order leaves out.
CARBON_TAU = 65.0

# Which availability profile drives which technology.
PROFILE_OF = {
    "solar_pv": "solar_pu",
    "wind_onshore": "wind_onshore_pu",
    "wind_offshore": "wind_offshore_pu",
}

IMPORTS = "imports"

# DK1's cross-border capacity in MW, and the price series that stands in for
# each neighbour. Denmark may buy at what the neighbours charge in that hour,
# up to the capacity of the wires -- an open economy with exogenous terms of
# trade. Section 6 replaces this with a network that computes the
# neighbours' prices instead of reading them off the market.
#
# The wires are Energinet's: Skagerrak to southern Norway, Konti-Skan to
# Sweden, the Jutland interconnectors to Germany, and the Great Belt link to
# DK2. Their prices are the day-ahead prices of those zones, in
# data/processed/spot_2024.csv.
INTERCONNECTORS = {
    "NO2": 1700.0,
    "SE3": 740.0,
    "DE": 2500.0,
    "DK2": 600.0,
}

# The backstop is one technology, so the four prices become one: a
# capacity-weighted average. Taking the cheapest neighbour instead would
# assume the whole import need can flow down whichever wire is cheapest,
# which the capacities do not allow.
IMPORT_WEIGHTS = {
    zone: mw / sum(INTERCONNECTORS.values())
    for zone, mw in INTERCONNECTORS.items()
}

# Capacity scaling grids for the penetration sweep, centred on DK1's actual
# capacities: wind starts at 5.1 GW and solar at 2.3 GW, so both grids run
# from a fraction of today's fleet up to a deeply renewable system.
SWEEP_SCALES = {
    "wind": [0.2, 0.4, 0.6, 1.0, 1.5, 2.0, 3.0],
    "solar": [0.2, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0],
}
SWEEP_TECHS = {
    "wind": ["wind_onshore", "wind_offshore"],
    "solar": ["solar_pv"],
}


def dk1_fleet(tech):
    """DK1's fleet in the base year, plus the import backstop.

    Wind and solar are set to the maxima the profiles were normalised by, so
    profile times capacity reproduces DK1's own hourly production rather than
    a stylised fraction of it. The thermal fleet is the vendored PyPSA-Eur
    snapshot of the same zone; DK1 has no oil or open-cycle peakers, so
    neither appears.

    Neither half covers the peak. DK1's firm capacity is about 2.6 GW against
    a 4.2 GW peak load, and the shortfall is imported -- in 2024 DK1 was a
    net importer in 53% of hours. The backstop is therefore not a numerical
    convenience: without it this model is infeasible in 448 hours of the
    year, which is itself the section's first result about system boundaries.

    Returns the capacity series and the technology table extended with a row
    for imports, whose marginal cost is supplied per hour by `import_price`
    and whose emission rate is zero -- territorial accounting, the same
    convention that makes leakage visible in section 7.
    """
    meta = json.loads(
        (PROCESSED / f"profiles_dk1_{YEAR}.json").read_text(encoding="utf-8")
    )
    mx = meta["normalisation_max_mw"]
    zone = (
        pd.read_csv(PROCESSED / "network_eur_bz_2024_fleet.csv")
        .query("bus == 'DK1'")
        .set_index("carrier")["p_nom_mw"]
    )
    biomass = float(zone["biomass"])
    capacity = pd.Series(
        {
            "solar_pv": float(mx["solar"]),
            "wind_onshore": float(mx["wind_onshore"]),
            "wind_offshore": float(mx["wind_offshore"]),
            "waste_chp": float(zone["waste"]),
            "coal_chp": float(zone["coal"]),
            # technology-data splits wood into chips and pellets and
            # PyPSA-Eur does not, so the zone's biomass is split in the
            # proportion the note's own two entries stood in.
            "wood_chips_chp": biomass * 0.6,
            "wood_pellets_chp": biomass * 0.4,
            "ccgt": float(zone["CCGT"]),
            IMPORTS: float(sum(INTERCONNECTORS.values())),
        },
        name="capacity",
    )

    imports_row = pd.DataFrame(
        {
            "label": ["Imports"],
            "fuel": ["none"],
            "fuel_price_eur_per_mwh_th": [0.0],
            "efficiency": [1.0],
            "vom_eur_per_mwh": [0.0],
            "co2_t_per_mwh_th": [0.0],
            "source": ["Neighbouring zones' day-ahead prices; see run_dispatch_t.py"],
        },
        index=pd.Index([IMPORTS], name="tech"),
    )
    tech = pd.concat([tech, imports_row.reindex(columns=tech.columns)])
    return capacity, tech


def import_price(index):
    """What the neighbours charge, hour by hour: the capacity-weighted mean
    of their day-ahead prices, as a one-column frame the model reads as
    c_{imports,t}."""
    spot = pd.read_csv(
        PROCESSED / f"spot_{YEAR}.csv", index_col=0, parse_dates=True
    )
    zones = spot.reindex(index)[list(IMPORT_WEIGHTS)]
    if zones.isna().any().any():
        raise SystemExit(
            "spot prices missing for some periods — the import backstop "
            "cannot be priced; re-run data/prepare.py"
        )
    weighted = sum(zones[z] * w for z, w in IMPORT_WEIGHTS.items())
    return pd.DataFrame({IMPORTS: weighted})


def load_instance(hours):
    """The sampled instance: load path, availability profiles, and the full
    hourly profile table (kept for figure 3.1)."""
    profiles = pd.read_csv(
        PROCESSED / f"profiles_dk1_{YEAR}.csv", index_col="time", parse_dates=True
    )
    stride = max(1, len(profiles) // hours)
    sample = profiles.iloc[::stride].iloc[:hours]

    load = sample["load_mw"].rename("load")
    availability = pd.DataFrame(
        {tech: sample[col] for tech, col in PROFILE_OF.items()}
    )
    return load, availability, profiles, stride


def marginal_shares(price, generators):
    """How often each technology sets the price.

    A technology is marginal in an hour when the price equals its marginal
    cost, which is the merit-order result of section 2 read backwards. The
    technologies priced by the hour — imports — cannot be identified that
    way, so they take the residual: the hours no constant cost explains.
    """
    constant = generators[generators["mc_is_constant"].astype(bool)]["mc"]
    p = price.round(2)
    shares = {t: float((p == round(c, 2)).mean()) for t, c in constant.items()}
    shares["imports"] = float((~p.isin(constant.round(2).values)).mean())
    return shares


def demand_and_trade(profiles):
    """What section 3.1 needs about demand and about the wires.

    The section's whole argument is that a technology's value depends on
    *when* it produces relative to when people consume, so the correlation
    between availability and demand is a primary object, not a footnote. It
    is reported three ways, because the single hourly number hides the
    interesting structure: solar's mild positive correlation is a strong
    daily alignment cancelling against a strong seasonal one.
    """
    load = profiles["load_mw"]
    by_hour = profiles.groupby(profiles.index.hour)
    by_month = profiles.groupby(profiles.index.month)
    hour_means, month_means = by_hour.mean(), by_month.mean()

    facts = {
        "load_mean_mw": float(load.mean()),
        "load_min_mw": float(load.min()),
        "load_max_mw": float(load.max()),
        "load_peak_hour": int(hour_means["load_mw"].idxmax()),
        "load_trough_hour": int(hour_means["load_mw"].idxmin()),
        "load_daily_swing_pct": float(
            100 * (hour_means["load_mw"].max() / hour_means["load_mw"].min() - 1)
        ),
        "load_seasonal_swing_pct": float(
            100 * (month_means["load_mw"].max() / month_means["load_mw"].min() - 1)
        ),
        "load_peak_month": int(month_means["load_mw"].idxmax()),
        "correlation": {},
    }
    for tech_name, col in PROFILE_OF.items():
        facts["correlation"][tech_name] = {
            "hourly": float(load.corr(profiles[col])),
            "seasonal": float(month_means["load_mw"].corr(month_means[col])),
            "daily": float(hour_means["load_mw"].corr(hour_means[col])),
        }

    # The wires, as they were actually used. Positive is import in the Energi
    # Data Service convention (data/prepare.py records it).
    path = PROCESSED / f"exchange_dk1_{YEAR}.csv"
    if path.exists():
        exchange = pd.read_csv(path, index_col=0, parse_dates=True)
        net = exchange.sum(axis=1).reindex(profiles.index).dropna()
        facts["trade"] = {
            "imports_gwh": float(net.clip(lower=0).sum() / 1000),
            "exports_gwh": float(-net.clip(upper=0).sum() / 1000),
            "net_import_gwh": float(net.sum() / 1000),
            "net_import_share_of_load": float(net.sum() / load.sum()),
            # Gross trade, which is the number that says how open the zone
            # is. DK1's net position is near zero and its turnover is a
            # third of consumption: the wires are busy in both directions,
            # and the net figure alone hides that.
            "turnover_share_of_load": float(net.abs().sum() / load.sum()),
            "hours_importing_share": float((net > 0).mean()),
            "max_net_import_mw": float(net.max()),
            "max_net_export_mw": float(-net.min()),
        }
    return facts


def metrics(tech, sol, load, techs):
    """The section 3 summary statistics for a group of technologies."""
    generation = sol["generation"]
    capture = dispatch_t.capture_price(sol["price"], generation)
    vf = dispatch_t.value_factor(sol["price"], generation, load)
    share = generation[techs].sum().sum() / load.sum()
    energy_weight = generation[techs].sum()
    energy = float(energy_weight.sum())
    capture_price = float((capture[techs] * energy_weight).sum() / energy_weight.sum())
    return {
        "energy_share": float(share),
        "capture_price": capture_price,
        "value_factor": float(
            (vf[techs] * energy_weight).sum() / energy_weight.sum()
        ),
        # Both averages, because they answer different questions and the
        # note uses both: `base_price` is the value factor's denominator,
        # `avg_price` the plain time-average quoted in the text next to
        # section 2's single-hour price.
        "base_price": dispatch_t.base_price(sol["price"], load),
        "avg_price": float(sol["price"].mean()),
        # Levels, not ratios. The value factor is a ratio whose denominator
        # moves, so it can rise while revenue falls -- the trap figure 3.6
        # is about. Keeping energy and revenue here lets stage 3 draw both.
        "energy_mwh": energy,
        "revenue_eur": capture_price * energy,
    }


def run_base(tech, capacity, load, availability, hourly_cost):
    sol = dispatch_t.solve(tech, capacity, load, availability,
                           hourly_cost=hourly_cost)
    generation = sol["generation"]

    # A technology priced by the hour has no single marginal cost. Report the
    # mean of its hourly cost and flag it, so stage 3 can keep it out of the
    # "the price is always some technology's marginal cost" annotations —
    # with imports in the fleet, that statement is no longer true.
    mc = dispatch.marginal_cost(tech).loc[capacity.index]
    constant = pd.Series(True, index=capacity.index)
    if hourly_cost is not None:
        for name in hourly_cost.columns.intersection(capacity.index):
            mc[name] = float(hourly_cost[name].mean())
            constant[name] = False

    generators = pd.DataFrame(
        {
            "label": tech.loc[capacity.index, "label"],
            "capacity_mw": capacity,
            "mc": mc,
            "mc_is_constant": constant,
            "energy_mwh": generation.sum(),
            "capacity_factor": dispatch_t.capacity_factor(generation, capacity),
            "capture_price": dispatch_t.capture_price(sol["price"], generation),
            "value_factor": dispatch_t.value_factor(
                sol["price"], generation, load
            ),
        }
    )

    hours = pd.DataFrame({"load_mw": load, "price": sol["price"]})
    for tech_name, col in PROFILE_OF.items():
        hours[col] = availability[tech_name]
    for g in capacity.index:
        hours[f"gen_{g}"] = generation[g]

    return sol, generators, hours


def run_sweep(tech, capacity_base, load, availability, hourly_cost):
    """Scale one VRE family at a time and record how market value moves.

    Two sets of columns come out of each solve. The unprefixed ones are the
    *swept* family's own statistics — self-cannibalisation, figure 3.5. The
    prefixed ones (`wind_*`, `solar_*`) are every family's statistics at the
    same point, which is what figure 3.6 needs: scaling solar and watching
    what happens to *wind* is the cross-technology case, where the value
    factor and the revenue move in opposite directions.
    """
    rows = []
    for family, scales in SWEEP_SCALES.items():
        for scale in scales:
            capacity = capacity_base.copy()
            capacity[SWEEP_TECHS[family]] *= scale
            sol = dispatch_t.solve(tech, capacity, load, availability,
                                   hourly_cost=hourly_cost)
            row = {"family": family, "scale": scale}
            row |= metrics(tech, sol, load, SWEEP_TECHS[family])
            for other, others_techs in SWEEP_TECHS.items():
                row |= {
                    f"{other}_{k}": v
                    for k, v in metrics(tech, sol, load, others_techs).items()
                }
            rows.append(row)
    return pd.DataFrame(rows)


def run_week_comparison(tech, capacity):
    """Model dispatch against realised dispatch, one week, hour by hour.

    This is the only experiment in the section solved at full hourly
    resolution on a *contiguous* block: the point is to look at the shape of
    a week, which a strided sample destroys. It is 168 periods and solves
    instantly.

    The week is chosen, from the profiles alone and before any solve, as the
    one with the most variable residual load — where the dispatch has the
    most work to do. Returns None if the realised data has not been prepared,
    so the rest of the pipeline still runs.
    """
    path = PROCESSED / f"actual_dispatch_dk1_{YEAR}.csv"
    if not path.exists():
        print(f"note: {path.name} missing — skipping the realised-dispatch "
              f"comparison (re-run data/prepare.py to build it)")
        return None, None

    profiles = pd.read_csv(
        PROCESSED / f"profiles_dk1_{YEAR}.csv", index_col="time", parse_dates=True
    )
    vre = (
        profiles["solar_pu"] * capacity["solar_pv"]
        + profiles["wind_onshore_pu"] * capacity["wind_onshore"]
        + profiles["wind_offshore_pu"] * capacity["wind_offshore"]
    )
    residual = profiles["load_mw"] - vre
    weekly_spread = residual.rolling("168h").std()
    end = weekly_spread.idxmax()
    week = profiles.loc[end - pd.Timedelta(hours=167) : end]

    load = week["load_mw"].rename("load")
    availability = pd.DataFrame({t: week[c] for t, c in PROFILE_OF.items()})
    sol = dispatch_t.solve(tech, capacity, load, availability,
                           hourly_cost=import_price(load.index))

    model = pd.DataFrame({"load_mw": load, "price": sol["price"]})
    for g in capacity.index:
        model[f"gen_{g}"] = sol["generation"][g]

    actual = pd.read_csv(path, index_col="time", parse_dates=True)
    actual = actual.reindex(model.index)

    print(f"week comparison: {model.index[0]:%Y-%m-%d} to {model.index[-1]:%Y-%m-%d}")
    return model, actual


def residual_duration(load, availability, capacity):
    """Duration curves for figure 3.3: load, and residual load at increasing
    wind capacity (solar at its base size). Residual load uses the *available*
    VRE energy, before any curtailment, so it can go negative."""
    solar = availability["solar_pv"] * capacity["solar_pv"]
    wind = (
        availability["wind_onshore"] * capacity["wind_onshore"]
        + availability["wind_offshore"] * capacity["wind_offshore"]
    )
    out = {"load": load}
    for scale in [1, 2, 4]:
        out[f"residual_wind_x{scale}"] = load - solar - scale * wind
    # Duration curves: each column sorted descending, index = fraction of hours.
    sorted_cols = {
        name: series.sort_values(ascending=False).to_numpy()
        for name, series in out.items()
    }
    df = pd.DataFrame(sorted_cols)
    df.index = (df.index + 0.5) / len(df) * 100.0
    return df


def run_validation():
    """Hold the model against the actual DK1 market outcomes of the same
    year: the realised day-ahead price distribution, and the capture prices
    and value factors the real wind and solar fleets earned. Written to
    results/ for figure 3.5 and the quoted comparisons of section 3."""
    spot = pd.read_csv(
        PROCESSED / f"spot_{YEAR}.csv", index_col="time", parse_dates=True
    )["DK1"].dropna()
    profiles = pd.read_csv(
        PROCESSED / f"profiles_dk1_{YEAR}.csv", index_col="time", parse_dates=True
    )
    meta = json.loads(
        (PROCESSED / f"profiles_dk1_{YEAR}.json").read_text(encoding="utf-8")
    )
    maxima = meta["normalisation_max_mw"]

    joined = profiles.join(spot.rename("price"), how="inner")
    price = joined["price"]

    def capture(weights):
        return float((price * weights).sum() / weights.sum())

    wind_mw = (
        joined["wind_onshore_pu"] * maxima["wind_onshore"]
        + joined["wind_offshore_pu"] * maxima["wind_offshore"]
    )
    # The market's own value factors are measured against the same base as
    # the model's: the consumption-weighted average price, weighted here by
    # actual DK1 gross consumption.
    base = dispatch_t.base_price(price, joined["load_mw"])
    actual = {
        "avg_price": float(price.mean()),
        "base_price": base,
        "price_quantiles": {q: float(price.quantile(q))
                            for q in (0.05, 0.5, 0.95)},
        "negative_hours_share": float((price < 0).mean()),
        "max_price": float(price.max()),
        "capture_wind": capture(wind_mw),
        "capture_solar": capture(joined["solar_pu"]),
        "vf_wind": capture(wind_mw) / base,
        "vf_solar": capture(joined["solar_pu"]) / base,
    }

    duration = pd.DataFrame(
        {"actual_price": price.sort_values(ascending=False).to_numpy()}
    )
    duration.index = (duration.index + 0.5) / len(duration) * 100.0
    return duration, actual


def crosscheck_pypsa(tech, capacity, load, availability, hourly_cost):
    """Build the identical instance as a PyPSA network and compare.

    This is the section 3 hinge: `Generator` with `p_nom`, `marginal_cost`
    and a time-varying `p_max_pu` is exactly eq:intermittency:capacity, and
    the bus's `marginal_price` is exactly the dual of
    eq:intermittency:balance. The note quotes the agreement achieved here.
    """
    import warnings

    import pypsa

    logging.getLogger("pypsa").setLevel(logging.WARNING)
    logging.getLogger("linopy").setLevel(logging.WARNING)
    # pypsa 1.x emits FutureWarnings about upcoming 2.0 defaults; they are
    # upstream noise, not something a reader of this pipeline can act on.
    warnings.filterwarnings("ignore", category=FutureWarning)

    mc = dispatch.marginal_cost(tech).loc[capacity.index]

    n = pypsa.Network()
    n.set_snapshots(load.index)
    n.add("Carrier", "AC")
    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "demand", bus="elec", p_set=load)
    for g in capacity.index:
        kwargs = {}
        if g in availability.columns:
            kwargs["p_max_pu"] = availability[g]
        # A technology priced hour by hour is still one generator: PyPSA
        # takes a series for marginal_cost exactly where the linopy model
        # takes a column of c_{g,t}.
        cost = hourly_cost[g] if (hourly_cost is not None
                                  and g in hourly_cost.columns) else mc[g]
        n.add(
            "Generator", g, bus="elec",
            p_nom=capacity[g], marginal_cost=cost, **kwargs,
        )
    n.optimize(solver_name="highs", progress=False,
               solver_options={"output_flag": False})

    linopy_sol = dispatch_t.solve(tech, capacity, load, availability,
                                  hourly_cost=hourly_cost)
    price_pypsa = n.buses_t.marginal_price["elec"]
    return {
        "max_abs_price_diff": float(
            (linopy_sol["price"] - price_pypsa).abs().max()
        ),
        "rel_objective_diff": float(
            abs(n.objective - linopy_sol["cost"]) / linopy_sol["cost"]
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours",
        type=int,
        default=168,
        help="periods to solve, sampled evenly across the year (default 168; "
        "the note's figures use 8784 = every hour of the year)",
    )
    args = parser.parse_args()

    tech = dispatch.read_tech(PROCESSED / "technology_costs_small.csv")
    load, availability, profiles, stride = load_instance(args.hours)
    capacity, tech = dk1_fleet(tech)
    hourly_cost = import_price(load.index)
    RESULTS.mkdir(parents=True, exist_ok=True)

    sol, generators, hours = run_base(tech, capacity, load, availability,
                                      hourly_cost)
    # The same year with the 2024 ETS price in every marginal cost — the
    # third curve on the validation figure.
    sol_carbon = dispatch_t.solve(
        tech, capacity, load, availability, co2_price=CARBON_TAU,
        hourly_cost=hourly_cost,
    )
    hours["price_carbon"] = sol_carbon["price"]
    sweep = run_sweep(tech, capacity, load, availability, hourly_cost)
    residual = residual_duration(load, availability, capacity)
    check = crosscheck_pypsa(tech, capacity, load, availability, hourly_cost)
    actual_duration, actual = run_validation()
    week_model, week_actual = run_week_comparison(tech, capacity)

    meta = json.loads(
        (PROCESSED / f"profiles_dk1_{YEAR}.json").read_text(encoding="utf-8")
    )
    summary = {
        "year": YEAR,
        "hours": len(load),
        "stride": stride,
        "load_mean_mw": meta["load_mean_mw"],
        "load_max_mw": meta["load_max_mw"],
        "avg_price": float(sol["price"].mean()),
        "base_price": dispatch_t.base_price(sol["price"], load),
        "import_share_of_load": float(
            sol["generation"][IMPORTS].sum() / load.sum()
        ),
        "import_price_mean": float(hourly_cost[IMPORTS].mean()),
        "emissions_t": sol["emissions"],
        "carbon_tau_eur_t": CARBON_TAU,
        "avg_price_carbon": float(sol_carbon["price"].mean()),
        "emissions_carbon_t": sol_carbon["emissions"],
        "profile_capacity_factors": meta["capacity_factor_of_profile"],
        "pypsa_crosscheck": check,
        "actual_market": actual,
        "demand_and_trade": demand_and_trade(profiles),
        "marginal_share": marginal_shares(sol["price"], generators),
        "price_quantiles": {
            q: float(sol["price"].quantile(q)) for q in (0.05, 0.5, 0.95)
        },
        "price_max": float(sol["price"].max()),
    }

    generators.to_csv(RESULTS / "dispatch_t_generators.csv", index_label="tech")
    hours.to_csv(RESULTS / "dispatch_t_hours.csv", index_label="time")
    sweep.to_csv(RESULTS / "dispatch_t_sweep.csv", index=False)
    residual.to_csv(RESULTS / "dispatch_t_residual.csv", index_label="pct_of_hours")
    profiles.to_csv(RESULTS / "dispatch_t_profiles.csv", index_label="time")
    actual_duration.to_csv(RESULTS / "dispatch_t_actual_duration.csv",
                           index_label="pct_of_hours")
    if week_model is not None:
        week_model.to_csv(RESULTS / "dispatch_t_week_model.csv", index_label="time")
        week_actual.to_csv(RESULTS / "dispatch_t_week_actual.csv", index_label="time")
    (RESULTS / "dispatch_t_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(
        f"{len(load)} hours (stride {stride}): avg price "
        f"{summary['avg_price']:.2f} EUR/MWh; pypsa cross-check: "
        f"max price diff {check['max_abs_price_diff']:.2e} EUR/MWh, "
        f"objective rel diff {check['rel_objective_diff']:.2e}"
    )
    for name in [
        "dispatch_t_generators.csv",
        "dispatch_t_hours.csv",
        "dispatch_t_sweep.csv",
        "dispatch_t_residual.csv",
        "dispatch_t_profiles.csv",
        "dispatch_t_summary.json",
    ]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
