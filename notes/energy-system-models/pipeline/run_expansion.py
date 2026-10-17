"""Solve the section 8 scenarios and write what their figures need.

    python pipeline/run_expansion.py                fast default (336 segments)
    python pipeline/run_expansion.py --hours 1095   the note's figures
    python pipeline/run_expansion.py --aggregation stride
                                                    every k-th hour instead of
                                                    chronological segments
                                                    (see model/network.py)
    python pipeline/run_expansion.py --hours 1095 --resolution-check [SCENARIO ...]
                                                    additionally solve these
                                                    scenarios (default: all of
                                                    CHECK_RUNGS) at the
                                                    reference budget at all
                                                    8760 hours (hours each on
                                                    Gurobi)

Four nested scenarios on the twelve-zone network:

    basic    every zone extendable beside its existing fleet, one
             system-wide CO2 budget, no industrial hydrogen, every vehicle
             charging on arrival
    ev       + smart charging of the passenger cars
    ev_v2g   + vehicle-to-grid (a branch off ev)
    ev_h2    ev + the industrial hydrogen sector and every route to meeting
             it: reformers, imports, electrolyser, store and turbine

basic, ev and ev_v2g share basic's budget in tonnes; ev_h2 faces a budget
set as a fraction of ITS OWN unconstrained emissions, because it carries a
hydrogen sector the others do not and one absolute target would mean a far
deeper cut for it. So sigma compares across the first three, and along
ev_h2's own path; see model/expansion.py.

Solved networks are cached in results/cache/ and fingerprinted against their
inputs; delete the cache to force re-solves.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))
sys.path.insert(0, str(NOTE / "pipeline"))

from model import expansion, greenfield, network
from run_dispatch import PROCESSED
from run_greenfield import (REFERENCE_WEATHER_YEAR, cache_name,
                            fingerprint_bytes, year_weather)

RESULTS = NOTE / "results"
CACHE = RESULTS / "cache"
NETWORK_NC = PROCESSED / "network_eur_bz_2024.nc"

# The scenarios. The order matters: the figures read them in this order,
# each one the one before plus one ingredient, except that ev_v2g branches
# off ev and ev_h2 builds on ev, not on ev_v2g.
# Transmission is in every scenario. A model that puts 2050 demand on a
# 2024 grid and then reports where it is congested is measuring its own
# assumption, so the grid is a decision here like any other -- see
# model/expansion.py for what may be bought and what may not.
RUNGS = {
    "basic": {"ev": "fixed", "transmission": True},
    "ev": {"ev": "smart", "transmission": True},
    "ev_v2g": {"ev": "v2g", "transmission": True},
    "ev_h2": {"ev": "smart", "p2x": True, "hydrogen": True,
              "transmission": True},
}

# Budget points, as fractions of each scenario's baseline emissions (below).
# Seven points, because the carbon price is read as a curve: the abatement
# cost curve of section 2, for the whole system. Most of them sit at the
# deep end, where the price moves -- a lightly decarbonised 2050 is not a
# scenario anyone is planning.
BUDGET_FRACTIONS = [None, 0.75, 0.5, 0.25, 0.10, 0.05, 0.01]

# Which scenario's unconstrained emissions each scenario's budget is a
# fraction of.
#
# basic, ev and ev_v2g are the SAME system -- same demand, same
# technologies, differing only in what the cars may do -- so they share a
# baseline and their carbon prices compare directly. Give them their own and
# the flexible scenarios are asked for tighter targets in absolute tonnes,
# purely because flexibility lowered their unconstrained emissions; their
# sigma then comes out higher and flexibility looks harmful while the
# quantities say the opposite.
#
# ev_h2 keeps its own, because it carries a hydrogen sector the others do
# not: one absolute target for all would ask it for a far deeper cut than its
# neighbours. So sigma compares within {basic, ev, ev_v2g} and along ev_h2's
# own path, but not between those two groups.
BASELINE_RUNG = {"basic": "basic", "ev": "basic", "ev_v2g": "basic",
                 "ev_h2": "ev_h2"}
REFERENCE_FRACTION = 0.01
# The scenario whose reference case the zone table describes, and the
# scenarios checked at full resolution (a seasonal hydrogen store and the
# cars as a battery are what a year cut into segments might misjudge).
REFERENCE_RUNG = "ev_h2"
CHECK_RUNGS = ["ev_h2", "ev_v2g"]
# The intermediate budget the section quotes beside the reference one.
MID_FRACTION = 0.25


def load_shared():
    return pd.read_csv(
        PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}.csv", index_col="technology"
    )


def input_fingerprint(aggregation: str = "segments", weather=None) -> str:
    """A short hash of everything a cached solve depends on — the same
    discipline as run_greenfield.py, extended with what section 8 adds,
    and the same fingerprint_bytes(), so line endings do not count."""
    h = hashlib.sha256()
    if weather is not None:
        h.update(pd.util.hash_pandas_object(
            weather, index=True).to_numpy().tobytes())
    for path in [PROCESSED / f"fuel_assumptions_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / "potentials_zones.csv",
                 PROCESSED / f"demand_zones_{greenfield.FORWARD_HORIZON}.csv",
                 PROCESSED / "biomethane_potential.csv",
                 PROCESSED / "offshore_cost_premium.csv",
                 PROCESSED / "transmission_candidates.csv",
                 PROCESSED / "hydro_calibration.csv",
                 PROCESSED / "h2_storage_potential.csv",
                 PROCESSED / "ev_fleet.csv",
                 PROCESSED / "ev_profiles.csv",
                 PROCESSED / "h2_assumptions.csv",
                 PROCESSED / "h2_imports.csv",
                 NETWORK_NC]:
        h.update(fingerprint_bytes(path))
    # The model's own source. Changing how a case is BUILT must invalidate
    # the cases already solved, or an edit silently returns the previous
    # answer -- which is exactly what happened on 2026-09-01, when section 7
    # was moved from electrifying Denmark to electrifying every zone and
    # "re-ran" in seconds, entirely from cache, reporting the old numbers.
    # Only the modules this section actually builds from are hashed, so an
    # edit to an unrelated model does not throw away hours of solves.
    for module in ["expansion.py", "greenfield.py", "network.py"]:
        h.update(fingerprint_bytes(NOTE / "model" / module))
    h.update(repr([
        greenfield.DISCOUNT_RATE, greenfield.GAS_PRICE,
        greenfield.GAS_CO2_T_PER_MWH_TH, greenfield.BATTERY_MENU_HOURS,
        greenfield.FORWARD_HORIZON, sorted(greenfield.CANDIDATES.items()),
        # A rung is part of what a cached solve means: redefining one must
        # invalidate every case solved under the old definition, or a tag
        # like "basic_nocap" silently returns a different model's answer.
        sorted((k, sorted(v.items())) for k, v in RUNGS.items()),
        sorted(BASELINE_RUNG.items()),
        BUDGET_FRACTIONS, greenfield.BIOMETHANE_POTENTIAL_MWH,
        expansion.TRANSMISSION_LIFETIME, expansion.TRANSMISSION_FOM,
        sorted(greenfield.CANDIDATE_FUEL.items()),
        greenfield.DK_DEMAND_BLOCKS, greenfield.VOLL_EUR_MWH,
        sorted(network.RAMP_LIMIT_PER_HOUR.items()), "ramps-hourly-unscaled",
        sorted(network.OUTAGE_DERATE.items()),
        network.HVDC_LOSS, network.TRANSMISSION_LOSSES_SEGMENTS,
        # section 8's own constants
        sorted(expansion.CAVERN_ZONES), expansion.H2_STORE_CAVERN,
        expansion.H2_STORE_TANK, expansion.ELECTROLYSER, expansion.H2_TURBINE,
        expansion.EV_MODES, expansion.EV_PARTICIPATION,
        expansion.V2G_MARGINAL_COST,
        expansion.BIOMETHANE_DROP_IN, expansion.GAS_CARRIERS,
        expansion.BIOMETHANE_PRICE,
        expansion.SMR, expansion.SMR_EFFICIENCY, expansion.H2_DEMAND_FLAT,
        # The turbine's cost convention is not a constant, so it cannot be
        # hashed directly; this tag stands in for it, and must change if the
        # convention does. See add_p2x().
        "h2-turbine-cost-per-mwel",
        aggregation,
    ]).encode())
    return h.hexdigest()[:16]


def solve_case(tag, costs_full, hours, aggregation="segments", **kwargs):
    """Build and solve one rung at one budget, or load it from the cache.
    Every case runs on the zonal weather archive's reference year, as
    section 7's do (see run_greenfield.py)."""
    import pypsa

    weather = kwargs.pop("weather", None)
    if weather is None:
        weather = year_weather(REFERENCE_WEATHER_YEAR)
    fingerprint = input_fingerprint(aggregation, weather)
    cache_file = CACHE / cache_name("expansion", tag, hours, aggregation)
    if cache_file.exists():
        n = pypsa.Network(str(cache_file))
        stored = n.meta.get("input_fingerprint")
        if stored == fingerprint:
            # Reforming's rate must come back too, or a cached solve's
            # emissions would silently omit the hydrogen sector.
            n._emission_rates = expansion.emission_rates_with_smr(
                greenfield.candidate_costs(costs_full))
            return n, n.meta.get("co2_price")
        print(f"  cache {cache_file.name}: inputs changed "
              f"({stored} -> {fingerprint}) -- re-solving")

    start = time.time()
    n = expansion.build(NETWORK_NC, costs_full, hours,
                        aggregation=aggregation, weather=weather, **kwargs)
    sigma = expansion.solve(n)
    print(f"  solved {tag} in {time.time() - start:.0f}s"
          + (f", sigma = {sigma:.2f} EUR/t" if sigma is not None else ""))
    n.meta["co2_price"] = sigma
    n.meta["input_fingerprint"] = fingerprint
    CACHE.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(cache_file)
    return n, sigma


def cost_split(n):
    """The year's system cost in two parts: the capital of everything bought
    (plants, batteries, wires and the hydrogen chain, at their annual fixed
    cost) and the rest of the objective, which is what running the system
    costs: fuel, upkeep that scales with output, the demand blocks, and the
    biomethane premium. The existing fleet carries no capital cost."""
    capital = 0.0
    for component, attr in [("Generator", "p_nom"), ("StorageUnit", "p_nom"),
                            ("Link", "p_nom"), ("Line", "s_nom"),
                            ("Store", "e_nom")]:
        frame = n.components[component].static
        if frame.empty:
            continue
        bought = frame[f"{attr}_extendable"].astype(bool)
        capital += float((frame["capital_cost"] * frame[f"{attr}_opt"])[bought].sum())
    return {"capital_cost_eur": capital,
            "operating_cost_eur": float(n.objective) - capital}


def biomethane_share(n):
    """Per zone, the share of the gas burnt that was biomethane: what the
    zone bought (greenfield.read_dropin) over all the gas its plants and
    reformers burnt. The model fixes only each zone's purchase, not which
    machine burns it, so a figure that splits output by fuel splits every
    machine in the zone alike."""
    bought = n.meta.get("biomethane_dropin_mwh") or {}
    if not isinstance(bought, dict):
        bought = {}
    w = n.snapshot_weightings.objective
    rates = expansion.emission_rates(n, n._emission_rates)
    gas = n.generators.index[n.generators.carrier.isin(expansion.GAS_CARRIERS)]
    # A machine's gas per MWh is its CO2 rate over the gas's (expansion.solve).
    fuel = (n.generators_t.p[gas].mul(w, axis=0).sum() * rates[gas]
            / greenfield.GAS_CO2_T_PER_MWH_TH)
    burnt = fuel.groupby(n.generators.loc[gas, "bus"].map(
        expansion.electrical_zone)).sum()
    return {zone: min(1.0, float(bought.get(zone, 0.0)) / mwh)
            for zone, mwh in burnt.items() if mwh > 0}


def hydrogen_routes(n):
    """What hydrogen_balance() leaves out: the imports, and the part of the
    reformers' output that was made from biomethane (biomethane_share())."""
    w = n.snapshot_weightings.objective
    g = n.generators
    imports = g.index[g.carrier == "h2_import"]
    smr = g.index[g.carrier == "smr"]
    share = biomethane_share(n)
    made = n.generators_t.p[smr].mul(w, axis=0).sum()
    return {
        "h2_imported_mwh": float(n.generators_t.p[imports].mul(w, axis=0).sum().sum()),
        "h2_from_smr_biomethane_mwh": float(sum(
            made[s] * share.get(expansion.electrical_zone(g.at[s, "bus"]), 0.0)
            for s in smr)),
    }


def mix_row(n, sigma, rung, fraction):
    """One row of the ladder table: what was built, what it cost, what it
    emitted, and the carbon price that made it so."""
    caps = expansion.capacity(n).sum()
    caps["battery"] = sum(
        mw for tech, mw in caps.items() if str(tech).startswith("battery_")
    )
    # Summed over the zones: every zone has its own blocks of each kind.
    shed = {}
    for g, c in n.generators.carrier.items():
        if str(c).startswith("shed_"):
            shed[c] = shed.get(c, 0.0) + float(
                (n.generators_t.p[g] * n.snapshot_weightings.objective).sum())
    # How much of TYNDP's candidate menu the model took. Worth carrying into
    # the results rather than inferring later: at the tight budgets it builds
    # most of what is on offer, which makes the MENU the binding constraint
    # rather than the economics, and the note has to say so.
    new_lines = n.links[n.links.carrier == "transmission_new"]
    row = {
        "rung": rung,
        "grid_offered_mw": float(new_lines.p_nom_max.sum()),
        "grid_built_mw": float(new_lines.p_nom_opt.sum()),
        # Two columns on purpose: a label stage 3 can print, and a number it
        # can sort and plot on an axis. One mixed-type column would make the
        # figures parse strings.
        "budget_fraction": "none" if fraction is None else fraction,
        "budget_share": float("nan") if fraction is None else float(fraction),
        "co2_price_eur_t": sigma,
        "system_cost_eur": float(n.objective),
        **cost_split(n),
        "emissions_t": expansion.system_emissions(n),
        "h2_store_mwh": float(expansion.h2_store_energy(n).sum()),
        **expansion.hydrogen_balance(n),
        **hydrogen_routes(n),
        **expansion.biomethane_use(n),
        **expansion.ev_balance(n),
        **{f"cap_{tech}_mw": float(mw) for tech, mw in caps.items()},
    }
    for carrier, mwh in shed.items():
        row[f"{carrier}_mwh"] = mwh
    return row


def run_ladder(costs_full, hours, aggregation):
    """Every rung at every budget point, each rung on its own baseline."""
    rows, baselines = [], {}
    # Every unconstrained case first: a rung's budget may be a fraction of
    # another rung's baseline, so all of them have to exist before any
    # constrained case can be posed.
    for rung, kwargs in RUNGS.items():
        base, _ = solve_case(f"{rung}_nocap", costs_full, hours,
                             aggregation=aggregation, **kwargs)
        baselines[rung] = expansion.system_emissions(base)
        print(f"{rung}: unconstrained emissions {baselines[rung] / 1e6:.2f} Mt")

    for rung in RUNGS:
        unconstrained = baselines[BASELINE_RUNG[rung]]
        print(f"{rung}: budgets from {BASELINE_RUNG[rung]}'s baseline "
              f"({unconstrained / 1e6:.2f} Mt)")
        for fraction in BUDGET_FRACTIONS:
            n, sigma = ladder_case(rung, fraction, baselines, costs_full,
                                   hours, aggregation)
            row = mix_row(n, sigma, rung, fraction)
            row["unconstrained_t"] = unconstrained
            row["baseline_rung"] = BASELINE_RUNG[rung]
            row["biomethane_shadow_eur_mwh"] = n.meta.get("biomethane_shadow")
            rows.append(row)
    return pd.DataFrame(rows), baselines


def ladder_case(rung, fraction, baselines, costs_full, hours, aggregation):
    """One scenario at one budget point, posed as the ladder poses it: a
    fraction of its baseline scenario's unconstrained emissions (None: no
    budget). After run_ladder() this only reads the cache."""
    if fraction is None:
        return solve_case(f"{rung}_nocap", costs_full, hours,
                          aggregation=aggregation, **RUNGS[rung])
    return solve_case(f"{rung}_cap{int(fraction * 100)}", costs_full, hours,
                      co2_budget=fraction * baselines[BASELINE_RUNG[rung]],
                      aggregation=aggregation, **RUNGS[rung])


def reference_case(rung, costs_full, hours, aggregation):
    """One scenario at the reference budget, posed as run_ladder() poses it,
    with the budget in tonnes alongside."""
    base, _ = solve_case(f"{BASELINE_RUNG[rung]}_nocap", costs_full, hours,
                         aggregation=aggregation, **RUNGS[BASELINE_RUNG[rung]])
    budget = REFERENCE_FRACTION * expansion.system_emissions(base)
    n, sigma = solve_case(
        f"{rung}_cap{int(REFERENCE_FRACTION * 100)}", costs_full, hours,
        co2_budget=budget, aggregation=aggregation, **RUNGS[rung],
    )
    return n, sigma, budget


def zone_detail(costs_full, hours, aggregation):
    """Built capacity by zone and technology at the reference budget: the
    reference scenario on its own (the map behind the ladder table), and
    every scenario in one long table."""
    frames = []
    for rung in RUNGS:
        n, _, _ = reference_case(rung, costs_full, hours, aggregation)
        frame = expansion.capacity(n)
        frame["h2_store_mwh"] = expansion.h2_store_energy(n)
        frame = frame.fillna(0.0)
        if rung == REFERENCE_RUNG:
            reference = frame
        frames.append(frame.assign(rung=rung).reset_index())
    return reference, pd.concat(frames, ignore_index=True).fillna(0.0)


# ---------------------------------------------------------------------------
# What the section's figures read, beside the ladder. Every table comes from
# the cached solves; nothing here solves.

# The budget points the figures show, and the zone whose prices and hours
# they follow (most of the demand in this footprint).
FIGURE_FRACTIONS = [None, MID_FRACTION, REFERENCE_FRACTION]
FIGURE_ZONE = "DE"
# The two weeks of the EV figure, Monday to Monday, in the reference weather
# year.
EV_WEEKS = {"summer": "2024-07-01", "winter": "2024-01-15"}

# What a figure calls each carrier. Batteries, pumped hydro and the cars
# move electricity in time and the demand blocks are demand, so none of
# them is a source.
SOURCE = {
    "nuclear": "nuclear", "lignite": "lignite", "coal": "coal", "oil": "oil",
    "CCGT": "gas", "OCGT": "gas", "ccgt": "gas", "ocgt": "gas",
    "biomass": "biomass", "waste": "waste", "geothermal": "geothermal",
    "ror": "hydro", "onwind": "wind_onshore", "wind_onshore": "wind_onshore",
    "offwind-ac": "wind_offshore", "wind_offshore": "wind_offshore",
    "solar": "solar", "solar_pv": "solar",
}


def budget_label(fraction):
    return "none" if fraction is None else fraction


def hourly_index():
    """The reference weather year hour by hour, as expansion.build() has it
    before cutting it into snapshots: what an hourly series is mapped
    through, and what dates each hour of a solved year."""
    n = greenfield.load_forward_network(NETWORK_NC)
    network.apply_weather(n, year_weather(REFERENCE_WEATHER_YEAR))
    return n.snapshots.copy()


def by_hour(n, frame, hourly):
    """A snapshot-indexed frame as one dated row per hour of the year
    (network.expand_to_hours)."""
    out = network.expand_to_hours(n, frame)
    if len(out) != len(hourly):
        raise ValueError(f"{len(out)} hours expanded for a {len(hourly)}-hour year")
    out.index = hourly
    return out


def generation_by_source(n):
    """Electricity generated in a year, MWh, by zone and source, existing
    plants and new apart, with gas-fired output split into natural gas and
    biomethane by biomethane_share()."""
    w = n.snapshot_weightings.objective
    made = n.generators_t.p.mul(w, axis=0).sum()
    rows = [(expansion.electrical_zone(g.bus), SOURCE[g.carrier],
             "new" if g.p_nom_extendable else "existing", float(made[name]))
            for name, g in n.generators.iterrows() if g.carrier in SOURCE]
    reservoirs = n.storage_units.index[n.storage_units.carrier == "hydro"]
    released = n.storage_units_t.p[reservoirs].clip(lower=0).mul(w, axis=0).sum()
    rows += [(n.storage_units.at[s, "bus"], "hydro", "existing", float(released[s]))
             for s in reservoirs]
    turbines = n.links.index[n.links.carrier == "h2_turbine"]
    if len(turbines):
        burnt = (-n.links_t.p1[turbines]).mul(w, axis=0).sum()
        rows += [(n.links.at[t, "bus1"], "hydrogen", "new", float(burnt[t]))
                 for t in turbines]
    frame = pd.DataFrame(rows, columns=["zone", "source", "vintage", "mwh"])
    share = frame.zone.map(biomethane_share(n)).fillna(0.0)
    gas = frame.source == "gas"
    bio = frame[gas].assign(source="biomethane", mwh=frame.mwh[gas] * share[gas])
    frame.loc[gas, "mwh"] *= 1.0 - share[gas]
    out = pd.concat([frame, bio], ignore_index=True)
    return out.groupby(["zone", "source", "vintage"], as_index=False).mwh.sum()


def effective_marginal_cost(n):
    """Each generator's marginal cost as its optimality condition sees it,
    c_g + sigma e_g, except for gas once the carbon price is above the
    switch price (switch_price()): then every MWh of gas a zone burns is
    biomethane, and a gas plant's marginal fuel is biomethane at its own
    price, whatever sigma is."""
    sigma = n.meta.get("co2_price")
    sigma = 0.0 if sigma is None or pd.isna(sigma) else float(sigma)
    rates = expansion.emission_rates(n, n._emission_rates)
    cost = n.generators.marginal_cost + sigma * rates
    gas = n.generators.carrier.isin(expansion.GAS_CARRIERS)
    premium = max(0.0, sigma - switch_price()) * greenfield.GAS_CO2_T_PER_MWH_TH
    cost[gas] -= premium * rates[gas] / greenfield.GAS_CO2_T_PER_MWH_TH
    return cost


def switch_price():
    """The carbon price at which a gas plant is indifferent between natural
    gas and biomethane, EUR/t: the fuel-price gap over the gas's CO2."""
    return ((expansion.BIOMETHANE_PRICE - greenfield.GAS_PRICE)
            / greenfield.GAS_CO2_T_PER_MWH_TH)


def price_setters(n, zone, tol=0.6):
    """For every snapshot, the zone's price and what sets it: a plant in the
    zone running between zero and its available capacity whose effective
    marginal cost is the price; failing that, an electrolyser, a battery or
    the cars running in between their limits, whose valuations are the
    price by their own optimality conditions. Otherwise the price is set
    outside the zone, across an uncongested wire, and the setter is left
    blank."""
    price = n.buses_t.marginal_price[zone]
    cost = effective_marginal_cost(n)
    gens = n.generators.index[n.generators.bus == zone]
    p = n.generators_t.p[gens]
    room = n.generators.loc[gens, "p_nom_opt"] * n.get_switchable_as_dense(
        "Generator", "p_max_pu")[gens]
    running = (p > 1e-3) & (p < room - 1e-3)
    at_cost = np.abs(cost[gens].to_numpy()[None, :] - price.to_numpy()[:, None]) < tol
    plant = running & at_cost

    def between(names, flow, nom):
        if not len(names):
            return pd.Series(False, index=n.snapshots)
        lo, hi = flow[names], nom[names]
        return ((lo.abs() > 1e-3) & (lo.abs() < hi - 1e-3)).any(axis=1)

    links = n.links
    electrolysers = links.index[(links.carrier == "electrolyser") & (links.bus0 == zone)]
    cars = links.index[links.carrier.isin(["ev_charger", "ev_v2g"])
                       & ((links.bus0 == zone) | (links.bus1 == zone))]
    batteries = n.storage_units.index[n.storage_units.carrier.str.startswith("battery_")
                                      & (n.storage_units.bus == zone)]
    link_room = links.p_nom_opt * n.get_switchable_as_dense("Link", "p_max_pu")
    others = [("electrolyser", between(electrolysers, n.links_t.p0, link_room)),
              ("battery", between(batteries, n.storage_units_t.p,
                                  n.storage_units.p_nom_opt)),
              ("cars", between(cars, n.links_t.p0, link_room))]
    setters = []
    for s in n.snapshots:
        names = sorted({n.generators.at[g, "carrier"] for g in gens[plant.loc[s].to_numpy()]})
        if not names:
            names = [label for label, flag in others if flag[s]]
        setters.append(",".join(names))
    return pd.DataFrame({"price_eur_mwh": price.round(1), "setter": setters,
                         "hours": n.snapshot_weightings.objective})


def fixed_charging(n, zone, hourly):
    """What the zone's passenger cars draw when they charge on arrival, MW per
    snapshot: the baseline's profile (expansion.add_ev), to set a smart
    scenario's charging against."""
    fleet = expansion.EV_FLEET[expansion.EV_FLEET["zone"] == zone]
    cars = fleet[fleet["flexible"].astype(str).str.lower().eq("true")]
    return float(cars["grid_twh"].sum()) * 1e6 * expansion.to_snapshots(
        n, hourly, expansion.EV_PROFILES[f"{zone}|arrival_passenger"])


def ev_series(n, zone, hourly):
    """One zone through the year, hour by hour: the price, what the passenger
    cars draw from the grid and give back, and what the batteries do."""
    links = n.links
    charger = links.index[(links.carrier == "ev_charger") & (links.bus0 == zone)]
    v2g = links.index[(links.carrier == "ev_v2g") & (links.bus1 == zone)]
    batteries = n.storage_units.index[n.storage_units.carrier.str.startswith("battery_")
                                      & (n.storage_units.bus == zone)]
    p = n.storage_units_t.p[batteries].sum(axis=1)
    frame = pd.DataFrame({
        "price_eur_mwh": n.buses_t.marginal_price[zone],
        "ev_charging_mw": (n.links_t.p0[charger].sum(axis=1) if len(charger)
                           else fixed_charging(n, zone, hourly)),
        "ev_v2g_mw": (-n.links_t.p1[v2g]).sum(axis=1) if len(v2g) else 0.0,
        "battery_charging_mw": (-p).clip(lower=0),
        "battery_discharging_mw": p.clip(lower=0),
    }, index=n.snapshots)
    return by_hour(n, frame, hourly)


def ev_statistics(n, hourly):
    """How the passenger cars use their freedom over a year, all zones: the
    share of their energy drawn at other times than on arrival, the average
    price they pay against what the arrival profile would pay at the same
    prices, and how often the store sits at its floor or its ceiling and the
    chargers at their limit (shares of the year)."""
    w = n.snapshot_weightings.objective
    links = n.links
    chargers = links.index[links.carrier == "ev_charger"]
    zones = links.loc[chargers, "bus0"]
    drawn = n.links_t.p0[chargers]
    price = n.buses_t.marginal_price[zones.to_list()].set_axis(chargers, axis=1)
    fixed = pd.DataFrame({c: fixed_charging(n, z, hourly) for c, z in zones.items()})
    stores = n.stores.index[n.stores.carrier == "ev_battery"]
    level = n.stores_t.e[stores].sum(axis=1)
    ceiling = float(n.stores.loc[stores, "e_nom"].sum())
    floor = (n.stores.loc[stores, "e_nom"]
             * n.get_switchable_as_dense("Store", "e_min_pu")[stores]).sum(axis=1)
    limit = (links.loc[chargers, "p_nom"]
             * n.get_switchable_as_dense("Link", "p_max_pu")[chargers]).sum(axis=1)

    def weighted(frame):
        return float(frame.mul(w, axis=0).sum().sum())

    def share_of_year(mask):
        return float(w[mask].sum()) / float(w.sum())

    v2g = links.index[links.carrier == "ev_v2g"]
    out = {
        "moved_share": weighted((drawn - fixed).clip(lower=0)) / weighted(fixed),
        "price_paid_eur_mwh": weighted(drawn * price) / weighted(drawn),
        "price_on_arrival_eur_mwh": weighted(fixed * price) / weighted(fixed),
        "store_full_share": share_of_year(level > 0.99 * ceiling),
        "store_at_floor_share": share_of_year(level < floor + 0.01 * ceiling),
        "chargers_at_limit_share": share_of_year(drawn.sum(axis=1) > 0.99 * limit),
        "store_mwh": ceiling,
    }
    if len(v2g):
        back = (-n.links_t.p1[v2g]).sum(axis=1)
        out |= {
            "v2g_out_mwh": float((back * w).sum()),
            "v2g_hours": float(w[back > 1e3].sum()),
            "v2g_peak_mw": float(back.max()),
            "v2g_mw": float(links.loc[v2g, "p_nom"].sum()),
            "store_min_share": float(level.min()) / ceiling,
        }
    return out


def deep_end(n, zone):
    """Why sigma sits where it does at the reference budget, beyond the
    switch price: every gas plant already burns biomethane, so the tonnes
    left are coal, and what pushes coal out in the hours it is marginal is a
    new gas turbine burning biomethane. That turbine's investment condition
    returns sigma (the section's eq:expansion:sigma-deep):

        sigma = (c_bio - c_coal + (F - R_other) / (gamma H)) / e_coal,

    with F its annual fixed cost, R_other the rent it earns in every other
    hour, H the hours coal is marginal in the zone and gamma its average
    availability in them."""
    sigma = float(n.meta["co2_price"])
    cost = effective_marginal_cost(n)
    rates = expansion.emission_rates(n, n._emission_rates)
    w = n.snapshot_weightings.objective
    price = n.buses_t.marginal_price[zone]
    g = n.generators
    turbine = g.index[(g.carrier == "ocgt") & (g.bus == zone) & g.p_nom_extendable]
    coal = g.index[(g.carrier == "coal") & (g.bus == zone)]
    if not len(turbine) or not len(coal):
        return None
    t = turbine[0]
    avail = n.get_switchable_as_dense("Generator", "p_max_pu")
    rent = (price - cost[t]).clip(lower=0) * avail[t] * w
    room = g.loc[coal, "p_nom_opt"] * avail[coal]
    p = n.generators_t.p[coal]
    marginal = pd.Series(False, index=n.snapshots)
    for c in coal:
        marginal |= ((p[c] > 1e-3) & (p[c] < room[c] - 1e-3)
                     & ((cost[c] - price).abs() < 0.6))
    hours = float(w[marginal].sum())
    if hours == 0:
        return None
    gamma = float((avail[t] * w)[marginal].sum()) / hours
    fixed = float(g.at[t, "capital_cost"])
    other = float(rent[~marginal].sum())
    c_coal = float((cost[coal] - sigma * rates[coal]).mean())
    e_coal = float(rates[coal].mean())
    return {
        "sigma_eur_t": sigma,
        "turbine_gw": float(g.at[t, "p_nom_opt"]) / 1e3,
        "turbine_fixed_eur_mw": fixed,
        "turbine_cost_eur_mwh": float(cost[t]),
        "coal_cost_eur_mwh": c_coal,
        "coal_rate_t_mwh": e_coal,
        "coal_marginal_hours": hours,
        "turbine_availability": gamma,
        "rent_other_eur_mw": other,
        "sigma_from_formula_eur_t": (float(cost[t]) - c_coal
                                     + (fixed - other) / (gamma * hours)) / e_coal,
    }


def wire_rents(n):
    """Each new corridor's congestion rent per MW over the year against its
    annual fixed cost (prop:wire): equal for every corridor built below its
    ceiling, above it for those at the ceiling."""
    w = n.snapshot_weightings.objective
    price = n.buses_t.marginal_price
    rows = []
    for name, row in n.links[n.links.carrier == "transmission_new"].iterrows():
        mw = float(row.p_nom_opt)
        if mw < 1.0:
            continue
        rent = float((w * n.links_t.p0[name]
                      * (price[row.bus1] - price[row.bus0])).sum()) / mw
        rows.append({"mw": mw, "ceiling": mw > float(row.p_nom_max) - 1.0,
                     "rent_over_cost": rent / float(row.capital_cost)})
    frame = pd.DataFrame(rows)
    inside, full = frame[~frame.ceiling], frame[frame.ceiling]
    return {
        "built_mw": float(frame.mw.sum()),
        "below_ceiling": int(len(inside)),
        "at_ceiling": int(len(full)),
        "max_gap_below_ceiling": float((inside.rent_over_cost - 1).abs().max())
        if len(inside) else None,
        "max_ratio_at_ceiling": float(full.rent_over_cost.max()) if len(full) else None,
    }


def hydrogen_months(n, zone, hourly):
    """The zone's hydrogen month by month, MWh: reformed (from natural gas
    and from biomethane, by biomethane_share()), imported, electrolysed and
    burnt for power, and its store's mean and highest level."""
    bus = f"{zone} H2"
    links, g = n.links, n.generators
    share = biomethane_share(n).get(zone, 0.0)
    smr = g.index[(g.carrier == "smr") & (g.bus == bus)]
    reformed = n.generators_t.p[smr].sum(axis=1)
    electrolysers = links.index[(links.carrier == "electrolyser") & (links.bus1 == bus)]
    turbines = links.index[(links.carrier == "h2_turbine") & (links.bus0 == bus)]
    stores = n.stores.index[n.stores.bus == bus]
    frame = pd.DataFrame({
        "reformed_gas_mwh": reformed * (1.0 - share),
        "reformed_biomethane_mwh": reformed * share,
        "imported_mwh": n.generators_t.p[g.index[(g.carrier == "h2_import")
                                                 & (g.bus == bus)]].sum(axis=1),
        "electrolysed_mwh": (-n.links_t.p1[electrolysers]).sum(axis=1),
        "to_power_mwh": (n.links_t.p0[turbines].sum(axis=1) if len(turbines) else 0.0),
        "store_mwh": (n.stores_t.e[stores].sum(axis=1) if len(stores) else 0.0),
    }, index=n.snapshots)
    hours = by_hour(n, frame, hourly)
    months = hours.drop(columns="store_mwh").resample("MS").sum()
    months["store_mean_mwh"] = hours["store_mwh"].resample("MS").mean()
    months["store_max_mwh"] = hours["store_mwh"].resample("MS").max()
    months.index = months.index.month
    months.index.name = "month"
    return months


def hydrogen_price(n, zone, hourly):
    """The zone's hydrogen price over the year, EUR/MWh: its mean, and its
    mean from March to September and from October to February."""
    price = by_hour(n, n.buses_t.marginal_price[[f"{zone} H2"]], hourly)[f"{zone} H2"]
    summer = price.index.month.isin(range(3, 10))
    return {"mean": float(price.mean()), "summer": float(price[summer].mean()),
            "winter": float(price[~summer].mean())}


def reformer_costs(n):
    """The reformer as the model prices it: its running cost on natural gas,
    EUR/MWh of hydrogen, its annual fixed cost, EUR/MW, and its CO2 per MWh
    of hydrogen. With an import step's price they return the carbon price
    where reforming is the margin (eq:expansion:sigma-import)."""
    smr = n.generators[n.generators.carrier == "smr"]
    return {"smr_marginal_cost_eur_mwh": float(smr.marginal_cost.iloc[0]),
            "smr_fixed_cost_eur_mw": float(smr.capital_cost.iloc[0]),
            "smr_emission_rate_t_mwh": expansion.smr_emission_rate()}


def figure_tables(baselines, costs_full, hours, aggregation):
    """Write the tables the section's figures read, and return the numbers
    the text quotes about them, for the summary."""
    hourly = hourly_index()
    zone = FIGURE_ZONE

    def case(rung, fraction):
        return ladder_case(rung, fraction, baselines, costs_full, hours,
                           aggregation)[0]

    generation, durations, setters, facts = [], {}, [], {}
    for rung in RUNGS:
        for fraction in BUDGET_FRACTIONS:
            n = case(rung, fraction)
            label = budget_label(fraction)
            generation.append(generation_by_source(n).assign(
                rung=rung, budget_fraction=label))
            if fraction not in FIGURE_FRACTIONS:
                continue
            key = f"{rung}|{label}"
            hourly_price = by_hour(n, n.buses_t.marginal_price[[zone]], hourly)[zone]
            durations[key] = hourly_price.sort_values(ascending=False).to_numpy()
            levels = (price_setters(n, zone).groupby(["price_eur_mwh", "setter"])
                      .hours.sum().reset_index())
            setters.append(levels.assign(rung=rung, budget_fraction=label))
            if rung == "basic":
                facts[f"wires_{label}"] = wire_rents(n)
            if fraction == REFERENCE_FRACTION and rung != "ev_h2":
                facts[f"deep_end_{rung}"] = deep_end(n, zone)
            if rung in ("ev", "ev_v2g") and fraction is not None:
                facts[f"cars_{rung}_{label}"] = ev_statistics(n, hourly)
            if rung == "ev_h2" and fraction is not None:
                facts[f"h2_price_{label}"] = hydrogen_price(n, zone, hourly)
            if rung == "ev_h2" and fraction == REFERENCE_FRACTION:
                facts |= reformer_costs(n)
    pd.concat(generation, ignore_index=True).to_csv(
        RESULTS / "expansion_generation.csv", index=False)
    pd.DataFrame(durations).round(2).to_csv(
        RESULTS / "expansion_price_duration.csv", index=False)
    pd.concat(setters, ignore_index=True).to_csv(
        RESULTS / "expansion_price_setters.csv", index=False)

    weeks = []
    for rung in ["basic", "ev", "ev_v2g"]:
        year = ev_series(case(rung, MID_FRACTION), zone, hourly)
        for name, start in EV_WEEKS.items():
            t0 = pd.Timestamp(start)
            week = year[(year.index >= t0) & (year.index < t0 + pd.Timedelta("7D"))]
            weeks.append(week.assign(rung=rung, week=name).rename_axis("hour"))
    pd.concat(weeks).to_csv(RESULTS / "expansion_ev_weeks.csv")

    hydrogen_months(case("ev_h2", REFERENCE_FRACTION), zone, hourly).to_csv(
        RESULTS / "expansion_hydrogen_months.csv")
    print("wrote results/expansion_generation.csv, expansion_price_duration.csv, "
          "expansion_price_setters.csv, expansion_ev_weeks.csv and "
          "expansion_hydrogen_months.csv")
    return facts


# What each full-year check compares, beside the carbon price and the bill.
CHECK_KEYS = {
    "ev_h2": ["h2_store_mwh", "cap_h2_turbine_mw", "cap_electrolyser_mw",
              "electrolyser_flh", "cap_battery_mw", "biomethane_total_mwh"],
    "ev_v2g": ["cap_battery_mw", "ev_charged_mwh", "ev_v2g_out_mwh",
               "biomethane_total_mwh", "grid_built_mw"],
}


def run_resolution_check(rung, costs_full, hours, aggregation):
    """Does the time aggregation move section 8's answer?

    A year cut into segments hides the variation inside each segment, which
    is where batteries earn, and it could misjudge a seasonal store or the
    cars' storing. So this solves one scenario at the reference budget at
    all 8760 hours, posed as the ladder poses it -- the same share of its
    baseline's unconstrained emissions, solved at the same resolution -- and
    writes the two answers side by side. (The Lab reads these solves and
    poses its own full-year and every-eighth-hour cases the same way.)
    Expensive: on Gurobi the hydrogen check took over six hours and the
    vehicle-to-grid one three (2026-10-17).
    """
    ladder = pd.read_csv(RESULTS / "expansion_ladder.csv")
    row = ladder[(ladder.rung == rung)
                 & (ladder.budget_share == REFERENCE_FRACTION)].iloc[0]
    base_rung = BASELINE_RUNG[rung]
    tag = f"{rung}_cap{int(REFERENCE_FRACTION * 100)}"
    # The full year is the full year under either scheme; "stride" keeps
    # the bare cache names expansion_{tag}_8760.nc.
    base, _ = solve_case(f"{base_rung}_nocap", costs_full, 8760,
                         aggregation="stride", **RUNGS[base_rung])
    budget = REFERENCE_FRACTION * expansion.system_emissions(base)
    n, sigma = solve_case(tag, costs_full, 8760, aggregation="stride",
                          co2_budget=budget, **RUNGS[rung])
    full = mix_row(n, sigma, rung, REFERENCE_FRACTION)
    # For the hydrogen scenario, the every-k-th-hour answer at the same size
    # too, the scheme the note's figures moved away from: keeping every
    # eighth hour loses most of the daily cycle (see model/network.py).
    stride = None
    if rung == "ev_h2" and aggregation != "stride":
        b, _ = solve_case(f"{base_rung}_nocap", costs_full, hours,
                          aggregation="stride", **RUNGS[base_rung])
        ns, sig = solve_case(
            tag, costs_full, hours, aggregation="stride",
            co2_budget=REFERENCE_FRACTION * expansion.system_emissions(b),
            **RUNGS[rung])
        stride = mix_row(ns, sig, rung, REFERENCE_FRACTION)
    keys = ["co2_price_eur_t", "system_cost_eur", "emissions_t",
            *CHECK_KEYS.get(rung, [])]
    check = {
        "rung": rung,
        "budget_fraction": REFERENCE_FRACTION,
        "budget_t_full": budget,
        "budget_t_sampled": float(row["unconstrained_t"]) * REFERENCE_FRACTION,
        "hours_sampled": hours,
        "aggregation_sampled": aggregation,
        "sampled": {k: float(row[k]) for k in keys if k in row.index},
        "full": {k: float(full[k]) for k in keys if k in full},
        "stride_same_hours": (
            {k: float(stride[k]) for k in keys if k in stride}
            if stride is not None else None),
    }
    # The hydrogen check keeps the name stage 3 has always read.
    name = ("expansion_resolution_check.json" if rung == "ev_h2"
            else f"expansion_resolution_check_{rung}.json")
    (RESULTS / name).write_text(json.dumps(check, indent=2), encoding="utf-8")
    print(f"resolution check, {rung}: sigma "
          f"{check['sampled']['co2_price_eur_t']:.0f} EUR/t at {hours} "
          f"{aggregation} vs {check['full']['co2_price_eur_t']:.0f} at 8760")
    print(f"wrote results/{name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=336,
                        help="snapshots the year is reduced to (default 336; "
                        "the note uses 1095)")
    parser.add_argument(
        "--aggregation", choices=network.AGGREGATION_SCHEMES, default="segments",
        help="how the year is reduced to --hours snapshots: chronological "
        "segments of varying length (segments, the default) or every k-th "
        "hour (stride); see model/network.py",
    )
    parser.add_argument(
        "--resolution-check", nargs="*", metavar="SCENARIO", default=None,
        choices=CHECK_RUNGS,
        help="additionally solve these scenarios (default: all of "
        f"{', '.join(CHECK_RUNGS)}) at the reference budget at full hourly "
        "resolution and record how far the aggregated answer sits from it "
        "(very expensive; run after the ladder)",
    )
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    costs_full = load_shared()

    ladder, baselines = run_ladder(costs_full, args.hours, args.aggregation)
    ladder.to_csv(RESULTS / "expansion_ladder.csv", index=False)
    print(f"wrote results/expansion_ladder.csv ({len(ladder)} rows)")

    detail, detail_all = zone_detail(costs_full, args.hours, args.aggregation)
    detail.to_csv(RESULTS / "expansion_zones.csv")
    detail_all.to_csv(RESULTS / "expansion_zones_all.csv", index=False)
    print(f"wrote results/expansion_zones.csv ({len(detail)} zones) and "
          "results/expansion_zones_all.csv")
    summary = {
        "hours": args.hours,
        "aggregation": args.aggregation,
        "rungs": list(RUNGS),
        "budget_fractions": ["none" if f is None else f
                             for f in BUDGET_FRACTIONS],
        "reference_fraction": REFERENCE_FRACTION,
        "mid_fraction": MID_FRACTION,
        "unconstrained_emissions_t": {k: v for k, v in baselines.items()},
        "reference_rung": REFERENCE_RUNG,
        "reference_budget_t": REFERENCE_FRACTION * baselines[REFERENCE_RUNG],
        "biomethane_potential_twh":
            greenfield.BIOMETHANE_POTENTIAL_MWH / 1e6,
        "biomethane_dropin": expansion.BIOMETHANE_DROP_IN,
        "biomethane_price_eur_mwh": expansion.BIOMETHANE_PRICE,
        "gas_price_eur_mwh": greenfield.GAS_PRICE,
        "gas_co2_t_per_mwh": greenfield.GAS_CO2_T_PER_MWH_TH,
        "cavern_zones": expansion.CAVERN_ZONES,
        "ev_participation": expansion.EV_PARTICIPATION,
        "forward_horizon": greenfield.FORWARD_HORIZON,
        "switch_price_eur_t": switch_price(),
        "figure_zone": FIGURE_ZONE,
        "ev_weeks": EV_WEEKS,
    }

    def write_summary():
        (RESULTS / "expansion_summary.json").write_text(
            json.dumps(summary, indent=2, default=float), encoding="utf-8")
        print("wrote results/expansion_summary.json")

    write_summary()
    # The full-year checks before the figures' tables, so that a fault in
    # a table cannot cost a check that took hours.
    if args.resolution_check is not None:
        for rung in args.resolution_check or CHECK_RUNGS:
            run_resolution_check(rung, costs_full, args.hours, args.aggregation)
    summary.update(figure_tables(baselines, costs_full, args.hours,
                                 args.aggregation))
    write_summary()


if __name__ == "__main__":
    main()
