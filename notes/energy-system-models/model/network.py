"""The 12-bidding-zone network — sections 6 to 8.

The network itself lives in `data/processed/network_eur_bz_2024.nc`: DK1,
DK2, DE, SE1-SE4 and NO1-NO5 — the actual bidding zones of the Nordic and
German power markets — with 2024 hourly loads and weather, today's fleets
(from powerplantmatching/OPSD), reservoir hydro with historical inflow, and
the real transmission system: AC circuits and the named DC cables
(Skagerrak, Kontek, Konti-Skan, the Great Belt, NordLink, Baltic Cable). It
was derived from PyPSA-Eur, clustered to bidding zones; Appendix C of the
note documents the derivation.

This module is what the run scripts use to work with it: load it, subsample
its year, solve it, and read the trade economics off the solution.

The zonal price is the dual of each zone's market clearing — one lambda per
zone per hour, exactly as in section 3, but now linked by trade. When a
branch between two zones is unconstrained it equalises their prices; when it
is congested a price spread survives, and the flow earns the *congestion
rent* (eq:transmission:rent):

    rent_h = flow_h * (lambda_to,h - lambda_from,h)

which at the optimum is non-negative in both flow directions — power flows
toward the expensive zone.
"""

import logging
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

logging.getLogger("pypsa").setLevel(logging.ERROR)
logging.getLogger("linopy").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning)

# Solver selection. The published default is HiGHS: a student must never
# need a licence to reproduce the note. Set ESM_SOLVER=gurobi to solve
# with a local Gurobi installation instead (free academic licences
# exist) — barrier with crossover reproduces the same basic solution and
# exact duals, several times faster on the larger instances.
SOLVER = os.environ.get("ESM_SOLVER", "highs")


def solver_options(ipm: bool = False) -> dict:
    """Per-solver options: quiet, and (for the big LPs, `ipm=True`)
    interior point with crossover."""
    if SOLVER == "gurobi":
        return {"OutputFlag": 0, "Method": 2}  # barrier; crossover default-on
    options = {"output_flag": False}
    if ipm:
        options |= {"solver": "ipm", "run_crossover": "on"}
    return options

# EDS profile column for each VRE carrier — both the network's native
# (PyPSA-Eur) carriers and the note's own candidate carriers of section 7,
# so the weather swap of section 9 covers existing and greenfield fleets.
VRE_PROFILE_OF = {
    "onwind": "wind_onshore_pu",
    "offwind-ac": "wind_offshore_pu",
    "offwind-dc": "wind_offshore_pu",
    "offwind-float": "wind_offshore_pu",
    "solar": "solar_pu",
    "solar-hsat": "solar_pu",
    "wind_onshore": "wind_onshore_pu",
    "wind_offshore": "wind_offshore_pu",
    "solar_pv": "solar_pu",
}


# The shipped network arrives from PyPSA-Eur carrying the workflow's own fuel
# prices, which are not the note's. Left alone, section 2 tells the reader a
# combined-cycle plant costs 66 EUR/MWh to run while sections 6-9 quietly
# dispatch one at 44, and no figure anywhere shows the disagreement. So every
# thermal generator is re-priced on load, on the note's own fuel assumptions.
#
# What is replaced is the FUEL PRICE and the variable operating cost, not the
# efficiency: PyPSA-Eur's plant-level efficiencies are real heterogeneity
# (vintage, size, site) and are worth keeping. Each generator therefore keeps
# its own eta and gets the note's p^F and o, which is exactly
# eq:dispatch:mc applied to the real fleet.
FUEL_OF_CARRIER = {
    "CCGT": "gas",
    "OCGT": "gas",
    "coal": "coal",
    "lignite": "lignite",
    "oil": "oil",
    "nuclear": "uranium",
    "biomass": "solid biomass",
    "waste": "waste",
}
# Which technology-data row supplies each carrier's variable operating cost.
VOM_TECH_OF_CARRIER = {
    "CCGT": "CCGT",
    "OCGT": "OCGT",
    "coal": "coal",
    "lignite": "lignite",
    "oil": "oil",
    "nuclear": "nuclear",
    "biomass": "central solid biomass CHP",
    "waste": "waste CHP",
}


# ---------------------------------------------------------------------------
# Realism features.
#
# The note's boxed models stay minimal on purpose; every data-confronted
# solve of sections 6-9 carries three features on top of them — ramping
# limits, outage derating and transmission losses. (An operational
# reserve requirement was tried and removed, 2026-08-30: it doubled the
# LP, degenerated the crossover, and the capacity-expansion literature
# does not carry reserves in comparable solves either — PyPSA-Eur ships
# it off. Forecast-error cover therefore remains a named omission in the
# note's Appendix D, not a feature.) The appendix documents each feature,
# with its parameters and its known limitations; keep it in step with
# these constants.

# Hourly ramp limits per unit of capacity: PyPSA-Eur's own per-carrier
# values (data/unit_commitment.csv at v2026.08.0). Carriers it rates at
# 1/hour (OCGT, CCGT) traverse their whole range within an hour and are
# omitted.
#
# Convention (RKB, 2026-08-30): the limits are imposed at their TRUE
# HOURLY values on the sampled snapshots, NOT scaled up by the sampling
# stride. At 4-hour sampling that is deliberately conservative — a
# four-hour step is allowed only one hour's ramp — but the sampled series
# is itself a smoothed version of the hourly path, so scaling the limits
# up (the PyPSA issue #1273 reading) compounds one optimism with another
# and makes every limit vacuous. Aggregated capacity-expansion studies
# apply per-step limits the same way. Full-resolution runs are identical
# under either convention.
#
# Biomass and waste are not in PyPSA-Eur's table and carried no limit
# until 2026-09-03 (RKB), when the unlimited 13 GW biomass fleet was found
# running as the neighbours' peaker — moving more than half its range
# between segments in a quarter of all steps. Biomass takes coal's value:
# the Danish units are converted coal boilers, and the DEA catalogue gives
# a large wood-chip CHP a 45% minimum load and a two-hour warm start.
# Waste takes 0.6/hour from the catalogue's note that the boiler regulates
# about 1% per minute. Oil (steam plant in Sweden, turbines in Germany)
# stays unrated for want of a number.
RAMP_LIMIT_PER_HOUR = {
    "coal": 0.9, "lignite": 0.6, "nuclear": 0.3,
    "biomass": 0.9, "waste": 0.6,
}

# Forced-outage derating: static availability ceilings per thermal carrier,
# generic EFOR-style values (an assumption, not a dataset). Applied as
# min(existing, value), so the shipped network's own nuclear derating
# (0.812, PyPSA-Eur's) survives. Lower-case carriers are the greenfield
# candidates of section 7 — the same machines under the note's names.
OUTAGE_DERATE = {
    "CCGT": 0.95, "OCGT": 0.95, "oil": 0.95,
    "coal": 0.90, "lignite": 0.90, "biomass": 0.90, "waste": 0.90,
    "nuclear": 0.90,
    "ccgt": 0.95, "ocgt": 0.95, "ocgt_biogas": 0.95,
}

# HVDC losses: a flat 3% per crossing (converter pair plus cable),
# independent of length — crude, but the right order. A bidirectional link
# applies its efficiency in the wrong direction when flow reverses, so each
# DC link is split into two unidirectional ones (PyPSA-Eur's
# lossy_bidirectional_links pattern).
HVDC_LOSS = 0.03

# AC losses: PyPSA's piecewise-linear approximation of the quadratic
# resistive loss, at PyPSA-Eur's own default of 2 tangents. Passed to every
# optimize() call by the solve functions below.
TRANSMISSION_LOSSES_SEGMENTS = 2

def derate_outages(n: pypsa.Network) -> None:
    """Cap each thermal generator's availability at its carrier's EFOR-style
    derate, in place. Idempotent; generators with time-varying availability
    (VRE, run-of-river) are untouched because their carriers are not listed."""
    for carrier, derate in OUTAGE_DERATE.items():
        rows = n.generators.index[n.generators.carrier == carrier]
        if len(rows):
            n.generators.loc[rows, "p_max_pu"] = (
                n.generators.loc[rows, "p_max_pu"].clip(upper=derate)
            )


def split_lossy_links(n: pypsa.Network) -> None:
    """Give every bidirectional DC link its loss, by splitting it into two
    unidirectional links of efficiency 1 - HVDC_LOSS, in place."""
    bidirectional = n.links.index[
        (n.links.p_min_pu < 0) & (n.links.efficiency == 1.0)
    ]
    for name in bidirectional:
        row = n.links.loc[name]
        n.add(
            "Link", f"{name} rev", bus0=row.bus1, bus1=row.bus0,
            p_nom=row.p_nom, p_min_pu=0.0, p_max_pu=row.p_max_pu,
            efficiency=1.0 - HVDC_LOSS, carrier=row.carrier,
        )
    n.links.loc[bidirectional, "p_min_pu"] = 0.0
    n.links.loc[bidirectional, "efficiency"] = 1.0 - HVDC_LOSS


def apply_ramp_limits(n: pypsa.Network) -> None:
    """Set per-carrier ramp limits at their hourly values, per snapshot
    step — the deliberately conservative convention documented above.
    Call after any candidates are added."""
    for carrier, limit in RAMP_LIMIT_PER_HOUR.items():
        rows = n.generators.index[n.generators.carrier == carrier]
        if len(rows):
            n.generators.loc[rows, "ramp_limit_up"] = limit
            n.generators.loc[rows, "ramp_limit_down"] = limit


def reprice(n: pypsa.Network, fuels: pd.DataFrame, costs: pd.DataFrame) -> None:
    """Put the shipped fleet on the note's fuel prices, in place.

    Also refreshes each carrier's CO2 emission factor, so that
    `emission_rates()` and anything downstream of it use the same fuel
    accounting as the small table of sections 2-5.
    """
    for carrier, fuel in FUEL_OF_CARRIER.items():
        rows = n.generators.index[n.generators.carrier == carrier]
        if not len(rows):
            continue
        price = float(fuels.loc[fuel, "price_used_eur_per_mwh_th"])
        vom_tech = VOM_TECH_OF_CARRIER[carrier]
        vom = costs.loc[vom_tech, "VOM"] if vom_tech in costs.index else 0.0
        vom = float(vom) if pd.notna(vom) else 0.0
        efficiency = n.generators.loc[rows, "efficiency"].replace(0.0, pd.NA)
        n.generators.loc[rows, "marginal_cost"] = price / efficiency + vom
        if carrier in n.carriers.index:
            n.carriers.loc[carrier, "co2_emissions"] = float(
                fuels.loc[fuel, "co2_used_t_per_mwh_th"]
            )


def load_network(path: Path, fuels: pd.DataFrame | None = None,
                 costs: pd.DataFrame | None = None) -> pypsa.Network:
    """Load the shipped network, put it on the note's fuel prices, and apply
    the snapshot-independent realism features (outage derating, lossy DC
    links). Ramp limits depend on the sampling stride, so apply_ramp_limits()
    is a separate call, made after subsample().

    `fuels` and `costs` default to the processed files beside the network, so
    callers get the re-priced fleet without having to remember to ask. Pass
    `fuels=False` to get the network exactly as PyPSA-Eur exported it.
    """
    n = pypsa.Network(str(path))
    if fuels is False:
        return n
    processed = Path(path).parent
    if fuels is None:
        fuels = pd.read_csv(processed / "fuel_assumptions.csv", comment="#",
                            index_col="carrier")
    if costs is None:
        costs = pd.read_csv(processed / "technology_costs_full_2025.csv",
                            index_col="technology")
    reprice(n, fuels, costs)
    derate_outages(n)
    split_lossy_links(n)
    normalise_hydro(n, processed / "hydro_calibration.csv")
    return n


def normalise_hydro(n: pypsa.Network, table_path: Path) -> dict:
    """Put each country's hydro on its normal-year level: scale reservoir
    inflow so that reservoir inflow plus run-of-river over the year equals
    the normal annual production recorded in data/processed/
    hydro_calibration.csv (Norway: NVE's 137.6 TWh, reference 1991-2020).

    The shipped network normalises its 2024 runoff by a regression that
    lands about ten percent below a normal year (Appendix C), which is the
    wrong level for the 2050 reference cases of sections 7-9. Section 6,
    held against the 2024 market, scales further to that year's published
    production on top of this. Returns {country: factor}. Spill is not
    netted out here: a full reservoir spills in the solve, so output comes
    out a little below the target."""
    table = pd.read_csv(table_path, comment="#").set_index("country")
    factors = {}
    for country, row in table.iterrows():
        target = row.get("normal_production_twh")
        if pd.isna(target):
            continue
        units = [u for u in n.storage_units.index
                 if u.startswith(country) and n.storage_units.loc[u, "carrier"] == "hydro"
                 and u in n.storage_units_t.inflow.columns]
        inflow = float(n.storage_units_t.inflow[units].sum().sum()) / 1e6
        ror = n.generators.index[n.generators.bus.str.startswith(country)
                                 & (n.generators.carrier == "ror")]
        ror_twh = float(n.generators_t.p_max_pu.reindex(columns=ror).fillna(0.0)
                        .mul(n.generators.loc[ror, "p_nom"]).sum().sum()) / 1e6
        factor = (float(target) - ror_twh) / inflow
        n.storage_units_t.inflow[units] *= factor
        factors[country] = factor
    n.meta["hydro_normal_factors"] = factors
    return factors


# ---------------------------------------------------------------------------
# Time aggregation.
#
# A year has 8,760 hours and the note's LPs are solved on far fewer
# snapshots. Two ways of choosing them are implemented, and every run script
# takes `--aggregation` to pick one:
#
#   stride    keep every k-th hour and weight it by k. Cheap and unbiased for
#             anything that is an annual average, but the kept hours are k
#             hours apart, so nothing shorter than k hours -- a 2-hour
#             battery at 8-hour sampling -- can be represented, and the
#             extremes survive only if they happen to fall on a kept hour.
#   segments  cut the year into `hours` contiguous segments of varying
#             length -- short where the series move, long where they do not
#             -- and represent each by its hourly means, weighted by its
#             duration. Chronology is intact from January to December, so a
#             store of any duration sees the real sequence and a cyclic
#             seasonal store means what it says; annual energy is exact by
#             construction. What is lost is the variation *within* a
#             segment. This is what PyPSA-Eur does (its "SEG" resolutions),
#             and the same package, tsam, does the cutting here.
#
# Both leave one snapshot per row of every time series and one weight per
# snapshot, which is all the models downstream ever look at. Asked for the
# whole year (`hours` >= 8760), both leave it alone.
#
# Which to use was settled against full-year solves of the section 7 and
# section 8 reference cases (2026-09-02). At 1095 snapshots the two agree
# with the full year on section 7 to a few per cent, battery duration
# included; on section 8 only segments do -- stride at 1095 over-states the
# seasonal hydrogen store by a factor of three (20.8 against 6.3 TWh),
# because eight-hour jumps hide the intra-day flexibility that makes the
# store unnecessary. At 336 snapshots segments still reproduce the section
# 9 carbon price to 2 EUR/t where stride misses it by 85. So segments are
# the default, at 336 snapshots for exploration and 1095 for the note's
# figures; stride is kept because it is what the text of sections 2-5
# assumes and because it is the full-resolution path. A third scheme,
# typical days with an inter-day storage linkage, was built and tested and
# lost on storage; it lives in scratch/typical_days.py with its results.
AGGREGATION_SCHEMES = ("stride", "segments")


def aggregate(n: pypsa.Network, hours: int, scheme: str = "segments") -> None:
    """Reduce the network's year to `hours` snapshots, in place, by one of
    AGGREGATION_SCHEMES (see the note above). Records the scheme in
    `n.meta["aggregation"]` so a cached solve says how it was built."""
    if scheme not in AGGREGATION_SCHEMES:
        raise ValueError(
            f"unknown aggregation scheme {scheme!r}; one of {AGGREGATION_SCHEMES}")
    if hours >= len(n.snapshots):
        n.snapshot_weightings.loc[:, :] = 1.0
    elif scheme == "stride":
        subsample(n, hours)
    else:
        segment(n, hours)
    n.meta["aggregation"] = scheme


def subsample(n: pypsa.Network, hours: int) -> None:
    """Keep every k-th snapshot and weight each by k, so annual quantities
    (energy, costs, rents, reservoir inflow) keep their scale."""
    stride = max(1, len(n.snapshots) // hours)
    kept = n.snapshots[::stride][:hours]
    n.set_snapshots(kept)
    n.snapshot_weightings.loc[:, :] = float(stride)


def _time_varying(n: pypsa.Network):
    """Every non-empty time-varying frame the network carries, as a list of
    (component, attribute, frame) and as one wide frame whose columns are
    prefixed "component:attribute:" so they can be split again."""
    frames = [(c.name, attr, df) for c in n.components
              for attr, df in c.dynamic.items() if not df.empty]
    raw = pd.concat(
        [df.add_prefix(f"{component}:{attr}:") for component, attr, df in frames],
        axis=1,
    )
    return frames, raw


def _set_time_varying(n: pypsa.Network, frames, values: pd.DataFrame,
                      snapshots: pd.DatetimeIndex) -> None:
    """Replace the network's snapshots and every time-varying frame with the
    rows of `values` (columns prefixed as in _time_varying)."""
    new = {}
    for component, attr, df in frames:
        block = values[[f"{component}:{attr}:{c}" for c in df.columns]].copy()
        block.columns = df.columns
        block.index = snapshots
        new[(component, attr)] = block
    n.set_snapshots(snapshots)
    for (component, attr), block in new.items():
        n.dynamic(component)[attr] = block


def segment(n: pypsa.Network, hours: int) -> None:
    """Cut the year into `hours` contiguous segments and keep one snapshot
    per segment, carrying the segment's hourly means and weighted by its
    duration.

    Where to cut is tsam's decision (Hoffmann et al., the package behind
    PyPSA-Eur's time-series aggregation), on everything time-varying the
    network carries -- loads, availability profiles, reservoir inflow --
    each series scaled to [0, 1] so that a 60 GW German load and a per-unit
    Danish wind profile count the same. The criterion is Ward's, restricted
    to neighbours: start with every hour as its own segment and repeatedly
    merge the adjacent pair whose merger adds the least within-segment
    variance, until `hours` remain. A calm week collapses into a few long
    segments; a ramp or a spike stays its own short one.
    """
    import tsam

    frames, raw = _time_varying(n)
    result = tsam.aggregate(
        raw, n_clusters=1, period_duration=len(raw),
        segments=tsam.SegmentConfig(n_segments=hours),
    )
    labels = result.assignments["segment_idx"].to_numpy()
    durations = np.asarray(result.segment_durations[0], dtype="float64")

    starts = n.snapshots[np.flatnonzero(np.r_[True, np.diff(labels) != 0])]
    means = {}
    for component, attr, df in frames:
        m = df.groupby(labels).mean()
        m.index = starts
        means[(component, attr)] = m
    n.set_snapshots(starts)
    for (component, attr), m in means.items():
        n.dynamic(component)[attr] = m
    for column in n.snapshot_weightings.columns:
        n.snapshot_weightings[column] = durations


WIND_CARRIERS = {"onwind", "offwind-ac", "offwind-dc", "offwind-float",
                 "wind_onshore", "wind_offshore"}
SOLAR_CARRIERS = {"solar", "solar-hsat", "solar_pv"}


def _rescale_to_mean(shape, target, tol=1e-4, iterations=40):
    """Scale a per-unit shape to a target mean, respecting the [0, 1] ceiling.

    A single multiply-then-clip undershoots whenever the scaled series pokes
    above one: the clipping throws away exactly the energy the scaling was
    meant to add. For a high capacity factor that is not a rounding error --
    Danish onshore wind came out 7% below its target this way -- and capacity
    factor drives the economics directly, so it is worth the few iterations.
    """
    shape = np.asarray(shape, dtype="float64")
    target = float(np.clip(target, 0.0, 1.0))
    if shape.mean() <= 0 or target <= 0:
        return np.zeros_like(shape)
    factor = target / shape.mean()
    for _ in range(iterations):
        scaled = np.clip(shape * factor, 0.0, 1.0)
        mean = scaled.mean()
        if mean <= 0 or abs(mean - target) < tol:
            break
        factor *= target / mean
    return np.clip(shape * factor, 0.0, 1.0)


def apply_weather(n: pypsa.Network, weather: pd.DataFrame) -> None:
    """Re-run the network on another weather year, in every zone at once.

    `weather` is one year of data/processed/weather_zones_{year}.csv: a
    per-unit wind and solar series for each of the twelve bidding zones,
    derived from a single consistent ERA5 year (see data/prepare.py). That
    consistency is the whole point. The earlier version of this function
    swapped the Danish zones only and left the neighbours on the network's
    2013 weather, which paired a becalmed Denmark with an unrelated German
    year and so made imports available in Danish scarcity hours far more
    often than the atmosphere allows.

    Levels come from the network, shapes from the weather file. Each
    generator's swapped profile is rescaled to preserve the mean of the
    profile it already carried, so the capacity factors stay the carefully
    derived ones (atlite, with power curves and land-use weighting) and only
    the timing — and the correlation across zones — comes from here. A crude
    power curve on a single point per zone is a fine way to get a calm week
    in the right place; it is not a way to get a capacity factor right.

    Loads are left alone: this is a sweep over renewable weather, holding
    demand, costs and the network fixed. Danish demand really is
    weather-correlated, and not swapping it is a limitation the note states.
    """
    if n.meta.get("aggregation") == "segments":
        raise ValueError(
            "apply_weather() must run before segment(): the weather file is "
            "hourly and the segments are cut on the year it describes")

    def align(values):
        stride = max(1, len(values) // len(n.snapshots))
        return values[::stride][: len(n.snapshots)]

    for g, row in n.generators.iterrows():
        if row.carrier in WIND_CARRIERS:
            column = f"{row.bus}_wind_pu"
        elif row.carrier in SOLAR_CARRIERS:
            column = f"{row.bus}_solar_pu"
        else:
            continue
        if column not in weather.columns:
            continue

        shape = align(weather[column].to_numpy())
        if shape.mean() <= 0:
            continue
        # Preserve the capacity factor the network already carries.
        if g in n.generators_t.p_max_pu.columns:
            target = float(n.generators_t.p_max_pu[g].mean())
        else:
            target = float(row.p_max_pu)
        n.generators_t.p_max_pu[g] = _rescale_to_mean(shape, target)


def solve(n: pypsa.Network) -> None:
    status, condition = n.optimize(
        solver_name=SOLVER, progress=False,
        transmission_losses=TRANSMISSION_LOSSES_SEGMENTS,
        solver_options=solver_options(),
    )
    if status != "ok":
        raise RuntimeError(f"network LP did not solve: {status} / {condition}")


def expand_to_hours(n: pypsa.Network, frame: pd.DataFrame) -> pd.DataFrame:
    """A snapshot-indexed frame repeated into one row per hour of the year,
    each snapshot's row standing for as many hours as its weight. Under
    stride sampling every row is repeated k times; under segments a long
    calm-week segment is repeated for its whole length and a short volatile
    one only briefly -- which is what makes an unweighted duration curve or
    mean of segment values wrong, and this one right. The index is a plain
    hour count."""
    weights = n.snapshot_weightings.objective.reindex(frame.index)
    counts = weights.round().astype(int).clip(lower=1).to_numpy()
    out = frame.loc[frame.index.repeat(counts)].reset_index(drop=True)
    out.index.name = "hour"
    return out


def apply_carbon_price(n: pypsa.Network, tau: float) -> None:
    """Charge every generator tau EUR per tonne of CO2, in place: marginal
    cost gains tau times the generator's emission rate — eq:dispatch:mc with
    the carbon term, applied to the real fleet. Call after load_network()
    so the rates reflect the note's fuel accounting."""
    n.generators["marginal_cost"] = (
        n.generators["marginal_cost"] + tau * emission_rates(n)
    )


def emission_rates(n: pypsa.Network) -> pd.Series:
    """Per-generator CO2 in t/MWh electric: the carrier's fuel emission
    factor over the generator's efficiency — eq:dispatch:emissionrate on
    the real fleet."""
    co2 = n.carriers.co2_emissions.reindex(n.generators.carrier).to_numpy()
    return pd.Series(co2 / n.generators.efficiency.to_numpy(),
                     index=n.generators.index).fillna(0.0)


def congestion_rent(n: pypsa.Network) -> pd.DataFrame:
    """Per interzonal corridor (parallel AC circuits and DC cables between
    the same zone pair aggregated): annual congestion rent (EUR), the share
    of hours the corridor is at its limit, and its capacity."""
    price = n.buses_t.marginal_price
    weights = n.snapshot_weightings.objective

    branches = []
    for df, flows, nom, derate in [
        (n.lines, n.lines_t.p0, "s_nom", n.lines.s_max_pu),
        (n.links, n.links_t.p0, "p_nom", pd.Series(1.0, index=n.links.index)),
    ]:
        for name, row in df.iterrows():
            branches.append(
                {
                    "corridor": "–".join(sorted([row.bus0, row.bus1])),
                    # The lossy-link split leaves each DC direction its own
                    # branch, so parallel branches are aggregated per
                    # DIRECTION: a corridor is at its limit when all the
                    # branches of one direction are, and its capacity is
                    # one direction's, not the two summed.
                    "direction": (row.bus0, row.bus1),
                    "flow": flows[name],
                    "spread": price[row.bus1] - price[row.bus0],
                    "cap": float(row[nom] * derate[name]),
                }
            )

    rows = {}
    for b in branches:
        entry = rows.setdefault(
            b["corridor"], {"rent_eur": 0.0, "_directions": {}}
        )
        entry["rent_eur"] += float((b["flow"] * b["spread"] * weights).sum())
        d = entry["_directions"].setdefault(
            b["direction"], {"cap_mw": 0.0, "at_limit": None}
        )
        d["cap_mw"] += b["cap"]
        at_limit = b["flow"].abs() >= 0.999 * b["cap"]
        d["at_limit"] = (
            at_limit if d["at_limit"] is None else d["at_limit"] & at_limit
        )

    out = {}
    for corridor, entry in rows.items():
        directions = entry["_directions"].values()
        congested = None
        for d in directions:
            congested = (
                d["at_limit"] if congested is None else congested | d["at_limit"]
            )
        out[corridor] = {
            "rent_eur": entry["rent_eur"],
            "cap_mw": max(d["cap_mw"] for d in directions),
            # Share of HOURS, not of snapshots: weighted by snapshot length.
            "congested_share": float(
                (congested.astype(float) * weights).sum() / weights.sum()),
        }
    return pd.DataFrame(out).T.astype(
        {"rent_eur": float, "cap_mw": float, "congested_share": float}
    )
