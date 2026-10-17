"""Section 8: capacity expansion for the whole twelve-zone system.

Section 7 rebuilds Denmark from scratch beside neighbours that keep their
fleets, under a common carbon price. That is the right shape for learning
what a capacity expansion model *is* -- the margin that sets the carbon price
is identifiable by hand. It is not the shape the literature works in. This
module is the other one: every zone may build beside the fleet it already
has, and one CO2 budget covers all of them.

It is built as nested scenarios, so what each ingredient does is visible
rather than asserted:

    basic    twelve zones extendable, one EU-wide budget, buyable
             interconnectors, no industrial hydrogen; every vehicle charges
             on arrival
    ev       + smart charging: the passenger cars' batteries become a store
             between the grid and the driving
    ev_v2g   + vehicle-to-grid: that store may also discharge to the grid
             (a branch off ev; the hydrogen scenario does not have it)
    ev_h2    ev + the industrial hydrogen sector AND every route to meeting
             it -- reformers, imports, electrolyser, store and turbine

basic, ev and ev_v2g are the same system and differ only in flexibility, so
their costs, emissions and carbon prices compare directly. ev_h2 is
deliberately NOT the same system: it carries an industrial hydrogen demand
the others do not have, because a Europe that declines to build a hydrogen
economy really is a smaller system, and inventing an "equivalent" electricity
demand for the others would presume the electrolysis that ev_h2 exists to
test. So ev -> ev_h2 is not a marginal-effect comparison. It answers "what
does adding the hydrogen economy do to the power system", and ev_h2's budget
is a fraction of ITS OWN unconstrained emissions.

Biomethane is a drop-in fuel: every gas plant, existing or new, and every
reformer may burn it in place of natural gas, up to one ceiling for all
zones (solve()).

Brownfield, not greenfield: existing plant is kept and is not retirable. The
capital is sunk, so a plant may simply not run -- and wiping twelve zones
would ask the model to re-invent Norwegian hydro.

Instance size is a parameter, as everywhere else in this note. The default
168-hour instance solves in well under a minute even at rung (iii).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from model import greenfield
from model import network as network_model

NOTE = Path(__file__).resolve().parent.parent
PROCESSED = NOTE / "data" / "processed"

# The candidate menu, the published per-zone potentials and the helper that
# attaches candidates beside an existing fleet live in model/greenfield.py,
# where section 7 uses them for the neighbours; section 8 uses them for
# every zone.
POTENTIALS = greenfield.POTENTIALS
EXISTING_CARRIERS = greenfield.EXISTING_CARRIERS
candidate_headroom = greenfield.candidate_headroom
native_profile = greenfield.native_profile
add_candidates = greenfield.add_candidates

# The vehicle fleet per zone and vehicle type: counts, battery and charger
# sizes, and the energy each type draws from the grid in a year. Written by
# data/prepare.py from TYNDP's EV modelling inputs, source beside used;
# Norway is not in them and carries Sweden's fleet per head.
EV_FLEET = pd.read_csv(PROCESSED / "ev_fleet.csv", comment="#")
# Hour by hour over the year, one column per zone and series: driving,
# charging on arrival, the share of cars plugged in, and the minimum charge.
# Also from prepare.py; mapped onto the snapshots after the year is cut
# (to_snapshots), so the vehicles never move a segment boundary.
EV_PROFILES = pd.read_csv(PROCESSED / "ev_profiles.csv", comment="#",
                          index_col=0)

# Annual industrial hydrogen demand per zone, TWh of hydrogen. Same source
# family and the same source-beside-used format; see the hydrogen sector
# below for why this is the number that decides whether electrolysis pays.
H2_DEMAND_TWH = pd.read_csv(
    PROCESSED / "h2_assumptions.csv", comment="#"
).set_index("zone")["h2_twh_used"]

# ---------------------------------------------------------------------------
# The hydrogen sector.
#
# Hydrogen enters this model as a SECTOR, not as a storage gadget, and the
# distinction is the whole reason the section works. A first version gave the
# chain nothing to sell hydrogen to except its own turbine, and it was never
# built: the electrolyser could run at most about 2,000 hours a year to feed
# roughly 500 hours of generation, and at that utilisation its capital alone
# came to some 370 EUR per MWh of electricity delivered, against 224 for a
# biomethane peaker. An electrolyser is not expensive per MWh; it is
# expensive per MWh when it stands idle.
#
# So wherever the sector appears it arrives whole: a demand, and every route
# that can serve it -- reforming, imports, and (with p2x) electrolysis, a
# store and a turbine. The model then chooses between them, which is a
# question it can answer; "should we build a round-trip storage device
# nobody buys the storage medium from" was not.
#
# The sector is in rung (iii) only. That costs the ladder its marginal-effect
# reading and buys back an honest baseline -- see the module docstring.
#
# The turbine is an OCGT running on hydrogen rather than a fuel cell --
# cheaper capital, twenty-five years against ten, and it keeps hydrogen and
# biomethane the *same machine burning different fuel*, which is section 2's
# fuel-switching arithmetic and therefore checkable by hand.
#
# The storage cost is the assumption that decides how much seasonal hydrogen
# is worth holding. A salt cavern is a factor of twenty cheaper per kWh than
# a tank, and salt geology is not evenly distributed: Germany has by far
# Europe's largest cavern potential and Denmark has operating caverns at
# Lille Torup and Stenlille, while Norway sits on crystalline bedrock with
# none (Caglayan et al. 2020).
# The ceiling per zone, GWh of hydrogen, comes from TYNDP rather than from a
# list written by hand, and TYNDP gives the Swedish zones a cavern potential
# too. Zones absent from the source get none, and every zone keeps the
# uncapped tank beside it, so "nobody builds tanks" stays a result.
H2_STORE_CEILING_GWH = pd.read_csv(
    PROCESSED / "h2_storage_potential.csv", comment="#", index_col="zone"
)["max_gwh"]
CAVERN_ZONES = sorted(H2_STORE_CEILING_GWH.index[H2_STORE_CEILING_GWH > 0])
H2_STORE_CAVERN = "hydrogen storage underground"
H2_STORE_TANK = "hydrogen storage tank type 1 including compressor"
ELECTROLYSER = "electrolysis"
H2_TURBINE = "OCGT"

# Steam methane reforming: the way hydrogen is made today, and the
# alternative every rung has. Modelled as a generator on the hydrogen bus
# rather than a link, because this network prices fuel through marginal cost
# and carries no gas bus -- the same convention as every other fuel-burning
# machine in the note. Its CO2 is real and enters the budget, which is what
# makes the electrolytic route worth anything as the budget tightens.
SMR = "H2 production natural gas steam reforming"
# Efficiency is not in the kept parameter set, so it comes from TYNDP's own
# heat rate for the same plant: 4.74-5.18 GJ/MWh across the fleet, i.e. about
# 1.32-1.44 MWh of gas per MWh of hydrogen. The middle of that range is used
# and recorded in data/README.md.
SMR_EFFICIENCY = 0.72

# Hydrogen can also be bought. Leaving imports out would decide the answer --
# with only reforming and electrolysis on offer, a tight carbon budget forces
# electrolysis whatever it costs. Offering them without a quantity limit
# decides it the other way and just as artificially: a world that will sell
# any amount of zero-carbon hydrogen at a flat price is a backstop, and a
# backstop caps the carbon price and takes the whole market. A first version
# did exactly that and imported every terawatt-hour.
#
# So imports are a step supply curve, as TYNDP publishes them: one row per
# corridor, each a quantity at a price. The geography does the rest of the
# work -- only Germany has a corridor at all, about 19.7 GW against a
# European demand of 429 TWh, so Denmark and Sweden must reform or
# electrolyse their own.
H2_IMPORTS = pd.read_csv(PROCESSED / "h2_imports.csv", comment="#")

# Industrial hydrogen demand is taken as flat. Real industrial hydrogen use
# (refining, ammonia, steel) runs continuously and does not follow the
# electricity load; a flat profile is the honest simplification, and it is
# also the conservative one -- a demand that could shape itself around cheap
# power would flatter the electrolyser.
H2_DEMAND_FLAT = True

# ---------------------------------------------------------------------------
# The electric vehicles.
#
# Every scenario has the same vehicles drawing the same energy from the grid
# in a year, TYNDP's projection, ADDED to the zone's load: TYNDP counts
# vehicles outside its demand profiles, and so does this model. What changes
# between scenarios is when the passenger cars may charge, and whether they
# may give power back (add_ev()):
#
#   fixed  every vehicle charges on arrival, after Brown et al. (2018): a
#          third of each hour's driving is charged in that hour and a third
#          in each of the two that follow.
#   smart  the passenger cars' batteries become a store between the grid and
#          the driving, after Victoria et al. (2019) and PyPSA-Eur: one
#          charger per zone rated for every car and derated by the share
#          plugged in, losses on the way in, a minimum charge the store must
#          keep (TYNDP's profile), and a participation share of the
#          batteries made available to the system. Vans, buses and trucks
#          still charge on arrival: TYNDP models only passenger cars as
#          flexible vehicles.
#   v2g    smart, and the made-available store may also discharge to the
#          grid, through a link rated for the participating cars.
#
# The energy at the grid is TYNDP's figure in every mode, so the driving
# drain is that figure times the charging efficiency, and only V2G's round
# trips add to what the cars draw.
EV_MODES = ("fixed", "smart", "v2g")
# The share of the passenger cars' battery capacity made available to the
# system (Victoria et al. 2019; TYNDP has none).
EV_PARTICIPATION = 0.5
# V2G discharge carries the stationary battery's operating charge (section
# 4's c^s, the 0.1 EUR/MWh of greenfield.add_candidates()), so the cars do
# not cycle between hours of equal price.
V2G_MARGINAL_COST = 0.1

# ---------------------------------------------------------------------------
# Biomethane as a drop-in fuel, as in section 7 (greenfield.py,
# BIOMETHANE_DROP_IN): each zone may buy biomethane for its gas plants and
# reformers in place of natural gas, no more than they burn, under the one
# ceiling for all zones (solve()).
#
# Here every gas plant may, the new gas turbine and the reformers included,
# so the dedicated biomethane turbine would be the gas turbine twice over,
# and two identical options would leave the split between them arbitrary:
# build() removes it.
BIOMETHANE_DROP_IN = greenfield.BIOMETHANE_DROP_IN
GAS_CARRIERS = ("CCGT", "OCGT", "ccgt", "ocgt", "smr")
BIOMETHANE_PRICE = greenfield.BIOMETHANE_PRICE


def smr_emission_rate() -> float:
    """Tonnes of CO2 per MWh of hydrogen reformed from natural gas."""
    return greenfield.GAS_CO2_T_PER_MWH_TH / SMR_EFFICIENCY


def emission_rates_with_smr(costs: pd.DataFrame) -> pd.Series:
    """The candidate emission rates plus reforming's, which is what every
    caller actually needs: reforming is not a greenfield candidate but its
    CO2 is in the budget."""
    rates = costs["emission_rate"].copy()
    rates["smr"] = smr_emission_rate()
    return rates


def add_hydrogen_sector(n: pypsa.Network, costs_full: pd.DataFrame, r: float,
                        gas_price: float) -> float:
    """The hydrogen bus, its industrial demand and the routes that can serve
    it without electrolysis -- reforming and imports. The hydrogen scenario
    only (see build()).

    Returns steam methane reforming's emission rate in tonnes per MWh of
    hydrogen, which the caller must add to the network's emission rates or
    the CO2 budget will not see it.
    """
    smr = costs_full.loc[SMR]
    smr_capital = smr["investment"] * 1e3 * (
        greenfield.annuity(r, smr["lifetime"]) + smr.get("FOM", 0.0) / 100.0
    )
    smr_mc = gas_price / SMR_EFFICIENCY
    smr_rate = smr_emission_rate()

    n.add("Carrier", "H2")
    for zone in n.buses.index:
        if zone not in n.loads_t.p_set.columns:
            continue
        demand_mwh = float(H2_DEMAND_TWH.get(zone, 0.0)) * 1e6
        if demand_mwh <= 0:
            continue
        h2 = f"{zone} H2"
        n.add("Bus", h2, carrier="H2")
        hours = float(n.snapshot_weightings.objective.sum())
        n.add("Load", f"{zone} H2 industry", bus=h2,
              p_set=demand_mwh / hours)
        n.add(
            "Generator", f"{zone} smr", bus=h2, carrier="smr",
            p_nom_extendable=True,
            capital_cost=smr_capital, marginal_cost=smr_mc,
        )
        for _, corridor in H2_IMPORTS[H2_IMPORTS.zone == zone].iterrows():
            n.add(
                "Generator", f"{zone} h2 import {corridor.corridor}", bus=h2,
                carrier="h2_import", p_nom=float(corridor.p_nom_mw),
                marginal_cost=float(corridor.price_eur_per_mwh_h2),
            )
    return smr_rate


def add_p2x(n: pypsa.Network, costs_full: pd.DataFrame, r: float) -> None:
    """The electrolytic route: electrolyser, hydrogen store and hydrogen
    turbine, added to the hydrogen buses the sector already created
    (add_hydrogen_sector() brings the demand)."""
    el = costs_full.loc[ELECTROLYSER]
    tb = costs_full.loc[H2_TURBINE]
    el_capital = el["investment"] * 1e3 * (
        greenfield.annuity(r, el["lifetime"]) + el.get("FOM", 0.0) / 100.0
    )
    # A Link's p_nom is measured at bus0, which for the turbine is hydrogen.
    # technology-data prices an OCGT per MW of ELECTRICAL output, so both its
    # capital and its variable cost are multiplied by the efficiency to become
    # costs per MW of hydrogen input. Forgetting this charges the turbine
    # 1/eta = 2.4 times too much and quietly biases the model against the
    # hydrogen chain. (The electrolyser needs no such conversion: its bus0 is
    # electricity, and technology-data prices it per kW of electrical input.)
    tb_capital = tb["investment"] * 1e3 * (
        greenfield.annuity(r, tb["lifetime"]) + tb.get("FOM", 0.0) / 100.0
    ) * float(tb["efficiency"])
    tb_vom = (float(tb["VOM"]) if pd.notna(tb["VOM"]) else 0.0) * float(tb["efficiency"])

    store_capital = {}
    for kind, row_name in [("cavern", H2_STORE_CAVERN), ("tank", H2_STORE_TANK)]:
        row = costs_full.loc[row_name]
        store_capital[kind] = row["investment"] * 1e3 * (
            greenfield.annuity(r, row["lifetime"]) + row.get("FOM", 0.0) / 100.0
        )

    for zone in n.buses.index:
        h2 = f"{zone} H2"
        if h2 not in n.buses.index:
            continue          # no hydrogen demand in this zone, no chain
        n.add(
            "Link", f"{zone} electrolyser", bus0=zone, bus1=h2,
            carrier="electrolyser", p_nom_extendable=True,
            efficiency=float(el["efficiency"]), capital_cost=el_capital,
        )
        n.add(
            "Link", f"{zone} h2 turbine", bus0=h2, bus1=zone,
            carrier="h2_turbine", p_nom_extendable=True,
            efficiency=float(tb["efficiency"]), capital_cost=tb_capital,
            marginal_cost=tb_vom,
        )
        # Two stores, not one: the cheap cavern up to what the geology
        # allows, and an expensive tank with no ceiling beside it. The model
        # fills the cavern first and only reaches for the tank when it wants
        # more than the ground will hold -- which is the substitution the
        # old hand-written cavern list could not represent.
        ceiling = float(H2_STORE_CEILING_GWH.get(zone, 0.0)) * 1e3   # GWh->MWh
        if ceiling > 0:
            n.add(
                "Store", f"{zone} h2 cavern", bus=h2, carrier="h2_store_cavern",
                e_nom_extendable=True, e_nom_max=ceiling, e_cyclic=True,
                capital_cost=store_capital["cavern"],
            )
        n.add(
            "Store", f"{zone} h2 tank", bus=h2, carrier="h2_store_tank",
            e_nom_extendable=True, e_cyclic=True,
            capital_cost=store_capital["tank"],
        )


# ---------------------------------------------------------------------------
# Transmission.
#
# Everywhere else in this note the grid is given. Here it can be bought, from
# TYNDP's own candidate menu at TYNDP's own capex -- because a model that
# puts 2050 demand on a 2024 grid and then reports congestion is measuring
# its own assumption. What the menu does NOT contain is a 2050 reference
# grid: TYNDP publishes a starting grid and a set of options its cost-benefit
# analysis chooses among, so the only honest way to reach 2050 is to make the
# choice here. See data/prepare.py for why the reference grid itself is left
# alone rather than substituted for the network's line ratings.
#
# Six borders carry no candidates at all, every one of them inside Norway
# (NO1-NO2, NO1-NO3, NO1-NO5, NO1-SE3, NO2-NO5, NO3-NO5). That is TYNDP's
# zoning rather than a judgement about those corridors: southern Norway is
# one node there, so borders internal to it have no entry. They stay fixed,
# and some of them are among the largest in the system.
TRANSMISSION = pd.read_csv(
    PROCESSED / "transmission_candidates.csv", comment="#")
# Neither TYNDP nor technology-data carries a transmission lifetime in the
# kept parameter set, so the note states one: forty years and two per cent
# of investment a year, the usual convention for interconnectors and the
# same order as PyPSA-Eur's own.
TRANSMISSION_LIFETIME = 40.0
TRANSMISSION_FOM = 0.02
# New links are modelled lossless while the shipped DC fleet carries its
# three per cent. A bidirectional PyPSA link cannot represent a loss in both
# directions -- that is why load_network() splits the existing ones into
# directed pairs -- and splitting an EXTENDABLE link needs the two halves
# constrained to equal capacity. The simplification flatters new capacity by
# roughly three per cent of the energy it carries; the honest fix is the
# directed pair, and it is the first refinement if transmission turns out to
# matter to a conclusion.
TRANSMISSION_LOSSLESS_CANDIDATES = True


def add_transmission(n: pypsa.Network, r: float) -> None:
    """Committed reinforcements as fixed capacity, and the rest of TYNDP's
    candidates as increments the model may buy."""
    zones = set(n.buses.index)
    n.add("Carrier", "transmission_new")
    for _, row in TRANSMISSION.iterrows():
        z0, z1 = row["zone0"], row["zone1"]
        if z0 not in zones or z1 not in zones:
            continue
        name = f"{row['candidate']} ({z0}-{z1})"
        if row["kind"] == "committed":
            # Already paid for: it belongs to the grid, not to the menu.
            n.add("Link", f"{name} fwd", bus0=z0, bus1=z1,
                  p_nom=float(row["mw"]), p_min_pu=0.0,
                  efficiency=1.0 - network_model.HVDC_LOSS,
                  carrier="transmission_committed")
            n.add("Link", f"{name} rev", bus0=z1, bus1=z0,
                  p_nom=float(row["mw"]), p_min_pu=0.0,
                  efficiency=1.0 - network_model.HVDC_LOSS,
                  carrier="transmission_committed")
            continue
        capital = float(row["capex_eur_per_mw"]) * (
            greenfield.annuity(r, TRANSMISSION_LIFETIME) + TRANSMISSION_FOM)
        n.add(
            "Link", name, bus0=z0, bus1=z1, carrier="transmission_new",
            p_nom_extendable=True, p_nom_max=float(row["mw"]),
            p_min_pu=-1.0, efficiency=1.0, capital_cost=capital,
        )


def ev_mode(ev) -> str:
    """The charging mode a scenario asks for. False means "fixed" and True
    "smart", so callers written before vehicle-to-grid keep working."""
    if ev is None or ev is False:
        return "fixed"
    if ev is True:
        return "smart"
    if ev not in EV_MODES:
        raise ValueError(f"ev must be one of {EV_MODES}, got {ev!r}")
    return ev


def to_snapshots(n: pypsa.Network, hourly: pd.DatetimeIndex, values,
                 how: str = "mean") -> pd.Series:
    """Map an hourly series over the year onto the snapshots the year was cut
    into. `hourly` is the network's own hourly index from before the cut, in
    the order of `values`; each hour belongs to the snapshot at or before it,
    which holds for chronological segments and for every-k-th-hour sampling
    alike. `how` is "mean" for flows and shares, "max" for a floor, which a
    segment must then respect throughout (PyPSA-Eur's rule)."""
    values = np.asarray(values, dtype="float64")
    if len(values) != len(hourly):
        raise ValueError(f"{len(values)} hourly values for a {len(hourly)}-hour year")
    owner = np.searchsorted(n.snapshots.values, hourly.values, side="right") - 1
    grouped = pd.Series(values).groupby(owner)
    out = grouped.mean() if how == "mean" else grouped.max()
    out.index = n.snapshots[out.index.to_numpy()]
    return out.reindex(n.snapshots)


def add_ev(n: pypsa.Network, ev, hourly: pd.DatetimeIndex) -> None:
    """The electric vehicles, in EVERY scenario.

    The vehicles are not the EV scenario's ingredient -- their *flexibility*
    is. Every mode puts the same energy at the grid, TYNDP's projection for
    each vehicle type, so the scenarios differ only in when the passenger
    cars draw it and whether they give any back (the modes are described
    above EV_MODES). Vans, buses and trucks charge on arrival in every mode.
    """
    mode = ev_mode(ev)
    n.add("Carrier", "EV")

    def shape(zone, series, how="mean"):
        return to_snapshots(n, hourly, EV_PROFILES[f"{zone}|{series}"], how)

    for zone in n.buses.index:
        if zone not in n.loads_t.p_set.columns:
            continue
        fleet = EV_FLEET[EV_FLEET["zone"] == zone]
        if fleet.empty:
            continue
        flexible = fleet["flexible"].astype(str).str.lower().eq("true")
        cars, others = fleet[flexible], fleet[~flexible]

        others_mwh = float(others["grid_twh"].sum()) * 1e6
        if others_mwh > 0:
            n.loads_t.p_set[zone] += others_mwh * shape(zone, "arrival_other")
        cars_mwh = float(cars["grid_twh"].sum()) * 1e6
        if cars_mwh <= 0:
            continue
        if mode == "fixed":
            n.loads_t.p_set[zone] += cars_mwh * shape(zone, "arrival_passenger")
            continue

        eta = float(cars["efficiency"].iloc[0])
        bus = f"{zone} EV"
        n.add("Bus", bus, carrier="EV")
        n.add("Load", f"{zone} EV driving", bus=bus,
              p_set=eta * cars_mwh * shape(zone, "drive_passenger"))
        n.add(
            "Link", f"{zone} EV charger", bus0=zone, bus1=bus,
            carrier="ev_charger", efficiency=eta,
            p_nom=float((cars["units"] * cars["charge_kw"]).sum()) / 1e3,
            p_max_pu=shape(zone, "avail"),
        )
        n.add(
            "Store", f"{zone} EV battery", bus=bus, carrier="ev_battery",
            e_nom=EV_PARTICIPATION
            * float((cars["units"] * cars["battery_kwh"]).sum()) / 1e3,
            e_min_pu=shape(zone, "min_soc", how="max"), e_cyclic=True,
        )
        if mode == "v2g":
            n.add(
                "Link", f"{zone} V2G", bus0=bus, bus1=zone, carrier="ev_v2g",
                efficiency=eta, marginal_cost=V2G_MARGINAL_COST,
                p_nom=EV_PARTICIPATION
                * float((cars["units"] * cars["discharge_kw"]).sum()) / 1e3,
                p_max_pu=shape(zone, "avail"),
            )


def emission_rates(n: pypsa.Network, candidate_rates: pd.Series) -> pd.Series:
    """One emission rate per generator, tonnes per MWh of electricity:
    candidates on their own carrier's rate, the existing fleet on the
    re-priced network's."""
    shipped = network_model.emission_rates(n)
    out = {}
    for name, row in n.generators.iterrows():
        if row.p_nom_extendable and row.carrier in candidate_rates.index:
            out[name] = float(candidate_rates[row.carrier])
        else:
            out[name] = float(shipped.get(name, 0.0))
    return pd.Series(out)


def build(
    nc_path: Path,
    costs_full: pd.DataFrame,
    hours: int,
    co2_budget: float | None = None,
    hydrogen: bool = False,
    p2x: bool = False,
    ev: bool | str = False,
    transmission: bool = False,
    r: float = greenfield.DISCOUNT_RATE,
    gas_price: float = greenfield.GAS_PRICE,
    aggregation: str = "segments",
    weather: pd.DataFrame | None = None,
    carbon_tax: float | None = None,
) -> pypsa.Network:
    """One scenario.

    `carbon_tax` charges every emitter in every zone tau EUR/t, instead of
    or on top of a budget.

    Every scenario carries the vehicles; `ev` is their charging mode,
    "fixed" (or False), "smart" (or True) or "v2g" (add_ev()). `hydrogen`
    adds the hydrogen sector -- an industrial demand and the reforming and
    import routes that can serve it -- and `p2x` the electrolytic route
    beside them. `hours` and `aggregation` decide how the year is reduced to
    snapshots (network.aggregate); `weather` puts the year on the zonal
    weather archive first, as section 7 does, so that sections 7-9 share one
    construction of the weather (network.apply_weather).
    """
    n = greenfield.load_forward_network(nc_path)
    if weather is not None:
        network_model.apply_weather(n, weather)
    # The year hour by hour, kept before it is cut: the vehicles' profiles
    # are hourly, and to_snapshots() maps them onto the snapshots afterwards.
    hourly = n.snapshots.copy()
    network_model.aggregate(n, hours, aggregation)

    # Every zone moves to the forward horizon, not only Denmark: in a
    # European model, leaving eleven zones on 2024 demand would make
    # Denmark's answer an artefact of being the only electrified place on
    # the map.
    #
    # base_twh and transport_twh (Norway's ferries, shore power, rail and
    # short-haul flights), not total_twh: TYNDP counts vehicles and
    # electrolysis outside its demand profiles, and so does this model --
    # the EV block is added below and hydrogen is a sector of its own.
    # Adding the total and then adding them again would count both twice.
    greenfield.scale_load(n, list(n.loads_t.p_set.columns),
                          column=["base_twh", "transport_twh"])

    costs = greenfield.candidate_costs(costs_full, r=r, gas_price=gas_price)
    add_candidates(n, costs, costs_full, r)
    if BIOMETHANE_DROP_IN:
        # Any gas turbine may burn biomethane (solve()), so the dedicated
        # biomethane turbine would be the same machine offered twice.
        n.remove("Generator", n.generators.index[
            n.generators.carrier == greenfield.BIOMETHANE_CARRIER])
    greenfield.add_demand_blocks(n, block_zones=list(n.buses.index))
    # The hydrogen sector is a rung ingredient now, not a fixture. Rungs
    # without it are power systems with no industrial hydrogen at all --
    # a smaller system, so their cost and emissions are NOT comparable with
    # the hydrogen rung's. What stays comparable is what each builds and how
    # its carbon price behaves along its own budget path.
    if hydrogen or p2x:
        add_hydrogen_sector(n, costs_full, r, gas_price)
        if p2x:
            add_p2x(n, costs_full, r)
    # In every scenario; only the charging mode differs -- see add_ev().
    add_ev(n, ev, hourly)
    if transmission:
        add_transmission(n, r)

    network_model.derate_outages(n)
    network_model.apply_ramp_limits(n)

    n._co2_budget = co2_budget
    # solve() prices drop-in biomethane against the gas it replaces.
    n._gas_price = gas_price
    n.meta["gas_price"] = gas_price
    n.meta["ev_mode"] = ev_mode(ev)
    # Reforming burns gas to make hydrogen, so its emissions belong in the
    # budget like any other. It is not one of greenfield's candidates, so its
    # rate is appended here rather than coming from candidate_costs().
    n._emission_rates = emission_rates_with_smr(costs)
    if carbon_tax:
        rates = emission_rates(n, n._emission_rates)
        for name, rate in rates.items():
            if rate > 0:
                n.generators.at[name, "marginal_cost"] += carbon_tax * float(rate)
    n.meta["carbon_tax"] = carbon_tax
    return n


def solve(n: pypsa.Network) -> float | None:
    """Optimise under the system-wide CO2 budget and return its dual — the
    carbon price the whole twelve-zone system faces, rather than the price a
    Danish budget implies. Drop-in biomethane enters here as one variable
    for the year (see BIOMETHANE_DROP_IN); what the solve buys is kept in
    n.meta["biomethane_dropin_mwh"], which system_emissions() reads."""
    budget = getattr(n, "_co2_budget", None)
    rates = emission_rates(n, getattr(n, "_emission_rates"))
    gas_co2 = greenfield.GAS_CO2_T_PER_MWH_TH
    gas_price = getattr(n, "_gas_price", greenfield.GAS_PRICE)
    tax = float(n.meta.get("carbon_tax") or 0.0)
    # Per network, so an experiment can take biomethane away altogether.
    dropin_on = getattr(n, "_biomethane_dropin", BIOMETHANE_DROP_IN)

    def add_constraints(nw, snapshots):
        import xarray as xr

        m = nw.model
        p = m.variables["Generator-p"]
        gen_dim = next(d for d in p.dims if d != "snapshot")
        weight = xr.DataArray(
            nw.snapshot_weightings.objective.to_numpy(),
            coords={"snapshot": nw.snapshots},
        )

        # Drop-in biomethane, zone by zone (greenfield.add_biomethane_dropin).
        # A plant's fuel per MWh is its CO2 rate over the gas's, which is how
        # the rate table recovers it (the candidates leave PyPSA's efficiency
        # at one); the reformers sit on hydrogen buses, which belong to their
        # zone.
        dropin = {}
        gas = [g for g in nw.generators.index
               if nw.generators.at[g, "carrier"] in GAS_CARRIERS
               and rates.get(g, 0.0) > 0]
        if dropin_on and gas:
            dropin = greenfield.add_biomethane_dropin(
                m, nw, p, gen_dim, weight,
                {g: rates[g] / gas_co2 for g in gas}, gas_price,
                {z: tax for z in nw.buses.index}, zone_of=electrical_zone)

        if budget is not None:
            emitters = [g for g in nw.generators.index if rates.get(g, 0.0) > 0]
            rate = xr.DataArray(
                [rates[g] for g in emitters], coords={gen_dim: emitters},
            )
            expr = (p.sel({gen_dim: emitters}) * weight * rate).sum()
            for b in dropin.values():
                expr = expr - gas_co2 * b
            m.add_constraints(expr <= budget, name="co2_budget")

        # The biomethane is finite: one ceiling for all zones on what the
        # dedicated turbine burns (when there is one) and what is bought as
        # drop-in fuel together. While it is slack, the fuel switch bounds
        # the carbon price at the fuel-price gap over the gas's CO2; the dual
        # below says whether it is.
        biogas = [g for g in nw.generators.index
                  if nw.generators.at[g, "carrier"] == greenfield.BIOMETHANE_CARRIER]
        fuel = None
        if biogas:
            fuel = ((p.sel({gen_dim: biogas}) * weight).sum()
                    / greenfield.BIOMETHANE_EFFICIENCY)
        for b in dropin.values():
            fuel = 1.0 * b if fuel is None else fuel + b
        if fuel is not None:
            m.add_constraints(fuel <= greenfield.BIOMETHANE_POTENTIAL_MWH,
                              name="biomethane_potential")

    status, condition = n.optimize(
        solver_name=network_model.SOLVER, progress=False,
        transmission_losses=network_model.TRANSMISSION_LOSSES_SEGMENTS,
        solver_options=network_model.solver_options(ipm=True),
        extra_functionality=add_constraints,
    )
    if status != "ok":
        raise RuntimeError(f"expansion LP did not solve: {status} / {condition}")
    # Worth keeping even when it is zero: a slack ceiling is the statement
    # that the fuel-switching bound on the carbon price still holds.
    try:
        n.meta["biomethane_shadow"] = float(
            -n.model.constraints["biomethane_potential"].dual)
    except (KeyError, AttributeError):
        n.meta["biomethane_shadow"] = None
    n.meta["biomethane_dropin_mwh"] = greenfield.read_dropin(n)
    if budget is not None:
        return float(-n.model.constraints["co2_budget"].dual)
    return None


def system_emissions(n: pypsa.Network) -> float:
    """Realised annual CO2 across all twelve zones, tonnes: what the plants
    emit, less the natural gas that drop-in biomethane replaced."""
    rates = emission_rates(n, getattr(n, "_emission_rates"))
    w = n.snapshot_weightings.objective
    total = 0.0
    for name, rate in rates.items():
        if rate > 0:
            total += float((n.generators_t.p[name] * w).sum()) * rate
    return total - greenfield.GAS_CO2_T_PER_MWH_TH * greenfield.dropin_mwh(n)


def biomethane_use(n: pypsa.Network) -> dict:
    """Biomethane burnt in a year, MWh of fuel: in a dedicated turbine (when
    there is one) and as drop-in fuel, against the one ceiling, with the
    ceiling's shadow price."""
    w = n.snapshot_weightings.objective
    biogas = n.generators.index[
        n.generators.carrier == greenfield.BIOMETHANE_CARRIER]
    dedicated = (float((n.generators_t.p[biogas].sum(axis=1) * w).sum())
                 / greenfield.BIOMETHANE_EFFICIENCY) if len(biogas) else 0.0
    dropin = greenfield.dropin_mwh(n)
    return {
        "biomethane_dedicated_mwh": dedicated,
        "biomethane_dropin_mwh": dropin,
        "biomethane_total_mwh": dedicated + dropin,
        "biomethane_potential_mwh": greenfield.BIOMETHANE_POTENTIAL_MWH,
    }


def ev_balance(n: pypsa.Network) -> dict:
    """What the passenger cars drew from the grid and gave back in a year,
    MWh, and the size of what they made available: zero for the store and
    the links when the cars charge on arrival."""
    w = n.snapshot_weightings.objective
    charger = n.links.index[n.links.carrier == "ev_charger"]
    v2g = n.links.index[n.links.carrier == "ev_v2g"]
    store = n.stores.index[n.stores.carrier == "ev_battery"]

    def drawn(links):
        if not len(links) or "p0" not in n.links_t:
            return 0.0
        return float((n.links_t.p0[links].sum(axis=1) * w).sum())

    return {
        "ev_charged_mwh": drawn(charger),
        "ev_v2g_out_mwh": drawn(v2g),
        "ev_store_mwh": float(n.stores.loc[store, "e_nom"].sum()),
        "ev_charger_mw": float(n.links.loc[charger, "p_nom"].sum()),
        "ev_v2g_mw": float(n.links.loc[v2g, "p_nom"].sum()),
    }


def electrical_zone(bus: str) -> str:
    """The electrical bidding zone a bus belongs to. The hydrogen and EV
    buses are named after the zone they sit in, so a hydrogen turbine —
    whose bus0 is the hydrogen bus — is still capacity built in that zone,
    not in a thirteenth country."""
    for suffix in (" H2", " EV"):
        if bus.endswith(suffix):
            return bus[: -len(suffix)]
    return bus


def capacity(n: pypsa.Network) -> pd.DataFrame:
    """Optimised new capacity by zone and technology, MW — generators and
    battery power, plus the hydrogen chain's links where it is built."""
    rows = []
    for name, row in n.generators.iterrows():
        if row.p_nom_extendable:
            rows.append((electrical_zone(row.bus), row.carrier, float(row.p_nom_opt)))
    for name, row in n.storage_units.iterrows():
        if row.p_nom_extendable:
            rows.append((electrical_zone(row.bus), row.carrier, float(row.p_nom_opt)))
    for name, row in n.links.iterrows():
        if row.p_nom_extendable:
            rows.append((electrical_zone(row.bus0), row.carrier, float(row.p_nom_opt)))
    frame = pd.DataFrame(rows, columns=["zone", "carrier", "mw"])
    return frame.groupby(["zone", "carrier"]).mw.sum().unstack(fill_value=0.0)


def hydrogen_balance(n: pypsa.Network) -> dict:
    """Where the hydrogen came from and where it went, MWh of hydrogen.

    This is the section's central table in numbers: how much hydrogen the
    industry burned, how much of it was reformed from gas against
    electrolysed from power, how much was burned back for electricity, and
    how hard the electrolysers had to work to do it. The last one is the
    number that decides whether the chain pays -- an electrolyser is cheap
    per MWh only when it runs.
    """
    w = n.snapshot_weightings.objective
    # The industrial demand is a constant, so it lives in the static frame,
    # not the time-varying one; after a solve the realised series is in
    # loads_t.p and is the safer thing to read.
    industry = [l for l in n.loads.index if l.endswith("H2 industry")]
    if not industry:
        demand = 0.0
    elif set(industry) <= set(n.loads_t.p.columns):
        demand = float((n.loads_t.p[industry].sum(axis=1) * w).sum())
    else:
        demand = float(n.loads.loc[industry, "p_set"].sum()) * float(w.sum())
    out = {
        "h2_demand_mwh": demand,
        "h2_from_smr_mwh": 0.0,
        "h2_from_electrolysis_mwh": 0.0,
        "h2_to_power_mwh": 0.0,
        "electrolyser_flh": 0.0,
    }
    smr = [g for g, c in n.generators.carrier.items() if c == "smr"]
    if smr:
        out["h2_from_smr_mwh"] = float(
            (n.generators_t.p[smr].sum(axis=1) * w).sum())
    el = [l for l, c in n.links.carrier.items() if c == "electrolyser"]
    if el and "p1" in n.links_t:
        # p1 is the flow out at bus1, negative by PyPSA's sign convention.
        out["h2_from_electrolysis_mwh"] = float(
            (-n.links_t.p1[el].sum(axis=1) * w).sum())
        mw = float(n.links.loc[el, "p_nom_opt"].sum())
        drawn = float((n.links_t.p0[el].sum(axis=1) * w).sum())
        # Guard against 0/0: an unbuilt electrolyser comes back as solver
        # noise (5e-11 MW drawing 6e-08 MWh), and dividing those gives a
        # confident-looking four-digit utilisation for a machine that does
        # not exist. One MW is far below anything the model would build.
        out["electrolyser_flh"] = drawn / mw if mw > 1.0 else 0.0
    tb = [l for l, c in n.links.carrier.items() if c == "h2_turbine"]
    if tb and "p0" in n.links_t:
        out["h2_to_power_mwh"] = float(
            (n.links_t.p0[tb].sum(axis=1) * w).sum())
    return out


def h2_store_energy(n: pypsa.Network) -> pd.Series:
    """Built hydrogen storage energy per zone, MWh — zero when the rung has
    no hydrogen chain."""
    rows = n.stores.index[n.stores.carrier.astype(str).str.startswith("h2_store")]
    out = {}
    for name in rows:
        # A zone may hold both a cavern and a tank, so accumulate: assigning
        # would silently report whichever the index happened to reach last.
        zone = n.stores.loc[name, "bus"].replace(" H2", "")
        out[zone] = out.get(zone, 0.0) + float(n.stores.loc[name, "e_nom_opt"])
    return pd.Series(out, dtype=float)
