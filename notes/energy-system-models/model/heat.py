"""Power and heat, coupled by a heat pump — the model of section 5.

Two buses. The electricity side is the section 3 instance unchanged. The heat
bus carries a district-heating load and two ways of serving it:

    heat pump    a `Link` from the electricity bus whose efficiency is the
                 hour's COP — one MWh of electricity becomes COP_t MWh of
                 heat, so electrification demand is largest exactly when the
                 COP is worst (cold hours)      (eq:heat:hp)
    gas boiler   a `Generator` on the heat bus at the gas price over its
                 efficiency — the marginal technology and hence, whenever it
                 runs, the heat price                (eq:heat:boiler)

The COP follows the empirical air-sourced curve of Staffell et al. (2012),

    COP(dT) = 6.81 - 0.121 dT + 0.000630 dT^2,   dT = T_sink - T_source,

with the source at the outdoor temperature and the sink at the district
heating supply temperature.
"""

import logging
import warnings

import pandas as pd
import pypsa

from model.dispatch import marginal_cost

logging.getLogger("pypsa").setLevel(logging.WARNING)
logging.getLogger("linopy").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning)

SINK_TEMPERATURE_C = 50.0

# The gas boiler's heat marginal cost: fuel over thermal efficiency plus a
# small VOM, matching the gas price of the small technology table.
BOILER_EFFICIENCY = 0.95
BOILER_VOM = 1.0
GAS_PRICE = 35.0
GAS_CO2_T_PER_MWH_TH = 0.198


def cop_series(temperature_c: pd.Series, sink_c: float = SINK_TEMPERATURE_C) -> pd.Series:
    """Hourly COP of an air-sourced heat pump (eq:heat:cop), Staffell et al.
    (2012). Falls as it gets colder — the coupling's defining feature."""
    dt = (sink_c - temperature_c).clip(lower=15.0)
    return (6.81 - 0.121 * dt + 0.000630 * dt**2).rename("cop")


def heat_demand(
    temperature_c: pd.Series,
    annual_twh: float,
    threshold_c: float = 15.0,
    base_share: float = 0.15,
) -> pd.Series:
    """A degree-hour heat load (eq:heat:demand): space heating proportional
    to max(threshold - T, 0), plus a flat base for hot water, scaled to a
    given annual total. Stylised, and the note says so."""
    space = (threshold_c - temperature_c).clip(lower=0.0)
    shape = base_share + (1.0 - base_share) * space / space.mean()
    demand = shape / shape.mean() * annual_twh * 1e6 / len(temperature_c)
    return demand.rename("heat_demand_mw")


def build_network(
    tech: pd.DataFrame,
    capacity: pd.Series,
    load: pd.Series,
    availability: pd.DataFrame,
    heat_load: pd.Series,
    cop: pd.Series,
    hp_power_mw_el: float,
    boiler_mw_th: float = 10000.0,
    co2_price: float = 0.0,
    hourly_cost: pd.DataFrame | None = None,
) -> pypsa.Network:
    """The two-bus network. `hp_power_mw_el` is the heat pump's electric
    rating; its heat output is COP times larger. `co2_price` (EUR/t) is
    charged on both sides of the coupling: the power fleet through
    eq:dispatch:mc, and the boiler's gas directly. `hourly_cost` carries
    section 3's import backstop, whose marginal cost is the neighbours'
    price in that hour rather than a fuel price."""
    mc = marginal_cost(tech, co2_price).loc[capacity.index]

    n = pypsa.Network()
    n.set_snapshots(load.index)
    for carrier in ["AC", "heat"]:
        n.add("Carrier", carrier)

    n.add("Bus", "elec", carrier="AC")
    n.add("Load", "demand", bus="elec", p_set=load)
    for g in capacity.index:
        kwargs = {}
        if g in availability.columns:
            kwargs["p_max_pu"] = availability[g]
        cost = (hourly_cost[g] if hourly_cost is not None
                and g in hourly_cost.columns else mc[g])
        n.add("Generator", g, bus="elec",
              p_nom=capacity[g], marginal_cost=cost, **kwargs)

    n.add("Bus", "heat", carrier="heat")
    n.add("Load", "heat-demand", bus="heat", p_set=heat_load)
    n.add(
        "Generator", "gas_boiler", bus="heat", p_nom=boiler_mw_th,
        marginal_cost=(GAS_PRICE + co2_price * GAS_CO2_T_PER_MWH_TH)
        / BOILER_EFFICIENCY + BOILER_VOM,
    )
    if hp_power_mw_el > 0:
        n.add(
            "Link", "heat_pump", bus0="elec", bus1="heat",
            p_nom=hp_power_mw_el, efficiency=cop,
        )
    return n


def solve(n: pypsa.Network) -> None:
    status, condition = n.optimize(
        solver_name="highs", progress=False,
        solver_options={"output_flag": False},
    )
    if status != "ok":
        raise RuntimeError(f"heat LP did not solve: {status} / {condition}")
