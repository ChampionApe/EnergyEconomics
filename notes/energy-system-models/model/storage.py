"""Single-node dispatch with storage — the model of section 4.

From this section on the models are PyPSA networks: the section 3 instance
(the same fleet, load and availability profiles) plus one new component, a
`StorageUnit` — a battery described by its power rating `p_nom` (MW), its
energy-to-power ratio `max_hours`, and one-way charge/discharge efficiencies.

The economics change qualitatively with this one component: the hours are no
longer independent problems. Storage adds the intertemporal constraint

    soc_h = soc_{h-1} + eta_c * charge_h - discharge_h / eta_d
                                            (eq:storage:soc)

whose dual is the shadow value of stored energy, and optimal operation is
arbitrage: charge when the price is below that value, discharge when above.

Typical use (see pipeline/run_storage.py for the note's experiments):

    n = storage.build_network(tech, capacity, load, availability,
                              storage_power_mw=1000.0)
    storage.solve(n)
    n.buses_t.marginal_price["elec"]              # the price path
    n.storage_units_t.state_of_charge["battery"]  # the SoC path
"""

import logging
import warnings

import pandas as pd
import pypsa

from model.dispatch import marginal_cost

logging.getLogger("pypsa").setLevel(logging.WARNING)
logging.getLogger("linopy").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning)

# One-way efficiency: 0.95 in and 0.95 out give a ~90% round trip, a standard
# figure for grid-scale batteries.
EFFICIENCY_ONE_WAY = 0.95


def build_network(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: pd.Series,
    availability: pd.DataFrame,
    storage_power_mw: float,
    storage_hours: float = 4.0,
    cyclic: bool = True,
    hourly_cost: pd.DataFrame | None = None,
    ramp_rate: dict[str, float] | None = None,
) -> pypsa.Network:
    """The section 3 network plus one battery.

    `cyclic=True` requires the state of charge to end the horizon where it
    began — without it, the optimiser would happily drain a battery it never
    paid to fill. Set it False only for rolling-horizon experiments that
    carry the SoC across windows explicitly (section 9).

    `hourly_cost` carries section 3's import backstop: a column per
    technology whose marginal cost is set hour by hour rather than by a fuel
    price. Denmark's firm plant does not cover its peak, so the wires are
    what keeps this network feasible, here as there.

    `ramp_rate` maps a technology to its ramp rate rho_g in (0, 1]: the
    share of capacity by which output may change between consecutive hours
    (eq:storage:ramp), applied symmetrically up and down. Technologies not
    named are unconstrained, which is the note's default.
    """
    mc = marginal_cost(tech).loc[capacity.index]

    n = pypsa.Network()
    n.set_snapshots(load.index)
    n.add("Carrier", "AC")
    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "demand", bus="elec", p_set=load)
    for g in capacity.index:
        kwargs = {}
        if g in availability.columns:
            kwargs["p_max_pu"] = availability[g]
        if ramp_rate and g in ramp_rate:
            kwargs["ramp_limit_up"] = ramp_rate[g]
            kwargs["ramp_limit_down"] = ramp_rate[g]
        cost = (hourly_cost[g] if hourly_cost is not None
                and g in hourly_cost.columns else mc[g])
        n.add("Generator", g, bus="elec",
              p_nom=capacity[g], marginal_cost=cost, **kwargs)

    if storage_power_mw > 0:
        n.add(
            "StorageUnit", "battery", bus="elec",
            p_nom=storage_power_mw,
            max_hours=storage_hours,
            efficiency_store=EFFICIENCY_ONE_WAY,
            efficiency_dispatch=EFFICIENCY_ONE_WAY,
            cyclic_state_of_charge=cyclic,
            # A token marginal cost breaks ties: without it the optimiser may
            # cycle the battery pointlessly between equal-price hours.
            marginal_cost=0.1,
        )
    return n


def solve(n: pypsa.Network) -> None:
    """Optimise in place; results live on the network's *_t frames.

    `assign_all_duals` keeps every constraint's multiplier, so the ramp
    duals xi_{g,h} of eq:storage:ramp land in `n.generators_t` as
    `mu_ramp_limit_up` / `mu_ramp_limit_down` beside the usual ones.
    """
    status, condition = n.optimize(
        solver_name="highs", progress=False,
        solver_options={"output_flag": False},
        assign_all_duals=True,
    )
    if status != "ok":
        raise RuntimeError(f"storage LP did not solve: {status} / {condition}")


def flexibility_cost(n: pypsa.Network) -> float:
    """The summed shadow value of the ramp constraints, EUR over the horizon:

        sum_g sum_h (xi^up_{g,h} + xi^down_{g,h}) * rho_g * qbar_g

    Each term is a ramp constraint's multiplier times its right-hand side —
    what the system would pay for one more unit of ramping room in that
    hour, summed. Zero when no generator carries a ramp rate. Assumes the
    hourly snapshots of section 4 (unit weights).
    """
    total = 0.0
    for key in ("mu_ramp_limit_up", "mu_ramp_limit_down"):
        if key not in n.generators_t:
            continue
        mu = n.generators_t[key]
        for g in mu.columns:
            rho = n.generators.loc[g, "ramp_limit_up"]
            if pd.notna(rho):
                total += float(mu[g].abs().sum() * rho * n.generators.loc[g, "p_nom"])
    return total


def storage_revenue(n: pypsa.Network) -> float:
    """The battery's market revenue: sales at the hourly price minus
    purchases at the hourly price. Positive dispatch is selling.

    With optimal operation this equals the value the battery extracts from
    the price spread net of round-trip losses — the arbitrage profit the
    note discusses.
    """
    price = n.buses_t.marginal_price["elec"]
    net_dispatch = n.storage_units_t.p["battery"]
    weights = n.snapshot_weightings.objective
    return float((price * net_dispatch * weights).sum())
