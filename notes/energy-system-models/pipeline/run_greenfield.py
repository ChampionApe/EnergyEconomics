"""Solve the section 7 capacity expansion instances and write everything
the section's figures need into results/.

    python pipeline/run_greenfield.py                fast default (336 segments)
    python pipeline/run_greenfield.py --hours 1095   the note's figures
    python pipeline/run_greenfield.py --aggregation stride
                                                     every k-th hour instead of
                                                     chronological segments
                                                     (see model/network.py)

Experiments (all on the 12-bidding-zone network with the Danish fleets
replaced by extendable candidates and the neighbours free to add to theirs
-- see model/greenfield.py). Every case runs on the zonal weather archive's
REFERENCE_WEATHER_YEAR, the same construction the uncertainty section sweeps
over, so that its reference column is this section's reference case:

    screening   fixed and marginal costs of the candidates (no solve)
    tax         a common carbon price on every zone, swept from zero to
                beyond the fuel-switching point: what Denmark builds as the
                price rises, and the emissions that fall out
    scenarios   reference / autarky / expensive gas / cheap capital at the
                reference price, plus "Danish budget": no common price, a
                territorial CO2 budget on Danish generation alone -- the
                instrument section 2 called a cap, in an open economy
    recovery    Result 6 in numbers, zone by zone, the LCOE-against-capture
                table, the peakers' earnings by price band and the system
                through its longest scarcity spell, all at the reference
                case
    check       the small table against technology-data -> results/costs_check.csv

Solved networks are cached in results/cache/ keyed by experiment, instance
size and aggregation scheme, and fingerprinted against their inputs.

--resolution-check solves the reference case at all 8760 hours and records
how far the aggregated battery build and Danish bill sit from the full-year
ones.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import dispatch, greenfield, network
from run_dispatch import PROCESSED

RESULTS = NOTE / "results"
CACHE = RESULTS / "cache"
NETWORK_NC = PROCESSED / "network_eur_bz_2024.nc"

# The common carbon price, EUR/t, swept over every zone. The grid brackets
# the fuel-switching point of the Danish peakers -- (c_bio - c_gas)/e, about
# 223 EUR/t at the forward fuel prices -- so the sweep shows the plateau
# from the tax side: emissions fall in steps as each margin is exhausted,
# and the peakers switch fuel where the price crosses the switching cost.
TAX_POINTS = [0.0, 50.0, greenfield.ETS_PRICE, 150.0, 200.0, 250.0, 300.0]
REFERENCE_TAX = greenfield.ETS_PRICE   # the ETS-level case the rest of the note reads

# The territorial scenario: a Danish CO2 budget at this share of Denmark's
# emissions under no carbon price at all, with the neighbours unpriced.
DK_BUDGET_FRACTION = 0.10

# The weather every case is solved on: one year of the zonal archive
# (data/processed/weather_zones_{year}.csv, all twelve zones on one ERA5
# year, shapes from the archive and levels from the network -- see
# model/network.py:apply_weather). Sections 7-9 all solve on this
# construction; section 6 keeps the network's own profiles because it is
# validated against the 2024 market.
REFERENCE_WEATHER_YEAR = 2024

# Small-table technology -> technology-data technology, for costs_check().
CHECK_MAP = {
    "ccgt": "CCGT",
    "ocgt": "OCGT",
    "wind_onshore": "onwind",
    "wind_offshore": "offwind",
    "solar_pv": "solar-utility",
    "wood_chips_chp": "central solid biomass CHP",
}


def year_weather(year: int) -> pd.DataFrame:
    """One year of zonal availability — all twelve zones, one ERA5 year."""
    path = PROCESSED / f"weather_zones_{year}.csv"
    if not path.exists():
        raise SystemExit(
            f"missing {path.name} — run `python data/prepare.py` to build the "
            f"zonal weather archive sections 7-9 solve on"
        )
    return pd.read_csv(path, index_col="time", parse_dates=True)


def load_shared():
    return pd.read_csv(
        PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}.csv", index_col="technology"
    )


def tax_tag(tau: float) -> str:
    return f"tax{tau:g}"


def cache_name(experiment: str, tag: str, hours: int, aggregation: str) -> str:
    """The cache file for one solve. The aggregation scheme is part of the
    name: which snapshots the year was reduced to is an input like any
    other, and two schemes at the same `hours` must never share a solve.
    Stride sampling keeps the historical bare name."""
    suffix = "" if aggregation == "stride" else f"_{aggregation}"
    return f"{experiment}_{tag}_{hours}{suffix}.nc"


def fingerprint_bytes(path: Path) -> bytes:
    """What the cache fingerprint hashes for one input file.

    Text is hashed with its line endings normalised. Git rewrites them on
    checkout (CRLF on Windows, LF elsewhere), and data/prepare.py on Windows
    writes an LF comment header over CRLF rows, so the same content can
    arrive as different bytes; a change of line endings is not a change of
    input. The network (.nc) is binary and is hashed as it is.
    """
    if not path.exists():
        return b"<missing>"
    data = path.read_bytes()
    return data if path.suffix == ".nc" else data.replace(b"\r\n", b"\n")


def input_fingerprint(costs_full=None, aggregation: str = "segments",
                      weather=None) -> str:
    """A short hash of everything a cached solve depends on.

    The cache is keyed by tag and instance size alone, which says nothing
    about the *inputs*. So every file the model reads, the model's own
    source, the constants not read from any file, the cost table the case
    is solved on and the weather it is solved on are hashed, and the print
    is stored with the solve. A stale solve is re-solved, never trusted.
    Files are read through fingerprint_bytes(), so line endings do not count.
    """
    h = hashlib.sha256()
    for path in [PROCESSED / f"fuel_assumptions_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / f"demand_zones_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / "offshore_cost_premium.csv",
                 PROCESSED / "biomethane_potential.csv",
                 PROCESSED / "potentials_zones.csv",
                 PROCESSED / "hydro_calibration.csv",
                 NETWORK_NC]:
        h.update(fingerprint_bytes(path))
    if weather is not None:
        h.update(pd.util.hash_pandas_object(
            weather, index=True).to_numpy().tobytes())
    # Changing how a case is BUILT must invalidate the cases already
    # solved. Only the modules this section builds from are hashed.
    for module in ["greenfield.py", "network.py"]:
        h.update(fingerprint_bytes(NOTE / "model" / module))
    h.update(repr([
        greenfield.DISCOUNT_RATE, greenfield.GAS_PRICE,
        greenfield.GAS_CO2_T_PER_MWH_TH, greenfield.BATTERY_MENU_HOURS,
        greenfield.FORWARD_HORIZON, sorted(greenfield.CANDIDATES.items()),
        sorted(greenfield.CANDIDATE_FUEL.items()),
        greenfield.DK_DEMAND_BLOCKS, greenfield.VOLL_EUR_MWH,
        sorted(network.RAMP_LIMIT_PER_HOUR.items()), "ramps-hourly-unscaled",
        sorted(network.OUTAGE_DERATE.items()),
        network.HVDC_LOSS, network.TRANSMISSION_LOSSES_SEGMENTS,
        aggregation, "neighbours-extendable", "blocks-in-every-zone",
        greenfield.ETS_PRICE,
    ]).encode())
    if costs_full is not None:
        h.update(pd.util.hash_pandas_object(
            costs_full, index=True).to_numpy().tobytes())
    return h.hexdigest()[:16]


def solve_case(tag, costs_full, hours, weather=None, aggregation="segments",
               **kwargs):
    """Build and solve one case, or load it from results/cache/. `weather`
    is the weather year the case is solved on and defaults to
    REFERENCE_WEATHER_YEAR; the uncertainty section's sweep passes the
    others. `kwargs` go to greenfield.build: `ets_price` (the common carbon
    price), `co2_budget`, `autarky`, `gas_price`, `r`.
    """
    import pypsa

    if weather is None:
        weather = year_weather(REFERENCE_WEATHER_YEAR)
    fingerprint = input_fingerprint(costs_full, aggregation, weather)
    cache_file = CACHE / cache_name("greenfield", tag, hours, aggregation)
    # The case's own settings -- price, budget, autarky, gas price, discount
    # rate -- are stored with the solve and compared on load, so that two
    # cases sharing a tag but not a question can never be served from each
    # other's cache. (The tag alone once let a budget scenario stand in for
    # a price scenario with identical inputs.)
    settings = repr(sorted((k, v) for k, v in kwargs.items()))
    if cache_file.exists():
        n = pypsa.Network(str(cache_file))
        stored = n.meta.get("input_fingerprint")
        stored_settings = n.meta.get("case_settings", settings)
        if stored == fingerprint and stored_settings == settings:
            n._emission_rates = greenfield.candidate_costs(costs_full)["emission_rate"]
            return n, n.meta.get("co2_price")
        print(f"  cache {cache_file.name}: inputs changed "
              f"({stored} -> {fingerprint}) -- re-solving")

    n = greenfield.build(NETWORK_NC, costs_full, hours, weather=weather,
                         aggregation=aggregation, **kwargs)
    sigma = greenfield.solve(n)
    n.meta["co2_price"] = sigma
    n.meta["carbon_tax"] = kwargs.get("ets_price", greenfield.ETS_PRICE)
    n.meta["input_fingerprint"] = fingerprint
    n.meta["case_settings"] = settings
    CACHE.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(cache_file)
    return n, sigma


def dk_trade_revenue(n) -> float:
    """What Denmark earns selling across its borders, at its own zonal
    prices (negative when Denmark is a net importer).

    Sign convention: for any branch PyPSA reports `p0` as the power withdrawn
    from `bus0` and `p1` as the power withdrawn from `bus1`, so summing
    whichever end touches a Danish zone gives net export from that zone,
    losses already accounted for. Only branches to FOREIGN buses count; the
    Great Belt is internal trade. Under autarky no such branch exists and
    this is zero by construction.
    """
    w = n.snapshot_weightings.objective
    revenue = 0.0
    for component, flows in (("Line", n.lines_t), ("Link", n.links_t)):
        df = n.df(component)
        if df.empty or "p0" not in flows:
            continue
        for zone in greenfield.DK_ZONES:
            if zone not in n.buses_t.marginal_price.columns:
                continue
            price = n.buses_t.marginal_price[zone]
            out = df.index[(df.bus0 == zone)
                           & (~df.bus1.isin(greenfield.DK_ZONES))]
            into = df.index[(df.bus1 == zone)
                            & (~df.bus0.isin(greenfield.DK_ZONES))]
            net = pd.Series(0.0, index=n.snapshots)
            if len(out):
                net = net.add(flows.p0[out].sum(axis=1), fill_value=0.0)
            if len(into):
                net = net.add(flows.p1[into].sum(axis=1), fill_value=0.0)
            revenue += float(net.mul(price).mul(w).sum())
    return revenue


def mix_row(n, sigma, tau=None):
    """One row of results: what Denmark built, what it cost, what it
    emitted, at a common carbon price `tau` (and, for the budget scenario,
    the budget's dual `sigma`)."""
    caps = greenfield.dk_capacity(n)
    caps["battery"] = sum(
        mw for tech, mw in caps.items() if tech.startswith("battery_")
    )
    # Firm insurance capacity as one number: the fossil and biogenic peakers
    # are the same machine on different fuel.
    caps["peaker"] = caps.get("ocgt", 0.0) + caps.get("ocgt_biogas", 0.0)
    shed = greenfield.shed_energy(n)
    w = n.snapshot_weightings.objective
    dk_load = float(
        n.loads_t.p_set[[z for z in ("DK1", "DK2")
                         if z in n.loads_t.p_set.columns]].sum(axis=1).mul(w).sum()
    )
    breakdown = cost_breakdown(n)
    dk_cost = float(breakdown[["capex_eur", "opex_eur"]].sum().sum())
    trade_revenue = dk_trade_revenue(n)
    return {
        "carbon_price": tau if tau is not None else n.meta.get("carbon_tax"),
        "co2_price": sigma if sigma is not None else float("nan"),
        "system_cost": float(n.objective),
        # The Danish bill: annualised capital plus operating cost of the
        # candidates this section actually chooses. `system_cost` is the
        # solver's objective over all twelve zones.
        "dk_system_cost": dk_cost,
        "dk_trade_revenue": trade_revenue,
        "dk_net_cost": dk_cost - trade_revenue,
        "dk_load_mwh": dk_load,
        "emissions_t": greenfield.dk_emissions(n),
        # Whole-system emissions across all 12 zones.
        "emissions_total_t": greenfield.total_emissions(n),
        "avg_price_dk1": float(
            (n.buses_t.marginal_price["DK1"] * w).sum() / w.sum()),
        **{f"cap_{tech}_mw": mw for tech, mw in caps.items()},
        **{f"shed_{c.removeprefix('shed_')}_mwh": mwh for c, mwh in shed.items()},
    }


def dk_generation(n) -> dict:
    """Annual Danish generation by candidate, MWh, plus net imports."""
    w = n.snapshot_weightings.objective
    out = {}
    for g, row in n.generators.iterrows():
        if row.bus in greenfield.DK_ZONES and row.p_nom_extendable:
            out[row.carrier] = out.get(row.carrier, 0.0) + float(
                (n.generators_t.p[g] * w).sum())
    return out


def run_tax_sweep(costs_full, hours, aggregation):
    rows = []
    for tau in TAX_POINTS:
        n, _ = solve_case(tax_tag(tau), costs_full, hours,
                          aggregation=aggregation, ets_price=tau)
        row = mix_row(n, None, tau)
        row |= {f"gen_{tech}_mwh": mwh for tech, mwh in dk_generation(n).items()}
        rows.append(row)
        print(f"  tau {tau:.0f}: DK emissions {row['emissions_t'] / 1e6:.2f} Mt, "
              f"system {row['emissions_total_t'] / 1e6:.1f} Mt, "
              f"peaker {row['cap_ocgt_mw'] / 1e3:.1f} GW gas + "
              f"{row['cap_ocgt_biogas_mw'] / 1e3:.1f} GW biogas")
    return pd.DataFrame(rows)


def cost_breakdown(n):
    """Annual capital and operating cost per Danish technology — what the
    system's bill is made of."""
    w = n.snapshot_weightings.objective
    rows = {}
    for g, row in n.generators.iterrows():
        if row.bus not in ("DK1", "DK2") or not row.p_nom_extendable:
            continue
        tech = row.carrier
        entry = rows.setdefault(tech, {"capex_eur": 0.0, "opex_eur": 0.0})
        entry["capex_eur"] += float(row.capital_cost * row.p_nom_opt)
        entry["opex_eur"] += float(
            (n.generators_t.p[g] * w).sum() * row.marginal_cost
        )
    for s, row in n.storage_units.iterrows():
        if row.bus in ("DK1", "DK2") and row.p_nom_extendable:
            entry = rows.setdefault("battery", {"capex_eur": 0.0, "opex_eur": 0.0})
            entry["capex_eur"] += float(row.capital_cost * row.p_nom_opt)
    return pd.DataFrame(rows).T


def realised_duty(n):
    """Where each built technology actually landed on the screening
    picture: full-load hours, energy divided by installed capacity."""
    w = n.snapshot_weightings.objective
    rows = {}
    for g, row in n.generators.iterrows():
        if row.bus not in ("DK1", "DK2") or not row.p_nom_extendable:
            continue
        entry = rows.setdefault(row.carrier, {"capacity_mw": 0.0, "energy_mwh": 0.0})
        entry["capacity_mw"] += float(row.p_nom_opt)
        entry["energy_mwh"] += float((n.generators_t.p[g] * w).sum())
    df = pd.DataFrame(rows).T
    df["full_load_hours"] = (df["energy_mwh"] / df["capacity_mw"]).where(
        df["capacity_mw"] > 1.0
    )
    df["capacity_factor"] = df["full_load_hours"] / 8760.0
    return df


def storage_rent(price, w_objective, w_stores, hours, eta_store, eta_dispatch,
                 marginal_cost) -> float:
    """What one MW of a store would earn in a year as a price-taker on the
    solved prices, EUR: the margin of its best charging and discharging
    plan under the model's own storage constraints (the state of charge
    moves by the snapshot's length in hours, the energy rating is `hours`
    per MW, the year is cyclic). This is the store's envelope value. For a
    store the model built it equals the realised margin per MW; for one it
    did not build it is the only measure there is, since an unbuilt store
    never runs and its realised margin is zero by construction."""
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    lam = np.asarray(price, dtype=float)
    w = np.asarray(w_objective, dtype=float)
    ws = np.asarray(w_stores, dtype=float)
    S = len(lam)
    s = np.arange(S)
    # Variables: charging c_s, discharging d_s, state of charge e_s. Minimise
    # minus the margin: charging costs the price, discharging earns it less
    # the marginal cost.
    objective = np.concatenate([w * lam, w * (marginal_cost - lam), np.zeros(S)])
    # e_s - e_{s-1} - ws_s (eta_store c_s - d_s / eta_dispatch) = 0, with
    # e_{-1} = e_{S-1}: the year ends where it began.
    balance = coo_matrix(
        (np.concatenate([np.ones(S), -np.ones(S), -ws * eta_store, ws / eta_dispatch]),
         (np.concatenate([s, s, s, s]),
          np.concatenate([2 * S + s, 2 * S + (s - 1) % S, s, S + s]))),
        shape=(S, 3 * S)).tocsr()
    bounds = [(0.0, 1.0)] * (2 * S) + [(0.0, hours)] * S
    res = linprog(objective, A_eq=balance, b_eq=np.zeros(S), bounds=bounds,
                  method="highs")
    if res.status != 0:
        raise RuntimeError(f"storage valuation did not solve: {res.message}")
    return -float(res.fun)


def cost_recovery(n):
    """Result 6 (long-run zero profit) in numbers, per Danish candidate and
    zone.

    What one MW of a technology would earn in the price system of the solved
    case: for a generator the availability-weighted sum of its hourly
    scarcity rents, sum_h gamma * max(lambda - c, 0), with c the effective
    marginal cost (fuel plus the carbon price, plus the budget's dual where
    there is one); for a store the margin of its best operation at the same
    prices (storage_rent). Both are envelope quantities and exist for
    unbuilt candidates too. Zero profit says the rent equals the annualised
    fixed cost wherever a technology is built below its potential cap,
    exceeds it by the land rent at the cap, and falls short where the model
    declined to build. The condition holds zone by zone, so it is tested
    zone by zone: a technology can be interior in one zone and at its cap
    in the other, and an average over the two would mix the regimes.
    """
    w = n.snapshot_weightings.objective
    sigma = float(n.meta.get("co2_price") or 0.0)
    rates = getattr(n, "_emission_rates", pd.Series(dtype=float))
    rows = []
    for g, row in n.generators.iterrows():
        if row.bus not in greenfield.DK_ZONES or not row.p_nom_extendable:
            continue
        price = n.buses_t.marginal_price[row.bus]
        if g in n.generators_t.p_max_pu.columns:
            gamma = n.generators_t.p_max_pu[g]
        else:
            gamma = pd.Series(float(row.p_max_pu), index=n.snapshots)
        carbon = sigma * float(rates.get(row.carrier, 0.0))
        margin = (price - row.marginal_cost - carbon).clip(lower=0.0)
        rows.append({
            "tech": row.carrier, "zone": row.bus,
            "capacity_mw": float(row.p_nom_opt),
            "p_nom_max_mw": float(min(row.p_nom_max, 1e9)),
            "fixed_eur_mw_yr": float(row.capital_cost),
            "rent_eur_mw_yr": float((gamma * margin * w).sum()),
        })
    for s, row in n.storage_units.iterrows():
        if row.bus not in greenfield.DK_ZONES or not row.p_nom_extendable:
            continue
        rows.append({
            "tech": row.carrier, "zone": row.bus,
            "capacity_mw": float(row.p_nom_opt),
            "p_nom_max_mw": float(min(row.p_nom_max, 1e9)),
            "fixed_eur_mw_yr": float(row.capital_cost),
            "rent_eur_mw_yr": storage_rent(
                n.buses_t.marginal_price[row.bus], w,
                n.snapshot_weightings.stores, float(row.max_hours),
                float(row.efficiency_store), float(row.efficiency_dispatch),
                float(row.marginal_cost)),
        })
    df = pd.DataFrame(rows)
    df["built"] = df["capacity_mw"] > 1.0
    df["at_cap"] = df["built"] & (df["capacity_mw"] >= 0.999 * df["p_nom_max_mw"])
    df["rent_over_fixed"] = df["rent_eur_mw_yr"] / df["fixed_eur_mw_yr"]
    return df[["tech", "zone", "capacity_mw", "p_nom_max_mw", "built", "at_cap",
               "fixed_eur_mw_yr", "rent_eur_mw_yr", "rent_over_fixed"]]


def value_table(n, tau):
    """Levelised cost against capture price, per built Danish technology:
    the section 3 statistics evaluated at the section 7 optimum, where zero
    profit makes LCOE (carbon included) and capture price coincide for
    every technology built below its cap. `tau` is the common carbon
    price, already inside each generator's marginal cost; it is split out
    so the table can show LCOE with and without it."""
    w = n.snapshot_weightings.objective
    dk = [z for z in greenfield.DK_ZONES if z in n.loads_t.p_set.columns]
    load = n.loads_t.p_set[dk]
    price = n.buses_t.marginal_price[dk]
    base_price = float((price * load).mul(w, axis=0).sum().sum()
                       / load.mul(w, axis=0).sum().sum())
    rates = getattr(n, "_emission_rates", pd.Series(dtype=float))
    rows = {}
    for g, row in n.generators.iterrows():
        if row.bus not in greenfield.DK_ZONES or not row.p_nom_extendable:
            continue
        p = n.generators_t.p[g]
        carbon_per_mwh = tau * float(rates.get(row.carrier, 0.0))
        e = rows.setdefault(row.carrier, {
            "capacity_mw": 0.0, "energy_mwh": 0.0, "revenue_eur": 0.0,
            "fixed_eur": 0.0, "opex_eur": 0.0, "carbon_eur": 0.0,
            "marginal_cost": float(row.marginal_cost) - carbon_per_mwh})
        energy = float((p * w).sum())
        e["capacity_mw"] += float(row.p_nom_opt)
        e["energy_mwh"] += energy
        e["revenue_eur"] += float((p * n.buses_t.marginal_price[row.bus] * w).sum())
        e["fixed_eur"] += float(row.capital_cost * row.p_nom_opt)
        e["opex_eur"] += energy * (float(row.marginal_cost) - carbon_per_mwh)
        e["carbon_eur"] += energy * carbon_per_mwh
    df = pd.DataFrame(rows).T
    df = df[df["capacity_mw"] > 1.0].copy()
    df["full_load_hours"] = df["energy_mwh"] / df["capacity_mw"]
    df["lcoe_eur_mwh"] = (df["fixed_eur"] + df["opex_eur"]) / df["energy_mwh"]
    df["carbon_cost_eur_mwh"] = df["carbon_eur"] / df["energy_mwh"]
    df["capture_price_eur_mwh"] = df["revenue_eur"] / df["energy_mwh"]
    df["value_factor"] = df["capture_price_eur_mwh"] / base_price
    df["base_price_eur_mwh"] = base_price
    return df


# The price bands the peakers' earnings are counted in, EUR/MWh, above the
# two edges the economics supplies: the peakers' running cost, below which
# they earn nothing, and the flexible demand block's willingness to pay.
PEAKER_PRICE_BANDS = [200.0, 1000.0]


def scarcity_spells(price, hours, threshold) -> pd.DataFrame:
    """The runs of consecutive snapshots in which `price` is at or above
    `threshold`: the snapshot each run starts at, and its length in hours
    (`hours` is each snapshot's length, its objective weight)."""
    rows, start, run = [], None, 0.0
    for t, high, h in zip(price.index, (price >= threshold - 1e-6).to_numpy(),
                          hours.reindex(price.index).to_numpy()):
        if high:
            if start is None:
                start = t
            run += float(h)
        elif start is not None:
            rows.append((start, run))
            start, run = None, 0.0
    if start is not None:
        rows.append((start, run))
    return pd.DataFrame(rows, columns=["start", "hours"])


def scarcity_profile(n):
    """How the peakers get paid, in the zone where they stand.

    The hours of the year are sorted into price bands: below the peakers'
    running cost (carbon included), up to the flexible block's willingness
    to pay, then PEAKER_PRICE_BANDS. For each band the share of the year's
    hours is set against the share of the peaking fleet's annual operating
    margin earned in it. Each peaker's margin is counted at its own zone's
    price; the hours are those of the zone with the most peaking capacity.
    Returns the band table and a few summary numbers."""
    peakers = [g for g, row in n.generators.iterrows()
               if row.bus in greenfield.DK_ZONES
               and row.carrier in ("ocgt", "ocgt_biogas") and row.p_nom_opt > 1.0]
    prices = network.expand_to_hours(
        n, n.buses_t.marginal_price[list(greenfield.DK_ZONES)])
    blocks = {c: wtp for c, _, wtp in greenfield.DK_DEMAND_BLOCKS}
    summary = {"dk_max_price": float(prices.max().max()),
               "peaker_capacity_mw": float(n.generators.loc[peakers, "p_nom_opt"].sum())}
    if not peakers:
        return pd.DataFrame(), summary

    capacity = n.generators.loc[peakers].groupby("bus")["p_nom_opt"].sum()
    zone = str(capacity.idxmax())
    running = float(n.generators.loc[peakers, "marginal_cost"].min())
    edges = sorted({running, blocks["shed_flex"], *PEAKER_PRICE_BANDS})
    bins = [-np.inf, *edges, np.inf]
    margin = network.expand_to_hours(n, pd.DataFrame({
        g: (n.buses_t.marginal_price[n.generators.at[g, "bus"]]
            - n.generators.at[g, "marginal_cost"]) * n.generators_t.p[g]
        for g in peakers}))
    band_margin = pd.Series(0.0, index=range(len(bins) - 1))
    for g in peakers:
        band = pd.cut(prices[n.generators.at[g, "bus"]], bins, right=False, labels=False)
        band_margin = band_margin.add(margin[g].groupby(band).sum(), fill_value=0.0)
    band_hours = pd.cut(prices[zone], bins, right=False, labels=False).value_counts()
    bands = pd.DataFrame({
        "lower_eur_mwh": bins[:-1], "upper_eur_mwh": bins[1:],
        "hours": band_hours.reindex(range(len(bins) - 1), fill_value=0).to_numpy(),
    })
    bands["hours_share"] = bands["hours"] / bands["hours"].sum()
    bands["margin_share"] = (band_margin / band_margin.sum()).to_numpy()

    hourly = margin.sum(axis=1).sort_values(ascending=False).reset_index(drop=True)
    cum_share = hourly.cumsum() / hourly.sum()
    # The scarce hours come in spells, not one at a time: runs of
    # consecutive snapshots with the price at or above the flexible block's
    # willingness to pay, in hours, set against the longest battery on the
    # menu -- the reason the system holds turbines beside its batteries.
    spells = scarcity_spells(n.buses_t.marginal_price[zone],
                             n.snapshot_weightings.objective, blocks["shed_flex"])["hours"]
    longest_battery = max(greenfield.BATTERY_MENU_HOURS)
    summary |= {
        "scarcity_spells": int(len(spells)),
        "scarcity_spell_shortest_hours": float(spells.min()) if len(spells) else 0.0,
        "scarcity_spell_median_hours": float(spells.median()) if len(spells) else 0.0,
        "scarcity_spell_longest_hours": float(spells.max()) if len(spells) else 0.0,
        "scarcity_hours_in_spells_beyond_battery_share": (
            float(spells[spells > longest_battery].sum() / spells.sum())
            if len(spells) else 0.0),
    }
    summary |= {
        "peaker_zone": zone,
        "peaker_running_cost": running,
        "peaker_margin_total_eur": float(hourly.sum()),
        "share_in_top_100_hours": float(cum_share.iloc[99]),
        "share_in_top_500_hours": float(cum_share.iloc[499]),
        "hours_price_above_flex_block": int((prices[zone] >= blocks["shed_flex"] - 1e-6).sum()),
        "hours_price_above_industry_block": int((prices[zone] >= blocks["shed_industry"] - 1e-6).sum()),
        "hours_price_at_voll": int((prices[zone] >= greenfield.VOLL_EUR_MWH - 1e-6).sum()),
        "max_price_peaker_zone": float(prices[zone].max()),
    }
    return bands, summary


def dk_net_export(n) -> pd.Series:
    """Net export from Denmark per snapshot, MW: the power leaving the two
    Danish zones on every branch that crosses the border, with the sign
    convention of dk_trade_revenue (negative when Denmark imports)."""
    net = pd.Series(0.0, index=n.snapshots)
    for component, flows in (("Line", n.lines_t), ("Link", n.links_t)):
        df = n.df(component)
        if df.empty or "p0" not in flows:
            continue
        for zone in greenfield.DK_ZONES:
            out = df.index[(df.bus0 == zone) & (~df.bus1.isin(greenfield.DK_ZONES))]
            into = df.index[(df.bus1 == zone) & (~df.bus0.isin(greenfield.DK_ZONES))]
            if len(out):
                net = net.add(flows.p0[out].sum(axis=1), fill_value=0.0)
            if len(into):
                net = net.add(flows.p1[into].sum(axis=1), fill_value=0.0)
    return net


# The spell figure shows the reference system through its longest scarcity
# spell, with this many days either side of it.
SPELL_WINDOW_DAYS = 5


def spell_window(n, zone):
    """The reference system through its longest scarcity spell in `zone`
    (the price at or above the flexible block's willingness to pay), for
    the figure that shows what covers it. Per snapshot of the window: the
    price, Danish load, the wind and solar the weather offers, the
    batteries' state of charge and output, the turbines' output, the net
    imports and the flexible demand shed. One row per snapshot; `hours` is
    how many hours it stands for."""
    w = n.snapshot_weightings.objective
    blocks = {c: wtp for c, _, wtp in greenfield.DK_DEMAND_BLOCKS}
    price = n.buses_t.marginal_price[zone]
    spells = scarcity_spells(price, w, blocks["shed_flex"])
    if spells.empty:
        return pd.DataFrame()
    longest = spells.loc[spells["hours"].idxmax()]
    days = pd.Timedelta(days=SPELL_WINDOW_DAYS)
    end = longest["start"] + pd.Timedelta(hours=float(longest["hours"])) + days
    snaps = n.snapshots[(n.snapshots >= longest["start"] - days) & (n.snapshots < end)]
    g = n.generators
    danish = g.bus.isin(greenfield.DK_ZONES)
    candidates = danish & g.p_nom_extendable
    turbines = ["ocgt", "ocgt_biogas", "ccgt"]

    def output(rows):
        return n.generators_t.p.loc[snaps, rows].sum(axis=1)

    def available(carriers):
        rows = [r for r in g.index[candidates & g.carrier.isin(carriers)]
                if r in n.generators_t.p_max_pu.columns]
        return (n.generators_t.p_max_pu.loc[snaps, rows]
                .mul(g.loc[rows, "p_nom_opt"], axis=1).sum(axis=1))

    stores = n.storage_units.index[n.storage_units.bus.isin(greenfield.DK_ZONES)]
    loads = [z for z in greenfield.DK_ZONES if z in n.loads_t.p_set.columns]
    out = pd.DataFrame({
        "hours": w.loc[snaps],
        "price_eur_mwh": price.loc[snaps],
        "load_mw": n.loads_t.p_set.loc[snaps, loads].sum(axis=1),
        "wind_available_mw": available(["wind_onshore", "wind_offshore"]),
        "solar_available_mw": available(["solar_pv"]),
        "battery_mw": n.storage_units_t.p.loc[snaps, stores].sum(axis=1),
        "battery_soc_mwh": n.storage_units_t.state_of_charge.loc[snaps, stores].sum(axis=1),
        "turbine_mw": output(g.index[candidates & g.carrier.isin(turbines)]),
        "net_import_mw": -dk_net_export(n).loc[snaps],
        "flex_shed_mw": output(g.index[danish & (g.carrier == "shed_flex")]),
    })
    out["battery_energy_mwh"] = float(
        (n.storage_units.loc[stores, "p_nom_opt"] * n.storage_units.loc[stores, "max_hours"]).sum())
    out["turbine_capacity_mw"] = float(
        g.loc[g.index[candidates & g.carrier.isin(turbines)], "p_nom_opt"].sum())
    out["in_spell"] = out["price_eur_mwh"] >= blocks["shed_flex"] - 1e-6
    out.index.name = "time"
    return out


def run_scenarios(costs_full, hours, aggregation):
    """Same question, different worlds, all at the reference carbon price
    except the last: "Danish budget" removes the common price and puts a
    territorial CO2 budget on Danish generation alone, at
    DK_BUDGET_FRACTION of Denmark's unpriced emissions -- section 2's cap
    in an open economy, where imports count as carbon-free."""
    n0, _ = solve_case(tax_tag(0.0), costs_full, hours, aggregation=aggregation,
                       ets_price=0.0)
    dk_budget = DK_BUDGET_FRACTION * greenfield.dk_emissions(n0)
    cases = {
        "reference": ({"ets_price": REFERENCE_TAX}, tax_tag(REFERENCE_TAX)),
        "autarky": ({"ets_price": REFERENCE_TAX, "autarky": True}, "scen_autarky"),
        "expensive gas": ({"ets_price": REFERENCE_TAX,
                           "gas_price": 2.0 * greenfield.GAS_PRICE},
                          "scen_expensive_gas"),
        "cheap capital": ({"ets_price": REFERENCE_TAX, "r": 0.02},
                          "scen_cheap_capital"),
        "Danish budget": ({"ets_price": 0.0, "co2_budget": dk_budget},
                          "scen_dk_budget"),
    }
    rows = {}
    for name, (kwargs, tag) in cases.items():
        n, sigma = solve_case(tag, costs_full, hours, aggregation=aggregation,
                              **kwargs)
        rows[name] = mix_row(n, sigma, kwargs["ets_price"])
        rows[name]["budget_t"] = kwargs.get("co2_budget", float("nan"))
    df = pd.DataFrame(rows).T
    # The unpriced world the budget is set against, for the leakage
    # arithmetic: how much of the Danish cut reappears abroad.
    df.loc["no carbon price"] = mix_row(n0, None, 0.0) | {"budget_t": float("nan")}
    return df


def costs_check(costs_full):
    """The two cost tiers must not disagree: efficiency and VOM of the small
    table against technology-data, with the ratio printed for inspection."""
    small = dispatch.read_tech(PROCESSED / "technology_costs_small.csv")
    rows = {}
    for ours, theirs in CHECK_MAP.items():
        if ours not in small.index or theirs not in costs_full.index:
            print(f"  costs_check: skipping {ours!r} / {theirs!r} -- not in "
                  "both tables; check CHECK_MAP against data/prepare.py")
            continue
        td = costs_full.loc[theirs]
        rows[ours] = {
            "efficiency_small": float(small.loc[ours, "efficiency"]),
            "efficiency_td": float(td["efficiency"]) if pd.notna(td["efficiency"]) else None,
            "vom_small": float(small.loc[ours, "vom_eur_per_mwh"]),
            "vom_td": float(td["VOM"]) if pd.notna(td["VOM"]) else None,
        }
    df = pd.DataFrame(rows).T
    df["efficiency_ratio"] = df["efficiency_small"] / df["efficiency_td"]
    return df


def run_resolution_check(costs_full, hours, aggregation):
    """Does the time aggregation move the reference answer? Solves the
    reference case once at full hourly resolution and writes both answers
    side by side: the Danish bill, the battery build and Danish
    emissions."""
    n, _ = solve_case(tax_tag(REFERENCE_TAX), costs_full, 8760,
                      aggregation="stride", ets_price=REFERENCE_TAX)
    sampled = pd.read_csv(RESULTS / "greenfield_tax_sweep.csv")
    row = sampled.loc[sampled["carbon_price"] == REFERENCE_TAX].iloc[0]
    full = mix_row(n, None, REFERENCE_TAX)
    caps = greenfield.dk_capacity(n)
    check = {
        "hours_sampled": hours,
        "aggregation_sampled": aggregation,
        "carbon_price": REFERENCE_TAX,
        "battery_mw_sampled": float(row["cap_battery_mw"]),
        "battery_mw_full": float(
            sum(mw for t, mw in caps.items() if t.startswith("battery_"))
        ),
        "battery_by_duration_full": {
            t: float(mw) for t, mw in caps.items() if t.startswith("battery_")},
        "battery_by_duration_sampled": {
            c.removeprefix("cap_").removesuffix("_mw"): float(row[c])
            for c in sampled.columns
            if c.startswith("cap_battery_") and c != "cap_battery_mw"},
        "offshore_mw_sampled": float(row["cap_wind_offshore_mw"]),
        "offshore_mw_full": float(caps.get("wind_offshore", 0.0)),
        "dk_net_cost_full": float(full["dk_net_cost"]),
        "dk_net_cost_sampled": float(row["dk_net_cost"]),
        "emissions_full_t": float(full["emissions_t"]),
        "emissions_sampled_t": float(row["emissions_t"]),
    }
    (RESULTS / "greenfield_resolution_check.json").write_text(
        json.dumps(check, indent=2), encoding="utf-8"
    )
    print(f"resolution check: battery {check['battery_mw_sampled']:.0f} MW at "
          f"{hours} snapshots vs {check['battery_mw_full']:.0f} MW at 8760; "
          f"net cost {check['dk_net_cost_sampled'] / 1e9:.2f} vs "
          f"{check['dk_net_cost_full'] / 1e9:.2f} bnEUR")
    print("wrote results/greenfield_resolution_check.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=336,
        help="snapshots the year is reduced to (default 336; the note's "
        "figures use 1095)",
    )
    parser.add_argument(
        "--aggregation", choices=network.AGGREGATION_SCHEMES, default="segments",
        help="how the year is reduced to --hours snapshots: chronological "
        "segments of varying length (segments, the default) or every k-th "
        "hour (stride); see model/network.py",
    )
    parser.add_argument(
        "--resolution-check", action="store_true",
        help="additionally solve the reference case at full hourly "
        "resolution and record how far the sampled answer sits from the "
        "full-year one (expensive; run after the main sweep)",
    )
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    costs_full = load_shared()

    screening = greenfield.candidate_costs(costs_full)
    sweep = run_tax_sweep(costs_full, args.hours, args.aggregation)
    n_ref, _ = solve_case(tax_tag(REFERENCE_TAX), costs_full, args.hours,
                          aggregation=args.aggregation, ets_price=REFERENCE_TAX)
    breakdown = cost_breakdown(n_ref)
    duty = realised_duty(n_ref)
    recovery = cost_recovery(n_ref)
    values = value_table(n_ref, REFERENCE_TAX)
    price_bands, scarcity = scarcity_profile(n_ref)
    spell = (spell_window(n_ref, scarcity["peaker_zone"])
             if scarcity.get("peaker_zone") else pd.DataFrame())
    scenarios = run_scenarios(costs_full, args.hours, args.aggregation)
    check = costs_check(costs_full)

    switch = (screening.loc["ocgt_biogas", "marginal_cost"]
              - screening.loc["ocgt", "marginal_cost"]) / screening.loc["ocgt", "emission_rate"]
    summary = {
        "hours": args.hours,
        "aggregation": args.aggregation,
        "snapshot_hours": {
            "min": float(n_ref.snapshot_weightings.objective.min()),
            "median": float(n_ref.snapshot_weightings.objective.median()),
            "max": float(n_ref.snapshot_weightings.objective.max()),
        },
        "forward_horizon": greenfield.FORWARD_HORIZON,
        "reference_weather_year": REFERENCE_WEATHER_YEAR,
        "neighbours_extendable": True,
        "tax_points": TAX_POINTS,
        "reference_tax_eur_t": REFERENCE_TAX,
        "switch_price_eur_t": float(switch),
        "dk_budget_fraction": DK_BUDGET_FRACTION,
        "discount_rate": greenfield.DISCOUNT_RATE,
        "battery_menu_hours": greenfield.BATTERY_MENU_HOURS,
        "voll_eur_mwh": greenfield.VOLL_EUR_MWH,
        "demand_blocks": greenfield.DK_DEMAND_BLOCKS,
        "p_nom_max": greenfield.P_NOM_MAX,
        "scarcity": scarcity,
    }

    screening.to_csv(RESULTS / "greenfield_screening.csv", index_label="tech")
    sweep.to_csv(RESULTS / "greenfield_tax_sweep.csv", index=False)
    breakdown.to_csv(RESULTS / "greenfield_cost_breakdown.csv", index_label="tech")
    duty.to_csv(RESULTS / "greenfield_realised_duty.csv", index_label="tech")
    recovery.to_csv(RESULTS / "greenfield_cost_recovery.csv", index=False)
    values.to_csv(RESULTS / "greenfield_value_table.csv", index_label="tech")
    price_bands.to_csv(RESULTS / "greenfield_price_bands.csv", index=False)
    spell.to_csv(RESULTS / "greenfield_spell_window.csv", index_label="time")
    scenarios.to_csv(RESULTS / "greenfield_scenarios.csv", index_label="scenario")
    check.to_csv(RESULTS / "costs_check.csv", index_label="tech")
    (RESULTS / "greenfield_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    for stale in ["greenfield_budget_sweep.csv",    # the budget sweep the tax sweep replaced
                  "greenfield_scarcity.csv"]:       # the duration curve the price bands replaced
        if (RESULTS / stale).exists():
            (RESULTS / stale).unlink()

    ref = sweep.loc[sweep["carbon_price"] == REFERENCE_TAX].iloc[0]
    print(f"{args.hours} hours: at {REFERENCE_TAX:.0f} EUR/t Denmark emits "
          f"{ref['emissions_t'] / 1e6:.2f} Mt and builds "
          f"{ref['cap_wind_offshore_mw'] / 1e3:.1f} GW offshore; fuel switch at "
          f"{switch:.0f} EUR/t")
    if args.resolution_check:
        run_resolution_check(costs_full, args.hours, args.aggregation)
    for name in ["greenfield_screening.csv", "greenfield_tax_sweep.csv",
                 "greenfield_cost_breakdown.csv", "greenfield_realised_duty.csv",
                 "greenfield_cost_recovery.csv", "greenfield_value_table.csv",
                 "greenfield_price_bands.csv", "greenfield_spell_window.csv",
                 "greenfield_scenarios.csv", "costs_check.csv",
                 "greenfield_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
