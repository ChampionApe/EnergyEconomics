"""Greenfield capacity expansion — the model of section 7.

The 12-bidding-zone network with the two Danish zones wiped clean: in DK1
and DK2 every capacity is a *choice variable*. PyPSA expresses this as
`p_nom_extendable=True` with a `capital_cost` — the annualised cost of a MW,

    capital_cost = investment * (annuity(r, lifetime) + FOM)
    annuity(r, n) = r / (1 - (1 + r)^-n)          (eq:investment:annuity)

so the objective becomes total annual system cost, capital plus operations,
and the LP trades the two off. Appendix B derives the annuity; the
investment numbers come from PyPSA's technology-data at a pinned tag
(data/prepare.py), the fuel prices from the note's small table. The
candidates' availability profiles are the network's own 2024 profiles for
the Danish zones, so candidate weather is consistent with the neighbours'.

A CO2 budget on Danish generation enters as one extra constraint whose dual
is the carbon price that would decentralise the plan — section 2's cap, now
setting the capacity mix rather than reshuffling a fixed one.

The neighbours keep the fleets they have and may add to them from the same
candidate menu, capped at their published potentials, under no carbon
constraint of their own: the question the model answers is what Denmark
should build, given a neighbourhood that is itself adapting to the horizon's
demand. (Freezing the neighbours' fleets at 2024 while every zone carries
2050 demand was tried first; it put southern Norway at the value of lost
load in every hour of the year, and every Danish export price with it.)
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

# The carbon price everyone in the neighbourhood pays, EUR/t: the EU ETS,
# at the level section 2 uses for its carbon-tax experiment (the range of
# recent allowance prices). It is charged on every emitter in every zone,
# existing plant and candidate alike, and the Danish CO2 budget sits ON TOP
# of it -- so the budget's dual sigma is the additional price a Danish
# territorial target needs beyond the ETS, and the fuel-switching
# arithmetic of section 7 reads sigma + ETS_PRICE = (c_bio - c_gas) / e.
# Without it the neighbours, free to build under a 2050 load, put up tens of
# gigawatts of unpriced gas and keep their coal running, which is not a
# neighbourhood any Danish target would be set in.
ETS_PRICE = 85.0


def load_forward_network(nc_path: Path) -> pypsa.Network:
    """The shipped network priced at the forward horizon rather than today."""
    return network_model.load_network(
        nc_path, fuels=FORWARD_FUELS, costs=FORWARD_COSTS)


def scale_load(n: pypsa.Network, zones, column: str = "base_twh") -> dict:
    """Scale each zone's load so its annual energy is the forward horizon's
    total, leaving the 2024 shape alone. Must be called after subsample(),
    because annual energy is the weighted sum. Returns the factors applied,
    which are worth printing: they are the assumption this replaces.
    """
    weights = n.snapshot_weightings.objective
    factors = {}
    for zone in zones:
        if zone not in n.loads_t.p_set.columns or zone not in DEMAND_TOTALS.index:
            continue
        served = float((n.loads_t.p_set[zone] * weights).sum())
        if served <= 0:
            continue
        factor = float(DEMAND_TOTALS.loc[zone, column]) * 1e6 / served
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
# job: `nuclear` demonstrates that at 2030 costs the LP builds none, and
# `ocgt_biogas` — the same machine as `ocgt` burning biomethane at zero
# fossil CO2 — is the backstop that caps the carbon price: however tight
# the budget, the model can always switch the peaker's fuel, so the CO2
# budget's dual can never exceed roughly the fuel-price gap divided by the
# gas plant's emission rate (section 2's fuel-switching arithmetic).
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

# Buildable potential per zone, MW — the land/NIMBY constraint. Offshore is
# what makes these bind interesting: when onshore and solar run out, the
# model must pay offshore's premium. These are the note's own stylised caps
# for the two greenfield zones; the neighbours build under the published
# per-zone potentials below, as section 8 does for every zone.
P_NOM_MAX = {
    "DK1": {"solar_pv": 10000, "wind_onshore": 5000, "wind_offshore": 20000},
    "DK2": {"solar_pv": 6000, "wind_onshore": 2500, "wind_offshore": 10000},
}

# Published buildable potential per zone: the smaller of the most ambitious
# published trajectory and what the land allows. Written by data/prepare.py,
# which records both sources beside the used value; see data/README.md.
POTENTIALS = pd.read_csv(
    PROCESSED_DIR / "potentials_zones.csv", comment="#"
).set_index(["zone", "technology"])["p_nom_max_used_mw"]

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
    # worth building, under no carbon constraint of its own. total_twh, not
    # base_twh: this section has no separate EV block, so the vehicles
    # belong in the load.
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
    return n


def solve(n: pypsa.Network) -> float | None:
    """Optimise; if a CO2 budget was set, add it as an explicit constraint
    and return its dual — the endogenous carbon price (EUR/t)."""
    budget = getattr(n, "_co2_budget", None)
    rates = getattr(n, "_emission_rates", None)

    def add_co2(nw, snapshots):
        import xarray as xr

        m = nw.model
        p = m.variables["Generator-p"]
        gen_dim = next(d for d in p.dims if d != "snapshot")
        emitters = [
            g for g, row in nw.generators.iterrows()
            if row.bus in DK_ZONES and row.carrier in rates.index
            and rates[row.carrier] > 0
        ]
        weight = xr.DataArray(
            nw.snapshot_weightings.objective.to_numpy(),
            coords={"snapshot": nw.snapshots},
        )
        rate = xr.DataArray(
            [rates[nw.generators.loc[g, "carrier"]] for g in emitters],
            coords={gen_dim: emitters},
        )
        expr = (p.sel({gen_dim: emitters}) * weight * rate).sum()
        m.add_constraints(expr <= budget, name="co2_budget")

    kwargs = {}
    if budget is not None:
        kwargs["extra_functionality"] = add_co2
    # Interior point with crossover: on instances of this size and cost
    # range (0.1 to 23,400 EUR/MWh once the VoLL block is in) HiGHS's
    # simplex grinds for hours where IPM finishes in minutes; crossover
    # restores a basic solution so every dual the note reads is exact.
    # (With ESM_SOLVER=gurobi the same role is played by barrier +
    # crossover — see model/network.py.)
    status, condition = n.optimize(
        solver_name=network_model.SOLVER, progress=False,
        transmission_losses=network_model.TRANSMISSION_LOSSES_SEGMENTS,
        solver_options=network_model.solver_options(ipm=True), **kwargs,
    )
    if status != "ok":
        raise RuntimeError(f"greenfield LP did not solve: {status} / {condition}")
    if budget is not None:
        return float(-n.model.constraints["co2_budget"].dual)
    return None


def dk_emissions(n: pypsa.Network) -> float:
    """Realised annual CO2 of the Danish candidate fleet, tonnes."""
    rates = getattr(n, "_emission_rates")
    w = n.snapshot_weightings.objective
    total = 0.0
    for g, row in n.generators.iterrows():
        if row.bus in DK_ZONES and row.carrier in rates.index and rates[row.carrier] > 0:
            total += float((n.generators_t.p[g] * w).sum()) * rates[row.carrier]
    return total


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
    emission factors plus the Danish candidates on their own.
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
    return total


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
