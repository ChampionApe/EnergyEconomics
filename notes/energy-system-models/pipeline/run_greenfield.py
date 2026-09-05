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
    recovery    Result 7.1 in numbers, the LCOE-against-capture table and
                the scarcity curve, all at the reference case
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


def input_fingerprint(costs_full=None, aggregation: str = "segments",
                      weather=None) -> str:
    """A short hash of everything a cached solve depends on.

    The cache is keyed by tag and instance size alone, which says nothing
    about the *inputs*. So every file the model reads, the model's own
    source, the constants not read from any file, the cost table the case
    is solved on and the weather it is solved on are hashed, and the print
    is stored with the solve. A stale solve is re-solved, never trusted.
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
        h.update(path.read_bytes() if path.exists() else b"<missing>")
    if weather is not None:
        h.update(pd.util.hash_pandas_object(
            weather, index=True).to_numpy().tobytes())
    # Changing how a case is BUILT must invalidate the cases already
    # solved. Only the modules this section builds from are hashed.
    for module in ["greenfield.py", "network.py"]:
        h.update((NOTE / "model" / module).read_bytes())
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


def cost_recovery(n):
    """Result 7.1 (long-run zero profit) in numbers, per Danish candidate.

    What one MW of a technology would earn in the price system of the solved
    case is the availability-weighted sum of its hourly scarcity rents,
    sum_h gamma * max(lambda - c, 0), with c the effective marginal cost
    (fuel plus the carbon price, plus the budget's dual where there is one).
    An envelope quantity that exists for unbuilt candidates too. Zero profit
    says it equals the annualised fixed cost for every technology built
    below its potential cap, exceeds it by the land rent at the cap, and
    falls short for one the model declined to build. Reported per
    technology over the two Danish zones, capacity-weighted where built and
    at the better site where not. Batteries report their realised arbitrage
    margin per MW, since a battery's envelope value is not a closed form.
    """
    w = n.snapshot_weightings.objective
    sigma = float(n.meta.get("co2_price") or 0.0)
    rates = getattr(n, "_emission_rates", pd.Series(dtype=float))
    rows = {}
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
        rent_per_mw = float((gamma * margin * w).sum())
        entry = rows.setdefault(row.carrier, {
            "capacity_mw": 0.0, "p_nom_max_mw": 0.0,
            "_rent_weighted": 0.0, "_rent_best": None,
            "_fixed_weighted": 0.0, "_fixed_best": None})
        cap = float(row.p_nom_opt)
        entry["capacity_mw"] += cap
        entry["p_nom_max_mw"] += float(min(row.p_nom_max, 1e9))
        entry["_rent_weighted"] += rent_per_mw * cap
        entry["_fixed_weighted"] += float(row.capital_cost) * cap
        if (entry["_rent_best"] is None
                or rent_per_mw - row.capital_cost
                > entry["_rent_best"] - entry["_fixed_best"]):
            entry["_rent_best"], entry["_fixed_best"] = rent_per_mw, float(row.capital_cost)
    for s, row in n.storage_units.iterrows():
        if row.bus not in greenfield.DK_ZONES or not row.p_nom_extendable:
            continue
        price = n.buses_t.marginal_price[row.bus]
        net = n.storage_units_t.p[s]        # positive when discharging
        margin = float((price * net * w).sum()
                       - row.marginal_cost * (net.abs() * w).sum())
        entry = rows.setdefault(row.carrier, {
            "capacity_mw": 0.0, "p_nom_max_mw": float("inf"),
            "_rent_weighted": 0.0, "_rent_best": 0.0,
            "_fixed_weighted": 0.0, "_fixed_best": float(row.capital_cost)})
        cap = float(row.p_nom_opt)
        entry["capacity_mw"] += cap
        entry["_rent_weighted"] += margin
        entry["_fixed_weighted"] += float(row.capital_cost) * cap
    out = {}
    for tech, e in rows.items():
        built = e["capacity_mw"] > 1.0
        fixed = (e["_fixed_weighted"] / e["capacity_mw"] if built
                 else e["_fixed_best"])
        rent = (e["_rent_weighted"] / e["capacity_mw"] if built
                else e["_rent_best"])
        out[tech] = {
            "capacity_mw": float(e["capacity_mw"]),
            "p_nom_max_mw": float(e["p_nom_max_mw"]),
            "built": bool(built),
            "at_cap": bool(built and e["capacity_mw"] >= 0.999 * e["p_nom_max_mw"]),
            "fixed_eur_mw_yr": float(fixed),
            "rent_eur_mw_yr": float(rent),
            "rent_over_fixed": float(rent) / float(fixed) if fixed else float("nan"),
        }
    return pd.DataFrame.from_dict(out, orient="index")


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


def scarcity_profile(n):
    """How the peakers get paid: the DK1 price duration curve in hours, and
    the cumulative share of the peaking fleet's annual operating margin
    earned in its best hours. Returns the curve and a few summary numbers."""
    w = n.snapshot_weightings.objective
    hourly_price = network.expand_to_hours(n, n.buses_t.marginal_price[["DK1"]])["DK1"]
    peakers = [g for g, row in n.generators.iterrows()
               if row.bus in greenfield.DK_ZONES
               and row.carrier in ("ocgt", "ocgt_biogas")]
    margin = pd.Series(0.0, index=n.snapshots)
    for g in peakers:
        row = n.generators.loc[g]
        margin += (n.buses_t.marginal_price[row.bus] - row.marginal_cost) * n.generators_t.p[g]
    hourly_margin = network.expand_to_hours(n, margin.to_frame("m"))["m"]
    sorted_margin = hourly_margin.sort_values(ascending=False).reset_index(drop=True)
    total = float(sorted_margin.sum())
    cum_share = sorted_margin.cumsum() / total if total > 0 else sorted_margin * 0.0
    curve = pd.DataFrame({
        "hour_rank": range(1, len(hourly_price) + 1),
        "dk1_price_sorted": hourly_price.sort_values(ascending=False).to_numpy(),
        "peaker_margin_cum_share": cum_share.to_numpy(),
    })
    blocks = {c: wtp for c, _, wtp in greenfield.DK_DEMAND_BLOCKS}
    summary = {
        "peaker_margin_total_eur": total,
        "peaker_capacity_mw": float(n.generators.loc[peakers, "p_nom_opt"].sum()),
        "share_in_top_100_hours": float(cum_share.iloc[99]) if len(cum_share) > 99 else None,
        "share_in_top_500_hours": float(cum_share.iloc[499]) if len(cum_share) > 499 else None,
        "hours_price_above_flex_block": int((hourly_price >= blocks["shed_flex"] - 1e-6).sum()),
        "hours_price_above_industry_block": int((hourly_price >= blocks["shed_industry"] - 1e-6).sum()),
        "hours_price_at_voll": int((hourly_price >= greenfield.VOLL_EUR_MWH - 1e-6).sum()),
        "dk1_max_price": float(hourly_price.max()),
    }
    return curve, summary


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
    scarcity_curve, scarcity = scarcity_profile(n_ref)
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
    recovery.to_csv(RESULTS / "greenfield_cost_recovery.csv", index_label="tech")
    values.to_csv(RESULTS / "greenfield_value_table.csv", index_label="tech")
    scarcity_curve.to_csv(RESULTS / "greenfield_scarcity.csv", index=False)
    scenarios.to_csv(RESULTS / "greenfield_scenarios.csv", index_label="scenario")
    check.to_csv(RESULTS / "costs_check.csv", index_label="tech")
    (RESULTS / "greenfield_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    stale = RESULTS / "greenfield_budget_sweep.csv"
    if stale.exists():
        stale.unlink()      # the budget sweep this replaced

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
                 "greenfield_scarcity.csv", "greenfield_scenarios.csv",
                 "costs_check.csv", "greenfield_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
