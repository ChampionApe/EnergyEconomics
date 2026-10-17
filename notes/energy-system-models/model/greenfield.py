"""Greenfield capacity expansion — the model of section 7.

The 12-bidding-zone network with the two Danish zones wiped clean: in DK1
and DK2 every capacity is a *choice variable*. PyPSA expresses this as
`p_nom_extendable=True` with a `capital_cost` — the annualised cost of a MW,

    capital_cost = investment * (annuity(r, lifetime) + FOM)
    annuity(r, n) = r / (1 - (1 + r)^-n)          (eq:investment:annuity)

so the objective becomes total annual system cost, capital plus operations,
and the LP trades the two off. Section 7.1 derives the annuity. The
investment numbers come from PyPSA's technology-data at a pinned tag and the
fuel prices from the forward fuel table, both written by data/prepare.py
for FORWARD_HORIZON (below). Each wind and solar candidate inherits the
availability profile of the same technology already standing in its zone,
so candidate weather is always the neighbours' weather: the network's own
2024 profiles, or the year from the zonal weather archive that build() is
given.

Carbon enters as a price: build(ets_price=...) charges every emitter in
every zone the same EUR/t. ETS_PRICE is the reference level, and section 7
sweeps it. The other instrument is a CO2 budget on Danish generation, one
extra constraint whose dual is the carbon price that would decentralise the
plan: section 2's cap, now setting the capacity mix rather than reshuffling
a fixed one. Section 7 uses it for one scenario, with no price on anyone.

Denmark's candidates are capped at the published potentials every zone
uses (P_NOM_MAX, below), and the biomethane all zones may burn has one
ceiling, as in section 8 (solve()).

The neighbours keep the fleets they have and may add to them from the same
candidate menu, capped at their published potentials, and pay the same
carbon price: the question the model answers is what Denmark should build,
given a neighbourhood that is itself adapting to the horizon's demand.
(Freezing the neighbours' fleets at 2024 while every zone carries 2050
demand, which neighbours_extendable=False still does, puts southern Norway
at the value of lost load in every hour of the year, and every Danish
export price with it.)
"""

import logging
import warnings
from pathlib import Path

import pandas as pd
import pypsa

from model import network as network_model

logging.getLogger("pypsa").setLevel(logging.ERROR)
logging.getLogger("linopy").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning)

DISCOUNT_RATE = 0.07

# ---------------------------------------------------------------------------
# The forward horizon.
#
# Sections 2-6 describe the system as it is, on 2024 weather, the 2024 fleet
# and today's fuel prices. Sections 7-9 ask what should be BUILT, which is a
# question about a year that has not happened yet, so they read the forward
# tables data/prepare.py writes at FORWARD_HORIZON: fuel prices, technology
# costs, buildable potentials, hydrogen and EV demand, and electricity
# demand. Sections 2-6 are untouched by any of it.
#
# Demand in particular used to be an assumed doubling of 2024 load, defended
# on the grounds that today's Danish load fits through the interconnectors
# and makes the question degenerate. The defence was sound and the number
# was invented. It is now TYNDP's own annual total per zone, mapped onto the
# network's 2024 hourly shape -- the shape ours because the weather is ours,
# the level theirs because the level is a scenario. The moves it replaces a
# flat factor of two with run from 0.97 (DK2) to 3.02 (SE1).
FORWARD_HORIZON = 2050

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def _forward(name: str, index: str) -> pd.DataFrame:
    return pd.read_csv(PROCESSED_DIR / name, comment="#", index_col=index)


FORWARD_FUELS = _forward(f"fuel_assumptions_{FORWARD_HORIZON}.csv", "carrier")
FORWARD_COSTS = _forward(
    f"technology_costs_full_{FORWARD_HORIZON}.csv", "technology")
DEMAND_TOTALS = _forward(f"demand_zones_{FORWARD_HORIZON}.csv", "zone")

# Offshore wind costs more in some zones than in Denmark, and the DEA number
# this note prices it with is Denmark's. See data/prepare.py for how the
# multiplier is built from IRENA's country costs and why it is corrected for
# capacity factor rather than taken raw.
OFFSHORE_PREMIUM = _forward("offshore_cost_premium.csv", "zone")["premium"]
OFFSHORE_CANDIDATE = "wind_offshore"


def offshore_premium(zone: str) -> float:
    """The multiplier on offshore capital cost in `zone`; 1.0 elsewhere."""
    return float(OFFSHORE_PREMIUM.get(zone, 1.0))

# How much biomethane the twelve zones may burn between them, MWh of fuel a
# year. Sourced and allocated in data/prepare.py, which also records why the
# allocation is ours rather than TYNDP's. Leaving this uncapped is what makes
# the fuel-switching backstop bound the carbon price; capping it means the
# bound holds only while the ceiling is slack.
BIOMETHANE_POTENTIAL_MWH = float(
    _forward("biomethane_potential.csv", "eu_potential_twh")
    ["potential_twh_used"].iloc[0]) * 1e6
BIOMETHANE_CARRIER = "ocgt_biogas"
# The candidates price fuel through marginal_cost and leave the PyPSA
# efficiency at one, so fuel burnt has to be recovered from the cost table.
BIOMETHANE_EFFICIENCY = float(FORWARD_COSTS.loc["OCGT", "efficiency"])


def _fuel(carrier: str, field: str) -> float:
    return float(FORWARD_FUELS.loc[carrier, field])


GAS_PRICE = _fuel("gas", "price_used_eur_per_mwh_th")
GAS_CO2_T_PER_MWH_TH = _fuel("gas", "co2_used_t_per_mwh_th")

# Biomethane as a drop-in fuel (sections 7 and 8; add_biomethane_dropin()).
#
# Biomethane is pipeline gas: a gas plant may burn it in place of natural
# gas, at its own price, and the CO2 of the gas it replaces is not emitted.
# So each zone may buy B_z MWh of it a year for its gas plants, no more than
# they burn, and all zones share one ceiling with the dedicated biomethane
# turbine. Per tonne avoided this costs (p_bio - p_gas) / e_gas whichever
# plant burns it, section 2's fuel-switching price: a carbon price above it
# makes the switch, and under a budget it is a plateau in the dual while the
# ceiling is slack.
#
# The new gas turbine is left out here because the dedicated biomethane
# turbine already is its biomethane twin, and two identical machines would
# make the split between them arbitrary. Section 8, which has no dedicated
# turbine, passes its own list (expansion.py).
BIOMETHANE_DROP_IN = True
BIOMETHANE_PRICE = _fuel("biomethane", "price_used_eur_per_mwh_th")
DROPIN_CARRIERS = ("CCGT", "OCGT", "ccgt")

# The reference carbon price, EUR/t: the EU ETS at the level section 2 uses
# for its carbon-tax experiment (the range of recent allowance prices).
# build() charges it on every emitter in every zone, existing plant and
# candidate alike. Section 7 sweeps the price around this level, and its
# Danish-budget scenario sets it to zero and puts a territorial CO2 budget
# on Danish generation instead. Without a price, the neighbours, free to
# build under a 2050 load, put up tens of gigawatts of unpriced gas and keep
# their coal running, which is the world that scenario's leakage comes from.
ETS_PRICE = 85.0


def load_forward_network(nc_path: Path) -> pypsa.Network:
    """The shipped network priced at the forward horizon rather than today."""
    return network_model.load_network(
        nc_path, fuels=FORWARD_FUELS, costs=FORWARD_COSTS)


def scale_load(n: pypsa.Network, zones, column="base_twh") -> dict:
    """Scale each zone's load so its annual energy is the forward horizon's
    total, leaving the 2024 shape alone. `column` is the DEMAND_TOTALS
    column that holds the total, or a list of columns that add up to it.
    Must be called after subsample(), because annual energy is the weighted
    sum. Returns the factors applied, which are worth printing: they are
    the assumption this replaces.
    """
    columns = [column] if isinstance(column, str) else list(column)
    weights = n.snapshot_weightings.objective
    factors = {}
    for zone in zones:
        if zone not in n.loads_t.p_set.columns or zone not in DEMAND_TOTALS.index:
            continue
        served = float((n.loads_t.p_set[zone] * weights).sum())
        if served <= 0:
            continue
        factor = float(DEMAND_TOTALS.loc[zone, columns].sum()) * 1e6 / served
        n.loads_t.p_set[zone] *= factor
        factors[zone] = factor
    return factors


BATTERY_HOURS = 4.0
# Section 7 offers batteries at several durations: PyPSA prices power
# (inverter) and energy (cells) separately, so duration is a real choice,
# and it connects section 4's duration lesson to the expansion problem.
BATTERY_MENU_HOURS = [2.0, 4.0, 8.0]

DK_ZONES = ["DK1", "DK2"]

# Candidate technologies: note name -> technology-data name, and the
# network's native carriers whose availability profile each candidate
# inherits (first one present in the zone wins).
#
# Two candidates exist to be *declined or barely used*, and that is their
# job: `nuclear` demonstrates that at the horizon's costs the LP builds
# none, and `ocgt_biogas` — the same machine as `ocgt` burning biomethane at
# zero fossil CO2 — is the fuel-switching margin. Once the carbon price
# passes the fuel-price gap divided by the gas plant's emission rate
# (section 2's fuel-switching arithmetic), the peakers burn biomethane.
# Under a CO2 budget that margin is a plateau in the budget's dual, not a
# ceiling: it holds the price only while there is peaker gas left to switch
# (section 7.4).
CANDIDATES = {
    "solar_pv": "solar-utility",
    "wind_onshore": "onwind",
    "wind_offshore": "offwind",
    "ccgt": "CCGT",
    "ocgt": "OCGT",
    "ocgt_biogas": "OCGT",
    "nuclear": "nuclear",
}
# Which fuel from fuel_assumptions.csv each fuel-burning candidate uses.
CANDIDATE_FUEL = {
    "ccgt": "gas",
    "ocgt": "gas",
    "ocgt_biogas": "biomethane",
    "nuclear": "uranium",
}
NATIVE_PROFILE = {
    "solar_pv": ["solar", "solar-hsat"],
    "wind_onshore": ["onwind"],
    "wind_offshore": ["offwind-ac", "offwind-dc", "offwind-float"],
}

# Published buildable potential per zone, MW — the land/NIMBY constraint:
# the smaller of the most ambitious published trajectory and what the land
# allows. Written by data/prepare.py, which records both sources beside the
# used value; see data/README.md.
POTENTIALS = pd.read_csv(
    PROCESSED_DIR / "potentials_zones.csv", comment="#"
).set_index(["zone", "technology"])["p_nom_max_used_mw"]

# The two greenfield zones are capped by the same published potentials as
# every other zone, here and in section 8, so that the two sections differ
# by what they add and not by their land. Wiped clean, Denmark has no
# existing plant to count against them, so each cap is the whole potential.
# (Until 2026-10-16 these were the note's own stylised round numbers.)
P_NOM_MAX = {
    zone: {tech: float(POTENTIALS[(zone, tech)])
           for tech in ("solar_pv", "wind_onshore", "wind_offshore")}
    for zone in DK_ZONES
}

# The existing carriers whose capacity counts against each candidate's cap
# (the potentials are ceilings on *total* capacity in a zone) and whose
# availability profile the candidate inherits.
EXISTING_CARRIERS = NATIVE_PROFILE


def candidate_headroom(n: pypsa.Network, zone: str, tech: str) -> float:
    """MW of `tech` still buildable in `zone`: the potential less what is
    already standing there. Zero means either the cap is used up or the
    exported network has no generator of this kind in this zone -- in which
    case there is no availability profile to build on either."""
    ceiling = float(POTENTIALS.get((zone, tech), 0.0))
    if ceiling <= 0:
        return 0.0
    existing = n.generators[
        (n.generators.bus == zone)
        & (n.generators.carrier.isin(EXISTING_CARRIERS[tech]))
    ].p_nom.sum()
    return max(0.0, ceiling - float(existing))


def native_profile(n: pypsa.Network, zone: str, tech: str):
    """The zone's own availability profile for a variable candidate, taken
    from the existing generator of that kind. Returns None for dispatchable
    candidates and where the network has no such generator."""
    for carrier in EXISTING_CARRIERS.get(tech, []):
        match = n.generators.index[
            (n.generators.bus == zone) & (n.generators.carrier == carrier)
        ]
        if len(match) and match[0] in n.generators_t.p_max_pu.columns:
            return n.generators_t.p_max_pu[match[0]].copy()
    return None


def add_candidates(n: pypsa.Network, costs: pd.DataFrame, costs_full: pd.DataFrame,
                   r: float, zones=None) -> None:
    """Give `zones` (every zone with a load, by default) the candidate menu
    beside the fleet they already have, each variable candidate capped at
    its headroom under the published potential. Used for the neighbours in
    section 7 and for every zone in section 8."""
    if zones is None:
        zones = list(n.buses.index)
    for zone in zones:
        if zone not in n.loads_t.p_set.columns:
            continue
        for name, c in costs.iterrows():
            kwargs = {}
            if name in EXISTING_CARRIERS:
                profile = native_profile(n, zone, name)
                if profile is None:
                    continue        # no profile, no candidate
                headroom = candidate_headroom(n, zone, name)
                if headroom <= 0:
                    continue
                kwargs["p_max_pu"] = profile
                kwargs["p_nom_max"] = headroom
            n.add(
                "Generator", f"{zone} {name}", bus=zone, carrier=name,
                p_nom_extendable=True,
                capital_cost=c["fixed_eur_mw_yr"] * (
                    offshore_premium(zone)
                    if name == OFFSHORE_CANDIDATE else 1.0),
                marginal_cost=c["marginal_cost"],
                **kwargs,
            )
        for hours_b in BATTERY_MENU_HOURS:
            n.add(
                "StorageUnit", f"{zone} battery {hours_b:g}h", bus=zone,
                carrier=f"battery_{hours_b:g}h",
                p_nom_extendable=True, max_hours=hours_b,
                efficiency_store=0.95, efficiency_dispatch=0.95,
                cyclic_state_of_charge=True, marginal_cost=0.1,
                capital_cost=battery_capital_cost(costs_full, r=r, hours=hours_b),
            )

# ---------------------------------------------------------------------------
# Flexible demand: a step demand curve, kept linear.
#
# PyPSA loads are not price-responsive, so demand elasticity enters by the
# standard substitution trick: the load keeps its full fixed profile and a
# "shedding" generator per consumer block sits at the same bus, dispatching
# *curtailed demand* at a marginal cost equal to the block's willingness to
# pay. The objective then maximises surplus rather than minimising the cost
# of serving everything, the zonal price is still the market-clearing dual,
# and in scarcity hours it clears at the marginal block's WTP.
#
# Every zone carries the last-resort block at the value of lost load
# (Danish Energy Agency 2023 survey, EENS-weighted average across sectors),
# which also guarantees feasibility. The two cheap Danish blocks are sized
# as shares of the hourly load ("you can only shed demand that is there"):
# flexible industry and power-to-heat, whose WTP sits in the 40-150 EUR/MWh
# band, and interruptible heavy industry, whose surveyed valuations run
# from ~700 (basic metals) to ~11,400 EUR/MWh (large industry, DEA 2023) —
# one level inside each range is used here.
VOLL_EUR_MWH = 23400.0
DK_DEMAND_BLOCKS = [
    # carrier, share of hourly load, WTP EUR/MWh
    ("shed_flex", 0.05, 100.0),
    ("shed_industry", 0.10, 3000.0),
]


def add_demand_blocks(n: pypsa.Network, block_zones=None) -> None:
    """Attach the shedding generators: the VoLL backstop in every zone, the
    two cheap consumer blocks in `block_zones` (the Danish zones by default;
    sections 7 and 9 both pass every zone, because leaving eleven zones with
    no demand response would show up as a Danish artefact)."""
    if block_zones is None:
        block_zones = DK_ZONES
    for zone in n.buses.index:
        if zone not in n.loads_t.p_set.columns:
            continue
        d = n.loads_t.p_set[zone]
        peak = float(d.max())
        profile = (d / peak).clip(upper=1.0)
        blocks = (DK_DEMAND_BLOCKS if zone in block_zones else [])
        for carrier, share, wtp in blocks:
            n.add(
                "Generator", f"{zone} {carrier}", bus=zone, carrier=carrier,
                p_nom=share * peak, p_max_pu=profile, marginal_cost=wtp,
            )
        n.add(
            "Generator", f"{zone} shed_voll", bus=zone, carrier="shed_voll",
            p_nom=peak, p_max_pu=profile, marginal_cost=VOLL_EUR_MWH,
        )


def annuity(r: float, lifetime: float) -> float:
    """The annuity factor (eq:investment:annuity): the constant annual
    payment per unit borrowed that exactly repays it over the lifetime."""
    return r / (1.0 - (1.0 + r) ** -lifetime)


def candidate_costs(costs_full: pd.DataFrame, r: float = DISCOUNT_RATE,
                    gas_price: float = GAS_PRICE) -> pd.DataFrame:
    """Per candidate: annualised fixed cost (EUR/MW/yr), marginal cost
    (EUR/MWh) and emission rate (t/MWh) — the three numbers a screening
    curve needs."""
    rows = {}
    for name, td in CANDIDATES.items():
        row = costs_full.loc[td]
        fixed = row["investment"] * 1000.0 * (
            annuity(r, row["lifetime"]) + row.get("FOM", 0.0) / 100.0
        )
        fuel = CANDIDATE_FUEL.get(name)
        vom = float(row["VOM"]) if pd.notna(row["VOM"]) else 0.0
        if fuel is None:
            mc = vom
            e = 0.0
        else:
            # `gas_price` stays a parameter so the scenario sweep can move
            # it; the other fuels come straight from the shared fuel file.
            price = gas_price if fuel == "gas" else _fuel(
                fuel, "price_used_eur_per_mwh_th")
            mc = price / row["efficiency"] + vom
            e = _fuel(fuel, "co2_used_t_per_mwh_th") / row["efficiency"]
        rows[name] = {"fixed_eur_mw_yr": float(fixed), "marginal_cost": float(mc),
                      "emission_rate": float(e)}
    return pd.DataFrame(rows).T


def battery_capital_cost(costs_full: pd.DataFrame, r: float = DISCOUNT_RATE,
                         hours: float = BATTERY_HOURS) -> float:
    """EUR per MW-year for a battery of the given duration: inverter plus
    `hours` times the storage cost, each annuitised over its own lifetime."""
    inv = costs_full.loc["battery inverter"]
    store = costs_full.loc["battery storage"]
    per_mw = inv["investment"] * 1000.0 * (
        annuity(r, inv["lifetime"]) + inv.get("FOM", 0.0) / 100.0
    )
    per_mwh = store["investment"] * 1000.0 * annuity(r, store["lifetime"])
    return float(per_mw + hours * per_mwh)


def build(
    nc_path: Path,
    costs_full: pd.DataFrame,
    hours: int,
    co2_budget: float | None = None,
    r: float = DISCOUNT_RATE,
    gas_price: float = GAS_PRICE,
    autarky: bool = False,
    aggregation: str = "segments",
    weather: pd.DataFrame | None = None,
    neighbours_extendable: bool = True,
    carbon_tax: float | None = None,
    ets_price: float = ETS_PRICE,
) -> pypsa.Network:
    """The greenfield network: the Danish zones rebuilt from scratch, the
    neighbours keeping their fleets and adding to them, every zone's load at
    the forward horizon (see DEMAND_TOTALS).

    `hours` and `aggregation` decide how the year is reduced to snapshots
    (network.aggregate). `weather` re-runs the year on a weather year from
    the zonal archive (network.apply_weather) -- applied at full resolution,
    before the aggregation, so that the snapshots are chosen on the year
    actually being solved. `neighbours_extendable=False` freezes the
    neighbours' fleets instead (the earlier convention; see the module
    docstring for what it did). `ets_price` is the carbon price every zone
    pays (see ETS_PRICE); `carbon_tax` charges the Danish candidates a
    further tau EUR/t instead of the budget -- the uncertainty section's
    tax-versus-cap sweep, in which the tax mirrors the Danish budget's
    territorial scope.
    """
    n = load_forward_network(nc_path)
    if ets_price:
        # The existing fleet, on the network's own emission factors. The
        # candidates get theirs below, once they exist.
        network_model.apply_carbon_price(n, ets_price)
    if weather is not None:
        network_model.apply_weather(n, weather)
    network_model.aggregate(n, hours, aggregation)

    # Capture the Danish zones' native VRE profiles before wiping the fleet.
    native = {}
    for zone in DK_ZONES:
        for cand, carriers in NATIVE_PROFILE.items():
            for carrier in carriers:
                match = n.generators.index[
                    (n.generators.bus == zone) & (n.generators.carrier == carrier)
                ]
                if len(match) and match[0] in n.generators_t.p_max_pu.columns:
                    native[(zone, cand)] = n.generators_t.p_max_pu[match[0]].copy()
                    break

    dk_gens = n.generators.index[n.generators.bus.isin(DK_ZONES)]
    n.remove("Generator", dk_gens)
    # EVERY zone moves to the forward horizon, not only Denmark.
    #
    # Moving Denmark alone was tried and it broke the section. Danish demand
    # rises to 48.6 TWh at 2050 while eleven neighbours stay on 2024 load
    # with their 2024 fleets, so the surrounding system looks hugely
    # oversupplied, Denmark imports its way through, and the greenfield
    # build collapses to 4.2 GW of onshore wind with unconstrained emissions
    # of eleven kilotonnes -- a carbon budget with nothing to bite on.
    #
    # That degeneracy is the one the old assumed doubling of Danish load was
    # invented to prevent. The doubling was doing two jobs: representing
    # electrification, and keeping Denmark scarce relative to its
    # neighbours. TYNDP demand does the first honestly and abandons the
    # second, so the second has to be done properly instead -- by
    # electrifying the neighbours too.
    #
    # Their fleets are kept and may be added to (below): the system around
    # Denmark is the one that exists plus whatever a 2050 load makes it
    # worth building, at the same carbon price as Denmark. total_twh, not
    # base_twh: this section has no separate EV block, so the vehicles
    # belong in the load, with the rest of Norway's electrified transport.
    scale_load(n, list(n.loads_t.p_set.columns), column="total_twh")

    if autarky:
        # Autarky models Denmark alone: drop the foreign zones and every
        # branch but the Great Belt.
        foreign = [b for b in n.buses.index if b not in DK_ZONES]
        for component in ["Line", "Link"]:
            df = n.df(component)
            touching = df.index[
                df.bus0.isin(foreign) | df.bus1.isin(foreign)
            ]
            n.remove(component, touching)
        n.remove("Load", [l for l, row in n.loads.iterrows() if row.bus in foreign])
        n.remove("Generator", [g for g, row in n.generators.iterrows()
                               if row.bus in foreign])
        n.remove("StorageUnit", [s for s, row in n.storage_units.iterrows()
                                 if row.bus in foreign])
        n.remove("Bus", foreign)

    costs = candidate_costs(costs_full, r=r, gas_price=gas_price)
    for zone in DK_ZONES:
        for name, c in costs.iterrows():
            kwargs = {}
            if (zone, name) in native:
                kwargs["p_max_pu"] = native[(zone, name)]
            n.add(
                "Generator", f"{zone} {name}", bus=zone, carrier=name,
                p_nom_extendable=True,
                p_nom_max=P_NOM_MAX[zone].get(name, float("inf")),
                capital_cost=c["fixed_eur_mw_yr"] * (
                    offshore_premium(zone) if name == OFFSHORE_CANDIDATE
                    else 1.0),
                marginal_cost=c["marginal_cost"],
                **kwargs,
            )
        for hours_b in BATTERY_MENU_HOURS:
            n.add(
                "StorageUnit", f"{zone} battery {hours_b:g}h", bus=zone,
                carrier=f"battery_{hours_b:g}h",
                p_nom_extendable=True, max_hours=hours_b,
                efficiency_store=0.95, efficiency_dispatch=0.95,
                cyclic_state_of_charge=True, marginal_cost=0.1,
                capital_cost=battery_capital_cost(costs_full, r=r, hours=hours_b),
            )
    if neighbours_extendable and not autarky:
        add_candidates(n, costs, costs_full, r,
                       zones=[z for z in n.buses.index if z not in DK_ZONES])

    # Carbon on the candidates: the ETS price everywhere, and the Danish
    # tax (when the tax-versus-cap sweep asks for one) on Danish generation
    # only, mirroring the budget's scope. Every Danish generator is a
    # candidate, so the candidate rates suffice.
    for g, row in n.generators.iterrows():
        if not row.p_nom_extendable or row.carrier not in costs.index:
            continue
        rate = float(costs.loc[row.carrier, "emission_rate"])
        tau = (ets_price or 0.0) + (
            carbon_tax if carbon_tax is not None and row.bus in DK_ZONES else 0.0)
        n.generators.at[g, "marginal_cost"] += tau * rate

    # Nobody is special: the flexible consumer blocks sit in every zone, as
    # in section 8, so that a Danish result is not an artefact of Denmark
    # being the only place on the map with demand response.
    add_demand_blocks(n, block_zones=list(n.buses.index))

    # The realism features on the candidate fleet: load_network() already
    # derated the neighbours, but the candidates are new generators, and the
    # ramp limits could not be set before the sampling stride was known.
    network_model.derate_outages(n)
    network_model.apply_ramp_limits(n)

    n._co2_budget = co2_budget
    n._emission_rates = costs["emission_rate"]
    # solve() prices drop-in biomethane against the gas and the carbon it
    # replaces, zone by zone.
    n._gas_price = gas_price
    n._carbon_price_by_zone = {
        z: (ets_price or 0.0)
        + (carbon_tax if carbon_tax is not None and z in DK_ZONES else 0.0)
        for z in n.buses.index}
    return n


def add_biomethane_dropin(m, n, p, gen_dim, weight, fuel_per_mwh: dict,
                          gas_price: float, carbon_price_by_zone: dict,
                          zone_of=lambda bus: bus) -> dict:
    """Drop-in biomethane (see BIOMETHANE_DROP_IN), inside an
    extra_functionality: one variable per zone, MWh of biomethane a year
    burnt in place of natural gas by the generators in `fuel_per_mwh` (MWh
    of fuel per MWh they produce), no more than they burn. Each costs the
    fuel-price gap less the carbon price it saves. Returns {zone: variable};
    the caller puts them into its budget and the biomethane ceiling."""
    import xarray as xr

    by_zone: dict[str, list] = {}
    for g in fuel_per_mwh:
        by_zone.setdefault(zone_of(n.generators.at[g, "bus"]), []).append(g)
    out, cost = {}, None
    for zone, gens in sorted(by_zone.items()):
        b = m.add_variables(lower=0.0, name=f"biomethane_dropin_{zone}")
        per = xr.DataArray([fuel_per_mwh[g] for g in gens], coords={gen_dim: gens})
        burnt = (p.sel({gen_dim: gens}) * weight * per).sum()
        m.add_constraints(b - burnt <= 0, name=f"biomethane_dropin_gas_{zone}")
        premium = (BIOMETHANE_PRICE - gas_price
                   - carbon_price_by_zone.get(zone, 0.0) * GAS_CO2_T_PER_MWH_TH)
        cost = premium * b if cost is None else cost + premium * b
        out[zone] = b
    if cost is not None:
        m.objective = m.objective.expression + cost
    return out


def read_dropin(n: pypsa.Network) -> dict:
    """What a solve bought of drop-in biomethane, {zone: MWh a year}. Also
    records the CO2 it saves per MWh, so that a reader of the solved network
    (the Lab's extraction) can net it out zone by zone without importing the
    model."""
    n.meta["biomethane_dropin_co2_t_per_mwh"] = GAS_CO2_T_PER_MWH_TH
    out = {}
    for name in n.model.variables:
        if str(name).startswith("biomethane_dropin_"):
            out[str(name)[len("biomethane_dropin_"):]] = float(
                n.model.variables[name].solution)
    return out


def dropin_mwh(n: pypsa.Network, zones=None) -> float:
    """Drop-in biomethane a solved (or cached) network bought in a year,
    MWh, in `zones` (default: all)."""
    bought = n.meta.get("biomethane_dropin_mwh") or {}
    if not isinstance(bought, dict):        # one pool, before the split by zone
        return float(bought) if zones is None else 0.0
    return sum(float(v) for z, v in bought.items() if zones is None or z in zones)


def solve(n: pypsa.Network) -> float | None:
    """Optimise; if a CO2 budget was set, add it as an explicit constraint
    and return its dual — the endogenous carbon price (EUR/t). Gas plants
    may burn drop-in biomethane (add_biomethane_dropin()); what each zone
    bought is kept in n.meta["biomethane_dropin_mwh"]. The biomethane all
    zones may burn is capped as in section 8, and the cap's shadow price is
    kept in n.meta["biomethane_shadow"]."""
    budget = getattr(n, "_co2_budget", None)
    rates = getattr(n, "_emission_rates", None)
    dropin_on = getattr(n, "_biomethane_dropin", BIOMETHANE_DROP_IN)
    gas_price = getattr(n, "_gas_price", GAS_PRICE)
    carbon_price = getattr(n, "_carbon_price_by_zone", {})
    network_rates = network_model.emission_rates(n)

    def add_constraints(nw, snapshots):
        import xarray as xr

        m = nw.model
        p = m.variables["Generator-p"]
        gen_dim = next(d for d in p.dims if d != "snapshot")
        weight = xr.DataArray(
            nw.snapshot_weightings.objective.to_numpy(),
            coords={"snapshot": nw.snapshots},
        )
        # Gas burnt per MWh: a candidate's CO2 rate (its own table) or an
        # existing plant's (the network's), over the gas's.
        dropin = {}
        if dropin_on:
            fuel = {}
            for g, row in nw.generators.iterrows():
                if row.carrier not in DROPIN_CARRIERS:
                    continue
                rate = (float(rates[row.carrier])
                        if row.p_nom_extendable and row.carrier in rates.index
                        else float(network_rates.get(g, 0.0)))
                if rate > 0:
                    fuel[g] = rate / GAS_CO2_T_PER_MWH_TH
            dropin = add_biomethane_dropin(m, nw, p, gen_dim, weight, fuel,
                                           gas_price, carbon_price)
        if budget is not None:
            emitters = [
                g for g, row in nw.generators.iterrows()
                if row.bus in DK_ZONES and row.carrier in rates.index
                and rates[row.carrier] > 0
            ]
            rate = xr.DataArray(
                [rates[nw.generators.loc[g, "carrier"]] for g in emitters],
                coords={gen_dim: emitters},
            )
            expr = (p.sel({gen_dim: emitters}) * weight * rate).sum()
            for zone, b in dropin.items():
                if zone in DK_ZONES:
                    expr = expr - GAS_CO2_T_PER_MWH_TH * b
            m.add_constraints(expr <= budget, name="co2_budget")
        # The backstop is finite, as in section 8 (expansion.solve): one
        # ceiling on the biomethane burnt in all zones together, by the
        # dedicated turbine and as drop-in fuel. While it is slack, the fuel
        # switch caps what a tonne can cost; the shadow price below says
        # whether that holds.
        biogas = [g for g in nw.generators.index
                  if nw.generators.at[g, "carrier"] == BIOMETHANE_CARRIER]
        fuel_total = None
        if biogas:
            fuel_total = ((p.sel({gen_dim: biogas}) * weight).sum()
                          / BIOMETHANE_EFFICIENCY)
        for b in dropin.values():
            fuel_total = 1.0 * b if fuel_total is None else fuel_total + b
        if fuel_total is not None:
            m.add_constraints(fuel_total <= BIOMETHANE_POTENTIAL_MWH,
                              name="biomethane_potential")

    # Interior point with crossover: on instances of this size and cost
    # range (0.1 to 23,400 EUR/MWh once the VoLL block is in) HiGHS's
    # simplex grinds for hours where IPM finishes in minutes; crossover
    # restores a basic solution so every dual the note reads is exact.
    # (With ESM_SOLVER=gurobi the same role is played by barrier +
    # crossover — see model/network.py.)
    status, condition = n.optimize(
        solver_name=network_model.SOLVER, progress=False,
        transmission_losses=network_model.TRANSMISSION_LOSSES_SEGMENTS,
        solver_options=network_model.solver_options(ipm=True),
        extra_functionality=add_constraints,
    )
    if status != "ok":
        raise RuntimeError(f"greenfield LP did not solve: {status} / {condition}")
    try:
        n.meta["biomethane_shadow"] = float(
            -n.model.constraints["biomethane_potential"].dual)
    except (KeyError, AttributeError):
        n.meta["biomethane_shadow"] = None
    n.meta["biomethane_dropin_mwh"] = read_dropin(n)
    if budget is not None:
        return float(-n.model.constraints["co2_budget"].dual)
    return None


def dk_emissions(n: pypsa.Network) -> float:
    """Realised annual CO2 of the Danish candidate fleet, tonnes, less the
    gas that Danish drop-in biomethane replaced."""
    rates = getattr(n, "_emission_rates")
    w = n.snapshot_weightings.objective
    total = 0.0
    for g, row in n.generators.iterrows():
        if row.bus in DK_ZONES and row.carrier in rates.index and rates[row.carrier] > 0:
            total += float((n.generators_t.p[g] * w).sum()) * rates[row.carrier]
    return total - GAS_CO2_T_PER_MWH_TH * dropin_mwh(n, DK_ZONES)


def dk_capacity(n: pypsa.Network) -> pd.Series:
    """Optimised Danish capacity by technology, MW, summed over zones — the
    batteries by their power rating, one entry per duration."""
    caps: dict[str, float] = {}
    for g, row in n.generators.iterrows():
        if row.bus in DK_ZONES and row.p_nom_extendable:
            caps[row.carrier] = caps.get(row.carrier, 0.0) + float(row.p_nom_opt)
    for s, row in n.storage_units.iterrows():
        if row.bus in DK_ZONES and row.p_nom_extendable:
            caps[row.carrier] = caps.get(row.carrier, 0.0) + float(row.p_nom_opt)
    return pd.Series(caps)


def total_emissions(n: pypsa.Network) -> float:
    """System-wide annual CO2 across all twelve zones, tonnes.

    The CO2 budget covers Danish generation only while imports are free, so
    part of a Danish "cut" can simply move abroad. This is the number that
    shows how much: the neighbours' fleets on the network's (re-priced)
    emission factors plus the Danish candidates on their own, less the gas
    that drop-in biomethane replaced.
    """
    rates_dk = getattr(n, "_emission_rates")
    net_rates = network_model.emission_rates(n)
    w = n.snapshot_weightings.objective
    total = 0.0
    for g, row in n.generators.iterrows():
        if row.p_nom_extendable and row.carrier in rates_dk.index:
            rate = float(rates_dk[row.carrier])
        else:
            rate = float(net_rates[g])
        if rate > 0:
            total += float((n.generators_t.p[g] * w).sum()) * rate
    return total - GAS_CO2_T_PER_MWH_TH * dropin_mwh(n)


def shed_energy(n: pypsa.Network) -> pd.Series:
    """Annual curtailed demand per shedding block (MWh), summed over the
    Danish zones — how much of the load the model chose not to serve."""
    w = n.snapshot_weightings.objective
    out: dict[str, float] = {}
    for g, row in n.generators.iterrows():
        if row.bus in DK_ZONES and row.carrier.startswith("shed_"):
            out[row.carrier] = out.get(row.carrier, 0.0) + float(
                (n.generators_t.p[g] * w).sum()
            )
    return pd.Series(out)
