"""Single-period economic dispatch as an explicit linear program.

The model of section 2 of the note. One period, inelastic load, a set of
generators with constant marginal cost. The planner minimises total generation
cost subject to market clearing and capacity limits; the economics of the
section — the price, the scarcity rents, the carbon price — are the dual
variables of those constraints.

Every constraint added here carries the name of the LaTeX label of the equation
it implements, so the code can be read next to the note:

    balance    <->  eq:dispatch:balance   (market clearing; dual = price)
    capacity   <->  eq:dispatch:capacity  (dual = scarcity rent)
    cap        <->  eq:dispatch:cap       (emissions cap; dual = carbon price)

Typical use (see pipeline/run_dispatch.py for the note's own instance):

    import pandas as pd
    from model import dispatch

    tech = dispatch.read_tech("data/processed/technology_costs_small.csv")
    capacity = pd.Series({"ccgt": 1500.0, ...})           # MW
    sol = dispatch.solve(tech, capacity, load=5000.0)     # MW
    sol["price"]                                          # EUR/MWh

Marginal cost and emission rate are *derived* from the technology table, never
stored alongside it, so the numbers printed in the note cannot drift from the
numbers the model uses.
"""

import linopy
import pandas as pd


def read_tech(path) -> pd.DataFrame:
    """Read a technology table, e.g. data/processed/technology_costs_small.csv.

    Returns a DataFrame indexed by technology key with the columns the model
    needs: fuel_price_eur_per_mwh_th, efficiency, vom_eur_per_mwh,
    co2_t_per_mwh_th, and a human-readable label.
    """
    return pd.read_csv(path, comment="#", index_col="tech")


def marginal_cost(tech: pd.DataFrame, co2_price: float = 0.0) -> pd.Series:
    """Marginal cost in EUR/MWh electric: fuel per unit of electricity, plus
    variable O&M, plus the carbon payment if a CO2 price applies.

        c_g(tau) = p_fuel / eta_g + vom_g + tau * e_g
    """
    mc = (
        tech["fuel_price_eur_per_mwh_th"] / tech["efficiency"]
        + tech["vom_eur_per_mwh"]
        + co2_price * emission_rate(tech)
    )
    return mc.rename("marginal_cost")


def emission_rate(tech: pd.DataFrame) -> pd.Series:
    """Emissions per MWh electric: the fuel's emission factor divided by the
    electrical efficiency,  e_g = phi_fuel / eta_g  [tCO2/MWh]."""
    return (tech["co2_t_per_mwh_th"] / tech["efficiency"]).rename("emission_rate")


def build(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: float,
    co2_price: float = 0.0,
    co2_cap: float | None = None,
) -> linopy.Model:
    """Build the dispatch LP.

    minimise    sum_g c_g q_g                        (eq:dispatch:objective)
    subject to  sum_g q_g  = load          (lambda)  (eq:dispatch:balance)
                q_g       <= capacity_g    (mu_g)    (eq:dispatch:capacity)
                q_g       >= 0
    and, only if co2_cap is given,
                sum_g e_g q_g <= co2_cap   (sigma)   (eq:dispatch:cap)

    `capacity` is in MW and selects which technologies enter the instance:
    only its index is used. A CO2 price enters the marginal costs; a CO2 cap
    enters as a constraint whose dual is the endogenous carbon price. The note
    uses one or the other, never both at once.
    """
    generators = capacity.index
    c = marginal_cost(tech, co2_price).loc[generators]
    e = emission_rate(tech).loc[generators]

    m = linopy.Model()
    q = m.add_variables(lower=0.0, coords=[generators], dims=["tech"], name="q")

    m.add_constraints(q.sum() == load, name="balance")
    m.add_constraints(q <= capacity, name="capacity")
    if co2_cap is not None:
        m.add_constraints((e * q).sum() <= co2_cap, name="cap")

    m.add_objective((c * q).sum())
    return m


def solve(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: float,
    co2_price: float = 0.0,
    co2_cap: float | None = None,
) -> dict:
    """Build, solve, and read the economics off the duals.

    Returns a dict with:
        generation  pd.Series [MW]      optimal dispatch q_g
        price       float [EUR/MWh]     dual of eq:dispatch:balance
        rent        pd.Series [EUR/MWh] dual of eq:dispatch:capacity, as the
                                        non-negative scarcity rent mu_g
        co2_shadow_price  float [EUR/t] dual of eq:dispatch:cap (0 if no cap)
        emissions   float [t]           realised emissions sum_g e_g q_g
        cost        float [EUR]         objective value
        marginal_cost, emission_rate    the derived per-generator series

    Sign conventions: solvers report the dual of a binding <= constraint in a
    minimisation as a non-positive number (relaxing the constraint lowers
    cost). The note works with the non-negative multipliers of the Lagrangian
    as written there, so the <=-constraint duals are returned with the sign
    flipped: rent_g = lambda - c_g >= 0 for inframarginal generators, and the
    cap's shadow price is the positive carbon price.
    """
    m = build(tech, capacity, load, co2_price=co2_price, co2_cap=co2_cap)
    # output_flag=False silences the solver log; the cap sweep alone solves
    # this LP a few hundred times.
    status, condition = m.solve(solver_name="highs", progress=False, output_flag=False)
    if status != "ok":
        raise RuntimeError(f"dispatch LP did not solve: {status} / {condition}")

    generation = m.variables["q"].solution.to_pandas().rename("generation")
    price = float(m.constraints["balance"].dual)
    rent = (-m.constraints["capacity"].dual.to_pandas()).clip(lower=0.0).rename("rent")
    sigma = float(-m.constraints["cap"].dual) if co2_cap is not None else 0.0

    e = emission_rate(tech).loc[capacity.index]
    return {
        "generation": generation,
        "price": price,
        "rent": rent,
        "co2_shadow_price": sigma,
        "emissions": float((e * generation).sum()),
        "cost": float(m.objective.value),
        "marginal_cost": marginal_cost(tech, co2_price).loc[capacity.index],
        "emission_rate": e,
    }
