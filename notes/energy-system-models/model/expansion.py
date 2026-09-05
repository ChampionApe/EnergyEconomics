"""Section 8: capacity expansion for the whole twelve-zone system.

Section 7 rebuilds Denmark and holds its neighbours fixed, under a Danish
CO2 budget. That is the right shape for learning what a capacity expansion
model *is* -- the margin that sets the carbon price is identifiable by hand,
and the budget's territorial edge is itself a lesson. It is not the shape the
literature works in. This module is the other one: every zone may build
beside the fleet it already has, and one CO2 budget covers all of them.

It is built in three rungs, so what each ingredient does is visible rather
than asserted:

    (i)   basic    twelve zones extendable, one EU-wide budget, no
                   industrial hydrogen at all; vehicles charge on a fixed
                   profile
    (ii)  + EV     the same system, the charging block's timing now a choice
    (iii) + H2     the industrial hydrogen sector AND the electrolytic route
                   -- reformers, imports, electrolyser, store and turbine

Rungs (i) and (ii) are the same system and differ only in flexibility, so
their costs, emissions and carbon prices compare directly. Rung (iii) is
deliberately NOT the same system: it carries an industrial hydrogen demand
the others do not have, because a Europe that declines to build a hydrogen
economy really is a smaller system, and inventing an "equivalent" electricity
demand for the others would presume the electrolysis that rung (iii) exists
to test. So (ii) -> (iii) is not a marginal-effect comparison. It answers
"what does adding the hydrogen economy do to the power system", and each
rung's budget is a fraction of ITS OWN unconstrained emissions.

Brownfield, not greenfield: existing plant is kept and is not retirable. The
capital is sunk, so a plant may simply not run -- and wiping twelve zones
would ask the model to re-invent Norwegian hydro.

Instance size is a parameter, as everywhere else in this note. The default
168-hour instance solves in well under a minute even at rung (iii).
"""

from pathlib import Path

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

# Annual electric-vehicle electricity demand per zone, TWh. Also from
# prepare.py, and also source-beside-used: Norway is not in the dataset and
# carries the mean share of the zones that are.
EV_DEMAND_TWH = pd.read_csv(
    PROCESSED / "ev_assumptions.csv", comment="#"
).set_index("zone")["ev_twh_used"]

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
# Lille Torup and Stenlille, while Norway and Sweden sit on crystalline
# bedrock with essentially none (Caglayan et al. 2020). So the two countries
# with salt get cavern costs and the two without get tanks, and the note says
# so rather than giving everyone the cheap number.
# The ceiling per zone, GWh of hydrogen, from TYNDP rather than from a list
# written by hand. Zones absent from the source get none, and every zone
# keeps the uncapped tank beside it, so "nobody builds tanks" stays a result.
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
# The electric-vehicle block.
#
# The fleet's annual energy is data; the flexibility is the model assumption,
# and it is a deliberately simple one. The block must meet its energy over a
# day and may choose the hours within it: a store sized at one day of demand,
# charged through a link with more power than the average draw needs, feeding
# a load that follows the zone's own load shape.
#
# The energy is carved OUT of the zone's load, never added to it. Every zone
# already carries a projected 2050 load (demand_zones_2050.csv), and the
# source counts road transport inside that total -- so adding an EV block on
# top would count the same electricity twice.
EV_STORE_DAYS = 1.0
# An aggregate fleet can charge much faster than its average draw: the link is
# sized at this multiple of mean charging power (or the carved profile's peak,
# whichever is larger, so the block is never infeasible by construction).
EV_CHARGER_HEADROOM = 3.0
# TYNDP's demand figures are metered at the grid, so charging losses are
# already inside them and the link is lossless.
EV_CHARGER_EFFICIENCY = 1.0


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
    """The hydrogen bus, its industrial demand and the reforming route that
    can serve it — in EVERY rung, so the ladder's rungs stay comparable.

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
    turbine, added to the hydrogen buses the sector already created. This is
    rung (ii)'s ingredient — the demand is not."""
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


def add_ev(n: pypsa.Network, flexible: bool) -> None:
    """The electric-vehicle charging block, in EVERY rung.

    The vehicles are not rung (iii)'s ingredient — their *flexibility* is.
    TYNDP counts vehicles outside its demand profiles, so the base load this
    model scales to does not contain them and they have to be added; and
    adding them in one rung only would make that rung a system with more
    demand than the rungs it is compared against, which is exactly what the
    hydrogen sector above is arranged to avoid.

    So both branches put the same energy into the system, and differ only in
    when it may be drawn:

      inflexible  the charging follows the zone's own load shape, added
                  straight onto the load. Cars charge when people are awake.
      flexible    the same energy on its own bus behind a charger and a
                  day's storage, so the model chooses the hours.
    """
    n.add("Carrier", "EV")
    weights = n.snapshot_weightings.objective
    for zone in n.buses.index:
        if zone not in n.loads_t.p_set.columns:
            continue
        energy_mwh = float(EV_DEMAND_TWH.get(zone, 0.0)) * 1e6
        if energy_mwh <= 0:
            continue
        load = n.loads_t.p_set[zone]
        served = float((load * weights).sum())
        if served <= 0:
            continue
        profile = load * (energy_mwh / served)

        if not flexible:
            n.loads_t.p_set[zone] = load + profile
            continue

        bus = f"{zone} EV"
        n.add("Bus", bus, carrier="EV")
        n.add("Load", f"{zone} EV charging", bus=bus, p_set=profile)
        mean_draw = float((profile * weights).sum() / weights.sum())
        n.add(
            "Link", f"{zone} EV charger", bus0=zone, bus1=bus,
            carrier="ev_charger", efficiency=EV_CHARGER_EFFICIENCY,
            p_nom=max(EV_CHARGER_HEADROOM * mean_draw, float(profile.max())),
        )
        n.add(
            "Store", f"{zone} EV battery", bus=bus, carrier="ev_battery",
            e_nom=EV_STORE_DAYS * 24.0 * mean_draw, e_cyclic=True,
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
    ev: bool = False,
    transmission: bool = False,
    r: float = greenfield.DISCOUNT_RATE,
    gas_price: float = greenfield.GAS_PRICE,
    aggregation: str = "segments",
    weather: pd.DataFrame | None = None,
    carbon_tax: float | None = None,
) -> pypsa.Network:
    """One rung of the ladder.

    `carbon_tax` charges every emitter in every zone tau EUR/t instead of
    (or on top of) a budget: the tax-versus-cap experiment of the
    uncertainty section, run on this system because here a cap binds.

    Every rung carries the hydrogen sector — an industrial demand and the
    reforming route that can serve it — and the vehicles. `p2x` adds the
    electrolytic route beside the reformers, and `ev` makes the charging
    block's timing a choice rather than a fixed profile. `hours` and
    `aggregation` decide how the year is reduced to snapshots
    (network.aggregate); `weather` puts the year on the zonal weather
    archive first, as section 7 does, so that sections 7-9 share one
    construction of the weather (network.apply_weather).
    """
    n = greenfield.load_forward_network(nc_path)
    if weather is not None:
        network_model.apply_weather(n, weather)
    network_model.aggregate(n, hours, aggregation)

    # Every zone moves to the forward horizon, not only Denmark: in a
    # European model, leaving eleven zones on 2024 demand would make
    # Denmark's answer an artefact of being the only electrified place on
    # the map.
    #
    # base_twh, not total_twh: TYNDP counts vehicles and electrolysis
    # outside its demand profiles, and so does this model -- the EV block is
    # added below and hydrogen is a sector of its own. Adding the base and
    # then adding them again would count both twice.
    greenfield.scale_load(n, list(n.loads_t.p_set.columns), column="base_twh")

    costs = greenfield.candidate_costs(costs_full, r=r, gas_price=gas_price)
    add_candidates(n, costs, costs_full, r)
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
    # In every rung, flexible in the last one -- see add_ev().
    add_ev(n, flexible=ev)
    if transmission:
        add_transmission(n, r)

    network_model.derate_outages(n)
    network_model.apply_ramp_limits(n)

    n._co2_budget = co2_budget
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
    Danish budget implies."""
    budget = getattr(n, "_co2_budget", None)
    rates = emission_rates(n, getattr(n, "_emission_rates"))

    def add_constraints(nw, snapshots):
        import xarray as xr

        m = nw.model
        p = m.variables["Generator-p"]
        gen_dim = next(d for d in p.dims if d != "snapshot")
        weight = xr.DataArray(
            nw.snapshot_weightings.objective.to_numpy(),
            coords={"snapshot": nw.snapshots},
        )

        if budget is not None:
            emitters = [g for g in nw.generators.index if rates.get(g, 0.0) > 0]
            rate = xr.DataArray(
                [rates[g] for g in emitters], coords={gen_dim: emitters},
            )
            expr = (p.sel({gen_dim: emitters}) * weight * rate).sum()
            m.add_constraints(expr <= budget, name="co2_budget")

        # The backstop is finite. Without this the model may switch any
        # number of peakers to biomethane, which is what bounds the carbon
        # price at the fuel-price gap over the gas plant's emission rate.
        # With it, that bound holds only while the ceiling is slack -- and
        # the dual below says whether it is.
        biogas = [g for g in nw.generators.index
                  if nw.generators.at[g, "carrier"] == greenfield.BIOMETHANE_CARRIER]
        if biogas:
            fuel = ((p.sel({gen_dim: biogas}) * weight).sum()
                    / greenfield.BIOMETHANE_EFFICIENCY)
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
    if budget is not None:
        return float(-n.model.constraints["co2_budget"].dual)
    return None


def system_emissions(n: pypsa.Network) -> float:
    """Realised annual CO2 across all twelve zones, tonnes."""
    rates = emission_rates(n, getattr(n, "_emission_rates"))
    w = n.snapshot_weightings.objective
    total = 0.0
    for name, rate in rates.items():
        if rate > 0:
            total += float((n.generators_t.p[name] * w).sum()) * rate
    return total


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
