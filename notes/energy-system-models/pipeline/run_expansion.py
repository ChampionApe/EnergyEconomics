"""Solve the section 8 expansion ladder and write what its figures need.

    python pipeline/run_expansion.py                fast default (336 segments)
    python pipeline/run_expansion.py --hours 1095   the note's figures
    python pipeline/run_expansion.py --aggregation stride
                                                    every k-th hour instead of
                                                    chronological segments
                                                    (see model/network.py)
    python pipeline/run_expansion.py --hours 1095 --resolution-check
                                                    additionally solve the top
                                                    rung at all 8760 hours
                                                    (about four hours on Gurobi)

Three rungs on the twelve-zone network:

    basic    every zone extendable beside its existing fleet, one
             system-wide CO2 budget, no industrial hydrogen, vehicles
             charging on a fixed profile
    ev       + the charging block's timing becomes a choice
    ev_h2    + the industrial hydrogen sector and the electrolytic route:
             reformers, imports, electrolyser, store and turbine

Each rung faces a budget set as a fraction of ITS OWN unconstrained
emissions, because rung (iii) carries a hydrogen sector the others do not
and one absolute target would mean a far deeper cut for it. So sigma
compares along a rung, not across rungs; see model/expansion.py.

Solved networks are cached in results/cache/ and fingerprinted against their
inputs; delete the cache to force re-solves.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTE))
sys.path.insert(0, str(NOTE / "pipeline"))

from model import expansion, greenfield, network
from run_dispatch import PROCESSED
from run_greenfield import REFERENCE_WEATHER_YEAR, cache_name, year_weather

RESULTS = NOTE / "results"
CACHE = RESULTS / "cache"
NETWORK_NC = PROCESSED / "network_eur_bz_2024.nc"

# The ladder. The order matters: each rung is the previous one plus one
# ingredient, and the figures read them in this order.
# Transmission is in every rung. A model that puts 2050 demand on a 2024
# grid and then reports where it is congested is measuring its own
# assumption, so the grid is a decision here like any other -- see
# model/expansion.py for what may be bought and what may not.
RUNGS = {
    "basic": {"transmission": True},
    "ev": {"ev": True, "transmission": True},
    "ev_h2": {"ev": True, "p2x": True, "hydrogen": True, "transmission": True},
}

# Budget points, as fractions of each rung's OWN unconstrained emissions.
# Per-rung baselines are forced by the ladder's shape: rung (iii) carries an
# industrial hydrogen sector the others do not, so one baseline in absolute
# tonnes would mean a far deeper cut for it than for the rungs it sits
# beside. The cost is that sigma is not comparable ACROSS rungs; what is
# comparable is each rung's own path from unconstrained to nearly zero.
#
# Three points, not more. The interesting region is the deep end -- a
# lightly decarbonised 2050 is not a scenario anyone is planning -- and the
# same three have to be affordable when this runs at full resolution.
BUDGET_FRACTIONS = [None, 0.25, 0.01]

# Which rung's unconstrained emissions each rung's budget is a fraction of.
#
# Rungs (i) and (ii) are the SAME system -- same demand, same technologies,
# differing only in whether charging may move -- so they share a baseline and
# their carbon prices compare directly. Give them their own and the ev rung
# is asked for a target some 7% tighter in absolute tonnes, purely because
# flexibility lowered its unconstrained emissions; its sigma then comes out
# higher and flexibility looks harmful while the quantities say the opposite.
#
# Rung (iii) keeps its own, because it carries a hydrogen sector the others
# do not: one absolute target across all three would ask it for a far deeper
# cut than its neighbours. So sigma compares within {basic, ev} and along
# rung (iii)'s own path, but not between those two groups.
BASELINE_RUNG = {"basic": "basic", "ev": "basic", "ev_h2": "ev_h2"}
REFERENCE_FRACTION = 0.01


def load_shared():
    return pd.read_csv(
        PROCESSED / f"technology_costs_full_{greenfield.FORWARD_HORIZON}.csv", index_col="technology"
    )


def input_fingerprint(aggregation: str = "segments", weather=None) -> str:
    """A short hash of everything a cached solve depends on — the same
    discipline as run_greenfield.py, extended with what section 8 adds."""
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
                 PROCESSED / "ev_assumptions.csv",
                 PROCESSED / "h2_assumptions.csv",
                 PROCESSED / "h2_imports.csv",
                 NETWORK_NC]:
        h.update(path.read_bytes() if path.exists() else b"<missing>")
    # The model's own source. Changing how a case is BUILT must invalidate
    # the cases already solved, or an edit silently returns the previous
    # answer -- which is exactly what happened on 2026-09-01, when section 7
    # was moved from electrifying Denmark to electrifying every zone and
    # "re-ran" in seconds, entirely from cache, reporting the old numbers.
    # Only the modules this section actually builds from are hashed, so an
    # edit to an unrelated model does not throw away hours of solves.
    for module in ["expansion.py", "greenfield.py", "network.py"]:
        h.update((NOTE / "model" / module).read_bytes())
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
        expansion.EV_STORE_DAYS, expansion.EV_CHARGER_HEADROOM,
        expansion.EV_CHARGER_EFFICIENCY,
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


def mix_row(n, sigma, rung, fraction):
    """One row of the ladder table: what was built, what it cost, what it
    emitted, and the carbon price that made it so."""
    caps = expansion.capacity(n).sum()
    caps["battery"] = sum(
        mw for tech, mw in caps.items() if str(tech).startswith("battery_")
    )
    shed = {
        c: float((n.generators_t.p[g] * n.snapshot_weightings.objective).sum())
        for g, c in n.generators.carrier.items()
        if str(c).startswith("shed_")
    }
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
        "emissions_t": expansion.system_emissions(n),
        "h2_store_mwh": float(expansion.h2_store_energy(n).sum()),
        **expansion.hydrogen_balance(n),
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

    for rung, kwargs in RUNGS.items():
        unconstrained = baselines[BASELINE_RUNG[rung]]
        print(f"{rung}: budgets from {BASELINE_RUNG[rung]}'s baseline "
              f"({unconstrained / 1e6:.2f} Mt)")
        for fraction in BUDGET_FRACTIONS:
            if fraction is None:
                tag, budget = f"{rung}_nocap", None
            else:
                tag = f"{rung}_cap{int(fraction * 100)}"
                budget = fraction * unconstrained
            n, sigma = solve_case(tag, costs_full, hours, co2_budget=budget,
                                  aggregation=aggregation, **kwargs)
            row = mix_row(n, sigma, rung, fraction)
            row["unconstrained_t"] = unconstrained
            row["baseline_rung"] = BASELINE_RUNG[rung]
            row["biomethane_shadow_eur_mwh"] = n.meta.get("biomethane_shadow")
            rows.append(row)
    return pd.DataFrame(rows), baselines


def zone_detail(costs_full, hours, aggregation):
    """Built capacity by zone and technology at the reference budget of the
    top rung — the map behind the ladder table."""
    top = list(RUNGS)[-1]
    base, _ = solve_case(f"{top}_nocap", costs_full, hours,
                         aggregation=aggregation, **RUNGS[top])
    unconstrained = expansion.system_emissions(base)
    n, _ = solve_case(
        f"{top}_cap{int(REFERENCE_FRACTION * 100)}", costs_full, hours,
        co2_budget=REFERENCE_FRACTION * unconstrained,
        aggregation=aggregation, **RUNGS[top],
    )
    frame = expansion.capacity(n)
    frame["h2_store_mwh"] = expansion.h2_store_energy(n)
    return frame.fillna(0.0)


def run_resolution_check(costs_full, hours, aggregation):
    """Does the time aggregation move section 8's answer?

    The section's headline storage number is a seasonal hydrogen store, and
    a seasonal store is exactly what a year cut into pieces can misjudge.
    This solves the top rung unconstrained and at the reference budget at
    all 8760 hours and writes the aggregated and full-year answers side by
    side: carbon price, hydrogen store, hydrogen turbine, battery. Expensive
    — the constrained case took over three hours on Gurobi on 2026-09-02.
    """
    top = list(RUNGS)[-1]
    # The full year is the full year under either scheme; "stride" keeps
    # the bare cache names expansion_{tag}_8760.nc.
    base, _ = solve_case(f"{top}_nocap", costs_full, 8760,
                         aggregation="stride", **RUNGS[top])
    unconstrained = expansion.system_emissions(base)
    tag = f"{top}_cap{int(REFERENCE_FRACTION * 100)}"
    n, sigma = solve_case(tag, costs_full, 8760, aggregation="stride",
                          co2_budget=REFERENCE_FRACTION * unconstrained,
                          **RUNGS[top])
    full = mix_row(n, sigma, top, REFERENCE_FRACTION)
    # The every-k-th-hour answer at the same size, kept beside the full-year
    # one because it is the reason the note's figures moved to segments:
    # it over-states the seasonal hydrogen store several-fold (see
    # model/network.py).
    stride = None
    if aggregation != "stride":
        b, _ = solve_case(f"{top}_nocap", costs_full, hours,
                          aggregation="stride", **RUNGS[top])
        ns, sig = solve_case(
            tag, costs_full, hours, aggregation="stride",
            co2_budget=REFERENCE_FRACTION * expansion.system_emissions(b),
            **RUNGS[top])
        stride = mix_row(ns, sig, top, REFERENCE_FRACTION)
    ladder = pd.read_csv(RESULTS / "expansion_ladder.csv")
    row = ladder[(ladder.rung == top)
                 & (ladder.budget_share == REFERENCE_FRACTION)].iloc[0]
    keys = ["co2_price_eur_t", "h2_store_mwh", "cap_h2_turbine_mw",
            "cap_electrolyser_mw", "electrolyser_flh", "cap_battery_mw",
            "cap_ocgt_biogas_mw", "system_cost_eur"]
    check = {
        "rung": top,
        "budget_fraction": REFERENCE_FRACTION,
        "hours_sampled": hours,
        "aggregation_sampled": aggregation,
        "sampled": {k: float(row[k]) for k in keys if k in row.index},
        "full": {k: float(full[k]) for k in keys if k in full},
        "stride_same_hours": (
            {k: float(stride[k]) for k in keys if k in stride}
            if stride is not None else None),
    }
    (RESULTS / "expansion_resolution_check.json").write_text(
        json.dumps(check, indent=2), encoding="utf-8")
    print(f"resolution check: sigma {check['sampled']['co2_price_eur_t']:.0f} "
          f"EUR/t at {hours} {aggregation} vs {check['full']['co2_price_eur_t']:.0f} "
          f"at 8760; hydrogen store {check['sampled']['h2_store_mwh'] / 1e6:.1f} vs "
          f"{check['full']['h2_store_mwh'] / 1e6:.1f} TWh")
    print("wrote results/expansion_resolution_check.json")


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
        "--resolution-check", action="store_true",
        help="additionally solve the top rung at full hourly resolution and "
        "record how far the aggregated answer sits from it (very expensive; "
        "run after the ladder)",
    )
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    costs_full = load_shared()

    ladder, baselines = run_ladder(costs_full, args.hours, args.aggregation)
    ladder.to_csv(RESULTS / "expansion_ladder.csv", index=False)
    print(f"wrote results/expansion_ladder.csv ({len(ladder)} rows)")

    detail = zone_detail(costs_full, args.hours, args.aggregation)
    detail.to_csv(RESULTS / "expansion_zones.csv")
    print(f"wrote results/expansion_zones.csv ({len(detail)} zones)")

    summary = {
        "hours": args.hours,
        "aggregation": args.aggregation,
        "rungs": list(RUNGS),
        "budget_fractions": ["none" if f is None else f
                             for f in BUDGET_FRACTIONS],
        "reference_fraction": REFERENCE_FRACTION,
        "unconstrained_emissions_t": {k: v for k, v in baselines.items()},
        "reference_rung": list(RUNGS)[-1],
        "reference_budget_t": REFERENCE_FRACTION * baselines[list(RUNGS)[-1]],
        "biomethane_potential_twh":
            greenfield.BIOMETHANE_POTENTIAL_MWH / 1e6,
        "cavern_zones": expansion.CAVERN_ZONES,
        "ev_store_days": expansion.EV_STORE_DAYS,
        "forward_horizon": greenfield.FORWARD_HORIZON,
    }
    (RESULTS / "expansion_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print("wrote results/expansion_summary.json")
    if args.resolution_check:
        run_resolution_check(costs_full, args.hours, args.aggregation)


if __name__ == "__main__":
    main()
