"""Stage 2: turn processed cost data into the numbers the note quotes.

    python pipeline/run_costs.py

Reads `data/processed/`, writes `results/`. Solves nothing and fits one
regression. Everything the note prints -- every table cell, every figure
series, every number quoted in the prose -- is computed here and written to
`results/`, so that `pipeline/build.py` can draw the note without recomputing
anything.

Writes:

    results/technology_costs.csv    the per-technology cost table of section 3
    results/decomposition.csv       cost per MWh, split into the categories
                                    that have a per-MWh form (not adjustment)
    results/lcoe_capacityfactor.csv levelised cost over a capacity-factor grid
    results/lcoe_envelope.csv       which technology is cheapest at each duty
    results/lcoe_discountrate.csv   levelised cost over a discount-rate grid
    results/cost_projections.csv    the pinned catalogue's 2025-2050 path
    results/cost_vintages.csv       the same projection across releases
    results/learning.csv            solar price and cumulative capacity
    results/geography.csv           section 6: the note's own technologies
                                    re-priced under each region's inputs
    results/geography_waterfall.csv section 6: the same, one input at a time
    results/summary.json            the scalars the note quotes in prose
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
PROCESSED = NOTE / "data" / "processed"
RESULTS = NOTE / "results"

HOURS_PER_YEAR = 8760

# Assumptions of section 4. Each is stated in the note and recorded in
# Appendix D; none of them is a measurement.
DISCOUNT_RATE = 0.07          # real, before tax, common to all technologies
CARBON_PRICE = 80.0           # EUR/tCO2, used only for one illustrative number
ELECTRICITY_PRICE = 60.0      # EUR/MWh, the heat pump's "fuel" price

# The technologies whose levelised cost the note plots. Restricted to plants
# whose only product is electricity: a levelised cost per MWh of electricity is
# meaningless for a co-generation plant that is built for its heat, and for a
# store, which produces no energy at all. Both appear in the cost table.
LCOE_TECHS = ["solar-utility", "onwind", "offwind", "hydro", "nuclear",
              "coal", "CCGT", "OCGT", "oil"]

# Technologies whose product is heat, not electricity. Reported separately.
HEAT_TECHS = ["central air-sourced heat pump", "central gas boiler"]
STORE_TECHS = ["PHS", "battery inverter", "battery storage"]

# The lower envelope of section 4 is computed over the thermal dispatchable
# plants only. These are the technologies whose utilisation is genuinely a
# choice AND which can be built more or less anywhere: reservoir hydro is
# dispatchable and cheap, but you cannot decide to have a valley.
ENVELOPE_TECHS = ["nuclear", "coal", "CCGT", "OCGT", "oil"]

# Section 6. The base region is the one every other is measured against, and
# it is the one the rest of the note is written about: its inputs are the
# note's own, so the European column of section 6 reproduces section 4 exactly.
BASE_REGION = "Europe"
GEOGRAPHY_ORDER = ["Europe", "United States", "China"]

# The technology Appendix A takes apart by hand. A combined-cycle plant is the
# right choice because both terms of the levelised cost are large enough to
# see: a peaker's capital term or a wind farm's fuel term would round away.
WORKED_EXAMPLE_TECH = "CCGT"

CAPACITY_FACTOR_GRID = np.linspace(0.01, 0.95, 190)
DISCOUNT_RATE_GRID = np.linspace(0.02, 0.12, 51)
PROJECTION_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
REFERENCE_YEAR = 2025


# ---------------------------------------------------------------------------
# The two formulas the whole section rests on
# ---------------------------------------------------------------------------
def annuity(rate: float, lifetime: float) -> float:
    """The constant annual payment that repays one unit of capital.

    The share of an up-front investment that has to be recovered each year
    over `lifetime` years at discount rate `rate`. Derived in the note's
    Appendix B.
    """
    if rate == 0:
        return 1.0 / lifetime
    return rate / (1.0 - (1.0 + rate) ** (-lifetime))


def levelised_cost(capital_eur_per_kw, fom_rate, lifetime, marginal_cost,
                   capacity_factor, rate=DISCOUNT_RATE):
    """Levelised cost in EUR/MWh at a given utilisation.

    Two terms: an annual capacity cost spread over however much energy the
    plant produces, plus a cost per MWh that does not care how much it
    produces. The first is what falls as the plant runs more; the second is
    the floor it falls towards.
    """
    annual_capacity_cost = capital_eur_per_kw * (annuity(rate, lifetime) + fom_rate)
    energy_per_kw = HOURS_PER_YEAR * capacity_factor / 1000.0  # MWh per kW-year
    return annual_capacity_cost / energy_per_kw + marginal_cost


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_costs(cost_year: int) -> pd.DataFrame:
    return pd.read_csv(PROCESSED / f"technology_costs_{cost_year}.csv",
                       index_col="technology")


def load_meta() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "technology_meta.csv", comment="#",
                       index_col="technology")


def load_fuels() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "fuel_assumptions.csv", comment="#",
                       index_col="carrier")


def assemble(cost_year: int = REFERENCE_YEAR) -> pd.DataFrame:
    """One row per technology, with everything needed to price it."""
    costs, meta, fuels = load_costs(cost_year), load_meta(), load_fuels()
    # Both frames carry a `fuel` column and they mean different things: in the
    # metadata it names the carrier, in the cost data it is a price. The
    # per-technology price is dropped -- prices come from the carrier table, so
    # that two technologies burning the same fuel cannot be given two prices.
    costs = costs.rename(columns={"fuel": "fuel_price_published"})
    frame = meta.join(costs, how="left")

    frame["investment"] = frame["investment"].astype(float)
    frame["lifetime"] = frame["lifetime"].astype(float)
    # FOM is published as a percentage of the investment per year.
    frame["fom_rate"] = frame["FOM"].fillna(0.0) / 100.0
    frame["vom"] = frame["VOM"].fillna(0.0)
    # Wind, solar and run-of-river have no conversion efficiency in the sense
    # the fuel formula uses: there is no fuel to convert.
    frame["efficiency"] = frame["efficiency"].fillna(1.0)

    price = frame["fuel"].map(fuels["price_used_eur_per_mwh_th"])
    carbon = frame["fuel"].map(fuels["co2_used_t_per_mwh_th"])
    price = price.where(frame["fuel"] != "electricity", ELECTRICITY_PRICE)
    carbon = carbon.where(frame["fuel"] != "electricity", 0.0)
    frame["fuel_price"] = price.fillna(0.0)
    frame["co2_intensity_fuel"] = carbon.fillna(0.0)

    # The two derived quantities of section 2, computed rather than assumed.
    frame["fuel_cost"] = frame["fuel_price"] / frame["efficiency"]
    frame["marginal_cost"] = frame["fuel_cost"] + frame["vom"]
    frame["emission_rate"] = frame["co2_intensity_fuel"] / frame["efficiency"]

    # A zero emission rate means two quite different things. Uranium and the
    # weather emit nothing; wood emits a great deal and is *counted* as zero by
    # an accounting convention the note argues with in section 3. Table 2 has
    # to be able to tell them apart, so the distinction is carried rather than
    # left to whoever formats the column.
    convention = frame["fuel"].map(fuels["co2_is_assumption"]) == True  # noqa: E712
    frame["carbon_is_convention"] = (convention
                                     & (frame["co2_intensity_fuel"] < 1e-9))

    frame["annuity_factor"] = [annuity(DISCOUNT_RATE, n) for n in frame["lifetime"]]
    frame["annual_capital"] = frame["investment"] * frame["annuity_factor"]
    frame["annual_fom"] = frame["investment"] * frame["fom_rate"]
    frame["annual_capacity_cost"] = frame["annual_capital"] + frame["annual_fom"]
    return frame.sort_values("order")


# ---------------------------------------------------------------------------
# The results
# ---------------------------------------------------------------------------
def write_cost_table(frame: pd.DataFrame):
    columns = ["label", "family", "class", "role", "fuel", "investment",
               "fom_rate", "lifetime", "efficiency", "fuel_price", "vom",
               "emission_rate", "carbon_is_convention", "marginal_cost",
               "annual_capacity_cost", "capacity_factor", "q_investment",
               "q_running", "q_adjustment", "q_time_to_build"]
    out = frame[columns].copy()
    # A levelised cost per MWh means nothing for a store, which produces no
    # energy of its own; those rows are left blank rather than filled with a
    # number that would only be misread.
    out["lcoe_reference"] = [
        np.nan if tech in STORE_TECHS else
        levelised_cost(r.investment, r.fom_rate, r.lifetime, r.marginal_cost,
                       r.capacity_factor)
        for tech, r in zip(frame.index, frame.itertuples())
    ]
    out.to_csv(RESULTS / "technology_costs.csv", float_format="%.4f")
    return out


def write_fuels():
    """Carry the fuel assumptions into results/ so stage 3 can tabulate them.

    Appendix D prints the dataset's own fuel prices next to the ones the note
    uses. Stage 3 may not read `data/`, so the comparison has to pass through
    here.
    """
    fuels = load_fuels()
    fuels.to_csv(RESULTS / "fuel_assumptions.csv", float_format="%.4f")
    return fuels


def write_decomposition(frame: pd.DataFrame):
    """Cost per MWh at the reference utilisation, split four ways."""
    rows = []
    for tech, r in frame.iterrows():
        if tech in STORE_TECHS:
            continue
        energy = HOURS_PER_YEAR * r.capacity_factor / 1000.0  # MWh per kW-year
        rows.append({
            "technology": tech,
            "label": r.label,
            "family": r.family,
            "capacity_factor": r.capacity_factor,
            "capital": r.annual_capital / energy,
            "fixed_om": r.annual_fom / energy,
            "fuel": r.fuel_cost,
            "variable_om": r.vom,
            "carbon_at_price": r.emission_rate * CARBON_PRICE,
        })
    out = pd.DataFrame(rows).set_index("technology")
    out["total"] = out[["capital", "fixed_om", "fuel", "variable_om"]].sum(axis=1)
    out.to_csv(RESULTS / "decomposition.csv", float_format="%.4f")
    return out


def write_lcoe_capacityfactor(frame: pd.DataFrame):
    rows = []
    for tech in LCOE_TECHS:
        r = frame.loc[tech]
        for cf in CAPACITY_FACTOR_GRID:
            rows.append({
                "technology": tech, "label": r.label, "capacity_factor": cf,
                "full_load_hours": cf * HOURS_PER_YEAR,
                "lcoe": levelised_cost(r.investment, r.fom_rate, r.lifetime,
                                       r.marginal_cost, cf),
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "lcoe_capacityfactor.csv", index=False,
               float_format="%.4f")

    # The lower envelope: at each duty, which technology is cheapest, and by
    # how much. Only the dispatchable technologies can actually choose their
    # utilisation, so the envelope is computed over those alone.
    dispatchable = ENVELOPE_TECHS
    envelope = []
    for cf in CAPACITY_FACTOR_GRID:
        costs = {t: levelised_cost(frame.loc[t, "investment"],
                                   frame.loc[t, "fom_rate"],
                                   frame.loc[t, "lifetime"],
                                   frame.loc[t, "marginal_cost"], cf)
                 for t in dispatchable}
        best = min(costs, key=costs.get)
        envelope.append({"capacity_factor": cf,
                         "full_load_hours": cf * HOURS_PER_YEAR,
                         "cheapest": best,
                         "label": frame.loc[best, "label"],
                         "lcoe": costs[best]})
    env = pd.DataFrame(envelope)
    env.to_csv(RESULTS / "lcoe_envelope.csv", index=False, float_format="%.4f")
    return out, env


def write_lcoe_discountrate(frame: pd.DataFrame):
    rows = []
    for tech in LCOE_TECHS:
        r = frame.loc[tech]
        for rate in DISCOUNT_RATE_GRID:
            rows.append({
                "technology": tech, "label": r.label, "discount_rate": rate,
                "lcoe": levelised_cost(r.investment, r.fom_rate, r.lifetime,
                                       r.marginal_cost, r.capacity_factor,
                                       rate=rate),
            })
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "lcoe_discountrate.csv", index=False,
               float_format="%.4f")
    return out


def write_projections(meta: pd.DataFrame):
    """What the pinned catalogue expects these technologies to cost later."""
    rows = []
    for year in PROJECTION_YEARS:
        costs = load_costs(year)
        for tech in LCOE_TECHS + ["battery storage", "battery inverter"]:
            if tech not in costs.index:
                continue
            rows.append({"cost_year": year, "technology": tech,
                         "label": meta.loc[tech, "label"],
                         "investment": costs.loc[tech, "investment"]})
    out = pd.DataFrame(rows)
    base = out[out.cost_year == REFERENCE_YEAR].set_index("technology")["investment"]
    out["index_2025"] = 100.0 * out["investment"] / out["technology"].map(base)
    out.to_csv(RESULTS / "cost_projections.csv", index=False,
               float_format="%.4f")
    return out


def write_vintages():
    vintages = pd.read_csv(PROCESSED / "cost_vintages.csv", comment="#")
    base = (vintages[vintages.release == "v0.1.0"]
            .set_index("technology")["investment_eur_per_kw"])
    vintages["index_first_release"] = (
        100.0 * vintages["investment_eur_per_kw"]
        / vintages["technology"].map(base))
    vintages.to_csv(RESULTS / "cost_vintages.csv", index=False,
                    float_format="%.4f")
    return vintages


def write_learning():
    """Fit the experience curve, and say what the fit means."""
    data = pd.read_csv(PROCESSED / "solar_learning.csv", comment="#")
    both = data.dropna(subset=["module_price_usd_per_w",
                               "cumulative_capacity_gw"]).copy()

    x = np.log2(both["cumulative_capacity_gw"].to_numpy())
    y = np.log2(both["module_price_usd_per_w"].to_numpy())
    slope, intercept = np.polyfit(x, y, 1)
    learning_rate = 1.0 - 2.0 ** slope
    fitted = 2.0 ** (intercept + slope * x)
    residual = y - np.log2(fitted)
    r_squared = 1.0 - residual.var() / y.var()

    both["fitted_price"] = fitted
    data.to_csv(RESULTS / "learning.csv", index=False, float_format="%.6f")
    both.to_csv(RESULTS / "learning_fit.csv", index=False, float_format="%.6f")

    return {
        "learning_rate": float(learning_rate),
        "slope": float(slope),
        "r_squared": float(r_squared),
        "first_year": int(both.year.min()),
        "last_year": int(both.year.max()),
        "first_price": float(both.module_price_usd_per_w.iloc[0]),
        "last_price": float(both.module_price_usd_per_w.iloc[-1]),
        "first_capacity": float(both.cumulative_capacity_gw.iloc[0]),
        "last_capacity": float(both.cumulative_capacity_gw.iloc[-1]),
        "doublings": float(np.log2(both.cumulative_capacity_gw.iloc[-1]
                                   / both.cumulative_capacity_gw.iloc[0])),
        "price_series_start": int(data.year.min()),
        "price_at_series_start": float(
            data.dropna(subset=["module_price_usd_per_w"]).module_price_usd_per_w.iloc[0]),
    }


def load_geography() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "geography_assumptions.csv", comment="#")


def write_geography(frame: pd.DataFrame):
    """Section 6: the note's own technology, re-priced under regional inputs.

    Nothing here is a published regional cost. Each region's levelised cost is
    computed from equation (4.2) with this note's investment, lifetime and
    fixed O&M, and only the four inputs of geography_assumptions.csv changed.
    That is what makes the numbers comparable: the boundary and the currency
    year are the note's own throughout.
    """
    geo = load_geography()
    wide = geo.pivot(index="region", columns="parameter", values="value")
    wide = wide.reindex(GEOGRAPHY_ORDER)
    base = wide.loc[BASE_REGION]

    solar, nuclear, ccgt = (frame.loc["solar-utility"], frame.loc["nuclear"],
                            frame.loc["CCGT"])

    def lcoe(row, rate, cf, capex_index=1.0, marginal=None):
        return levelised_cost(row.investment * capex_index, row.fom_rate,
                              row.lifetime,
                              row.marginal_cost if marginal is None else marginal,
                              cf, rate=rate)

    rows = []
    for region in GEOGRAPHY_ORDER:
        r = wide.loc[region]
        gas_mc = r["gas_price"] / ccgt.efficiency + ccgt.vom
        rows.append({
            "region": region,
            "discount_rate": r["discount_rate"],
            "solar_capacity_factor": r["solar_capacity_factor"],
            "solar_capex_index": r["solar_capex_index"],
            "gas_price": r["gas_price"],
            "carbon_price": r["carbon_price"],
            "nuclear_capex_index": r["nuclear_capex_index"],
            "lcoe_solar": lcoe(solar, r["discount_rate"],
                               r["solar_capacity_factor"],
                               r["solar_capex_index"]),
            "lcoe_nuclear": lcoe(nuclear, r["discount_rate"],
                                 nuclear.capacity_factor,
                                 r["nuclear_capex_index"]),
            "lcoe_ccgt": lcoe(ccgt, r["discount_rate"], ccgt.capacity_factor,
                              marginal=gas_mc),
            "mc_ccgt": gas_mc,
            "mc_ccgt_with_carbon": gas_mc + ccgt.emission_rate * r["carbon_price"],
        })
    table = pd.DataFrame(rows).set_index("region")
    table.to_csv(RESULTS / "geography.csv", float_format="%.4f")

    # The waterfall. One input is changed at a time, in a fixed order, from
    # the European case to each other region. The steps do not commute -- the
    # capacity factor divides the capital term that the discount rate scales
    # -- so the split between them depends on the order, and the note says so.
    steps = []
    for region in GEOGRAPHY_ORDER:
        if region == BASE_REGION:
            continue
        r = wide.loc[region]
        state = {"discount_rate": base["discount_rate"],
                 "solar_capacity_factor": base["solar_capacity_factor"],
                 "solar_capex_index": base["solar_capex_index"]}
        running = lcoe(solar, state["discount_rate"],
                       state["solar_capacity_factor"],
                       state["solar_capex_index"])
        steps.append({"region": region, "step": "start", "label": BASE_REGION,
                      "delta": np.nan, "level": running})
        for key, label in (("solar_capacity_factor", "Resource"),
                           ("solar_capex_index", "Investment cost"),
                           ("discount_rate", "Cost of capital")):
            state[key] = r[key]
            after = lcoe(solar, state["discount_rate"],
                         state["solar_capacity_factor"],
                         state["solar_capex_index"])
            steps.append({"region": region, "step": key, "label": label,
                          "delta": after - running, "level": after})
            running = after
        steps.append({"region": region, "step": "end", "label": region,
                      "delta": np.nan, "level": running})
    waterfall = pd.DataFrame(steps)
    waterfall.to_csv(RESULTS / "geography_waterfall.csv", index=False,
                     float_format="%.4f")

    # Carried through so stage 3 can print the assumptions table without
    # reaching into data/.
    geo.to_csv(RESULTS / "geography_assumptions.csv", index=False,
               float_format="%.4f")
    return table, waterfall


def write_summary(frame, decomposition, lcoe_cf, envelope, projections,
                  vintages, learning, geography, waterfall):
    """The scalars the prose quotes, so text and figures cannot disagree."""
    def lcoe_at(tech, cf):
        r = frame.loc[tech]
        return levelised_cost(r.investment, r.fom_rate, r.lifetime,
                              r.marginal_cost, cf)

    # Where the cheapest dispatchable technology changes, reading the envelope
    # from low duty to high.
    switches = []
    previous = None
    for _, row in envelope.iterrows():
        if row.cheapest != previous:
            switches.append({"full_load_hours": float(row.full_load_hours),
                             "capacity_factor": float(row.capacity_factor),
                             "technology": row.cheapest,
                             "label": row.label})
            previous = row.cheapest

    # How much of the levelised cost is capital, at the reference duty.
    capital_share = (decomposition["capital"] + decomposition["fixed_om"]) \
        / decomposition["total"]

    summary = {
        "discount_rate": DISCOUNT_RATE,
        "carbon_price": CARBON_PRICE,
        "electricity_price": ELECTRICITY_PRICE,
        "reference_year": REFERENCE_YEAR,
        "eur_year": int(frame["eur_year"].iloc[0]),
        "source_tag": str(frame["source_tag"].iloc[0]),
        "marginal_cost": {t: float(frame.loc[t, "marginal_cost"])
                          for t in frame.index},
        "emission_rate": {t: float(frame.loc[t, "emission_rate"])
                          for t in frame.index},
        "annuity_factor": {t: float(frame.loc[t, "annuity_factor"])
                           for t in frame.index},
        "capital_share_at_reference": {t: float(capital_share[t])
                                       for t in capital_share.index},
        "lcoe_reference": {t: float(lcoe_at(t, frame.loc[t, "capacity_factor"]))
                           for t in LCOE_TECHS},
        "envelope_switches": switches,
        "ocgt_vs_nuclear_crossover_hours": None,
        "carbon_cost_coal": float(frame.loc["coal", "emission_rate"] * CARBON_PRICE),
        "carbon_cost_ccgt": float(frame.loc["CCGT", "emission_rate"] * CARBON_PRICE),
        "learning": learning,
        "vintage_spread": {
            tech: {
                "first": float(sub.investment_eur_per_kw.iloc[0]),
                "last": float(sub.investment_eur_per_kw.iloc[-1]),
                "change_pct": float(100.0 * (sub.investment_eur_per_kw.iloc[-1]
                                             / sub.investment_eur_per_kw.iloc[0] - 1)),
            }
            for tech, sub in vintages.groupby("technology")
        },
        "projection_2050_index": {
            row.technology: float(row.index_2025)
            for row in projections[projections.cost_year == 2050].itertuples()
        },
        # The grid endpoints the two sweep figures are drawn over, and the
        # rates and sites the prose reads off them. Quoted rather than typed,
        # so that moving a grid moves the sentence describing it.
        "grids": {
            "rate_from": float(DISCOUNT_RATE_GRID[0]),
            "rate_to": float(DISCOUNT_RATE_GRID[-1]),
            "rate_low": 0.03,
            "rate_high": 0.11,
            "onwind_poor": 0.25,
            "onwind_good": 0.45,
            "solar_poor": 0.10,
            "solar_good": 0.25,
        },
    }

    # The duty at which a peaker stops being the cheapest way to serve a MWh.
    ocgt = lcoe_cf[lcoe_cf.technology == "OCGT"].set_index("full_load_hours")["lcoe"]
    ccgt = lcoe_cf[lcoe_cf.technology == "CCGT"].set_index("full_load_hours")["lcoe"]
    crossing = (ocgt - ccgt)
    sign_change = crossing[crossing.diff().notna() & (np.sign(crossing).diff() != 0)]
    if len(sign_change):
        summary["ocgt_ccgt_crossover_hours"] = float(sign_change.index[0])

    # What the discount rate does to the ranking: the two technologies whose
    # order it reverses, and where.
    rate_frame = pd.read_csv(RESULTS / "lcoe_discountrate.csv")
    wide = rate_frame.pivot(index="discount_rate", columns="technology",
                            values="lcoe")
    gap = wide["nuclear"] - wide["CCGT"]
    flips = gap[np.sign(gap).diff().fillna(0) != 0]
    summary["nuclear_ccgt_rate_crossover"] = (
        float(flips.index[0]) if len(flips) else None)
    summary["lcoe_by_rate"] = {
        f"{rate:.2f}": {tech: float(wide.loc[rate, tech]) for tech in wide.columns}
        for rate in (0.03, 0.07, 0.11) if rate in wide.index
    }

    # LCoE of wind and solar at their own capacity factor and at a much
    # better one -- the same machine, a different site.
    # Keyed by the capacity factor itself, because the macro name the note
    # quotes is built from it: a site moved here has to be moved in the prose.
    grids = summary["grids"]
    summary["site_quality"] = {
        f"onwind_at_{grids['onwind_poor']:.2f}": lcoe_at("onwind", grids["onwind_poor"]),
        f"onwind_at_{grids['onwind_good']:.2f}": lcoe_at("onwind", grids["onwind_good"]),
        f"solar_at_{grids['solar_poor']:.2f}": lcoe_at("solar-utility", grids["solar_poor"]),
        f"solar_at_{grids['solar_good']:.2f}": lcoe_at("solar-utility", grids["solar_good"]),
    }

    # Appendix A works one levelised cost out by hand and then claims the
    # answer matches Table 2. Every intermediate step is generated here, so
    # that the claim stays true when the pin moves instead of becoming a
    # silent lie in the one place a reader is most likely to check.
    ex = frame.loc[WORKED_EXAMPLE_TECH]
    energy_per_kw = HOURS_PER_YEAR * ex.capacity_factor / 1000.0
    summary["worked_example"] = {
        "technology": WORKED_EXAMPLE_TECH,
        "label": str(ex.label),
        "investment": float(ex.investment),
        "fom_rate": float(ex.fom_rate),
        "efficiency": float(ex.efficiency),
        "vom": float(ex.vom),
        "lifetime": float(ex.lifetime),
        "fuel_price": float(ex.fuel_price),
        "capacity_factor": float(ex.capacity_factor),
        "annuity_factor": float(ex.annuity_factor),
        "annual_capacity_cost": float(ex.annual_capacity_cost),
        "energy_per_kw_mwh": float(energy_per_kw),
        "capacity_cost_per_mwh": float(ex.annual_capacity_cost / energy_per_kw),
        "marginal_cost": float(ex.marginal_cost),
        "lcoe": float(lcoe_at(WORKED_EXAMPLE_TECH, ex.capacity_factor)),
    }

    # Section 6. Levels first, then the size of each channel in the waterfall,
    # so that the prose can say which one did the work without counting bars.
    summary["geography"] = {
        "base_region": BASE_REGION,
        "regions": GEOGRAPHY_ORDER,
        "levels": {
            region: {key: float(geography.loc[region, key])
                     for key in geography.columns}
            for region in geography.index
        },
        "waterfall": {
            region: {row.step: (None if pd.isna(row.delta) else float(row.delta))
                     for row in sub.itertuples()}
            for region, sub in waterfall.groupby("region")
        },
    }
    # Which single channel moves the number most, per region. This is the
    # sentence section 6 exists to be able to write.
    summary["geography"]["largest_channel"] = {
        region: max(
            ((row.label, abs(row.delta)) for row in sub.itertuples()
             if not pd.isna(row.delta)),
            key=lambda pair: pair[1])[0]
        for region, sub in waterfall.groupby("region")
    }

    # Appendix B illustrates that lifetime stops mattering once it is long, by
    # doubling a short life and a long one. Both the lifetimes and the annuity
    # factors are carried, so the prose cannot be left quoting a pair the
    # appendix no longer compares.
    summary["annuity_illustration"] = {
        name: {"from": lo, "to": hi,
               "factor_from": annuity(DISCOUNT_RATE, lo),
               "factor_to": annuity(DISCOUNT_RATE, hi)}
        for name, (lo, hi) in {"short": (10, 20), "long": (40, 80)}.items()
    }


    # Section 2 works the marginal-cost formula out on a coal plant. It uses
    # the note's own coal assumptions, so that the number a reader meets on
    # page 6 is the number Table 2 reports on page 14.
    coal = frame.loc["coal"]
    halved = coal.efficiency / 2.0
    summary["mc_example"] = {
        "fuel_price": float(coal.fuel_price),
        "efficiency": float(coal.efficiency),
        "vom": float(coal.vom),
        "co2_intensity_fuel": float(coal.co2_intensity_fuel),
        "marginal_cost": float(coal.marginal_cost),
        "emission_rate": float(coal.emission_rate),
        "efficiency_halved": float(halved),
        "marginal_cost_halved": float(coal.fuel_price / halved + coal.vom),
        "emission_rate_halved": float(coal.co2_intensity_fuel / halved),
    }

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                          encoding="utf-8")
    return summary


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    frame = assemble()

    table = write_cost_table(frame)
    write_fuels()
    decomposition = write_decomposition(frame)
    lcoe_cf, envelope = write_lcoe_capacityfactor(frame)
    write_lcoe_discountrate(frame)
    projections = write_projections(load_meta())
    vintages = write_vintages()
    learning = write_learning()
    geography, waterfall = write_geography(frame)
    summary = write_summary(frame, decomposition, lcoe_cf, envelope,
                            projections, vintages, learning, geography,
                            waterfall)

    print(f"wrote {len(table)} technologies to results/technology_costs.csv")
    print(f"solar learning rate: {summary['learning']['learning_rate']:.1%} "
          f"(R2 = {summary['learning']['r_squared']:.3f})")
    print("cheapest dispatchable technology, by duty:")
    for switch in summary["envelope_switches"]:
        print(f"  from {switch['full_load_hours']:>6.0f} h: {switch['label']}")
    print("\nstage 2 complete")


if __name__ == "__main__":
    main()
