"""Solve the section 6 network instances and write everything figures 6.1-6.4
need into results/.

    python pipeline/run_network.py                fast default (336 segments)
    python pipeline/run_network.py --hours 1095   the note's figures (1095
                                                  chronological segments, as
                                                  in sections 7-9; see
                                                  model/network.py)

Experiments on the 12-bidding-zone DK/DE/SE/NO network derived from
PyPSA-Eur (see Appendix C of the note; data/processed/network_eur_bz_2024.nc):

    base      one year of zonal dispatch     -> figs 6.1, 6.2 (prices, rents),
              at the 2024 ETS average (CARBON_TAU), on the network
              calibrated to its year (Norwegian inflow, Nordic NTCs);
              the validation figure holds it against the actual market,
              and the calibration check solves the four combinations of
              the two calibrations for Appendix C
    smoothing DK1 vs DK2 wind, from data     -> fig 6.3
    expansion the Skagerrak corridor (DK1 to
              southern Norway) swept from 0  -> fig 6.4 (system cost saving
              to 3x its actual capacity          and the rent on the cables)
                                             -> fig 6.5 (who wins and who
                                                loses, by country)
    geography the zone polygons and the
              network's own topology         -> the map of Europe's bidding
                                                zones and the AC/DC topology
                                                figure of section 6.1-6.2
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))

from model import network
from run_dispatch import PROCESSED
from run_dispatch_t import YEAR

RESULTS = NOTE / "results"
NETWORK_NC = PROCESSED / "network_eur_bz_2024.nc"

EXPANSION_CORRIDOR = ("DK1", "NO2")   # Skagerrak: two DC cables in the data
EXPANSION_SCALES = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

# The 2024 market the section is held against embedded the EU ETS at
# roughly this average allowance price (EUR/t), so every solve of the
# section charges it. Section 7's reference case charges 85 EUR/t: a 2030
# reference, not a 2024 outcome.
CARBON_TAU = 65.0

# The named HVDC cables, by zone pair, for the topology figure and the text.
# The unnamed remainder (a second, smaller SE3-SE4 link) is drawn unnamed.
CABLE_NAMES = {
    ("DK1", "NO2"): "Skagerrak",
    ("DE", "NO2"): "NordLink",
    ("DE", "DK2"): "Kontek",
    ("DE", "SE4"): "Baltic Cable",
    ("DK1", "DK2"): "Great Belt",
    ("DK1", "SE3"): "Konti-Skan",
    ("SE3", "SE4"): "SydVästlänken",
}


def country_of(zone: str) -> str:
    """DK1 -> DK, NO2 -> NO, DE -> DE."""
    return zone[:2]


def corridor_links(n, a, b):
    return [name for name, row in n.links.iterrows()
            if {row.bus0, row.bus1} == {a, b}]


def export_geography(n):
    """The map and the topology, in one file for stage 3: Europe's bidding
    zones as projected polygons (from data/processed/bidding_zones.json,
    assembled in data/prepare.py from Natural Earth), the network's zone
    nodes in the same projection, and every corridor of the network with
    its kind (AC or DC), its capacity as the market sees it, and the
    synchronous area each zone belongs to.

    `n` is the loaded network before aggregation: capacities are what the
    zonal market trades on, i.e. after the NTC derating of the cross-border
    AC corridors (s_max_pu) and with each DC corridor counted once per
    direction."""
    geo = json.loads(
        (PROCESSED / "bidding_zones.json").read_text(encoding="utf-8"))

    n.determine_network_topology()
    members = {}
    for zone, sub in n.buses["sub_network"].items():
        members.setdefault(str(sub), []).append(zone)
    # Name the two synchronous areas by a member everyone knows.
    area_of = {}
    for zones in members.values():
        name = "Continental Europe" if "DE" in zones else "Nordic"
        for z in zones:
            area_of[z] = name

    # One entry per zone pair AND kind: a pair can carry both an AC circuit
    # and a DC cable (SE3-SE4 does), and the figure draws them separately.
    corridors = {}
    for name, row in n.lines.iterrows():
        key = (*sorted([row.bus0, row.bus1]), "AC")
        c = corridors.setdefault(key, {"capacity_mw": 0.0})
        c["capacity_mw"] += float(row.s_nom * row.s_max_pu)
    by_direction = {}
    for name, row in n.links.iterrows():
        key = (*sorted([row.bus0, row.bus1]), "DC")
        d = by_direction.setdefault(key, {})
        d[(row.bus0, row.bus1)] = d.get((row.bus0, row.bus1), 0.0) + float(row.p_nom)
        corridors[key] = {"capacity_mw": max(d.values())}
    branches = []
    for (a, b, kind), c in sorted(corridors.items()):
        branches.append({
            "zone0": a, "zone1": b, "kind": kind,
            "capacity_mw": round(c["capacity_mw"]),
            "name": CABLE_NAMES.get((a, b), CABLE_NAMES.get((b, a))),
            "cross_border": country_of(a) != country_of(b),
        })

    # Independent AC loops per synchronous area: edges minus nodes plus one,
    # on the corridor graph (parallel circuits merged).
    loops = {}
    for zones in members.values():
        edges = [b for b in branches if b["kind"] == "AC"
                 and b["zone0"] in zones and b["zone1"] in zones]
        loops[area_of[zones[0]]] = max(0, len(edges) - len(zones) + 1)

    return {
        "crs": geo["crs"],
        "source": geo["source"],
        "zones": geo["zones"],
        "nodes": {z: geo["nodes"][z] for z in n.buses.index},
        "synchronous_area": area_of,
        "ac_loops": loops,
        "branches": branches,
        "hvdc_loss": network.HVDC_LOSS,
    }


def owner_income(n) -> pd.Series:
    """What the owner of each corridor actually collects over the year, in
    EUR: the power delivered at the receiving end sold at that end's price,
    minus the power taken at the sending end bought at that end's price.
    Unlike flow times spread (`network.congestion_rent`, the statistic the
    TSOs report as bottleneck income), this is net of the energy lost in
    transit, which is why the welfare accounts use it: nobody collects the
    value of the losses. PyPSA's sign convention: p0 and p1 are the powers
    entering the branch from each end, so p0 + p1 is the loss."""
    w = n.snapshot_weightings.objective
    price = n.buses_t.marginal_price
    income = {}
    for df, p0, p1 in [(n.lines, n.lines_t.p0, n.lines_t.p1),
                       (n.links, n.links_t.p0, n.links_t.p1)]:
        for name, row in df.iterrows():
            corridor = "\u2013".join(sorted([row.bus0, row.bus1]))
            earned = -(p0[name] * price[row.bus0] + p1[name] * price[row.bus1])
            income[corridor] = income.get(corridor, 0.0) + float((earned * w).sum())
    return pd.Series(income, name="owner_income_eur")


def zone_accounts(n) -> pd.DataFrame:
    """Who pays and who earns, zone by zone, in EUR for the year: what
    consumers spend (price times load), what generators and hydro earn net
    of their variable cost, the generation cost itself, and the zone's half
    share of what the owners of every corridor touching it collect (net of
    losses, see `owner_income`). Load is fixed, so a change in consumer
    spending is minus the change in consumer surplus. Every sum is weighted
    by snapshot length."""
    w = n.snapshot_weightings.objective
    price = n.buses_t.marginal_price
    rents = owner_income(n).to_frame("rent_eur")
    rows = {}
    for z in n.buses.index:
        loads = n.loads.index[n.loads.bus == z]
        load = pd.DataFrame(index=n.snapshots)
        for name in loads:
            if name in n.loads_t.p_set.columns:
                load[name] = n.loads_t.p_set[name]
            else:
                load[name] = float(n.loads.loc[name, "p_set"])
        load = load.sum(axis=1)
        gens = n.generators.index[n.generators.bus == z]
        p = n.generators_t.p[gens]
        cost = p.mul(n.generators.loc[gens, "marginal_cost"], axis=1).sum(axis=1)
        revenue = p.sum(axis=1) * price[z]
        units = n.storage_units.index[n.storage_units.bus == z]
        # Hydro and pumped storage: + when discharging, - when pumping, and
        # no variable cost in this network, so revenue is profit.
        storage_profit = n.storage_units_t.p[units].sum(axis=1) * price[z]
        rent_share = 0.0
        for corridor, row in rents.iterrows():
            a, b = corridor.split("–")
            if z in (a, b):
                rent_share += 0.5 * float(row["rent_eur"])
        rows[z] = {
            "consumer_expenditure_eur": float((price[z] * load * w).sum()),
            "generation_cost_eur": float((cost * w).sum()),
            "producer_profit_eur": float(((revenue - cost + storage_profit) * w).sum()),
            "rent_share_eur": rent_share,
        }
    return pd.DataFrame(rows).T


def hydro_table() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "hydro_calibration.csv", comment="#")


def calibrate_hydro(n, factors: dict) -> None:
    """Scale each country's reservoir inflow by its factor, in place.
    Section 6 only: the shipped network's regression-normalised 2024 level
    stays with sections 7-9, which look at 2050 and should not inherit an
    unusually wet year."""
    for country, factor in factors.items():
        units = n.storage_units.index[
            n.storage_units.bus.str.startswith(country)
            & (n.storage_units.carrier == "hydro")]
        units = [u for u in units if u in n.storage_units_t.inflow.columns]
        n.storage_units_t.inflow[units] *= factor


def find_hydro_factors(hours, tau, aggregation="segments", ntc=True,
                       tol_twh=0.5, max_iter=4) -> tuple:
    """The inflow factor per calibrated country at which the solved
    network's hydro output (reservoirs plus run-of-river) equals the
    published production of its year. Inflow and output are not the same
    number -- a full reservoir spills -- so the factor is found by a few
    secant steps on the solved output, starting from the ratio of the
    published production to the network's own hydro energy. Returns the
    factors and the search history."""
    table = hydro_table().set_index("country")
    factors, history = {}, []
    for country, row in table.iterrows():
        target = float(row["published_hydro_production_twh"])
        if pd.isna(target):
            continue
        # First guess: the published production over the normal-year level
        # the loaded network already sits on (model/network.py).
        factor = target / float(row["normal_production_twh"])
        points = []
        for _ in range(max_iter):
            n = build_instance(hours, aggregation, tau,
                               hydro_factors={country: factor}, ntc=ntc)
            network.solve(n)
            output = float(country_balance(n).loc[country, "hydro_twh"])
            points.append((factor, output))
            history.append({"country": country, "factor": factor, "hydro_twh": output})
            if abs(output - target) < tol_twh:
                break
            if len(points) >= 2 and points[-1][1] != points[-2][1]:
                (f0, o0), (f1, o1) = points[-2:]
                factor = f1 + (target - o1) * (f1 - f0) / (o1 - o0)
            else:
                factor *= target / output
        factors[country] = points[-1][0]
    return factors, pd.DataFrame(history)


def derate_to_ntc(n) -> pd.DataFrame:
    """Derate every corridor whose capacity exceeds TYNDP's reference-grid
    NTC (data/processed/transmission_ntc_reference.csv) to that figure, by
    scaling the AC circuits' s_max_pu; corridors at or below the NTC, and
    DC-only corridors, are left alone (never uprated). Returns what changed.
    Call before load_network's link split has been undone -- i.e. on the
    loaded network, where each DC direction is its own link."""
    table = pd.read_csv(PROCESSED / "transmission_ntc_reference.csv", comment="#")
    changes = []
    for _, row in table.iterrows():
        g0, g1 = set(row["zones0"].split("+")), set(row["zones1"].split("+"))
        lines = [name for name, r in n.lines.iterrows()
                 if (r.bus0 in g0 and r.bus1 in g1) or (r.bus0 in g1 and r.bus1 in g0)]
        links = [name for name, r in n.links.iterrows()
                 if r.bus0 in g0 and r.bus1 in g1]
        ac = float((n.lines.loc[lines, "s_nom"] * n.lines.loc[lines, "s_max_pu"]).sum())
        dc = float(n.links.loc[links, "p_nom"].sum())
        target = float(row["ntc_mw"])
        if not lines or ac + dc <= target:
            continue
        factor = max(target - dc, 0.0) / ac
        n.lines.loc[lines, "s_max_pu"] *= factor
        changes.append({"border": row["tyndp_border"], "zones0": row["zones0"],
                        "zones1": row["zones1"], "before_mw": round(ac + dc),
                        "after_mw": round(target), "lines": ";".join(lines)})
    return pd.DataFrame(changes)


def build_instance(hours, aggregation="segments", tau=None,
                   hydro_factors=None, ntc=True):
    """The section's instance: the network loaded, calibrated to its year
    (Norwegian inflow scaled by `hydro_factors`, internal Nordic corridors
    derated to reference NTCs if `ntc`), charged `tau` EUR/t on every
    emitter, cut to `hours` snapshots, with ramp limits."""
    n = network.load_network(NETWORK_NC)
    n.meta["calibration"] = {}
    if hydro_factors:
        calibrate_hydro(n, hydro_factors)
        n.meta["calibration"]["hydro_factors"] = dict(hydro_factors)
    if ntc:
        n.meta["calibration"]["ntc_changes"] = derate_to_ntc(n).to_dict(orient="records")
    if tau is not None:
        network.apply_carbon_price(n, tau)
    network.aggregate(n, hours, aggregation)
    network.apply_ramp_limits(n)
    return n


def country_balance(n) -> pd.DataFrame:
    """Per country, TWh over the year: load, hydro output (reservoirs and
    run-of-river), total generation, and net export."""
    w = n.snapshot_weightings.objective
    country = lambda s: s.str[:2]
    gen = n.generators_t.p.mul(w, axis=0).sum() / 1e6
    sto = n.storage_units_t.p.mul(w, axis=0).sum() / 1e6
    load = n.loads_t.p_set.mul(w, axis=0).sum() / 1e6
    out = pd.DataFrame({
        "load_twh": load.groupby(country(n.loads.bus.reindex(load.index))).sum(),
        "hydro_twh": (sto.groupby(country(n.storage_units.bus)).sum()
                      + gen[n.generators.carrier == "ror"].groupby(
                          country(n.generators.bus[n.generators.carrier == "ror"])).sum()),
        "generation_twh": (gen.groupby(country(n.generators.bus)).sum()
                           + sto.groupby(country(n.storage_units.bus)).sum()),
    }).fillna(0.0)
    out["net_export_twh"] = out["generation_twh"] - out["load_twh"]
    return out


def run_calibration_check(hours, tau, hydro_factors, aggregation="segments"):
    """The four combinations of the two calibrations, solved at the
    section's carbon price: mean zonal prices, and each country's hydro
    output and net export. What Appendix C quotes when it says what the
    calibration does."""
    rows = []
    for hydro, ntc in [(False, False), (True, False), (False, True), (True, True)]:
        n = build_instance(hours, aggregation, tau,
                           hydro_factors=hydro_factors if hydro else None, ntc=ntc)
        network.solve(n)
        prices = network.expand_to_hours(n, n.buses_t.marginal_price)
        balance = country_balance(n)
        row = {"hydro": hydro, "ntc": ntc,
               "total_rent_meur": float(network.congestion_rent(n)["rent_eur"].sum()) / 1e6}
        row |= {f"price_{z}": float(prices[z].mean()) for z in prices.columns}
        for c in balance.index:
            row[f"hydro_{c}_twh"] = float(balance.loc[c, "hydro_twh"])
            row[f"net_export_{c}_twh"] = float(balance.loc[c, "net_export_twh"])
        rows.append(row)
    return pd.DataFrame(rows)


def run_base(hours, tau=None, aggregation="segments", hydro_factors=None,
             ntc=True):
    """One year of zonal dispatch; `tau` charges every generator a carbon
    price (EUR/t) on top of its fuel cost."""
    n = build_instance(hours, aggregation, tau, hydro_factors, ntc)
    network.solve(n)

    # Prices go out as one row per HOUR of the year, each snapshot repeated
    # for the hours it stands for, so that every mean and every duration
    # curve downstream is weighted by snapshot length without stage 3 having
    # to know how the year was cut.
    prices = network.expand_to_hours(n, n.buses_t.marginal_price)
    rents = network.congestion_rent(n)
    return n, prices, rents


def run_smoothing():
    """Geographic smoothing, straight from the data: the two Danish zones'
    onshore wind profiles, their correlation, and the duration curve of the
    averaged profile against the individual ones."""
    profiles = {
        area: pd.read_csv(
            PROCESSED / f"profiles_{area}_{YEAR}.csv",
            index_col="time", parse_dates=True,
        )
        for area in ["dk1", "dk2"]
    }
    wind = pd.DataFrame(
        {
            "dk1": profiles["dk1"]["wind_onshore_pu"],
            "dk2": profiles["dk2"]["wind_onshore_pu"],
        }
    )
    wind["combined"] = wind.mean(axis=1)
    duration = pd.DataFrame(
        {col: wind[col].sort_values(ascending=False).to_numpy() for col in wind}
    )
    duration.index = (duration.index + 0.5) / len(duration) * 100.0
    return wind, duration, float(wind["dk1"].corr(wind["dk2"]))


def run_expansion(hours, tau=None, aggregation="segments",
                  hydro_factors=None, ntc=True):
    """Re-solve with the Skagerrak cables at different sizes. System cost
    falls at a decreasing rate; the rent on the corridor first grows with
    capacity, then is competed away as the DK1-NO2 spread closes."""
    a, b = EXPANSION_CORRIDOR
    rows = []
    accounts = []
    for scale in EXPANSION_SCALES:
        n = build_instance(hours, aggregation, tau, hydro_factors, ntc)
        links = corridor_links(n, a, b)
        # The corridor's NTC is its capacity in one direction. The lossy-link
        # split leaves every DC link unidirectional, so summing p_nom over
        # all links of the corridor would count both directions.
        actual = float(
            n.links.loc[links].query("bus0 == @a")["p_nom"].sum()
        )
        n.links.loc[links, "p_nom"] *= scale
        network.solve(n)
        rents = network.congestion_rent(n)
        corridor = "–".join(sorted([a, b]))
        hourly = network.expand_to_hours(n, n.buses_t.marginal_price)
        spread = (hourly[b] - hourly[a]).abs()
        rows.append(
            {
                "scale": scale,
                "ntc_mw": scale * actual,
                "system_cost": float(n.objective),
                "corridor_rent_eur": float(rents.loc[corridor, "rent_eur"]),
                "mean_abs_spread": float(spread.mean()),
            }
        )
        acc = zone_accounts(n)
        acc.insert(0, "scale", scale)
        accounts.append(acc.rename_axis("zone").reset_index())
    df = pd.DataFrame(rows)
    df["cost_saving_eur"] = df["system_cost"].iloc[0] - df["system_cost"]
    return df, pd.concat(accounts, ignore_index=True)


def run_validation():
    """Hold the model against the actual 2024 market outcomes it should
    resemble: realised zonal day-ahead prices, and the congestion rent the
    Danish borders actually collected (exchange flow times price spread).

    Corridor mapping for the settlement exchange columns: DK1's NO exchange
    is the Skagerrak corridor, its SE exchange Konti-Skan (SE3), its DE
    exchange the Jutland border; DK2's SE exchange is the Oresund (SE4) and
    its DE exchange the Kontek cable; the Great Belt is counted once, from
    the DK1 side. Flows are positive for imports, so the realised rent is
    flow times (own price minus neighbour price) in every hour, summed.
    """
    spot = pd.read_csv(
        PROCESSED / "spot_2024.csv", index_col="time", parse_dates=True
    )
    corridors = {
        "DK1–NO2": ("dk1", "ExchangeNO_MWh", "DK1", "NO2"),
        "DK1–SE3": ("dk1", "ExchangeSE_MWh", "DK1", "SE3"),
        "DE–DK1": ("dk1", "ExchangeGE_MWh", "DK1", "DE"),
        "DK1–DK2": ("dk1", "ExchangeGreatBelt_MWh", "DK1", "DK2"),
        "DK2–SE4": ("dk2", "ExchangeSE_MWh", "DK2", "SE4"),
        "DE–DK2": ("dk2", "ExchangeGE_MWh", "DK2", "DE"),
    }
    exchange = {
        area: pd.read_csv(
            PROCESSED / f"exchange_{area}_2024.csv",
            index_col="time", parse_dates=True,
        )
        for area in ["dk1", "dk2"]
    }
    rents = {}
    for corridor, (area, col, zone, neighbour) in corridors.items():
        flow = exchange[area][col]
        joined = pd.DataFrame(
            {"flow": flow, "own": spot[zone], "nb": spot[neighbour]}
        ).dropna()
        rents[corridor] = float(
            (joined["flow"] * (joined["own"] - joined["nb"])).sum()
        )
    actual = {
        "avg_price": {z: float(spot[z].mean()) for z in spot.columns},
        "corridor_rent_eur": rents,
    }
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, default=336,
        help="snapshots the year is reduced to (default 336; the note's "
        "figures use 1095 with --aggregation stride)",
    )
    parser.add_argument(
        "--aggregation", choices=network.AGGREGATION_SCHEMES, default="segments",
        help="how the year is reduced to --hours snapshots: chronological "
        "segments of varying length (segments, the default) or every k-th "
        "hour (stride); see model/network.py",
    )
    parser.add_argument(
        "--raw-hydro", action="store_true",
        help="keep the network's own Norwegian inflow instead of scaling it "
        "to the published 2024 hydro production",
    )
    parser.add_argument(
        "--raw-ntc", action="store_true",
        help="keep the network's thermal ratings on the internal Nordic "
        "corridors instead of derating them to TYNDP's reference NTCs",
    )
    parser.add_argument(
        "--hydro-factor", type=float, default=None,
        help="use this Norwegian inflow factor instead of searching for it "
        "(saves the search's solves when the factor is already known)",
    )
    parser.add_argument(
        "--skip-calibration-check", action="store_true",
        help="do not solve the four calibration combinations (saves four "
        "solves; Appendix C's calibration table is then not rebuilt)",
    )
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    ntc = not args.raw_ntc

    # Every solve of the section charges the year's ETS price: the section
    # is held against the 2024 market, and 2024's plants paid it.
    if args.raw_hydro:
        hydro_factors, search = {}, pd.DataFrame()
    elif args.hydro_factor is not None:
        hydro_factors, search = {"NO": args.hydro_factor}, pd.DataFrame()
    else:
        hydro_factors, search = find_hydro_factors(
            args.hours, CARBON_TAU, args.aggregation, ntc)
        print("hydro calibration:", hydro_factors)
    n, prices, rents = run_base(args.hours, tau=CARBON_TAU,
                                aggregation=args.aggregation,
                                hydro_factors=hydro_factors, ntc=ntc)
    balance = country_balance(n)
    wind, duration, corr = run_smoothing()
    expansion, accounts = run_expansion(args.hours, CARBON_TAU,
                                        args.aggregation, hydro_factors, ntc)
    actual = run_validation()
    calibration = (None if args.skip_calibration_check
                   else run_calibration_check(args.hours, CARBON_TAU,
                                              hydro_factors, args.aggregation))
    geography = export_geography(network.load_network(NETWORK_NC))
    transmission_costs = pd.read_csv(
        PROCESSED / "transmission_costs.csv", comment="#")
    candidates = pd.read_csv(
        PROCESSED / "transmission_candidates.csv", comment="#")
    a, b = EXPANSION_CORRIDOR
    skagerrak_candidates = candidates[
        (candidates["zone0"] == a) & (candidates["zone1"] == b)]
    skagerrak_km = float(n.links.loc[corridor_links(n, a, b), "length"].max())
    tcost = transmission_costs.set_index("technology")

    summary = {
        "hours": len(n.snapshots),
        "aggregation": args.aggregation,
        "network_year": 2024,
        "zones": list(n.buses.index),
        # The fleet the text describes: generators, and hydro storage units.
        "n_generators": int(len(n.generators)),
        "n_hydro_units": int(len(n.storage_units)),
        "avg_price": {z: float(prices[z].mean()) for z in n.buses.index},
        "carbon_tau_eur_t": CARBON_TAU,
        "wind_correlation_dk1_dk2": corr,
        "total_congestion_rent_eur": float(rents["rent_eur"].sum()),
        "actual_market": actual,
        # What the section did to the shipped network before solving.
        "calibration": {
            "hydro": bool(hydro_factors), "ntc": ntc,
            "hydro_factors": hydro_factors,
            "hydro_search": search.to_dict(orient="records"),
            "ntc_changes": n.meta["calibration"].get("ntc_changes", []),
            "hydro_table": pd.read_csv(PROCESSED / "hydro_calibration.csv",
                                       comment="#").to_dict(orient="records"),
        },
        "country_balance": balance.round(2).to_dict(orient="index"),
        # The market's capacity on every cross-border corridor, as the text
        # quotes it (MW, one direction; AC borders after NTC derating).
        "border_capacity_mw": {
            f"{br['zone0']}–{br['zone1']}": br["capacity_mw"]
            for br in geography["branches"] if br["cross_border"]
        },
        "synchronous_area": geography["synchronous_area"],
        "ac_loops": geography["ac_loops"],
        "n_ac_corridors": sum(br["kind"] == "AC" for br in geography["branches"]),
        "n_dc_corridors": sum(br["kind"] == "DC" for br in geography["branches"]),
        "hvdc_loss": geography["hvdc_loss"],
        "transmission_costs": transmission_costs.to_dict(orient="records"),
        # A Skagerrak-class cable priced two ways: technology-data's rule of
        # thumb (submarine cable per MW-km over the network's corridor
        # length, plus the converter pair) and TYNDP's own candidates.
        "skagerrak_length_km": skagerrak_km,
        "skagerrak_rule_of_thumb_eur_per_mw": float(
            tcost.loc["HVDC submarine", "investment"] * skagerrak_km
            + tcost.loc["HVDC inverter pair", "investment"]),
        "skagerrak_tyndp_capex_meur_per_gw": {
            "min": float(skagerrak_candidates["capex_eur_per_mw"].min() * 1e3 / 1e6),
            "max": float(skagerrak_candidates["capex_eur_per_mw"].max() * 1e3 / 1e6),
        },
    }

    prices.to_csv(RESULTS / "network_prices.csv", index_label="hour")
    rents.to_csv(RESULTS / "network_rents.csv", index_label="corridor")
    for stale in ["network_prices_carbon.csv", "network_rents_carbon.csv"]:
        (RESULTS / stale).unlink(missing_ok=True)   # from the two-run design
    if calibration is not None:
        calibration.to_csv(RESULTS / "network_calibration.csv", index=False)
    duration.to_csv(RESULTS / "network_wind_duration.csv", index_label="pct_of_hours")
    wind.to_csv(RESULTS / "network_wind_hourly.csv", index_label="time")
    expansion.to_csv(RESULTS / "network_expansion.csv", index=False)
    accounts.to_csv(RESULTS / "network_expansion_accounts.csv", index=False)
    (RESULTS / "network_geography.json").write_text(
        json.dumps(geography, ensure_ascii=False), encoding="utf-8"
    )
    (RESULTS / "network_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    avg = summary["avg_price"]
    print(
        f"{summary['hours']} hours: mean prices "
        + ", ".join(f"{z} {p:.0f}" for z, p in list(avg.items())[:6])
        + f" ... EUR/MWh; total congestion rent "
        f"{summary['total_congestion_rent_eur'] / 1e6:.0f} MEUR"
    )
    for name in ["network_prices.csv", "network_rents.csv",
                 "network_calibration.csv",
                 "network_wind_duration.csv", "network_wind_hourly.csv",
                 "network_expansion.csv", "network_expansion_accounts.csv",
                 "network_geography.json", "network_summary.json"]:
        print(f"wrote results/{name}")


if __name__ == "__main__":
    main()
