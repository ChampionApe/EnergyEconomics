"""Multi-period economic dispatch with availability profiles.

The model of section 3 of the note: the dispatch LP of `dispatch.py` repeated
over many periods, with one change of substance — the capacity limit of wind
and solar varies hour by hour with the weather. Periods remain independent
(nothing stores energy between them; that is section 4), so the model is one
merit order per hour, and its dual is a *path* of prices.

Constraint names again carry the LaTeX labels of the equations they implement:

    balance    <->  eq:intermittency:balance   (per period; dual = price path)
    capacity   <->  eq:intermittency:capacity  (availability-scaled limit;
                                                dual = per-period scarcity rent)

Typical use (see pipeline/run_dispatch_t.py for the note's own instance):

    sol = dispatch_t.solve(tech, capacity, load, availability)
    sol["price"]           # EUR/MWh, one per period
    capture_price(sol["price"], sol["generation"])

The summary statistics of section 3 — capacity factor, capture price, value
factor — are defined here as small named functions so the code states the
formulas the note numbers.
"""

import linopy
import pandas as pd
import xarray as xr

from model.dispatch import emission_rate, marginal_cost


def build(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: pd.Series,
    availability: pd.DataFrame,
    co2_price: float = 0.0,
    hourly_cost: pd.DataFrame | None = None,
) -> linopy.Model:
    """Build the multi-period dispatch LP.

    minimise    sum_{g,h} c_{g,h} q_{g,h}                 (eq:intermittency:objective)
    subject to  sum_g q_{g,h}  = D_h         (lambda_h)   (eq:intermittency:balance)
                q_{g,h)       <= gamma_{g,h} qbar_g
                                             (mu_{g,h})   (eq:intermittency:capacity)
                q_{g,h}       >= 0

    `load` is D_h in MW, indexed by period. `availability` holds the profiles
    gamma_{g,h} in [0, 1] for the technologies that have one (columns named by
    technology); every other technology is available at gamma = 1 in every
    period — the single-period model's assumption, now made explicit and
    confined to the dispatchable plants.

    `hourly_cost` does the same job for the *cost* side: a column per
    technology whose marginal cost varies by period, which every technology
    burning a fuel does not — c_{g,h} = c_g unless stated here. Section 3
    uses it for one technology only, imports, whose cost is the price the
    neighbouring markets charge in that hour.
    """
    generators = capacity.index.rename("tech")
    periods = load.index.rename("period")
    c = marginal_cost(tech, co2_price).loc[generators]

    gamma = pd.DataFrame(1.0, index=periods, columns=generators)
    for name in availability.columns.intersection(generators):
        gamma[name] = availability[name].loc[periods]

    upper = xr.DataArray(
        gamma.mul(capacity, axis=1).values,
        coords={"period": periods, "tech": generators},
        dims=["period", "tech"],
    )

    m = linopy.Model()
    q = m.add_variables(
        lower=0.0, coords=[periods, generators], dims=["period", "tech"], name="q"
    )

    m.add_constraints(
        q.sum("tech") == xr.DataArray(load.values, coords={"period": periods}),
        name="balance",
    )
    m.add_constraints(q <= upper, name="capacity")

    cost_t = pd.DataFrame(
        [c.values] * len(periods), index=periods, columns=generators
    )
    if hourly_cost is not None:
        for name in hourly_cost.columns.intersection(generators):
            cost_t[name] = hourly_cost[name].loc[periods]
    cost = xr.DataArray(
        cost_t.values,
        coords={"period": periods, "tech": generators},
        dims=["period", "tech"],
    )
    m.add_objective((cost * q).sum())
    return m


def solve(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: pd.Series,
    availability: pd.DataFrame,
    co2_price: float = 0.0,
    hourly_cost: pd.DataFrame | None = None,
) -> dict:
    """Build, solve, and read the economics off the duals.

    Returns a dict with:
        generation  DataFrame [MW]      dispatch, period x technology
        price       Series [EUR/MWh]    dual of eq:intermittency:balance, per period
        rent        DataFrame [EUR/MWh] dual of eq:intermittency:capacity,
                                        sign-flipped to the note's mu >= 0
        emissions   float [t]           total over all periods
        cost        float [EUR]         objective value

    Sign conventions are as in dispatch.solve: <=-constraint duals are
    returned as the non-negative multipliers of the note's Lagrangian.
    """
    m = build(tech, capacity, load, availability, co2_price=co2_price,
              hourly_cost=hourly_cost)
    status, condition = m.solve(solver_name="highs", progress=False, output_flag=False)
    if status != "ok":
        raise RuntimeError(f"dispatch_t LP did not solve: {status} / {condition}")

    generation = m.variables["q"].solution.to_pandas()
    price = m.constraints["balance"].dual.to_pandas().rename("price")
    rent = (-m.constraints["capacity"].dual.to_pandas()).clip(lower=0.0)

    e = emission_rate(tech).loc[capacity.index]
    return {
        "generation": generation,
        "price": price,
        "rent": rent,
        "emissions": float((generation * e).sum().sum()),
        "cost": float(m.objective.value),
    }


def capacity_factor(generation: pd.DataFrame, capacity: pd.Series) -> pd.Series:
    """Average output per unit of capacity  (eq:intermittency:cf):

        CF_g = (1/T) sum_h q_{g,h} / qbar_g
    """
    return (generation.mean() / capacity).rename("capacity_factor")


def capture_price(price: pd.Series, generation: pd.DataFrame) -> pd.Series:
    """Generation-weighted average price earned  (eq:intermittency:capture):

        pbar_g = sum_h lambda_h q_{g,h} / sum_h q_{g,h}

    NaN for a technology that never runs — it earns no price at all.
    """
    return (generation.mul(price, axis=0).sum() / generation.sum()).rename(
        "capture_price"
    )


def base_price(price: pd.Series, load: pd.Series) -> float:
    """The consumption-weighted average price  (eq:intermittency:vf):

        pbar = sum_h lambda_h D_h / sum_h D_h

    This, not the plain time-average, is the benchmark a technology's capture
    price is measured against: it is what the average MWh consumed actually
    costs. A time-average would give a cheap hour of low demand the same
    weight as an expensive hour of peak demand, which flatters exactly the
    technologies that produce when nobody needs the power.
    """
    return float((price * load).sum() / load.sum())


def value_factor(
    price: pd.Series, generation: pd.DataFrame, load: pd.Series
) -> pd.Series:
    """Capture price relative to the base price  (eq:intermittency:vf):

        VF_g = pbar_g / pbar

    Above one: the technology produces disproportionately in expensive hours.
    Below one: it produces when electricity is cheap — including when its own
    abundance is what makes electricity cheap.
    """
    return (capture_price(price, generation) / base_price(price, load)).rename(
        "value_factor"
    )
