"""Turn results into the figures and tables the note includes.

    python pipeline/build.py

Stage 3 of the pipeline. Reads **only** `results/`. Imports no model code,
unpickles no model instance, solves nothing. That invariant is what makes
rebuilding the note cost seconds rather than hours, and it is enforced below
rather than left to discipline.

If a figure needs a number that is not in `results/`, the fix is to have the
`run_*` stage write it out — not to import a model here.

Output goes to `writing/generated/` — figures and table fragments land next to
the tex source so the note compiles from `writing/` alone. Everything under
`writing/generated/` is owned by this script and overwritten on every build;
hand-made figures live in `writing/figures/` and are never touched.

Currently builds, from the output of run_dispatch.py:

    generated/figures/dispatch_merit_order.pdf   fig 2.1  merit order, price, rents
    generated/figures/dispatch_carbon_tax.pdf    fig 2.2  merit order with/without tax
    generated/figures/dispatch_cap_sweep.pdf     fig 2.3  cap shadow price vs cap level
    generated/tables/dispatch_tech_table.tex     tab 2.1  the small technology table
    generated/tables/dispatch_values.tex         macros for numbers quoted in prose
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
RESULTS = NOTE / "results"
GENERATED = NOTE / "writing" / "generated"
FIGURES = GENERATED / "figures"
TABLES = GENERATED / "tables"

# One restrained style for every figure in the note: recessive axes and grid,
# colour only where it carries meaning. The two hues are colourblind-safe
# (Okabe-Ito); identity is always also carried by a direct label.
BLUE = "#0072B2"
VERMILLION = "#D55E00"
BLOCK_FILL = "#aecde3"
INK = "#333333"


def label_color(color):
    """A series colour for a direct label, darkened when it is too pale to
    read as text on white (the Okabe-Ito yellow is): text needs more
    contrast than a line or a bar does. Other colours pass unchanged."""
    from matplotlib.colors import to_rgb
    rgb = to_rgb(color)
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    if luminance <= 0.75:
        return color
    return tuple(c * 0.45 / luminance for c in rgb)

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#666666",
        "axes.labelcolor": INK,
        "xtick.color": "#666666",
        "ytick.color": "#666666",
        "grid.color": "#e0e0e0",
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "figure.constrained_layout.use": True,
    }
)


def _forbid_model_imports():
    """Fail loudly if anything pulls in model code.

    Importing a model module for a constant or an axis label is the usual way
    this stage quietly turns into a solve. Make it an error instead of a
    slowdown nobody notices until the note takes an hour to rebuild.
    """

    class _Blocker:
        # find_spec, not find_module: the latter is not called at all from
        # Python 3.12 onwards, so a blocker written against it does nothing.
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {"model", "models"}:
                raise ImportError(
                    f"build.py must not import {name!r}. This stage reads only "
                    f"results/. If you need a value from the model, have the "
                    f"run_* stage write it into results/."
                )
            return None

    sys.meta_path.insert(0, _Blocker())


def load_results():
    """Read everything this stage is allowed to read. Missing files are left
    out of the dict, and the figures that need them are skipped — the pipeline
    stays runnable while only some run_* stages exist."""
    if not RESULTS.exists():
        raise SystemExit(
            "results/ does not exist — run the pipeline's run_* stage first."
        )
    results = {}
    if (RESULTS / "dispatch_summary.json").exists():
        results["dispatch"] = {
            "generators": pd.read_csv(RESULTS / "dispatch_generators.csv", index_col="tech"),
            "cap_sweep": pd.read_csv(RESULTS / "dispatch_cap_sweep.csv"),
            "tech_table": pd.read_csv(RESULTS / "dispatch_tech_table.csv"),
            "summary": json.loads((RESULTS / "dispatch_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "dispatch_t_summary.json").exists():
        results["dispatch_t"] = {
            "generators": pd.read_csv(RESULTS / "dispatch_t_generators.csv", index_col="tech"),
            "hours": pd.read_csv(RESULTS / "dispatch_t_hours.csv", index_col="time", parse_dates=True),
            "sweep": pd.read_csv(RESULTS / "dispatch_t_sweep.csv"),
            "residual": pd.read_csv(RESULTS / "dispatch_t_residual.csv", index_col="pct_of_hours"),
            "profiles": pd.read_csv(RESULTS / "dispatch_t_profiles.csv", index_col="time", parse_dates=True),
            "summary": json.loads((RESULTS / "dispatch_t_summary.json").read_text(encoding="utf-8")),
        }
        actual_file = RESULTS / "dispatch_t_actual_duration.csv"
        if actual_file.exists():
            results["dispatch_t"]["actual_duration"] = pd.read_csv(
                actual_file, index_col="pct_of_hours"
            )
        week_model = RESULTS / "dispatch_t_week_model.csv"
        week_actual = RESULTS / "dispatch_t_week_actual.csv"
        if week_model.exists() and week_actual.exists():
            results["dispatch_t"]["week_model"] = pd.read_csv(
                week_model, index_col="time", parse_dates=True
            )
            results["dispatch_t"]["week_actual"] = pd.read_csv(
                week_actual, index_col="time", parse_dates=True
            )
    if (RESULTS / "storage_summary.json").exists():
        results["storage"] = {
            "hours": pd.read_csv(RESULTS / "storage_hours.csv", index_col="time", parse_dates=True),
            "prices": pd.read_csv(RESULTS / "storage_prices.csv", index_col="time", parse_dates=True),
            "recovery": pd.read_csv(RESULTS / "storage_recovery.csv"),
            "ramp": pd.read_csv(RESULTS / "storage_ramp_sweep.csv"),
            "summary": json.loads((RESULTS / "storage_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "heat_summary.json").exists():
        results["heat"] = {
            "hours": pd.read_csv(RESULTS / "heat_hours.csv", index_col="time", parse_dates=True),
            "rollout": pd.read_csv(RESULTS / "heat_rollout.csv"),
            "summary": json.loads((RESULTS / "heat_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "network_summary.json").exists():
        results["network"] = {
            "prices": pd.read_csv(RESULTS / "network_prices.csv", index_col="hour"),
            "rents": pd.read_csv(RESULTS / "network_rents.csv", index_col="corridor"),
            "wind_duration": pd.read_csv(RESULTS / "network_wind_duration.csv", index_col="pct_of_hours"),
            "wind_hourly": pd.read_csv(RESULTS / "network_wind_hourly.csv", index_col="time", parse_dates=True),
            "expansion": pd.read_csv(RESULTS / "network_expansion.csv"),
            "rents_carbon": (
                pd.read_csv(RESULTS / "network_rents_carbon.csv", index_col="corridor")
                if (RESULTS / "network_rents_carbon.csv").exists() else None
            ),
            "summary": json.loads((RESULTS / "network_summary.json").read_text(encoding="utf-8")),
        }
        accounts_file = RESULTS / "network_expansion_accounts.csv"
        if accounts_file.exists():
            results["network"]["accounts"] = pd.read_csv(accounts_file)
        calibration_file = RESULTS / "network_calibration.csv"
        if calibration_file.exists():
            results["network"]["calibration"] = pd.read_csv(calibration_file)
        geography_file = RESULTS / "network_geography.json"
        if geography_file.exists():
            results["network"]["geography"] = json.loads(
                geography_file.read_text(encoding="utf-8"))
    if (RESULTS / "greenfield_summary.json").exists():
        results["greenfield"] = {
            "screening": pd.read_csv(RESULTS / "greenfield_screening.csv", index_col="tech"),
            "duty": (
                pd.read_csv(RESULTS / "greenfield_realised_duty.csv", index_col="tech")
                if (RESULTS / "greenfield_realised_duty.csv").exists() else None
            ),
            "sweep": pd.read_csv(RESULTS / "greenfield_tax_sweep.csv"),
            "breakdown": pd.read_csv(RESULTS / "greenfield_cost_breakdown.csv", index_col="tech"),
            "scenarios": pd.read_csv(RESULTS / "greenfield_scenarios.csv", index_col="scenario"),
            "resolution": (
                json.loads((RESULTS / "greenfield_resolution_check.json").read_text(encoding="utf-8"))
                if (RESULTS / "greenfield_resolution_check.json").exists() else None
            ),
            "summary": json.loads((RESULTS / "greenfield_summary.json").read_text(encoding="utf-8")),
            # Result 6 in numbers (one row per candidate and Danish zone),
            # the LCOE-against-capture-price table and the scarcity curve:
            # written by run_greenfield.py from the reference solve.
            **{key: (pd.read_csv(RESULTS / f"greenfield_{key}.csv", **kw)
                     if (RESULTS / f"greenfield_{key}.csv").exists() else None)
               for key, kw in [("cost_recovery", {}),
                               ("value_table", {"index_col": "tech"}),
                               ("price_bands", {}),
                               ("spell_window", {"index_col": "time",
                                                 "parse_dates": ["time"]})]},
        }
    if (RESULTS / "weather_summary.json").exists():
        results["weather"] = {
            "mix": pd.read_csv(RESULTS / "weather_mix.csv", index_col="year"),
            "summary": json.loads((RESULTS / "weather_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "costs_summary.json").exists():
        results["costs"] = {
            "mix": pd.read_csv(RESULTS / "costs_mix.csv", index_col="scenario"),
            "summary": json.loads((RESULTS / "costs_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "expansion_summary.json").exists():
        ladder = pd.read_csv(RESULTS / "expansion_ladder.csv")
        if "budget_share" not in ladder.columns:
            # Written by a run_expansion.py older than the numeric budget
            # column. Say so instead of failing three functions later on a
            # KeyError, and instead of quietly reconstructing it here --
            # stage 3 does not repair stage 2's schema.
            print("skipping section 8 — results/expansion_ladder.csv predates "
                  "the budget_share column; re-run pipeline/run_expansion.py "
                  "(every solve is cached, so it only rewrites the tables)")
        else:
            results["expansion"] = {
                "ladder": ladder,
                "zones": pd.read_csv(RESULTS / "expansion_zones.csv", index_col="zone"),
                "summary": json.loads((RESULTS / "expansion_summary.json").read_text(encoding="utf-8")),
                "resolution": (
                    json.loads((RESULTS / "expansion_resolution_check.json").read_text(encoding="utf-8"))
                    if (RESULTS / "expansion_resolution_check.json").exists() else None
                ),
                "resolution_v2g": (
                    json.loads((RESULTS / "expansion_resolution_check_ev_v2g.json").read_text(encoding="utf-8"))
                    if (RESULTS / "expansion_resolution_check_ev_v2g.json").exists() else None
                ),
                # The figures' tables, all of the whole system: generation
                # by source, the price duration curves and what sets the
                # price, what covers the scarcest hours, what a marginal
                # storage facility earns and the hydrogen by month, written
                # by run_expansion.py from the ladder's solves.
                **{key: (pd.read_csv(RESULTS / f"expansion_{key}.csv", **kw)
                         if (RESULTS / f"expansion_{key}.csv").exists() else None)
                   for key, kw in [("generation", {}), ("price_duration", {}),
                                   ("price_setters", {}), ("scarce_hours", {}),
                                   ("marginal_storage", {}),
                                   ("hydrogen_months", {"index_col": "month"})]},
            }
    return results


# --------------------------------------------------------------------------
# Section 2 — dispatch
# --------------------------------------------------------------------------

def _draw_merit_order(ax, generators, mc_col, gen_col, price, load_mw,
                      shade_rent=False, highlight=None):
    """One merit-order panel: capacity blocks sorted by marginal cost, the
    load, and the market-clearing price read off the intersection."""
    df = generators.sort_values(mc_col)
    x = 0.0
    for tech, row in df.iterrows():
        width = row["capacity_mw"] / 1000.0
        fill = VERMILLION if tech == highlight else BLOCK_FILL
        ax.bar(x, row[mc_col], width=width, align="edge",
               color=fill, edgecolor="white", linewidth=0.8)
        if shade_rent and price > row[mc_col] and row[gen_col] > 0:
            # Scarcity rent lambda - c_g over the dispatched width.
            ax.bar(x, price - row[mc_col], bottom=row[mc_col],
                   width=row[gen_col] / 1000.0, align="edge",
                   color=BLUE, alpha=0.18, linewidth=0)
        label_y = max(row[mc_col], price if shade_rent and row[gen_col] > 0 else 0.0)
        ax.text(x + width / 2.0, label_y + 4, row["label"], rotation=90,
                ha="center", va="bottom", fontsize=7, color=INK)
        x += width

    ax.axvline(load_mw / 1000.0, color=INK, linewidth=1.0, linestyle="--")
    ax.axhline(price, color=INK, linewidth=0.8, linestyle=":")
    ax.text(load_mw / 1000.0, ax.get_ylim()[1], " load $D$",
            ha="left", va="top", fontsize=8, color=INK)
    # Above the dotted line, not on it.
    ax.annotate(rf"$\lambda = {price:.0f}$", xy=(x + 0.05, price), xytext=(0, 2),
                textcoords="offset points", ha="left", va="bottom",
                fontsize=8, color=INK)
    ax.set_xlim(0, x * 1.09)
    ax.grid(axis="y")
    ax.set_ylabel("marginal cost (€/MWh)")


def fig_dispatch_merit_order(d):
    """Figure 2.1: the merit order, the price, and the scarcity rents."""
    s = d["summary"]
    fig, ax = plt.subplots(figsize=(6.1, 3.5))
    _draw_merit_order(ax, d["generators"], "mc_base", "generation_base_mw",
                      s["price_base_eur_per_mwh"], s["load_mw"], shade_rent=True)
    ax.text(1.7, s["price_base_eur_per_mwh"] * 0.55,
            "scarcity rents\n" + r"$\mu_g = \lambda - c_g$",
            ha="center", va="center", fontsize=8, color=BLUE)
    ax.set_ylim(0, d["generators"]["mc_base"].max() * 1.45)
    ax.set_xlabel("cumulative capacity (GW)")
    fig.savefig(FIGURES / "dispatch_merit_order.pdf")
    plt.close(fig)


def fig_dispatch_carbon_tax(d):
    """Figure 2.2: the same merit order without and with a carbon price. Coal
    is highlighted in both panels — the tax moves it from the middle of the
    order to the expensive end, and out of the dispatch."""
    s = d["summary"]
    tau = s["co2_price_eur_per_t"]
    fig, axes = plt.subplots(2, 1, figsize=(6.1, 5.6), sharex=True)
    _draw_merit_order(axes[0], d["generators"], "mc_base", "generation_base_mw",
                      s["price_base_eur_per_mwh"], s["load_mw"], highlight="coal_chp")
    _draw_merit_order(axes[1], d["generators"], "mc_tax", "generation_tax_mw",
                      s["price_tax_eur_per_mwh"], s["load_mw"], highlight="coal_chp")
    axes[0].set_ylim(0, d["generators"]["mc_tax"].max() * 1.5)
    axes[1].set_ylim(0, d["generators"]["mc_tax"].max() * 1.5)
    axes[0].set_title(r"(a) no carbon price", loc="left", fontsize=9, color=INK)
    axes[1].set_title(rf"(b) carbon price $\tau = {tau:.0f}$ €/t", loc="left",
                      fontsize=9, color=INK)
    axes[1].set_xlabel("cumulative capacity (GW)")
    fig.savefig(FIGURES / "dispatch_carbon_tax.pdf")
    plt.close(fig)


def fig_dispatch_cap_sweep(d):
    """Figure 2.3: the shadow price of the emissions cap against the cap
    level — the marginal abatement cost step function."""
    s = d["summary"]
    sweep = d["cap_sweep"]
    tau = s["co2_price_eur_per_t"]

    fig, ax = plt.subplots(figsize=(6.1, 3.5))
    ax.plot(sweep["cap_t"], sweep["co2_shadow_price_eur_per_t"],
            color=BLUE, linewidth=1.8)

    # The tax experiment sits on this curve: a cap at the tax run's realised
    # emissions supports the same dispatch with sigma = tau.
    ax.plot([s["emissions_tax_t"]], [tau], marker="o", markersize=6,
            color=VERMILLION, zorder=3)
    ax.annotate(rf"cap at tax-run emissions:  $\sigma = \tau = {tau:.0f}$",
                xy=(s["emissions_tax_t"], tau),
                xytext=(s["emissions_tax_t"] + 60, tau + 60),
                fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="-", color="#999999", linewidth=0.8))
    ax.annotate("cap slack:\nunconstrained dispatch",
                xy=(s["emissions_unconstrained_t"], 0), xytext=(-10, 25),
                textcoords="offset points", ha="right", fontsize=8, color=INK)

    ax.grid(axis="y")
    ax.set_xlabel("emissions cap $E$ (t CO$_2$)")
    ax.set_ylabel(r"shadow price of the cap $\sigma$ (€/t CO$_2$)")
    fig.savefig(FIGURES / "dispatch_cap_sweep.pdf")
    plt.close(fig)


# ---------------------------------------------------------------------------
# The smooth, top-down marginal abatement cost curve.
#
# SHARED-FIGURE SEAM. This block is analytic, not a model result: it is the
# textbook MAC curve that a top-down model *assumes*, drawn so that section 2
# can hold it against the step function its own LP *derives*. It belongs to
# the abatement-costs note as much as to this one.
#
# When notes/abatement-costs lands, move MAC_TOPDOWN and topdown_mac() into a
# module both notes can import (or have that note's run stage write the curve
# into results/ and read it here like any other result). Until then it lives
# here, parameterised in one place, so the move is a cut-and-paste rather than
# an archaeology exercise. Nothing else in build.py depends on it.
#
# The model behind it is the one-good abatement problem: output F(E) from
# fossil energy E priced at p, emissions M = phi * E, so that
#     MAC(A) = (F'(E) - p) / phi   with abatement A = M0 - M.
# With F(E) = a * E^alpha the derivative is closed-form and MAC is convex and
# increasing in A, which is the shape the argument needs. The parameters are
# chosen so the curve spans the same range as this section's LP result; they
# are illustrative and the note says so.
# ---------------------------------------------------------------------------
MAC_TOPDOWN = {
    "alpha": 0.55,           # curvature of F(E) = a * E^alpha; alpha < 1
    "share_of_floor": 0.97,  # abate at most this far toward the feasible floor
}


def topdown_mac(emissions_unconstrained, emissions_floor, anchor, n=300):
    """The smooth MAC curve of the one-good abatement model, as a function of
    abatement. Returns (A, MAC).

    Shape comes from the model: with output F(E) = a E^alpha from fossil
    energy E priced at p, and emissions M = phi E,

        MAC(A) = (F'(E) - p) / phi  proportional to  (M/M_0)^(alpha-1) - 1,

    which is zero at A = 0 and rises convexly as abatement bites. Only the
    *shape* is meaningful, so the level is calibrated: the free multiplier is
    fixed by making the curve pass through `anchor` at maximum abatement, so
    the two curves span the same range and the eye compares shapes rather
    than scales. The note says the curve is illustrative.
    """
    import numpy as np

    alpha = MAC_TOPDOWN["alpha"]
    m0 = emissions_unconstrained
    reach = MAC_TOPDOWN["share_of_floor"] * (m0 - emissions_floor)
    abatement = np.linspace(0.0, reach, n)
    shape = ((m0 - abatement) / m0) ** (alpha - 1.0) - 1.0
    scale = anchor / shape[-1] if shape[-1] > 0 else 0.0
    return abatement, scale * shape


def fig_dispatch_mac(d):
    """Figure 2.4: the model's marginal abatement cost curve against the
    smooth one a top-down model would assume.

    Same object, two derivations. The steps are technology switches with
    names; the smooth curve is a functional-form assumption. This is the
    note's best single advertisement for bottom-up modelling."""
    s = d["summary"]
    sweep = d["cap_sweep"].sort_values("emissions_t")
    m0 = s["emissions_unconstrained_t"]
    floor = s["emissions_floor_t"]

    abatement = m0 - sweep["emissions_t"]
    sigma = sweep["co2_shadow_price_eur_per_t"]

    fig, ax = plt.subplots(figsize=(6.1, 3.6))
    ax.step(abatement, sigma, where="post", color=BLUE, linewidth=1.8,
            label="bottom-up: the LP's shadow price $\\sigma(E)$")

    a_smooth, mac_smooth = topdown_mac(m0, floor, anchor=float(sigma.max()))
    ax.plot(a_smooth, mac_smooth, color="#999999", linewidth=1.6,
            linestyle="--",
            label="top-down: an assumed MAC curve (illustrative)")

    ax.annotate("each flat step is one abatement margin —\n"
                "a named pair of technologies swapping places",
                xy=(0.42 * (m0 - floor), 70),
                xytext=(0.06 * (m0 - floor), 158),
                fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="->", color="#999999", linewidth=0.8))
    # In the empty corner under both curves, clear of the dashed one.
    ax.annotate("same object, two derivations:\none assumes the shape,\n"
                "the other explains it",
                xy=(0.99 * (m0 - floor), 6), ha="right", va="bottom",
                fontsize=8, color="#777777")

    ax.set_xlim(0, (m0 - floor) * 1.02)
    ax.grid(axis="y")
    ax.set_xlabel("abatement $A = M_0 - M$ (t CO$_2$)")
    ax.set_ylabel("marginal abatement cost (€/t CO$_2$)")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.savefig(FIGURES / "dispatch_mac.pdf")
    plt.close(fig)


def table_dispatch_tech(d):
    """Table 2.1: the small technology table, typeset from the exact numbers
    the model ran on, with a source note per row."""
    df = d["tech_table"]

    sources, notes = {}, []
    for src in df["source"]:
        if src not in sources:
            sources[src] = chr(ord("a") + len(sources))
            notes.append((sources[src], src))

    def fuel_cols(row):
        if row["fuel"] == "none":
            return "--", "--", "--", "--"
        return (
            row["fuel"],
            f"{row['fuel_price_eur_per_mwh_th']:.0f}",
            f"{row['efficiency']:.2f}",
            f"{row['co2_t_per_mwh_th']:.2f}",
        )

    lines = [
        "%% GENERATED by pipeline/build.py from results/dispatch_tech_table.csv",
        "%% -- do not edit; rerun the pipeline instead.",
        r"\begin{threeparttable}",
        r"\begin{tabular}{l l r r r r r r}",
        r"\toprule",
        r" & & $p^F_g$ & $\eta_g$ & $o_g$ & $\varphi_g$ & $c_g$ & $e_g$ \\",
        r"Technology & Fuel & \footnotesize{€/MWh$_{th}$} & & \footnotesize{€/MWh}"
        r" & \footnotesize{t/MWh$_{th}$} & \footnotesize{€/MWh} & \footnotesize{t/MWh} \\",
        r"\midrule",
    ]
    for _, row in df.iterrows():
        fuel, p_fuel, eta, phi = fuel_cols(row)
        lines.append(
            rf"{row['label']}\tnote{{{sources[row['source']]}}} & {fuel} & {p_fuel}"
            rf" & {eta} & {row['vom_eur_per_mwh']:.1f} & {phi}"
            rf" & {row['marginal_cost']:.1f} & {row['emission_rate']:.2f} \\"
        )
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\begin{tablenotes}\footnotesize",
    ]
    for letter, src in notes:
        # One full stop, whether or not the source note brings its own.
        src = src.replace("CO2", "CO$_2$").rstrip(".")
        lines.append(rf"\item[{letter}] {src}.")
    lines += [
        r"\end{tablenotes}",
        r"\end{threeparttable}",
        "",
    ]
    (TABLES / "dispatch_tech_table.tex").write_text("\n".join(lines), encoding="utf-8")


def values_dispatch(d):
    """Numbers quoted in the running text of section 2, as LaTeX macros. The
    section inputs this file, so a change in the data or the instance flows
    into the prose instead of silently contradicting it."""
    s = d["summary"]
    g = d["generators"]
    drop = 100.0 * (1.0 - s["emissions_tax_t"] / s["emissions_base_t"])
    macros = {
        "DispatchLoadGW": f"{s['load_mw'] / 1000:.0f}",
        "DispatchTax": f"{s['co2_price_eur_per_t']:.0f}",
        "DispatchPriceBase": f"{s['price_base_eur_per_mwh']:.1f}",
        "DispatchPriceTax": f"{s['price_tax_eur_per_mwh']:.1f}",
        "DispatchEmissionsBase": f"{s['emissions_base_t']:.0f}",
        "DispatchEmissionsTax": f"{s['emissions_tax_t']:.0f}",
        "DispatchEmissionsFloor": f"{s['emissions_floor_t']:.0f}",
        "DispatchEmissionsDropPct": f"{drop:.0f}",
        "DispatchRentCoalBase": f"{g.loc['coal_chp', 'rent_base']:.1f}",
        "DispatchRentWindBase": f"{g.loc['wind_onshore', 'rent_base']:.1f}",
        "DispatchRentWindTax": f"{g.loc['wind_onshore', 'rent_tax']:.1f}",
        "DispatchMCCoalBase": f"{g.loc['coal_chp', 'mc_base']:.1f}",
        "DispatchMCCoalTax": f"{g.loc['coal_chp', 'mc_tax']:.1f}",
        "DispatchECoal": f"{g.loc['coal_chp', 'emission_rate_t_per_mwh']:.2f}",
        "DispatchMCGasBase": f"{g.loc['ccgt', 'mc_base']:.1f}",
        "DispatchMCGasTax": f"{g.loc['ccgt', 'mc_tax']:.1f}",
    }
    lines = [
        "%% GENERATED by pipeline/build.py from results/dispatch_summary.json",
        "%% -- do not edit; rerun the pipeline instead.",
    ]
    lines += [rf"\providecommand{{\{name}}}{{{value}}}" for name, value in macros.items()]
    (TABLES / "dispatch_values.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Section 3 — intermittency
# --------------------------------------------------------------------------

# Fixed colours for the three VRE technologies, everywhere they appear.
VRE_COLORS = {
    "wind_onshore": BLUE,
    "wind_offshore": "#56B4E9",
    "solar": "#E69F00",
}
VRE_LABELS = {
    "wind_onshore": "onshore wind",
    "wind_offshore": "offshore wind",
    "solar": "solar",
}


def fig_intermittency_profiles(d):
    """Figure 3.1: the DK1 availability profiles — a winter and a summer week
    hour by hour, and the whole year as duration curves."""
    p = d["profiles"]
    year = d["summary"]["year"]
    cf = d["summary"]["profile_capacity_factors"]

    fig, axes = plt.subplots(3, 1, figsize=(6.1, 6.6))
    windows = [
        (f"{year}-01-08", f"{year}-01-15", "(a) a January week"),
        (f"{year}-07-08", f"{year}-07-15", "(b) a July week"),
    ]
    # Demand belongs on the same axes as availability. The section's argument
    # is about *when* a technology produces relative to when people consume,
    # and a reader cannot see that from two figures on different pages.
    load_max = p["load_mw"].max()
    for ax, (start, end, title) in zip(axes[:2], windows):
        window = p.loc[start:end]
        ax.fill_between(window.index, window["load_mw"] / load_max,
                        color="#d9d9d9", zorder=0, label="demand")
        for name, color in VRE_COLORS.items():
            ax.plot(window.index, window[f"{name}_pu"], color=color,
                    linewidth=1.3, label=VRE_LABELS[name])
        ax.set_title(title, loc="left", fontsize=9, color=INK)
        # Headroom above full output, so the legend sits over empty axes
        # rather than over a windy hour; the ticks stop at one.
        ax.set_ylim(0, 1.22)
        ax.set_yticks([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
        ax.grid(axis="y")
        ax.margins(x=0)
        ax.tick_params(axis="x", labelsize=7)
    axes[0].legend(frameon=False, fontsize=8, ncol=4, loc="upper center")

    ax = axes[2]
    pct = (pd.RangeIndex(len(p)) + 0.5) / len(p) * 100.0
    for name, color in VRE_COLORS.items():
        sorted_pu = p[f"{name}_pu"].sort_values(ascending=False).to_numpy()
        ax.plot(pct, sorted_pu, color=color, linewidth=1.6)
    for name, x in [("wind_offshore", 30), ("wind_onshore", 40)]:
        y = p[f"{name}_pu"].sort_values(ascending=False).to_numpy()[
            int(x / 100 * len(p))
        ]
        ax.annotate(f"{VRE_LABELS[name]}  (CF {cf[name]:.2f})", xy=(x, y),
                    xytext=(6, 6), textcoords="offset points",
                    fontsize=8, color=VRE_COLORS[name])
    # Solar's label sits under its own curve: above it, the onshore curve
    # runs through the text.
    ax.annotate(f"{VRE_LABELS['solar']}  (CF {cf['solar']:.2f})", xy=(10, 0.10),
                fontsize=8, color=VRE_COLORS["solar"])
    ax.set_title("(c) duration curves, whole year", loc="left", fontsize=9, color=INK)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1.02)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    fig.supylabel("availability (share of maximum output)", fontsize=9, color=INK)
    fig.savefig(FIGURES / "intermittency_profiles.pdf")
    plt.close(fig)


# The fleet section 3 dispatches, in the three groups the text reasons about.
# Order inside a group is by marginal cost, so the right-hand panel reads as a
# merit order rather than as an arbitrary list.
FLEET_GROUPS = [
    ("weather-driven", ["solar_pv", "wind_onshore", "wind_offshore"]),
    ("firm, domestic", ["waste_chp", "coal_chp", "ccgt", "wood_chips_chp",
                        "wood_pellets_chp", "ocgt", "oil_peak"]),
    ("the wires", ["imports"]),
]
# Same hues as the week comparison in figure 3.8, so a technology keeps one
# colour across the section.
FLEET_COLORS = {
    "solar_pv": "#E69F00", "wind_onshore": "#0072B2",
    "wind_offshore": "#56B4E9", "waste_chp": "#8C8C8C", "coal_chp": "#4D4D4D",
    "wood_chips_chp": "#009E73", "wood_pellets_chp": "#66C2A5",
    "ccgt": "#D55E00", "ocgt": "#CC79A7", "oil_peak": "#661100",
    "imports": "#CC79A7",
}


def fig_intermittency_fleet(d):
    """Figure 3.2: the fleet section 3 actually dispatches — how much of each
    technology is installed, and what it costs to run. It replaces a paragraph
    of numbers, and it is where the section's first surprise lives: firm
    domestic capacity does not reach peak demand."""
    g = d["generators"]
    s = d["summary"]
    peak = s["load_max_mw"] / 1000.0

    ypos, ticks, labels, colors, groups = [], [], [], [], []
    y = 0.0
    for name, techs in FLEET_GROUPS:
        present = sorted([t for t in techs if t in g.index],
                         key=lambda t: g.loc[t, "mc"])
        if not present:
            continue
        groups.append((name, y, present))
        for tech in present:
            ypos.append(y)
            ticks.append(y)
            labels.append(g.loc[tech, "label"])
            colors.append(FLEET_COLORS.get(tech, "#999999"))
            y -= 1.0
        y -= 0.9

    order = [t for _, _, techs in groups for t in techs]
    cap = [g.loc[t, "capacity_mw"] / 1000.0 for t in order]
    mc = [g.loc[t, "mc"] for t in order]
    # The import plant is a stand-in, not a Danish power station; hatching
    # says so in both panels without needing a second legend.
    hatch = ["///" if t == "imports" else None for t in order]

    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.5), sharey=True,
                             gridspec_kw={"width_ratios": [1.3, 1.0]})
    for ax, values, fmt in [(axes[0], cap, "{:.1f}"), (axes[1], mc, "{:.0f}")]:
        bars = ax.barh(ypos, values, height=0.62, color=colors,
                       edgecolor="white", linewidth=0.6)
        for bar, h in zip(bars, hatch):
            if h:
                bar.set_hatch(h)
        span = max(values)
        for pos, value in zip(ypos, values):
            ax.text(value + span * 0.02, pos, fmt.format(value), va="center",
                    fontsize=7.5, color=INK)
        ax.set_xlim(0, span * 1.22)
        ax.grid(axis="x")

    # Group headings carry the subtotals the text used to spell out.
    for name, top, techs in groups:
        subtotal = g.loc[techs, "capacity_mw"].sum() / 1000.0
        axes[0].text(0, top + 0.72, f"{name} — {subtotal:.1f} GW",
                     fontsize=7.5, style="italic", color=INK)

    # Peak demand against the firm bars: the comparison the paragraph makes.
    axes[0].axvline(peak, color=INK, linewidth=1.0, linestyle="--")
    axes[0].annotate(f" peak demand {peak:.1f} GW", xy=(peak, min(ypos) - 0.75),
                     fontsize=7.5, color=INK, ha="left", va="center",
                     annotation_clip=False)

    axes[0].set_yticks(ticks)
    axes[0].set_yticklabels(labels, fontsize=8)
    axes[0].set_ylim(min(ypos) - 1.1, 1.1)
    axes[0].set_xlabel("installed capacity (GW)")
    axes[1].set_xlabel("marginal cost (€/MWh)")
    axes[0].set_title("(a) what is installed", loc="left", fontsize=9, color=INK)
    axes[1].set_title("(b) what it costs to run", loc="left", fontsize=9,
                      color=INK)
    fig.tight_layout()
    fig.savefig(FIGURES / "intermittency_fleet.pdf")
    plt.close(fig)


def fig_intermittency_residual(d):
    """Figure 3.3: load duration curve and residual load duration curves at
    growing wind capacity."""
    r = d["residual"] / 1000.0  # MW -> GW

    fig, ax = plt.subplots(figsize=(6.1, 3.6))
    ax.plot(r.index, r["load"], color=INK, linewidth=1.8)
    shades = {"residual_wind_x1": "#9ecae1", "residual_wind_x2": "#4292c6",
              "residual_wind_x4": "#08519c"}
    for col, color in shades.items():
        ax.plot(r.index, r[col], color=color, linewidth=1.6)

    ax.axhline(0.0, color="#999999", linewidth=0.8)
    labels = [("load", "load"), ("residual_wind_x1", "residual, wind ×1"),
              ("residual_wind_x2", "wind ×2"), ("residual_wind_x4", "wind ×4")]
    for col, text in labels:
        ax.annotate(text, xy=(101, r[col].iloc[-1]), fontsize=8,
                    color=INK if col == "load" else shades[col],
                    va="center", annotation_clip=False)
    ax.set_xlim(0, 100)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("load net of available VRE (GW)")
    fig.savefig(FIGURES / "intermittency_residual.pdf")
    plt.close(fig)


def _pdc_levels(d):
    """The marginal costs figure 3.4 rules its axis on, and where it cuts.

    Shared with `values_dispatch_t`, which quotes the number of hours above
    the cut in the caption: the figure and the sentence describing it have
    to agree about where the axis ends.
    """
    gens = d["generators"]
    prices = d["hours"]["price"].sort_values(ascending=False).to_numpy()

    # Price levels are marginal costs: mark each technology that sets the
    # price in at least one hour. Imports are excluded — their cost is the
    # neighbours' hourly price, so they set no single level, and the part of
    # the curve they set is the part that is not a staircase.
    domestic = gens[gens.get("mc_is_constant", True).astype(bool)]
    setters = domestic[
        domestic["mc"].round(2).isin(pd.Series(prices).round(2).unique())
    ]
    # Wind and solar all bid within a euro or two of zero. Three labels there
    # land on top of each other and say the same thing; one says it once.
    zero_bid = setters[setters["mc"] < 2.0]
    levels = []
    if len(zero_bid):
        levels.append((float(zero_bid["mc"].max()), "wind and solar  (≈0)"))
    levels += [(float(row["mc"]), f"{row['label']}  ({row['mc']:.0f})")
               for _, row in setters[setters["mc"] >= 2.0].iterrows()]

    ceiling = max(mc for mc, _ in levels) * 1.12
    return prices, levels, ceiling


def fig_intermittency_price_duration(d):
    """Figure 3.4: the price duration curve of the base year, with the
    merit-order marginal costs it is quantised on.

    The year's scarcest few hours run an order of magnitude above every
    domestic marginal cost, and drawing them on the same axis squeezes the
    staircase — and its labels — into the bottom fifth of the panel. So the
    axis is cut just above the most expensive domestic plant. Nothing on
    the panel says so; the caption does.
    """
    hours = d["hours"]
    pct = (pd.RangeIndex(len(hours)) + 0.5) / len(hours) * 100.0
    prices, levels, ceiling = _pdc_levels(d)
    floor = min(prices.min() * 1.1, 0.0)

    fig, ax = plt.subplots(figsize=(6.1, 3.6))
    ax.plot(pct, prices, color=BLUE, linewidth=1.8)
    for mc, text in levels:
        ax.axhline(mc, color="#bbbbbb", linewidth=0.7, linestyle=":")
        ax.annotate(text, xy=(101, mc), fontsize=7.5, color=INK,
                    va="center", annotation_clip=False)
    ax.set_xlim(0, 100)
    ax.set_ylim(floor, ceiling)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("price (€/MWh)")

    # The tail is neither drawn nor annotated here. It runs to roughly six
    # times the top of this axis, and putting it on the same scale is what
    # made the staircase unreadable in the first place; the caption carries
    # it, through \PDCHoursAboveCut and \IntermittencyPriceMax.
    fig.savefig(FIGURES / "intermittency_price_duration.pdf")
    plt.close(fig)


def fig_intermittency_value(d):
    """Figure 3.5: capture price and value factor against energy share, for
    wind and for solar — cannibalisation as a curve."""
    sweep = d["sweep"]
    colors = {"wind": BLUE, "solar": "#E69F00"}

    fig, axes = plt.subplots(2, 1, figsize=(6.1, 5.4), sharex=True)
    for family, g in sweep.groupby("family"):
        g = g.sort_values("energy_share")
        share = g["energy_share"] * 100.0
        axes[0].plot(share, g["capture_price"], color=colors[family],
                     linewidth=1.8, marker="o", markersize=3.5)
        # The dashed line is the value factor's denominator along this very
        # sweep -- the base price falls as zero-cost capacity enters, which
        # is why panel (b) is a ratio of two moving numbers.
        axes[0].plot(share, g["base_price"], color=colors[family],
                     linewidth=1.2, linestyle="--")
        axes[1].plot(share, g["value_factor"], color=colors[family],
                     linewidth=1.8, marker="o", markersize=3.5, label=family)

    # Direct labels, each in empty space beside its own curve: under the
    # steep stretch for the capture prices, above the dashed lines for the
    # base prices.
    axes[0].annotate("wind capture price", xy=(40, 12), fontsize=8, color=BLUE)
    axes[0].annotate("base price,\nas wind grows", xy=(57, 38), fontsize=8,
                     color=BLUE, alpha=0.8)
    axes[0].annotate("solar capture price", xy=(6, 5), fontsize=8,
                     color=colors["solar"])
    axes[0].annotate("base price,\nas solar grows", xy=(24.5, 39.5), fontsize=8,
                     color=colors["solar"], alpha=0.8)
    axes[0].set_title(
        "(a) capture price (solid) and the base price it is divided by (dashed)",
        loc="left", fontsize=9, color=INK)
    axes[0].set_ylabel("€/MWh")
    axes[0].grid(axis="y")

    axes[1].axhline(1.0, color="#999999", linewidth=0.8, linestyle="--")
    axes[1].annotate("wind", xy=(47, 0.79), fontsize=8, color=BLUE)
    axes[1].annotate("solar", xy=(20.5, 0.60), fontsize=8, color=colors["solar"])
    axes[1].set_title("(b) value factor", loc="left", fontsize=9, color=INK)
    axes[1].set_ylabel("capture price / base price")
    axes[1].set_xlabel("energy share of the technology (%)")
    axes[1].grid(axis="y")
    fig.savefig(FIGURES / "intermittency_value_factors.pdf")
    plt.close(fig)


def fig_intermittency_ratio(d):
    """Figure 3.6: the ratio trap. As solar grows, wind's *value factor*
    rises while wind's *revenue* falls — because the denominator of the
    ratio falls faster than the numerator."""
    sweep = d["sweep"]
    solar_sweep = sweep[sweep["family"] == "solar"].sort_values("energy_share")
    if "wind_value_factor" not in solar_sweep.columns:
        print("skipping the ratio-trap figure — re-run run_dispatch_t.py "
              "for the cross-technology sweep columns")
        return
    share = solar_sweep["energy_share"] * 100.0

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.1))

    ax = axes[0]
    ax.plot(share, solar_sweep["wind_value_factor"], color=BLUE,
            linewidth=1.8, marker="o", markersize=3.5)
    ax.axhline(1.0, color="#999999", linewidth=0.8, linestyle="--")
    ax.set_title("(a) wind's value factor", loc="left", fontsize=9, color=INK)
    ax.set_ylabel("capture price / average price")
    ax.set_xlabel("solar's energy share (%)")
    ax.grid(axis="y")

    ax = axes[1]
    base = solar_sweep["wind_revenue_eur"].iloc[0]
    ax.plot(share, 100.0 * solar_sweep["wind_revenue_eur"] / base,
            color=BLUE, linewidth=1.8, marker="o", markersize=3.5,
            label="wind revenue")
    ax.plot(share,
            100.0 * solar_sweep["wind_capture_price"]
            / solar_sweep["wind_capture_price"].iloc[0],
            color=BLUE, linewidth=1.2, linestyle=":",
            label="wind capture price")
    ax.plot(share,
            100.0 * solar_sweep["avg_price"] / solar_sweep["avg_price"].iloc[0],
            color="#999999", linewidth=1.2, linestyle="--",
            label="average price")
    ax.set_title("(b) the same thing in levels", loc="left", fontsize=9,
                 color=INK)
    ax.set_ylabel("index, no added solar = 100")
    ax.set_xlabel("solar's energy share (%)")
    ax.legend(frameon=False, fontsize=7.5, loc="lower left")
    ax.grid(axis="y")

    fig.tight_layout()
    fig.savefig(FIGURES / "intermittency_ratio_trap.pdf")
    plt.close(fig)


# The two panels of figure 3.8 come from different accounting systems -- the
# model's ten named technologies against Energinet's settlement categories --
# so a technology-by-technology stack compares two things that are not the
# same list. Three blocks that both systems can be read into make the
# comparison an answerable one.
WEEK_BLOCKS = [
    ("VRE (wind + solar)", "#0072B2",
     ["gen_wind_onshore", "gen_wind_offshore", "gen_solar_pv"],
     ["wind", "solar"]),
    ("dispatchable", "#4D4D4D",
     ["gen_waste_chp", "gen_coal_chp", "gen_wood_chips_chp",
      "gen_wood_pellets_chp", "gen_ccgt", "gen_ocgt", "gen_oil_peak"],
     ["central_power", "local_power", "commercial_power"]),
    ("net imports", "#CC79A7", ["gen_imports"], ["net_imports"]),
]


def fig_intermittency_week(d):
    """Figure 3.8: a week of modelled dispatch against the week DK1 actually
    had, in three blocks each system can be read into. The visible residue is
    what the LP leaves out."""
    if "week_model" not in d:
        print("skipping the realised-dispatch week — re-run data/prepare.py "
              "and run_dispatch_t.py")
        return
    model, actual = d["week_model"], d["week_actual"]

    # Both panels as a share of that hour's load. The model runs the note's
    # teaching fleet, which is a fraction of DK1's real installed capacity, so
    # comparing gigawatts would compare fleet sizes rather than behaviour.
    # Shares put the two on one axis and make the question the right one: what
    # does each system's stack look like, and what is in the real one that the
    # model has no room for?
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 5.0), sharex=True, sharey=True)
    for ax, frame, side, title in [
        (axes[0], model, 0, "(a) the model's dispatch"),
        (axes[1], actual, 1, "(b) what DK1 actually did"),
    ]:
        load = frame["load_mw"]
        base_up = pd.Series(0.0, index=frame.index)
        base_dn = pd.Series(0.0, index=frame.index)
        for label, color, *sources in WEEK_BLOCKS:
            cols = [c for c in sources[side] if c in frame.columns]
            if not cols:
                continue
            share = 100.0 * frame[cols].sum(axis=1) / load
            # Net exports stack downwards, so a surplus reads as one.
            up, down = share.clip(lower=0), share.clip(upper=0)
            ax.fill_between(frame.index, base_up, base_up + up, color=color,
                            label=label, linewidth=0)
            if (down < 0).any():
                ax.fill_between(frame.index, base_dn, base_dn + down,
                                color=color, linewidth=0)
            base_up, base_dn = base_up + up, base_dn + down
        ax.axhline(100.0, color=INK, linewidth=1.0, linestyle="--")
        ax.axhline(0.0, color="#999999", linewidth=0.8)
        ax.set_title(title, loc="left", fontsize=9, color=INK)
        ax.set_ylabel("% of load")
        ax.grid(axis="y")

    axes[0].legend(frameon=False, fontsize=7.5, ncol=3, loc="upper left")
    # Room for the storm: the real week exports nearly a full load.
    axes[0].set_ylim(-108, 212)
    axes[0].annotate("dashed line: load. Below zero: net exports.",
                     xy=(0.99, 0.80), xycoords="axes fraction", ha="right",
                     fontsize=7.5, color=INK)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIGURES / "intermittency_week.pdf")
    plt.close(fig)


def fig_intermittency_validation(d):
    """Figure 3.7: the model's price duration curve held against the actual
    DK1 day-ahead prices of the same year — same axes, same year, one an
    LP's dual, the other a market outcome."""
    hours = d["hours"]
    actual = d["actual_duration"]
    s = d["summary"]

    pct_model = (pd.RangeIndex(len(hours)) + 0.5) / len(hours) * 100.0
    model = hours["price"].sort_values(ascending=False).to_numpy()

    fig, ax = plt.subplots(figsize=(6.1, 3.7))
    ax.plot(actual.index, actual["actual_price"], color=VERMILLION,
            linewidth=1.6)
    ax.plot(pct_model, model, color=BLUE, linewidth=1.8)
    if "price_carbon" in hours.columns:
        model_c = hours["price_carbon"].sort_values(ascending=False).to_numpy()
        ax.plot(pct_model, model_c, color=BLUE, linewidth=1.4,
                linestyle="--")
        tau = s.get("carbon_tau_eur_t", 0.0)
        ax.annotate(f"model + ETS at {tau:.0f} €/t", xy=(66, 95),
                    fontsize=8, color=BLUE)
    ax.axhline(0.0, color="#bbbbbb", linewidth=0.8)

    ax.set_ylim(-70, 200)
    peak = s["actual_market"]["max_price"]
    ax.annotate(f"actual DK1 prices (peaks reach {peak:,.0f} €/MWh, cut off)",
                xy=(20, 130), fontsize=8, color=VERMILLION)
    ax.annotate("model prices", xy=(45, 45), fontsize=8, color=BLUE)
    ax.annotate("negative prices:\nthe model has no floor below 0",
                xy=(88, -40), fontsize=7.5, color=INK, ha="center")
    ax.set_xlim(0, 100)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("price (€/MWh)")
    fig.savefig(FIGURES / "intermittency_validation.pdf")
    plt.close(fig)


def fig_network_validation(d):
    """Figure 6.5: model against market — mean zonal prices without and
    with the year's ETS price (a) and the congestion rent collected on the
    Danish borders (b)."""
    s = d["summary"]
    actual = s["actual_market"]
    rents = d["rents"]
    with_carbon = True
    year = s.get("network_year", "")

    zones = ["DK1", "DK2", "DE", "NO2", "SE3", "SE4"]
    x = range(len(zones))
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2))
    width = 0.38
    tau = s["carbon_tau_eur_t"]
    axes[0].bar([i - width / 2 for i in x],
                [s["avg_price"][z] for z in zones], width=width,
                color=BLUE, alpha=0.8, edgecolor="white",
                label=f"model ({tau:.0f} €/t)")
    axes[0].bar([i + width / 2 for i in x],
                [actual["avg_price"][z] for z in zones], width=width,
                color=VERMILLION, alpha=0.75, edgecolor="white", label="actual")
    axes[0].set_xticks(list(x), zones, fontsize=8)
    axes[0].legend(frameon=False, fontsize=7, loc="upper right")
    axes[0].set_ylim(0, 100)
    axes[0].grid(axis="y")
    axes[0].set_ylabel("mean price (€/MWh)")
    axes[0].set_title("(a) zonal price levels", loc="left", fontsize=9, color=INK)

    corridors = list(actual["corridor_rent_eur"])
    y = range(len(corridors))
    axes[1].barh([i + 0.19 for i in y],
                 [rents.loc[c, "rent_eur"] / 1e6 if c in rents.index else 0.0
                  for c in corridors],
                 height=0.38, color=BLUE if with_carbon else BLOCK_FILL,
                 alpha=0.8, edgecolor="white")
    axes[1].barh([i - 0.19 for i in y],
                 [actual["corridor_rent_eur"][c] / 1e6 for c in corridors],
                 height=0.38, color=VERMILLION, alpha=0.75, edgecolor="white")
    axes[1].set_yticks(list(y), corridors, fontsize=8)
    axes[1].grid(axis="x")
    axes[1].set_xlabel(f"congestion rent (M€, {year})")
    axes[1].set_title("(b) Danish border rents", loc="left", fontsize=9, color=INK)
    fig.savefig(FIGURES / "network_validation.pdf")
    plt.close(fig)


def values_dispatch_t(d):
    """Numbers quoted in the running text of section 3."""
    s = d["summary"]
    g = d["generators"]
    sweep = d["sweep"]
    cf = s["profile_capacity_factors"]

    wind = sweep[sweep["family"] == "wind"].set_index("scale")
    solar = sweep[sweep["family"] == "solar"].set_index("scale")
    # "High" is the top of each sweep, whatever the grid happens to be.
    wind_hi, solar_hi = wind.index.max(), solar.index.max()

    diff = s["pypsa_crosscheck"]["max_abs_price_diff"]
    price_diff = "0" if diff == 0 else f"{diff:.0e}".replace("e-0", r"\times 10^{-") + "}"

    macros = {
        "IntermittencyYear": f"{s['year']}",
        "IntermittencyHours": f"{s['hours']}",
        "IntermittencyStride": f"{s['stride']}",
        "IntermittencyLoadMeanGW": f"{s['load_mean_mw'] / 1000:.1f}",
        "IntermittencyLoadMaxGW": f"{s['load_max_mw'] / 1000:.1f}",
        "CFWindOnshore": f"{cf['wind_onshore']:.2f}",
        "CFWindOffshore": f"{cf['wind_offshore']:.2f}",
        "CFSolar": f"{cf['solar']:.2f}",
        "IntermittencyAvgPrice": f"{s['avg_price']:.1f}",
        "WindShareBase": f"{100 * wind.loc[1.0, 'energy_share']:.0f}",
        "WindCaptureBase": f"{wind.loc[1.0, 'capture_price']:.1f}",
        "WindVFBase": f"{wind.loc[1.0, 'value_factor']:.2f}",
        "SolarShareBase": f"{100 * solar.loc[1.0, 'energy_share']:.1f}",
        "SolarVFBase": f"{solar.loc[1.0, 'value_factor']:.2f}",
        "WindShareHigh": f"{100 * wind.loc[wind_hi, 'energy_share']:.0f}",
        "WindVFHigh": f"{wind.loc[wind_hi, 'value_factor']:.2f}",
        "SolarShareHigh": f"{100 * solar.loc[solar_hi, 'energy_share']:.0f}",
        "SolarVFHigh": f"{solar.loc[solar_hi, 'value_factor']:.2f}",
        "SolarCaptureBase": f"{g.loc['solar_pv', 'capture_price']:.1f}",
        "IntermittencyPriceDiff": price_diff,
        # The fleet the section actually solves: DK1 as installed, plus the
        # wires. Read off the solved instance, so the note cannot quote a
        # capacity the model did not use.
        "FleetSolarGW": f"{g.loc['solar_pv', 'capacity_mw'] / 1000:.1f}",
        "FleetOnshoreGW": f"{g.loc['wind_onshore', 'capacity_mw'] / 1000:.1f}",
        "FleetOffshoreGW": f"{g.loc['wind_offshore', 'capacity_mw'] / 1000:.1f}",
        "FleetVREGW": f"{g.loc[['solar_pv', 'wind_onshore', 'wind_offshore'], 'capacity_mw'].sum() / 1000:.1f}",
        "FleetCoalMW": f"{g.loc['coal_chp', 'capacity_mw']:.0f}",
        "FleetCCGTMW": f"{g.loc['ccgt', 'capacity_mw']:.0f}",
        "FleetBiomassMW": f"{g.loc[['wood_chips_chp', 'wood_pellets_chp'], 'capacity_mw'].sum():.0f}",
        "FleetWasteMW": f"{g.loc['waste_chp', 'capacity_mw']:.0f}",
        "FleetFirmGW": f"{g.drop(index=['solar_pv', 'wind_onshore', 'wind_offshore', 'imports'])['capacity_mw'].sum() / 1000:.1f}",
        "FleetImportGW": f"{g.loc['imports', 'capacity_mw'] / 1000:.1f}",
        "IntermittencyBasePrice": f"{s['base_price']:.1f}",
        "IntermittencyImportSharePct": f"{100 * s['import_share_of_load']:.0f}",
        "IntermittencyImportPrice": f"{s['import_price_mean']:.1f}",
        "IntermittencyPriceMedian": f"{s['price_quantiles']['0.5']:.0f}",
        "IntermittencyPriceHigh": f"{s['price_quantiles']['0.95']:.0f}",
        "IntermittencyPriceMax": f"{s['price_max']:.0f}",
        # Figure 3.4 cuts its axis above the most costly domestic plant and says
        # nothing about it; the caption reports what was left off.
        "PDCHoursAboveCut": f"{int((d['hours']['price'] > _pdc_levels(d)[2]).sum())}",
        # The model does reach negative prices -- but only through the
        # import plant, which inherits whatever the neighbours are paying.
        # No Danish generator in this fleet ever bids below zero.
        "IntermittencyNegHoursPct": f"{100 * (d['hours']['price'] < 0).mean():.0f}",
    }
    # The ratio trap of section 3.6, in numbers: across the solar sweep,
    # wind's value factor rises while everything about wind gets worse.
    if "wind_value_factor" in solar.columns:
        lo, hi = solar.index.min(), solar.index.max()
        macros |= {
            "RatioWindVFStart": f"{solar.loc[lo, 'wind_value_factor']:.2f}",
            "RatioWindVFEnd": f"{solar.loc[hi, 'wind_value_factor']:.2f}",
            "RatioWindCaptureStart": f"{solar.loc[lo, 'wind_capture_price']:.1f}",
            "RatioWindCaptureEnd": f"{solar.loc[hi, 'wind_capture_price']:.1f}",
            "RatioWindRevenueDropPct": f"{100 * (1 - solar.loc[hi, 'wind_revenue_eur'] / solar.loc[lo, 'wind_revenue_eur']):.0f}",
            "RatioSolarShareEndPct": f"{100 * solar.loc[hi, 'energy_share']:.0f}",
        }
    if "marginal_share" in s:
        ms = s["marginal_share"]
        macros |= {
            "MarginalOnshorePct": f"{100 * ms.get('wind_onshore', 0):.0f}",
            "MarginalCoalPct": f"{100 * ms.get('coal_chp', 0):.0f}",
            "MarginalCCGTPct": f"{100 * ms.get('ccgt', 0):.0f}",
            "MarginalImportsPct": f"{100 * ms.get('imports', 0):.0f}",
        }
    if "demand_and_trade" in s:
        dt = s["demand_and_trade"]
        macros |= {
            "LoadMinGW": f"{dt['load_min_mw'] / 1000:.1f}",
            "LoadPeakHour": f"{dt['load_peak_hour']:02d}",
            "LoadTroughHour": f"{dt['load_trough_hour']:02d}",
            "LoadDailySwingPct": f"{dt['load_daily_swing_pct']:.0f}",
            "LoadSeasonalSwingPct": f"{dt['load_seasonal_swing_pct']:.0f}",
        }
        names = {"wind_onshore": "Onshore", "wind_offshore": "Offshore",
                 "solar_pv": "Solar"}
        for key, label in names.items():
            c = dt["correlation"][key]
            macros |= {
                f"Corr{label}Hourly": f"{c['hourly']:+.2f}",
                f"Corr{label}Seasonal": f"{c['seasonal']:+.2f}",
                f"Corr{label}Daily": f"{c['daily']:+.2f}",
            }
        if "trade" in dt:
            t = dt["trade"]
            macros |= {
                "TradeImportsTWh": f"{t['imports_gwh'] / 1000:.1f}",
                "TradeExportsTWh": f"{t['exports_gwh'] / 1000:.1f}",
                "TradeNetTWh": f"{t['net_import_gwh'] / 1000:.1f}",
                "TradeNetPct": f"{100 * t['net_import_share_of_load']:.1f}",
                "TradeTurnoverPct": f"{100 * t['turnover_share_of_load']:.0f}",
                "TradeHoursImportingPct": f"{100 * t['hours_importing_share']:.0f}",
            }
    if "avg_price_carbon" in s:
        macros |= {
            "IntermittencyCarbonTau": f"{s['carbon_tau_eur_t']:.0f}",
            "IntermittencyAvgPriceCarbon": f"{s['avg_price_carbon']:.1f}",
        }
    if "actual_market" in s:
        a = s["actual_market"]
        macros |= {
            "ActualAvgPrice": f"{a['avg_price']:.1f}",
            "ActualWindCapture": f"{a['capture_wind']:.1f}",
            "ActualPriceMedian": f"{a['price_quantiles']['0.5']:.0f}",
            "ActualPriceHigh": f"{a['price_quantiles']['0.95']:.0f}",
            "ActualWindVF": f"{a['vf_wind']:.2f}",
            "ActualSolarVF": f"{a['vf_solar']:.2f}",
            "ActualNegHoursPct": f"{100 * a['negative_hours_share']:.0f}",
            "ActualMaxPrice": f"{a['max_price']:,.0f}",
        }
    # The illustrated week and its windiest day. Stage 2 picks the week
    # automatically as the year's most variable, so hard-typing "8-15
    # January" into the prose -- which is what section 3 did until
    # 2026-09-02 -- silently goes wrong the first time the data moves.
    if "week_model" in d:
        idx = d["week_model"].index
        first, last = idx.min(), idx.max()
        wind = d["week_model"][[c for c in d["week_model"].columns
                                if c.startswith("gen_wind")]].sum(axis=1)
        storm = wind.groupby(idx.date).mean().idxmax()
        macros |= {
            "IntermittencyWeekStart": f"{first.day}",
            "IntermittencyWeekEnd": f"{last.day}",
            "IntermittencyWeekMonth": f"{first:%B}",
            "IntermittencyStormDay": f"{storm.day} {storm:%B}",
        }
        # The trade swing figure 3.8 shows, and the block of thermal output
        # the market never switches off. Both are read off the same week the
        # figure draws, so prose and picture cannot disagree.
        if "week_actual" in d:
            a = d["week_actual"]
            trade = 100.0 * a["net_imports"] / a["load_mw"]
            firm = a[["central_power", "local_power",
                      "commercial_power"]].sum(axis=1)
            vre = 100.0 * a[["wind", "solar"]].sum(axis=1) / a["load_mw"]
            macros |= {
                "WeekImportPeakPct": f"{trade.max():.0f}",
                "WeekExportPeakPct": f"{-trade.min():.0f}",
                "WeekVREPeakPct": f"{vre.max():.0f}",
                "WeekFirmFloorPct": f"{(100.0 * firm / a['load_mw']).min():.0f}",
                "WeekFirmFloorMW": f"{firm.min():.0f}",
            }
    lines = [
        "%% GENERATED by pipeline/build.py from results/dispatch_t_summary.json",
        "%% -- do not edit; rerun the pipeline instead.",
    ]
    lines += [rf"\providecommand{{\{name}}}{{{value}}}" for name, value in macros.items()]
    (TABLES / "dispatch_t_values.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Sections 4-8 share one categorical palette for technologies and zones
# (Okabe-Ito, fixed assignment everywhere they appear).
# --------------------------------------------------------------------------

TECH_COLORS = {
    "solar_pv": "#E69F00",
    "wind_onshore": "#0072B2",
    "wind_offshore": "#56B4E9",
    "ccgt": "#D55E00",
    "ocgt": "#CC79A7",
    "ocgt_biogas": "#F0E442",
    "nuclear": "#999999",
    "battery": "#009E73",
}
TECH_LABELS = {
    "solar_pv": "solar", "wind_onshore": "onshore wind",
    "wind_offshore": "offshore wind", "ccgt": "CCGT", "ocgt": "OCGT",
    "ocgt_biogas": "OCGT (biomethane)", "nuclear": "nuclear",
    "battery": "battery",
}
# Of the network's 12 bidding zones, figures highlight the five that face
# Denmark; the remaining Nordic zones would only clutter the duration plot.
ZONE_COLORS = {
    "DK1": "#0072B2", "DK2": "#56B4E9", "DE": "#D55E00",
    "SE3": "#009E73", "NO2": "#CC79A7",
}


# --------------------------------------------------------------------------
# Section 4 — storage
# --------------------------------------------------------------------------

def _liveliest_week(prices):
    """The Monday-aligned week with the largest price variance — where the
    storage story is visible."""
    std = prices["without_storage"].resample("7D").std()
    start = std.idxmax()
    return prices.index[(prices.index >= start) & (prices.index < start + pd.Timedelta("7D"))]


def fig_storage_week(d):
    """Figure 4.1: the price path and the state of charge over one week."""
    hours = d["hours"]
    prices = d["prices"]
    window = _liveliest_week(prices)

    fig, axes = plt.subplots(2, 1, figsize=(6.1, 4.8), sharex=True)
    axes[0].plot(window, prices.loc[window, "without_storage"], color="#bbbbbb",
                 linewidth=1.2, label="price, no storage")
    axes[0].plot(window, prices.loc[window, "with_storage"], color=BLUE,
                 linewidth=1.5, label="price, with storage")
    # The week is picked from the data, so is the empty corner: let the
    # legend find the place where it covers the least of the price path.
    axes[0].legend(frameon=False, fontsize=8, loc="best", ncol=2)
    axes[0].set_ylabel("price (€/MWh)")
    axes[0].grid(axis="y")
    axes[0].set_title("(a) the price path", loc="left", fontsize=9, color=INK)

    soc = hours.loc[window, "soc_mwh"] / 1000.0
    axes[1].fill_between(window, soc, color="#009E73", alpha=0.35, linewidth=0)
    axes[1].plot(window, soc, color="#009E73", linewidth=1.4)
    axes[1].set_ylabel("state of charge (GWh)")
    axes[1].grid(axis="y")
    axes[1].set_title("(b) the battery fills in cheap hours, empties in costly ones",
                      loc="left", fontsize=9, color=INK)
    axes[1].tick_params(axis="x", labelsize=7)
    fig.savefig(FIGURES / "storage_week.pdf")
    plt.close(fig)


def fig_storage_pdc(d):
    """Figure 4.2: storage compresses the price distribution from both ends.

    Two panels zoomed on the tails: the two duration curves are identical
    across the middle of the year, so a full-width plot shows nothing but
    the tail of scarcity prices squashing the rest. Each panel has its own
    price axis; the compression is what the reader is meant to see, not the
    level."""
    prices = d["prices"]
    n = len(prices)
    pct = (pd.RangeIndex(n).to_numpy() + 0.5) / n * 100.0
    tail = 20.0     # share of hours shown in each panel
    ceiling = 250.0  # panel (a) is clipped here; the scarcity peaks are annotated
    series = [
        ("without_storage", "#bbbbbb", "no storage"),
        ("with_storage", BLUE, f"{d['summary']['battery_mw']:.0f} MW battery"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2))
    panels = [
        (axes[0], pct <= tail, f"(a) the {tail:.0f}% most expensive hours"),
        (axes[1], pct >= 100.0 - tail, f"(b) the {tail:.0f}% cheapest hours"),
    ]
    peaks = []
    for ax, mask, title in panels:
        for col, color, label in series:
            sorted_prices = prices[col].sort_values(ascending=False).to_numpy()
            ax.plot(pct[mask], sorted_prices[mask], color=color,
                    linewidth=1.7, label=label)
            peaks.append(sorted_prices[0])
        ax.set_title(title, loc="left", fontsize=9, color=INK)
        ax.grid(axis="y")
        ax.set_xlabel("share of hours (%)")
    axes[0].set_xlim(0, tail)
    axes[0].set_ylim(0, ceiling)
    axes[0].annotate(
        f"peaks off scale: {peaks[0]:.0f} without,\n{peaks[1]:.0f} with the battery",
        xy=(0.97, 0.04), xycoords="axes fraction", fontsize=7, color=INK,
        ha="right", va="bottom",
    )
    axes[1].set_xlim(100.0 - tail, 100.0)
    axes[1].annotate(
        "the two curves coincide:\nthe price is set by curtailed wind\nor by imports, and neither moves",
        xy=(0.05, 0.05), xycoords="axes fraction", fontsize=7, color=INK,
        ha="left", va="bottom",
    )
    axes[0].set_ylabel("price (€/MWh)")
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.savefig(FIGURES / "storage_price_duration.pdf")
    plt.close(fig)


def fig_storage_ramp(d):
    """Figure 4.3: the ramping wedge in numbers. One ramp rate on DK1's slow
    thermal plant, tightened from none (rho = 1) to 0.1 per hour; the x-axis
    runs from loose to stiff so the story reads left to right.

    (a) the battery's arbitrage revenue and its system value;
    (b) what the rigidity costs the system relative to no limit, with and
        without the battery, and the summed shadow value of the ramp
        constraints (the flexibility cost of section 4.3, item 1)."""
    r = d["ramp"].sort_values("rho", ascending=False).reset_index(drop=True)
    rho = r["rho"]
    base = r.loc[r["rho"].idxmax()]
    catalogue = d["summary"].get("ramp", {}).get("catalogue_rho")

    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2))
    for ax in axes:
        ax.set_xlim(1.02, 0.08)
        ax.set_xticks(rho)
        ax.set_xticklabels([f"{x:g}" for x in rho])
        ax.set_xlabel(r"ramp rate $\rho$ (share of capacity per hour)", fontsize=8)
        ax.grid(axis="y")
        if catalogue is not None:
            ax.axvline(catalogue, color="#bbbbbb", linewidth=0.8, linestyle=":")

    ax = axes[0]
    value = r["battery_value"] / 1e6
    revenue = r["storage_revenue"] / 1e6
    ax.plot(rho, value, color=BLUE, linewidth=1.8, marker="o", markersize=4)
    ax.plot(rho, revenue, color=INK, linewidth=1.2, linestyle="--",
            marker="o", markersize=3)
    ax.annotate("system value", xy=(rho.iloc[3], value.iloc[3]),
                xytext=(0, 8), textcoords="offset points", fontsize=8, color=BLUE)
    ax.annotate("arbitrage revenue", xy=(rho.iloc[3], revenue.iloc[3]),
                xytext=(0, -12), textcoords="offset points", fontsize=8, color=INK)
    ax.set_ylabel("M€ per year")
    ax.set_ylim(bottom=0)
    ax.set_title("(a) the battery, as the fleet stiffens", loc="left",
                 fontsize=9, color=INK)

    ax = axes[1]
    rigidity_without = (r["system_cost_without"] - base["system_cost_without"]) / 1e6
    rigidity_with = (r["system_cost_with"] - base["system_cost_with"]) / 1e6
    flex = r["flexibility_cost_without"] / 1e6
    # The three curves cross each other near the stiff end, so a legend in
    # the empty upper-left corner beats direct labels here.
    ax.plot(rho, rigidity_without, color=VERMILLION, linewidth=1.8,
            marker="o", markersize=4, label="rigidity cost, no battery")
    ax.plot(rho, rigidity_with, color=BLUE, linewidth=1.4, marker="o",
            markersize=3, label="rigidity cost, with the battery")
    ax.plot(rho, flex, color=INK, linewidth=1.2, linestyle="--",
            label=r"$\sum_{g,h}\xi_{g,h}\,\rho_g\bar q_g$, no battery")
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")
    ax.set_ylabel("M€ per year")
    ax.set_ylim(bottom=0)
    ax.set_title("(b) what the rigidity costs", loc="left", fontsize=9, color=INK)
    if catalogue is not None:
        axes[0].annotate("catalogue\nvalue", xy=(catalogue, 0), xycoords=("data", "axes fraction"),
                         xytext=(2, 4), textcoords="offset points", fontsize=7,
                         color="#888888", ha="left", va="bottom")
    fig.savefig(FIGURES / "storage_ramp.pdf")
    plt.close(fig)


def fig_storage_recovery(d):
    """Figure 4.4: wind's capture price against battery capacity, wind at 1.5x."""
    r = d["recovery"]
    fig, ax = plt.subplots(figsize=(6.1, 3.5))
    gw = r["storage_mw"] / 1000.0
    ax.plot(gw, r["wind_capture_price"], color=BLUE, linewidth=1.8,
            marker="o", markersize=4)
    # The base price, not the time-average: it is the denominator of the
    # value factor quoted beside this figure, so plotting the other average
    # here would leave the reader unable to divide one by the other.
    ax.plot(gw, r["base_price"], color=INK, linewidth=1.2, linestyle="--")
    ax.annotate("wind capture price", xy=(gw.iloc[2], r["wind_capture_price"].iloc[2]),
                xytext=(0, 10), textcoords="offset points", fontsize=8, color=BLUE)
    ax.annotate("base price", xy=(gw.iloc[3], r["base_price"].iloc[3]),
                xytext=(0, 8), textcoords="offset points", fontsize=8, color=INK)
    ax.grid(axis="y")
    ax.set_xlabel("battery power (GW, 4-hour duration)")
    ax.set_ylabel("€/MWh")
    fig.savefig(FIGURES / "storage_recovery.pdf")
    plt.close(fig)


def values_storage(d):
    s = d["summary"]
    r = d["recovery"].set_index("storage_mw")
    f = s["foresight"]
    vf0 = r.loc[0.0, "wind_value_factor"]
    vf_max = r["wind_value_factor"].iloc[-1]
    ramp = d["ramp"].set_index("rho").sort_index()
    ramp_meta = s.get("ramp", {})
    rho_min = ramp.index.min()
    rho_cat = ramp_meta.get("catalogue_rho", 0.9)
    value_free = ramp.loc[1.0, "battery_value"]
    macros_ramp = {
        "StorageRampGridMin": f"{rho_min:g}",
        "StorageRampCatalogue": f"{rho_cat:g}",
        "StorageRampSlowGW": f"{ramp_meta.get('slow_thermal_mw', float('nan')) / 1000:.1f}",
        "StorageRampImportGW": f"{ramp_meta.get('import_mw', float('nan')) / 1000:.1f}",
        "StorageRampValueFreeMEUR": f"{value_free / 1e6:.1f}",
        "StorageRampValueStiffMEUR": f"{ramp.loc[rho_min, 'battery_value'] / 1e6:.1f}",
        "StorageRampValueLiftPct": f"{100 * (ramp.loc[rho_min, 'battery_value'] / value_free - 1):.0f}",
        "StorageRampFlexCostCatalogueMEUR": f"{ramp.loc[rho_cat, 'flexibility_cost_without'] / 1e6:.1f}",
        "StorageRampFlexCostStiffMEUR": f"{ramp.loc[rho_min, 'flexibility_cost_without'] / 1e6:.1f}",
        "StorageRampRigidityCostStiffMEUR": f"{(ramp.loc[rho_min, 'system_cost_without'] - ramp.loc[1.0, 'system_cost_without']) / 1e6:.1f}",
        "StorageRampRigidityCostCatalogueMEUR": f"{(ramp.loc[rho_cat, 'system_cost_without'] - ramp.loc[1.0, 'system_cost_without']) / 1e6:.1f}",
    }
    macros = {
        **macros_ramp,
        "StorageBatteryMW": f"{s['battery_mw']:.0f}",
        "StorageBatteryHours": f"{s['battery_hours']:.0f}",
        "StorageRoundTripPct": f"{100 * s['efficiency_one_way'] ** 2:.0f}",
        "StorageAvgPriceWithout": f"{s['avg_price_without']:.1f}",
        "StorageAvgPriceWith": f"{s['avg_price_with']:.1f}",
        "StoragePriceStdWithout": f"{s['price_std_without']:.1f}",
        "StoragePriceStdWith": f"{s['price_std_with']:.1f}",
        "StorageRevenueMEUR": f"{s['storage_revenue'] / 1e6:.1f}",
        **({"StorageAnnualCostMEUR": f"{s['battery_annual_cost_eur'] / 1e6:.1f}"}
           if "battery_annual_cost_eur" in s else {}),
        "StorageCostSavingMEUR": f"{(s['system_cost_without'] - s['system_cost_with']) / 1e6:.1f}",
        "StorageWindVFNoStorage": f"{vf0:.2f}",
        "StorageWindVFMax": f"{vf_max:.2f}",
        "StorageRecoveryMaxGW": f"{r.index.max() / 1000:.0f}",
        "StorageWindScale": f"{s.get('wind_scale_recovery', 1.0):g}",
        "StorageForesightValueMEUR": f"{f['value_of_foresight'] / 1e6:.2f}",
        "StorageMyopicWindows": f"{f['windows']}",
    }
    _write_values("storage_values.tex", macros, "results/storage_summary.json")


# --------------------------------------------------------------------------
# Section 5 — heat
# --------------------------------------------------------------------------

def fig_heat_cop(d):
    """Figure 5.1: outdoor temperature and the COP it implies, over the year."""
    h = d["hours"]
    fig, axes = plt.subplots(2, 1, figsize=(6.1, 4.6), sharex=True)
    axes[0].plot(h.index, h["temperature_c"], color="#999999", linewidth=0.7)
    axes[0].axhline(0.0, color="#dddddd", linewidth=0.8)
    axes[0].set_ylabel("temperature (°C)")
    axes[0].grid(axis="y")
    axes[0].set_title("(a) outdoor temperature, Aarhus", loc="left",
                      fontsize=9, color=INK)
    axes[1].plot(h.index, h["cop"], color=VERMILLION, linewidth=0.7)
    axes[1].set_ylabel("COP")
    axes[1].grid(axis="y")
    axes[1].set_title("(b) heat pump COP — worst exactly when heat demand peaks",
                      loc="left", fontsize=9, color=INK)
    axes[1].tick_params(axis="x", labelsize=7)
    fig.savefig(FIGURES / "heat_cop.pdf")
    plt.close(fig)


def fig_heat_dispatch(d):
    """Figure 5.2: a cold week — who serves the heat, and what it does to
    the power price."""
    h = d["hours"]
    coldest = h["temperature_c"].resample("7D").mean().idxmin()
    window = h.index[(h.index >= coldest) & (h.index < coldest + pd.Timedelta("7D"))]
    w = h.loc[window]

    fig, axes = plt.subplots(2, 1, figsize=(6.1, 4.8), sharex=True)
    gw = 1 / 1000.0
    axes[0].stackplot(
        window, w["hp_heat_mw"] * gw, w["boiler_mw"] * gw,
        colors=["#009E73", "#D55E00"], alpha=0.75,
        labels=["heat pump", "gas boiler"],
    )
    axes[0].plot(window, w["heat_demand_mw"] * gw, color=INK, linewidth=1.0)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right", ncol=2)
    axes[0].set_ylabel("heat (GW$_{th}$)")
    axes[0].grid(axis="y")
    axes[0].set_title("(a) serving the heat load in the coldest week",
                      loc="left", fontsize=9, color=INK)

    axes[1].plot(window, w["elec_price"], color=BLUE, linewidth=1.3)
    axes[1].set_ylabel("electricity price (€/MWh)")
    axes[1].grid(axis="y")
    axes[1].set_title("(b) the electricity price the heat pump faces and moves",
                      loc="left", fontsize=9, color=INK)
    axes[1].tick_params(axis="x", labelsize=7)
    fig.savefig(FIGURES / "heat_dispatch.pdf")
    plt.close(fig)


def fig_heat_rollout(d):
    """Figure 5.3: emissions and prices as heat pump capacity grows —
    panel (a) without and with section 2's carbon tax."""
    rollout = d["rollout"]
    if "tau_eur_t" not in rollout.columns:
        rollout = rollout.assign(tau_eur_t=0.0)
    r = rollout[rollout["tau_eur_t"] == 0.0].reset_index(drop=True)
    r_tax = rollout[rollout["tau_eur_t"] > 0.0].reset_index(drop=True)
    gw = r["hp_mw_el"] / 1000.0

    fig, axes = plt.subplots(2, 1, figsize=(6.1, 4.8), sharex=True)
    axes[0].plot(gw, r["emissions_t"] / 1e6, color=INK, linewidth=1.8,
                 marker="o", markersize=4)
    if len(r_tax):
        tau = r_tax["tau_eur_t"].iloc[0]
        axes[0].plot(r_tax["hp_mw_el"] / 1000.0, r_tax["emissions_t"] / 1e6,
                     color=BLUE, linewidth=1.6, linestyle="--",
                     marker="o", markersize=3.5)
        axes[0].annotate("no carbon price",
                         xy=(gw.iloc[-2], r["emissions_t"].iloc[-2] / 1e6),
                         xytext=(0, 8), textcoords="offset points",
                         fontsize=8, color=INK)
        axes[0].annotate(f"$\\tau = {tau:.0f}$ €/t",
                         xy=(r_tax["hp_mw_el"].iloc[-2] / 1000.0,
                             r_tax["emissions_t"].iloc[-2] / 1e6),
                         xytext=(0, 10), textcoords="offset points",
                         fontsize=8, color=BLUE)
    axes[0].set_ylabel("CO$_2$, power + heat (Mt)")
    axes[0].grid(axis="y")
    axes[0].set_title("(a) total emissions across both sectors", loc="left",
                      fontsize=9, color=INK)

    axes[1].plot(gw, r["avg_elec_price"], color=BLUE, linewidth=1.8,
                 marker="o", markersize=4)
    axes[1].plot(gw, r["avg_heat_price"], color=VERMILLION, linewidth=1.8,
                 marker="o", markersize=4)
    axes[1].annotate("electricity", xy=(gw.iloc[-2], r["avg_elec_price"].iloc[-2]),
                     xytext=(0, 8), textcoords="offset points", fontsize=8, color=BLUE)
    axes[1].annotate("heat", xy=(gw.iloc[-2], r["avg_heat_price"].iloc[-2]),
                     xytext=(0, 8), textcoords="offset points", fontsize=8,
                     color=VERMILLION)
    axes[1].set_ylabel("average price (€/MWh)")
    axes[1].set_xlabel("heat pump capacity (GW electric)")
    axes[1].grid(axis="y")
    axes[1].set_title("(b) average electricity and heat prices", loc="left",
                      fontsize=9, color=INK)
    fig.savefig(FIGURES / "heat_rollout.pdf")
    plt.close(fig)


def values_heat(d):
    s = d["summary"]
    rollout = d["rollout"]
    if "tau_eur_t" not in rollout.columns:
        rollout = rollout.assign(tau_eur_t=0.0)
    r = rollout[rollout["tau_eur_t"] == 0.0].set_index("hp_mw_el")
    r_tax = rollout[rollout["tau_eur_t"] > 0.0].set_index("hp_mw_el")
    macros = {
        "HeatAnnualTWh": f"{s['heat_annual_twh']:.0f}",
        "HeatHPBaseMW": f"{s['hp_base_mw_el']:.0f}",
        "HeatSinkC": f"{s['sink_temperature_c']:.0f}",
        "HeatCOPMean": f"{s['cop_mean']:.1f}",
        "HeatCOPMin": f"{s['cop_min']:.1f}",
        "HeatCOPMax": f"{s['cop_max']:.1f}",
        "HeatHPShareBase": f"{100 * s['hp_heat_share_base']:.0f}",
        "HeatEmissionsNoHPMt": f"{r.loc[0.0, 'emissions_t'] / 1e6:.2f}",
        "HeatEmissionsMaxHPMt": f"{r['emissions_t'].iloc[-1] / 1e6:.2f}",
        "HeatEmissionsDropPct": f"{100 * (1 - r['emissions_t'].iloc[-1] / r.loc[0.0, 'emissions_t']):.0f}",
        "HeatRolloutMaxGW": f"{r.index.max() / 1000:.0f}",
        "HeatPriceNoHP": f"{r.loc[0.0, 'avg_elec_price']:.1f}",
        "HeatPriceMaxHP": f"{r['avg_elec_price'].iloc[-1]:.1f}",
    }
    # The pump's load cost, the metric of Ruhnau et al. (2020) that the §5.3
    # prose quotes: the electricity price weighted by the pump's own
    # consumption, the demand-side mirror of a capture price. Beside it, the
    # base case's average price, and the same hourly prices weighted by the
    # heat load's shape, which is the electricity a pump with neither a
    # boiler nor a heat store behind it would have to draw. All three come
    # from the base case's hours; nothing is re-solved.
    h = d["hours"]
    follow = h["heat_demand_mw"] / h["cop"]
    macros |= {
        "HeatPriceBase": f"{r.loc[s['hp_base_mw_el'], 'avg_elec_price']:.1f}",
        "HeatLoadCost":
            f"{(h['elec_price'] * h['hp_elec_mw']).sum() / h['hp_elec_mw'].sum():.1f}",
        "HeatLoadCostHeatShape":
            f"{(h['elec_price'] * follow).sum() / follow.sum():.1f}",
    }
    if len(r_tax):
        base = s["hp_base_mw_el"]
        macros |= {
            "HeatRolloutTax": f"{r_tax['tau_eur_t'].iloc[0]:.0f}",
            "HeatEmissionsTaxNoHPMt": f"{r_tax.loc[0.0, 'emissions_t'] / 1e6:.2f}",
            "HeatEmissionsTaxMaxHPMt": f"{r_tax['emissions_t'].iloc[-1] / 1e6:.2f}",
            "HeatEmissionsTaxDropPct": f"{100 * (1 - r_tax['emissions_t'].iloc[-1] / r_tax.loc[0.0, 'emissions_t']):.0f}",
            # The first tranche of rollout, with and without the tax — the
            # complementarity comparison the §5.3 prose quotes; and where
            # the taxed line bottoms out, since past that point extra pump
            # load drags the margin back into coal and emissions rise.
            "HeatEmissionsDropToBasePct":
                f"{100 * (1 - r.loc[base, 'emissions_t'] / r.loc[0.0, 'emissions_t']):.1f}",
            "HeatEmissionsTaxDropToBasePct":
                f"{100 * (1 - r_tax.loc[base, 'emissions_t'] / r_tax.loc[0.0, 'emissions_t']):.1f}",
            "HeatTaxTroughGW":
                f"{r_tax['emissions_t'].idxmin() / 1000:.1f}",
        }
    _write_values("heat_values.tex", macros, "results/heat_summary.json")


# --------------------------------------------------------------------------
# Section 6 — transmission
# --------------------------------------------------------------------------

def fig_network_prices(d):
    """Figure (fig:transmission:prices): zonal price duration curves. The
    five curves run together through the middle of the year, where direct
    labels would sit on each other's lines, so they get a legend in the
    empty corner below them."""
    prices = d["prices"]
    pct = (pd.RangeIndex(len(prices)) + 0.5) / len(prices) * 100.0

    fig, ax = plt.subplots(figsize=(6.1, 3.7))
    for zone in ["DE", "DK1", "DK2", "NO2", "SE3"]:
        sorted_p = prices[zone].sort_values(ascending=False).to_numpy()
        ax.plot(pct, sorted_p, color=ZONE_COLORS[zone], linewidth=1.6,
                label=zone)
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="lower left")
    ax.set_xlim(0, 100)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("zonal price (€/MWh)")
    fig.savefig(FIGURES / "network_price_duration.pdf")
    plt.close(fig)


def fig_network_rents(d):
    """Figure 6.2: annual congestion rent per interzonal corridor, with the
    share of congested hours. Corridors earning under 1 M€ are left out."""
    rents = d["rents"]
    rents = rents[rents["rent_eur"] > 1e6].sort_values("rent_eur")
    fig, ax = plt.subplots(figsize=(6.1, 3.4))
    y = range(len(rents))
    ax.barh(y, rents["rent_eur"] / 1e6, color=BLOCK_FILL, edgecolor="white")
    ax.set_yticks(list(y), rents.index)
    for i, (_, row) in enumerate(rents.iterrows()):
        ax.annotate(f"congested {100 * row['congested_share']:.0f}% of hours",
                    xy=(row["rent_eur"] / 1e6, i), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=7.5,
                    color=INK)
    ax.set_xlim(0, rents["rent_eur"].max() / 1e6 * 1.35)
    ax.grid(axis="x")
    ax.set_xlabel("congestion rent (M€ per year)")
    fig.savefig(FIGURES / "network_rents.pdf")
    plt.close(fig)


def fig_network_smoothing(d):
    """Figure 6.3: geographic smoothing in the raw data — DK1 vs DK2 wind."""
    wind = d["wind_hourly"]
    duration = d["wind_duration"]
    corr = d["summary"]["wind_correlation_dk1_dk2"]

    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2))
    axes[0].scatter(wind["dk1"], wind["dk2"], s=1.2, alpha=0.12, color=BLUE,
                    rasterized=True)
    axes[0].set_xlabel("DK1 onshore wind (share of maximum output)")
    axes[0].set_ylabel("DK2 onshore wind (share of maximum output)")
    axes[0].set_title(f"(a) hourly, corr. {corr:.2f}", loc="left",
                      fontsize=9, color=INK)
    axes[0].grid(axis="y")

    styles = {"dk1": (ZONE_COLORS["DK1"], "DK1"), "dk2": (ZONE_COLORS["DK2"], "DK2"),
              "combined": (INK, "average")}
    for col, (color, label) in styles.items():
        axes[1].plot(duration.index, duration[col], color=color, linewidth=1.5,
                     label=label)
    axes[1].legend(frameon=False, fontsize=8)
    axes[1].set_xlabel("share of hours (%)")
    axes[1].set_title("(b) duration curves", loc="left", fontsize=9, color=INK)
    axes[1].grid(axis="y")
    fig.savefig(FIGURES / "network_smoothing.pdf")
    plt.close(fig)


def fig_network_expansion(d):
    """Figure 6.4: what growing the Skagerrak corridor is worth, and who
    keeps the rent."""
    e = d["expansion"]
    gw = e["ntc_mw"] / 1000.0
    actual = e.loc[e["scale"] == 1.0, "ntc_mw"].iloc[0] / 1000.0
    fig, ax = plt.subplots(figsize=(6.1, 3.5))
    ax.plot(gw, e["cost_saving_eur"] / 1e6, color=BLUE, linewidth=1.8,
            marker="o", markersize=4)
    ax.plot(gw, e["corridor_rent_eur"] / 1e6, color=VERMILLION, linewidth=1.8,
            marker="o", markersize=4)
    ax.axvline(actual, color="#bbbbbb", linewidth=0.9, linestyle="--")
    ax.annotate("actual capacity", xy=(actual, ax.get_ylim()[1] * 0.05),
                xytext=(4, 0), textcoords="offset points", fontsize=7.5,
                color=INK)
    ax.annotate("system cost saving vs no cables",
                xy=(gw.iloc[5], e["cost_saving_eur"].iloc[5] / 1e6),
                xytext=(6, -14), textcoords="offset points", fontsize=8, color=BLUE)
    ax.annotate("congestion rent on the interconnector",
                xy=(gw.iloc[5], e["corridor_rent_eur"].iloc[5] / 1e6),
                xytext=(6, 8), textcoords="offset points", fontsize=8,
                color=VERMILLION)
    ax.grid(axis="y")
    ax.set_xlabel("Skagerrak (DK1–NO2) capacity (GW)")
    ax.set_ylabel("M€ per year")
    fig.savefig(FIGURES / "network_expansion.pdf")
    plt.close(fig)


# The geography figures draw projected polygons written by the run stage
# (metres, ETRS89-LCC); nothing geographic is computed here.
MODEL_ZONE_FILL = "#aecde3"
COUPLED_FILL = "#e9e9e9"
BACKGROUND_FILL = "#f5f5f5"
AREA_FILL = {"Continental Europe": "#dfe9f3", "Nordic": "#f3ebdc"}
# Where each labelled corridor's text sits, as an offset from the corridor's
# midpoint in map metres. Only the corridors listed are labelled: the named
# DC cables and the two AC borders that face Denmark.
TOPOLOGY_LABEL_OFFSETS = {
    "DK1–NO2 DC": (-330e3, 60e3),
    "DK1–SE3 DC": (455e3, -100e3),
    "DK1–DK2 DC": (-300e3, -120e3),
    "DE–NO2 DC": (-380e3, -280e3),
    "DE–DK2 DC": (400e3, -140e3),
    "DE–SE4 DC": (430e3, 10e3),
    "SE3–SE4 DC": (360e3, -40e3),
    "DE–DK1 AC": (-240e3, -200e3),
    "DK2–SE4 AC": (300e3, -30e3),
}


def _draw_zones(ax, zones, fill_of, edge="white", linewidth=0.5):
    from matplotlib.patches import Polygon
    for z in zones:
        fill = fill_of(z)
        if fill is None:
            continue
        for ring in z["rings"]:
            ax.add_patch(Polygon(ring, closed=True, facecolor=fill,
                                 edgecolor=edge, linewidth=linewidth))


def _bounds(zones, pad=0.03):
    xs = [x for z in zones for ring in z["rings"] for x, _ in ring]
    ys = [y for z in zones for ring in z["rings"] for _, y in ring]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    return (min(xs) - pad * dx, max(xs) + pad * dx,
            min(ys) - pad * dy, max(ys) + pad * dy)


def fig_network_map(d):
    """Figure 6.1: Europe's bidding zones, with the model's twelve
    highlighted. Zone borders are white; countries outside the coupled
    market are drawn as background only."""
    g = d["geography"]
    zones = g["zones"]
    fig, ax = plt.subplots(figsize=(6.1, 5.6))
    _draw_zones(ax, zones, lambda z: BACKGROUND_FILL if not z["coupled"] else None,
                edge="none")
    _draw_zones(ax, zones, lambda z: COUPLED_FILL if z["coupled"] and not z["in_model"] else None)
    _draw_zones(ax, zones, lambda z: MODEL_ZONE_FILL if z["in_model"] else None)
    for z in zones:
        if z["in_model"]:
            label = "DE" if z["zone"] == "DE-LU" else z["zone"]
            ax.annotate(label, z["label_xy"], ha="center", va="center",
                        fontsize=6.5, color=INK)
    x0, x1, y0, y1 = _bounds([z for z in zones if z["coupled"]])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(FIGURES / "network_map.pdf")
    plt.close(fig)


def fig_network_topology(d):
    """Figure 6.2: the network's twelve zones, shaded by synchronous area,
    with every corridor drawn as an AC circuit or a DC cable, its width
    scaled by the capacity the market trades on."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    g = d["geography"]
    zones = [z for z in g["zones"] if z["in_model"]]
    nodes = g["nodes"]
    area = g["synchronous_area"]

    def zone_code(z):
        return "DE" if z["zone"] == "DE-LU" else z["zone"]

    fig, ax = plt.subplots(figsize=(6.1, 6.0))
    _draw_zones(ax, zones, lambda z: AREA_FILL[area[zone_code(z)]], linewidth=0.7)
    for br in sorted(g["branches"], key=lambda b: b["kind"]):
        (xa, ya), (xb, yb) = nodes[br["zone0"]], nodes[br["zone1"]]
        width = 0.5 + 1.6 * min(br["capacity_mw"], 5000) / 5000
        if br["kind"] == "AC":
            ax.plot([xa, xb], [ya, yb], color=INK, linewidth=width,
                    solid_capstyle="round", zorder=3)
        else:
            ax.plot([xa, xb], [ya, yb], color=BLUE, linewidth=width,
                    linestyle=(0, (3, 2)), zorder=4)
        key = f"{br['zone0']}–{br['zone1']} {br['kind']}"
        if key in TOPOLOGY_LABEL_OFFSETS:
            dx, dy = TOPOLOGY_LABEL_OFFSETS[key]
            text = (f"{br['name']}, " if br["name"] else "") + f"{br['capacity_mw'] / 1000:.1f} GW"
            color = BLUE if br["kind"] == "DC" else INK
            mid = ((xa + xb) / 2, (ya + yb) / 2)
            ax.annotate(text, mid, xytext=(mid[0] + dx, mid[1] + dy),
                        fontsize=6, color=color, ha="center", va="center",
                        arrowprops=dict(arrowstyle="-", color="#aaaaaa",
                                        linewidth=0.5, shrinkB=2),
                        bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                                  edgecolor="none", alpha=0.9), zorder=6)
    for zone, (x, y) in nodes.items():
        ax.annotate(zone, (x, y), fontsize=7.5, fontweight="bold", color=INK,
                    ha="center", va="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                              edgecolor="#999999", linewidth=0.5))
    handles = [
        Patch(facecolor=AREA_FILL["Continental Europe"], label="Continental synchronous area"),
        Patch(facecolor=AREA_FILL["Nordic"], label="Nordic synchronous area"),
        Line2D([0], [0], color=INK, linewidth=1.5, label="AC interconnector"),
        Line2D([0], [0], color=BLUE, linewidth=1.5, linestyle=(0, (3, 2)), label="DC cable"),
    ]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=7)
    x0, x1, y0, y1 = _bounds(zones, pad=0.04)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(FIGURES / "network_topology.pdf")
    plt.close(fig)


DISTRIBUTION_PROJECTS = {
    # label -> (scale after, scale before) in the Skagerrak sweep
    "Built": (1.0, 0.0),
    "Double": (2.0, 1.0),
}
DISTRIBUTION_COUNTRIES = ["DK", "NO", "DE", "SE"]


def distribution_table(d, after, before):
    """Change in each country's consumer surplus, producer profit and half
    share of congestion rents between two sizes of the Skagerrak corridor,
    in EUR per year; plus the change in total system cost and the residual
    the accounting identity leaves (the loss formulation's own terms)."""
    acc = d["accounts"].copy()
    acc["country"] = acc["zone"].str[:2]
    by = acc.groupby(["scale", "country"])[
        ["consumer_expenditure_eur", "generation_cost_eur",
         "producer_profit_eur", "rent_share_eur"]].sum()
    delta = by.loc[after] - by.loc[before]
    table = pd.DataFrame({
        "consumers": -delta["consumer_expenditure_eur"],
        "producers": delta["producer_profit_eur"],
        "rent": delta["rent_share_eur"],
    }).reindex(DISTRIBUTION_COUNTRIES)
    table["net"] = table.sum(axis=1)
    e = d["expansion"].set_index("scale")
    total = float(e.loc[before, "system_cost"] - e.loc[after, "system_cost"])
    return table, total, total - float(table["net"].sum())


def fig_network_distribution(d):
    """Figure (fig:transmission:distribution): who wins and who loses from
    the Skagerrak corridor, by country: consumers, producers and the
    countries' halves of the rent, for the corridor as built against none,
    and for a doubling. The bars fill both panels top to bottom, so the
    legend sits below them."""
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.6))
    titles = {"Built": "(a) the interconnector as built, against none",
              "Double": "(b) a second interconnector of the same size"}
    colors = {"consumers": BLUE, "producers": VERMILLION, "rent": "#999999"}
    labels = {"consumers": "consumers", "producers": "producers",
              "rent": "cable owners (rent)"}
    for ax, (label, (after, before)) in zip(axes, DISTRIBUTION_PROJECTS.items()):
        table, total, residual = distribution_table(d, after, before)
        x = range(len(table))
        pos = pd.Series(0.0, index=table.index)
        neg = pd.Series(0.0, index=table.index)
        for col in ["consumers", "producers", "rent"]:
            values = table[col] / 1e6
            bottom = pos.where(values >= 0, neg)
            ax.bar(x, values, bottom=bottom, color=colors[col], width=0.6,
                   label=labels[col], edgecolor="white", linewidth=0.5)
            pos += values.clip(lower=0)
            neg += values.clip(upper=0)
        ax.scatter(x, table["net"] / 1e6, marker="_", s=260, color=INK,
                   linewidths=1.8, zorder=5, label="net")
        ax.axhline(0, color="#666666", linewidth=0.7)
        ax.set_xticks(list(x), [f"{c}" for c in table.index])
        ax.set_title(titles[label], loc="left", fontsize=9, color=INK)
        ax.grid(axis="y")
    axes[0].set_ylabel("M€ per year")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, frameon=False, fontsize=8, ncol=4,
               loc="outside lower center")
    fig.savefig(FIGURES / "network_distribution.pdf")
    plt.close(fig)


def _write_network_calibration_table(d):
    """Appendix B: what each calibration of the shipped network does to
    the Nordic price level, against the market. One row per combination,
    plus the realised year."""
    cal = d["calibration"]
    actual = d["summary"]["actual_market"]["avg_price"]
    h = {row["country"]: row for row in d["summary"]["calibration"]["hydro_table"]}["NO"]
    labels = {(False, False): "network at the normal-year hydro level",
              (True, False): "Norwegian inflow scaled",
              (False, True): "Nordic corridors at reference NTCs",
              (True, True): "both (the section's instance)"}
    lines = [
        r"\begin{tabular}{@{} L{0.34\textwidth} R{0.09\textwidth} R{0.09\textwidth} R{0.09\textwidth} R{0.11\textwidth} R{0.11\textwidth} @{}}",
        r"\toprule",
        r" & NO2 & SE3 & SE4 & NO hydro & NO net export \\",
        r" & \multicolumn{3}{c}{mean price, €/MWh} & TWh & TWh \\",
        r"\midrule",
    ]
    for _, row in cal.iterrows():
        key = (bool(row["hydro"]), bool(row["ntc"]))
        lines.append(
            f"{labels[key]} & {row['price_NO2']:.0f} & {row['price_SE3']:.0f} & "
            f"{row['price_SE4']:.0f} & {row['hydro_NO_twh']:.0f} & "
            f"{row['net_export_NO_twh']:.0f} \\\\")
        lines.append(r"\midrule")
    lines.append(
        f"the 2024 market & {actual['NO2']:.0f} & {actual['SE3']:.0f} & "
        f"{actual['SE4']:.0f} & {h['published_hydro_production_twh']:.0f} & "
        f"{h['published_net_export_twh']:.0f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "network_calibration_table.tex").write_text(
        "%% GENERATED by pipeline/build.py from results/network_calibration.csv\n"
        + "\n".join(lines) + "\n", encoding="utf-8")


def values_network(d):
    s = d["summary"]
    e = d["expansion"].set_index("scale")
    rents = d["rents"]
    skagerrak = rents.loc["DK1–NO2"]
    macros = {
        "NetworkHours": f"{s['hours']}",
        "NetworkYear": f"{s['network_year']}",
        "NetworkZones": f"{len(s['zones'])}",
        "NetworkGenerators": f"{s.get('n_generators', 0)}",
        "NetworkHydroUnits": f"{s.get('n_hydro_units', 0)}",
        "NetworkPriceDKOne": f"{s['avg_price']['DK1']:.1f}",
        "NetworkPriceDKTwo": f"{s['avg_price']['DK2']:.1f}",
        "NetworkPriceDE": f"{s['avg_price']['DE']:.1f}",
        "NetworkPriceSE": f"{s['avg_price']['SE3']:.1f}",
        "NetworkPriceSEFour": f"{s['avg_price']['SE4']:.1f}",
        "NetworkCarbonTau": f"{s['carbon_tau_eur_t']:.0f}",
        # Danish borders only — the like-for-like counterpart of
        # ActualDKRentTotalMEUR. The all-corridor total also counts internal
        # Nordic/German corridors the realised comparison has no data for.
        "NetworkDKRentTotalMEUR":
            f"{rents['rent_eur'].reindex(['DK1–NO2', 'DK1–SE3', 'DE–DK1', 'DK1–DK2', 'DK2–SE4', 'DE–DK2']).sum() / 1e6:.0f}",
        "NetworkPriceNO": f"{s['avg_price']['NO2']:.1f}",
        "NetworkWindCorr": f"{s['wind_correlation_dk1_dk2']:.2f}",
        "NetworkTotalRentMEUR": f"{s['total_congestion_rent_eur'] / 1e6:.0f}",
        "NetworkSkagerrakRentMEUR": f"{skagerrak['rent_eur'] / 1e6:.0f}",
        "NetworkSkagerrakCongestedPct": f"{100 * skagerrak['congested_share']:.0f}",
        "NetworkExpActualGW": f"{e.loc[1.0, 'ntc_mw'] / 1000:.1f}",
        "NetworkExpSavingActualMEUR": f"{e.loc[1.0, 'cost_saving_eur'] / 1e6:.0f}",
        "NetworkExpSavingTripleMEUR": f"{e.loc[3.0, 'cost_saving_eur'] / 1e6:.0f}",
        "NetworkExpRentActualMEUR": f"{e.loc[1.0, 'corridor_rent_eur'] / 1e6:.0f}",
        "NetworkExpRentTripleMEUR": f"{e.loc[3.0, 'corridor_rent_eur'] / 1e6:.0f}",
    }
    if "actual_market" in s:
        a = s["actual_market"]
        macros |= {
            "ActualPriceDKOneYr": f"{a['avg_price']['DK1']:.1f}",
            "ActualPriceNOYr": f"{a['avg_price']['NO2']:.1f}",
            "ActualPriceDEYr": f"{a['avg_price']['DE']:.1f}",
            "ActualPriceSEThreeYr": f"{a['avg_price']['SE3']:.1f}",
            "ActualPriceSEFourYr": f"{a['avg_price']['SE4']:.1f}",
            "ActualSkagerrakRentMEUR": f"{a['corridor_rent_eur']['DK1–NO2'] / 1e6:.0f}",
            "ActualDKRentTotalMEUR": f"{sum(a['corridor_rent_eur'].values()) / 1e6:.0f}",
        }
    if "calibration" in s:
        c = s["calibration"]
        h = {row["country"]: row for row in c["hydro_table"]}["NO"]
        b = s["country_balance"]
        macros |= {
            "NetworkHydroNetworkTWh":
                f"{h['network_reservoir_inflow_twh'] + h['network_run_of_river_twh']:.0f}",
            "NetworkHydroPublishedTWh": f"{h['published_hydro_production_twh']:.0f}",
            "NetworkHydroNormalTWh": f"{h.get('normal_production_twh', float('nan')):.1f}",
            "NetworkHydroModelTWh": f"{b['NO']['hydro_twh']:.0f}",
            "NetworkHydroFactor": f"{c['hydro_factors'].get('NO', 1.0):.2f}",
            "NetworkNOExportTWh": f"{b['NO']['net_export_twh']:.0f}",
            "NetworkSEExportTWh": f"{b['SE']['net_export_twh']:.0f}",
            "ActualNOExportTWh": f"{h['published_net_export_twh']:.0f}",
            "NetworkNTCDerated": f"{len(c['ntc_changes'])}",
        }
    if d.get("calibration") is not None:
        _write_network_calibration_table(d)
    if "border_capacity_mw" in s:
        cap = s["border_capacity_mw"]
        costs = {row["technology"]: row for row in s["transmission_costs"]}
        macros |= {
            # The grid as the market sees it
            "NetworkNTCDKOneDE": f"{cap['DE–DK1'] / 1000:.1f}",
            "NetworkNTCDKTwoSEFour": f"{cap['DK2–SE4'] / 1000:.1f}",
            "NetworkSkagerrakGW": f"{cap['DK1–NO2'] / 1000:.1f}",
            "NetworkNordLinkGW": f"{cap['DE–NO2'] / 1000:.1f}",
            "NetworkKontiSkanGW": f"{cap['DK1–SE3'] / 1000:.1f}",
            "NetworkKontekGW": f"{cap['DE–DK2'] / 1000:.1f}",
            "NetworkACCorridors": f"{s['n_ac_corridors']}",
            "NetworkDCCorridors": f"{s['n_dc_corridors']}",
            "NetworkNordicLoops": f"{s['ac_loops']['Nordic']}",
            "NetworkHVDCLossPct": f"{100 * s['hvdc_loss']:.0f}",
            # What a wire costs (technology-data)
            "NetworkCostACOverhead": f"{costs['HVAC overhead']['investment']:.0f}",
            "NetworkCostDCOverhead": f"{costs['HVDC overhead']['investment']:.0f}",
            "NetworkCostDCSubmarine": f"{costs['HVDC submarine']['investment']:.0f}",
            "NetworkCostDCConverterKEUR": f"{costs['HVDC inverter pair']['investment'] / 1e3:.0f}",
            "NetworkLineLifetime": f"{costs['HVAC overhead']['lifetime_years']:.0f}",
            "NetworkSkagerrakLengthKm": f"{s['skagerrak_length_km']:.0f}",
            "NetworkSkagerrakRuleOfThumbMEURperGW":
                f"{s['skagerrak_rule_of_thumb_eur_per_mw'] * 1e3 / 1e6:.0f}",
            "NetworkSkagerrakTyndpMinMEURperGW":
                f"{s['skagerrak_tyndp_capex_meur_per_gw']['min']:.0f}",
            "NetworkSkagerrakTyndpMaxMEURperGW":
                f"{s['skagerrak_tyndp_capex_meur_per_gw']['max']:.0f}",
        }
    if d.get("accounts") is not None:
        # Who wins and who loses, by country, signed in M€ (a negative number
        # is a loss) and in absolute value for prose that states the
        # direction itself.
        for label, (after, before) in DISTRIBUTION_PROJECTS.items():
            table, total, residual = distribution_table(d, after, before)
            for country in DISTRIBUTION_COUNTRIES:
                for item, col in [("Cons", "consumers"), ("Prod", "producers"),
                                  ("Rent", "rent"), ("Net", "net")]:
                    value = table.loc[country, col] / 1e6
                    macros[f"NetworkDist{label}{country}{item}MEUR"] = f"{value:.0f}"
                    macros[f"NetworkDist{label}{country}{item}AbsMEUR"] = f"{abs(value):.0f}"
            macros[f"NetworkDist{label}TotalMEUR"] = f"{total / 1e6:.0f}"
            macros[f"NetworkDist{label}ResidualMEUR"] = f"{residual / 1e6:.0f}"
            macros[f"NetworkDist{label}ResidualPct"] = f"{100 * residual / total:.0f}"
    _write_values("network_values.tex", macros, "results/network_summary.json")


# --------------------------------------------------------------------------
# Section 7 — investment
# --------------------------------------------------------------------------

def fig_greenfield_screening(d):
    """Figure 7.1: screening curves — annual cost per MW against running
    hours; the lower envelope picks the technology for each duty."""
    s = d["screening"]
    hours = pd.Series(range(0, 8761, 20))
    fig, ax = plt.subplots(figsize=(6.1, 3.7))
    for tech, row in s.iterrows():
        # Nuclear's fixed cost sits four times above everything else; drawing
        # it would flatten the envelope the figure exists to show. Its cost
        # is quoted in the prose (\InvNuclearFixed) instead.
        if tech == "nuclear":
            continue
        cost = (row["fixed_eur_mw_yr"] + row["marginal_cost"] * hours) / 1e3
        ax.plot(hours, cost, color=TECH_COLORS[tech], linewidth=1.6)
        ax.annotate(TECH_LABELS[tech], xy=(hours.iloc[-1], cost.iloc[-1]),
                    xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=8, color=label_color(TECH_COLORS[tech]),
                    annotation_clip=False)
    # Where the LP actually put each technology. The screening curve names the
    # cheapest technology for a *given* duty; it cannot say which duty a
    # technology ends up serving once intermittency, storage and trade are in
    # the problem. Marking the model's own answer on the same axis closes that
    # gap -- and shows how far the renewables sit from the flat-line reading.
    duty = d.get("duty")
    if duty is not None:
        for tech, row in duty.iterrows():
            flh = row["full_load_hours"]
            if tech not in TECH_COLORS or not pd.notna(flh):
                continue
            line = s.loc[tech]
            cost = (line["fixed_eur_mw_yr"] + line["marginal_cost"] * flh) / 1e3
            ax.plot([flh], [cost], marker="o", markersize=6.5,
                    color=TECH_COLORS[tech], markeredgecolor="white",
                    markeredgewidth=1.1, zorder=4)
            ax.plot([flh, flh], [0, cost], color=TECH_COLORS[tech],
                    linewidth=0.7, linestyle=":", alpha=0.7, zorder=1)
        ax.annotate("markers: the duty each technology actually serves\n"
                    "in the reference system",
                    xy=(0.02, 0.97), xycoords="axes fraction", ha="left",
                    va="top", fontsize=7.5, color=INK)

    ax.set_xlim(0, 8760)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y")
    ax.set_xlabel("full-load hours per year")
    ax.set_ylabel("total annual cost (k€ per MW)")
    fig.savefig(FIGURES / "greenfield_screening.pdf")
    plt.close(fig)


def _stacked_mix(ax, frame, order=None):
    """Stacked capacity bars, GW, one bar per row of `frame`."""
    order = order or [t for t in TECH_COLORS if f"cap_{t}_mw" in frame.columns]
    x = range(len(frame))
    bottom = pd.Series(0.0, index=frame.index)
    for tech in order:
        col = f"cap_{tech}_mw"
        if col not in frame.columns:
            continue
        values = frame[col].fillna(0.0) / 1000.0
        ax.bar(x, values, bottom=bottom, color=TECH_COLORS[tech],
               edgecolor="white", linewidth=0.8, width=0.65,
               label=TECH_LABELS[tech])
        bottom = bottom + values.to_numpy()
    ax.set_xticks(list(x), frame.index)
    ax.grid(axis="y")
    ax.set_ylabel("capacity (GW)")
    return bottom


def fig_greenfield_mix(d):
    """Figure (fig:investment:mix): (a) the optimal Danish mix as the common
    carbon price rises, with Danish emissions in Mt above each bar (the unit
    is in the caption: with it, neighbouring labels collide); (b) Danish and
    twelve-zone emissions against the price, each as a share of its level at
    the lowest price of the sweep (zero), on one axis -- the marginal
    abatement curve read from the tax side, with the fuel-switching price
    marked. The two levels differ by a factor of a few hundred; indexing
    them is what lets one axis carry both paths."""
    sweep = d["sweep"].copy().sort_values("carbon_price")
    s = d["summary"]
    sweep.index = [f"{t:.0f}" for t in sweep["carbon_price"]]
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.9),
                             gridspec_kw={"width_ratios": [1.5, 1.0]})
    top = _stacked_mix(axes[0], sweep)
    for i, (_, row) in enumerate(sweep.iterrows()):
        axes[0].annotate(f"{row['emissions_t'] / 1e6:.2f}", xy=(i, top.iloc[i]),
                         xytext=(0, 4), textcoords="offset points", ha="center",
                         fontsize=7, color=INK)
    axes[0].legend(frameon=False, fontsize=7, ncol=2, loc="upper left")
    axes[0].set_ylim(0, top.max() * 1.6)
    axes[0].set_xlabel("common carbon price (€/t)")
    axes[0].set_title("(a) what Denmark builds", loc="left", fontsize=9, color=INK)
    ax = axes[1]
    first = sweep.iloc[0]
    for column, color, marker, label in [
        ("emissions_t", BLUE, "o", "Denmark"),
        ("emissions_total_t", VERMILLION, "s", "twelve zones"),
    ]:
        ax.plot(sweep["carbon_price"], 100 * sweep[column] / first[column],
                marker=marker, color=color, linewidth=1.5, markersize=4.5,
                label=label)
    ax.axvline(s["switch_price_eur_t"], color=INK, linewidth=0.8, linestyle=":")
    ax.annotate("fuel switch", xy=(s["switch_price_eur_t"], 100),
                xytext=(3, -2), textcoords="offset points", fontsize=7,
                color=INK, va="top")
    ax.set_ylim(0, 105)
    ax.set_xlabel("common carbon price (€/t)")
    base = "without a carbon price" if first["carbon_price"] == 0 else "at the lowest price"
    ax.set_ylabel(f"% of emissions {base}")
    ax.legend(frameon=False, fontsize=7.5, loc="upper right",
              bbox_to_anchor=(1.0, 0.86))
    ax.grid(axis="y")
    ax.set_title("(b) emissions", loc="left", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(FIGURES / "greenfield_mix.pdf")
    plt.close(fig)


# The experiments of the scenarios figure, each against its own baseline:
# the first three change one thing in the reference system; the Danish
# budget replaces the common price, so its baseline is the unpriced system.
EXPERIMENT_BASELINES = [("autarky", "reference"), ("expensive gas", "reference"),
                        ("cheap capital", "reference"),
                        ("Danish budget", "no carbon price")]
EXPERIMENT_TECHS = ["solar_pv", "wind_onshore", "wind_offshore", "battery",
                    "ocgt", "ccgt"]


def fig_greenfield_scenarios(d):
    """Figure (fig:investment:scenarios): the four experiments beyond the
    carbon price. (a) What Denmark builds in each, beside the system it is
    compared with: the reference for the first three, the unpriced system
    for the Danish budget, set apart. Danish emissions above each bar, and
    the budget's shadow price. (b) What moved: the change in each
    technology's Danish capacity against the experiment's own baseline, one
    small panel per experiment, in the technology colours of (a)."""
    import numpy as np

    scen = d["scenarios"]
    order = ["reference", "autarky", "expensive gas", "cheap capital",
             "no carbon price", "Danish budget"]
    scen = scen.reindex([s for s in order if s in scen.index])
    fig = plt.figure(figsize=(6.1, 6.3))
    upper, lower = fig.subfigures(2, 1, height_ratios=[1.3, 1.0])
    ax = upper.subplots()
    # (a) the levels, with a gap before the unpriced pair.
    x = np.array([i + (0.6 if name in ("no carbon price", "Danish budget") else 0.0)
                  for i, name in enumerate(scen.index)])
    bottom = np.zeros(len(scen))
    for tech in TECH_COLORS:
        column = f"cap_{tech}_mw"
        if column not in scen.columns or not (scen[column].fillna(0.0) > 1.0).any():
            continue
        values = scen[column].fillna(0.0).to_numpy() / 1000.0
        ax.bar(x, values, bottom=bottom, color=TECH_COLORS[tech],
               edgecolor="white", linewidth=0.8, width=0.65, label=TECH_LABELS[tech])
        bottom = bottom + values
    for xi, top, (name, row) in zip(x, bottom, scen.iterrows()):
        label = f"{row['emissions_t'] / 1e6:.2f} Mt"
        if pd.notna(row.get("co2_price")):
            label += f"\nσ = {row['co2_price']:.0f} €/t"
        ax.annotate(label, xy=(xi, top), xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=7, color=INK)
    names = {"expensive gas": "expensive\ngas", "cheap capital": "cheap\ncapital",
             "no carbon price": "no carbon\nprice", "Danish budget": "Danish\nbudget"}
    ax.set_xticks(x, [names.get(s, s) for s in scen.index], fontsize=8)
    ax.set_ylim(0, bottom.max() * 1.45)
    ax.set_ylabel("capacity (GW)")
    ax.grid(axis="y")
    split = (x[3] + x[4]) / 2 if len(x) > 4 else None
    if split is not None:
        ax.axvline(split, ymax=0.8, color="#bbbbbb", linewidth=0.8)
        ax.annotate("no common\ncarbon price", xy=(split, bottom.max() * 1.1),
                    xytext=(5, 0), textcoords="offset points", fontsize=7.5,
                    color=INK, va="bottom")
    ax.legend(frameon=False, fontsize=7.5, ncol=3, loc="upper left")
    ax.set_title("(a) what Denmark builds", loc="left", fontsize=9, color=INK)
    # (b) the change against each experiment's baseline.
    changes = {}
    for experiment, baseline in EXPERIMENT_BASELINES:
        if experiment in scen.index and baseline in scen.index:
            changes[experiment] = pd.Series({
                tech: (scen.loc[experiment, f"cap_{tech}_mw"]
                       - scen.loc[baseline, f"cap_{tech}_mw"]) / 1000.0
                for tech in EXPERIMENT_TECHS})
    reach = max(float(c.abs().max()) for c in changes.values()) * 1.8
    y = np.arange(len(EXPERIMENT_TECHS))[::-1]
    experiments = [(e, b) for e, b in EXPERIMENT_BASELINES if e in changes]
    panels = lower.subplots(1, len(experiments), sharey=True)
    for k, ((experiment, baseline), bx) in enumerate(zip(experiments, panels)):
        change = changes[experiment]
        bx.barh(y, change.to_numpy(), height=0.62,
                color=[TECH_COLORS[t] for t in EXPERIMENT_TECHS], edgecolor="white")
        for yi, value in zip(y, change.to_numpy()):
            if abs(value) < 0.05:
                continue
            bx.annotate(f"{value:+.1f}".replace("-", "−"), xy=(value, yi),
                        xytext=(3 if value > 0 else -3, 0), textcoords="offset points",
                        ha="left" if value > 0 else "right", va="center",
                        fontsize=6.5, color=INK)
        bx.axvline(0, color=INK, linewidth=0.8)
        bx.set_xlim(-reach, reach)
        bx.grid(axis="x")
        bx.tick_params(axis="x", labelsize=7)
        title = experiment if baseline == "reference" else f"{experiment}\n(vs no carbon price)"
        bx.set_title(title, fontsize=8, color=INK)
        if k == 0:
            bx.set_yticks(y, [TECH_LABELS[t] for t in EXPERIMENT_TECHS], fontsize=8)
        else:
            bx.tick_params(axis="y", labelleft=False, length=0)
    lower.suptitle("(b) what moved: change in capacity against the baseline (GW)",
                   x=0.02, ha="left", fontsize=9, color=INK)
    fig.savefig(FIGURES / "greenfield_scenarios.pdf")
    plt.close(fig)


RECOVERY_ORDER = ["solar_pv", "wind_onshore", "wind_offshore", "battery_8h",
                  "battery_4h", "battery_2h", "ocgt_biogas", "ocgt", "ccgt",
                  "nuclear"]
RECOVERY_LABELS = {**TECH_LABELS, "battery_2h": "battery 2h",
                   "battery_4h": "battery 4h", "battery_8h": "battery 8h"}


def recovery_by_tech(r):
    """Rent over annualised fixed cost per technology, as the figure and the
    text quote it: for a technology the model built, its whole Danish
    fleet's rents over the fleet's fixed cost, so one capped in one zone and
    not in the other shows part of a land rent; for one it declined, the
    better of the two zones."""
    out = {}
    for tech, rows in r.groupby("tech"):
        built = rows[rows["built"]]
        if len(built):
            out[tech] = float((built["rent_eur_mw_yr"] * built["capacity_mw"]).sum()
                              / (built["fixed_eur_mw_yr"] * built["capacity_mw"]).sum())
        else:
            out[tech] = float(rows["rent_over_fixed"].max())
    return pd.Series(out)


def recovery_tag(r, tech) -> str:
    """The value table's regime column for a built technology: interior, at
    its cap, or at its cap in the zones named when the zones differ."""
    built = r[(r["tech"] == tech) & r["built"]]
    if built.empty:
        return ""
    capped = built.loc[built["at_cap"], "zone"].tolist()
    if not capped:
        return "interior"
    if len(capped) == len(built):
        return "at its cap"
    return "at its cap in " + " and ".join(capped)


POTENTIAL_FILL = "#e3e3e3"


def fig_greenfield_recovery(d):
    """Figure (fig:investment:recovery): what Denmark builds and why, one row
    per candidate in both panels. (a) the capacity built in the two Danish
    zones together, against the buildable potential where there is one: a
    grey bar to the cap, with a tick at it. (b) Long-run zero profit in
    numbers: what a MW earns in the solved prices as a share of what it costs
    to hold for a year (recovery_by_tech). One colour: the bar's length says
    which case of Result 6 a technology is in, exactly 100% when built below
    its cap, above when at the land cap, below when not built. The rows are
    sorted on (b), and the panels share them, so a row reads across."""
    from matplotlib.patches import Patch

    r = d["cost_recovery"]
    ratio = 100 * recovery_by_tech(r)
    rank = {t: i for i, t in enumerate(RECOVERY_ORDER)}
    order = sorted(ratio.index, key=lambda t: (-round(ratio[t], 6), rank.get(t, 99)))
    ratio = ratio.reindex(order)
    built = (r.groupby("tech")["capacity_mw"].sum() / 1e3).reindex(order).fillna(0.0)
    capped = r[r["p_nom_max_mw"] < 1e8]
    potential = (capped.groupby("tech")["p_nom_max_mw"].sum() / 1e3).reindex(order)
    y = list(range(len(ratio)))[::-1]          # the largest on top

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(6.1, 3.5), sharey=True,
                                 gridspec_kw={"width_ratios": [1.0, 1.0]})
    # (a) built against the potential.
    for yi, tech in zip(y, order):
        cap = potential.get(tech)
        if pd.notna(cap):
            ax.barh(yi, cap, height=0.62, color=POTENTIAL_FILL, edgecolor="none")
            ax.plot([cap, cap], [yi - 0.36, yi + 0.36], color=INK, linewidth=1.2,
                    solid_capstyle="butt")
        gw = built[tech]
        if gw > 0.05:
            ax.barh(yi, gw, height=0.62, color=BLOCK_FILL, edgecolor="white")
            at_cap = pd.notna(cap) and gw >= 0.999 * cap
            # The label goes past the tick when the bar ends on it.
            ax.annotate(f"{gw:.1f}", xy=(max(gw, cap) if at_cap else gw, yi),
                        xytext=(3, 0), textcoords="offset points", va="center",
                        fontsize=7.5, color=INK)
        else:
            ax.annotate("not built", xy=(0, yi), xytext=(3, 0),
                        textcoords="offset points", va="center", fontsize=7.5,
                        color="#888888")
    ax.set_xlim(0, float(potential.max()) * 1.08)
    ax.set_xlabel("capacity in DK1 and DK2 (GW)")
    ax.grid(axis="x")
    ax.legend(handles=[Patch(color=BLOCK_FILL, label="built"),
                       Patch(color=POTENTIAL_FILL, label="buildable potential")],
              frameon=False, fontsize=7.5, loc="lower right")
    ax.set_title("(a) what Denmark builds", loc="left", fontsize=9, color=INK)
    # (b) what a MW earns.
    bx.barh(y, ratio.to_numpy(), height=0.62, color=BLOCK_FILL, edgecolor="white")
    for yi, value in zip(y, ratio.to_numpy()):
        bx.annotate(f"{value:.0f}%", xy=(value, yi), xytext=(3, 0),
                    textcoords="offset points", va="center", fontsize=7.5,
                    color=INK)
    bx.axvline(100, color=INK, linewidth=0.9)
    bx.annotate("zero profit", xy=(100, len(ratio) - 0.55), xytext=(3, 0),
                textcoords="offset points", ha="left", va="bottom", fontsize=7.5,
                color=INK)
    bx.set_xlim(0, ratio.max() * 1.16)
    bx.set_xlabel("% of its annualised fixed cost")
    bx.grid(axis="x")
    bx.set_title("(b) what a MW earns", loc="left", fontsize=9, color=INK)
    ax.set_yticks(y, [RECOVERY_LABELS.get(t, t) for t in order], fontsize=8)
    ax.set_ylim(-0.6, len(ratio) - 0.1)
    bx.tick_params(axis="y", length=0)
    fig.savefig(FIGURES / "greenfield_recovery.pdf")
    plt.close(fig)


def fig_greenfield_scarcity(d):
    """Figure: how the peakers get paid. The hours of the year sorted into
    bands of the price where the peakers stand (written by run_greenfield's
    scarcity_profile), and for each band the share of the year's hours set
    against the share of the peaking fleet's annual operating margin earned
    in it. Both are shares, so they share one linear axis, and the
    concentration of the margin is the mismatch between a band's two bars."""
    import numpy as np

    b = d["price_bands"]
    zone = d["summary"]["scarcity"]["peaker_zone"]
    labels = []
    for lo, hi in zip(b["lower_eur_mwh"], b["upper_eur_mwh"]):
        if not np.isfinite(lo):
            labels.append(f"below {hi:,.0f}\n(running cost)")
        elif not np.isfinite(hi):
            labels.append(f"above {lo:,.0f}")
        else:
            labels.append(f"{lo:,.0f}–{hi:,.0f}")
    x = np.arange(len(b))
    width = 0.38
    fig, ax = plt.subplots(figsize=(6.1, 3.3))
    series = [(-width / 2, 100 * b["hours_share"], BLOCK_FILL, "share of the year's hours"),
              (width / 2, 100 * b["margin_share"].clip(lower=0.0), VERMILLION,
               "share of the peakers' annual margin")]
    for shift, values, color, label in series:
        ax.bar(x + shift, values, width, color=color, edgecolor="white", label=label)
        for xi, v in zip(x + shift, values):
            text = f"{v:.0f}%" if v >= 1 or v == 0 else f"{v:.1f}%"
            ax.annotate(text, xy=(xi, v), xytext=(0, 2), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7, color=INK)
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_xlabel(f"price in {zone} (€/MWh)")
    ax.set_ylabel("% of the year's total")
    ax.set_ylim(0, 100)
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.savefig(FIGURES / "greenfield_scarcity.pdf")
    plt.close(fig)


# What covers Danish load less the wind and solar on offer, in the spell
# figure: above zero what fills a deficit, below it where a surplus goes.
SPELL_COVER = [
    ("imports (below zero: exports)", "#8c8c8c", "net_import_mw"),
    ("gas turbines", TECH_COLORS["ocgt"], "turbine_mw"),
    ("batteries (below zero: charging)", TECH_COLORS["battery"], "battery_mw"),
    ("flexible demand not served", VERMILLION, "flex_shed_mw"),
    ("wind and solar curtailed", "#d9d9d9", "curtailed_mw"),
]


def fig_greenfield_spell(d):
    """Figure (fig:investment:spell): the reference system through its
    longest scarcity spell, with a few days either side (run_greenfield's
    spell_window). (a) The price where the turbines stand, with the
    flexible block's willingness to pay that defines a spell. (b) Danish
    load less the wind and solar the weather offers, and what covers it:
    imports, the turbines, the batteries and the flexible block above zero;
    exports, charging and curtailment below. (c) The batteries' state of
    charge. Each snapshot stands for several hours, so everything is drawn
    as steps, and the spells are shaded in every panel."""
    import matplotlib.dates as mdates
    import numpy as np

    s = d.get("spell_window")
    if s is None or s.empty:
        print("skipping the spell figure — re-run pipeline/run_greenfield.py")
        return
    summary = d["summary"]
    zone = summary["scarcity"]["peaker_zone"]
    flex = {c: wtp for c, _, wtp in summary["demand_blocks"]}["shed_flex"]
    edges = list(s.index) + [s.index[-1] + pd.Timedelta(hours=float(s["hours"].iloc[-1]))]

    def stepped(values):
        values = np.asarray(values, dtype=float)
        return np.append(values, values[-1])

    offer = s["wind_available_mw"] + s["solar_available_mw"]
    residual = (s["load_mw"] - offer) / 1e3
    # Curtailment is what the balance leaves of the wind and solar on offer.
    used = (s["load_mw"] - s["turbine_mw"] - s["battery_mw"] - s["net_import_mw"]
            - s["flex_shed_mw"])
    s = s.assign(curtailed_mw=(offer - used).clip(lower=0.0))

    fig, axes = plt.subplots(3, 1, figsize=(6.1, 6.0), sharex=True,
                             gridspec_kw={"height_ratios": [1.0, 1.7, 0.75]})
    for ax in axes:
        for t, hours, spell in zip(s.index, s["hours"], s["in_spell"]):
            if spell:
                ax.axvspan(t, t + pd.Timedelta(hours=float(hours)), color="#f0f0f0",
                           linewidth=0, zorder=0)
    # (a) the price, cut off above where the scarcity spells sit; a price
    # beyond the axis is written where it leaves it.
    ax = axes[0]
    price = s["price_eur_mwh"]
    top = min(float(price.max()) * 1.08, 300.0)
    ax.step(edges, stepped(price.clip(upper=top)), where="post", color=BLUE,
            linewidth=1.3)
    if price.max() > top:
        ax.annotate(f"up to {price.max():,.0f} €/MWh", xy=(price[price > top].index[0], top),
                    xytext=(-3, -2), textcoords="offset points", ha="right",
                    va="top", fontsize=7, color=INK)
    # The line's label goes where the price is far below it for longest.
    low = (price < 0.5 * flex).to_numpy()
    best, run, start = (0, 0), 0, 0
    for i, flag in enumerate(low):
        if flag:
            start = i if run == 0 else start
            run += 1
            best = max(best, (run, start))
        else:
            run = 0
    ax.axhline(flex, color=INK, linewidth=0.8, linestyle=":")
    ax.annotate("flexible block's\nwillingness to pay", xy=(s.index[best[1]], flex),
                xytext=(2, 3), textcoords="offset points", fontsize=7, color=INK,
                va="bottom")
    ax.set_ylim(0, top)
    ax.set_ylabel("€/MWh")
    ax.grid(axis="y")
    ax.set_title(f"(a) the price in {zone}; scarcity spells shaded", loc="left",
                 fontsize=9, color=INK)
    # (b) what covers load less wind and solar.
    ax = axes[1]
    up = np.zeros(len(s))
    down = np.zeros(len(s))
    for label, color, column in SPELL_COVER:
        values = s[column].to_numpy() / 1e3
        if column == "curtailed_mw":
            values = -values
        pos, neg = np.clip(values, 0, None), np.clip(values, None, 0)
        if pos.any():
            ax.fill_between(edges, stepped(up), stepped(up + pos), step="post",
                            color=color, linewidth=0, label=label)
        if neg.any():
            ax.fill_between(edges, stepped(down), stepped(down + neg), step="post",
                            color=color, linewidth=0,
                            label=None if pos.any() else label)
        up, down = up + pos, down + neg
    ax.step(edges, stepped(residual), where="post", color=INK, linewidth=1.2,
            label="load less the wind and solar on offer")
    ax.axhline(0, color="#999999", linewidth=0.8)
    ax.set_ylabel("GW")
    ax.set_ylim(min(down.min(), residual.min()) * 1.1,
                max(up.max(), residual.max()) * 1.9)
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper left")
    ax.set_title("(b) what covers Danish load less wind and solar", loc="left",
                 fontsize=9, color=INK)
    # (c) the batteries' state of charge.
    ax = axes[2]
    soc = 100 * s["battery_soc_mwh"] / s["battery_energy_mwh"]
    ax.step(edges, stepped(soc), where="post", color=TECH_COLORS["battery"],
            linewidth=1.3)
    ax.set_ylim(0, 105)
    ax.set_ylabel("% of full")
    ax.grid(axis="y")
    ax.set_title("(c) the batteries' state of charge", loc="left", fontsize=9,
                 color=INK)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(axis="x", labelsize=7.5)
    fig.savefig(FIGURES / "greenfield_spell.pdf")
    plt.close(fig)


def table_greenfield_values(d):
    """Table: levelised cost against capture price at the reference optimum,
    per built Danish generator -- section 3's statistics evaluated where
    zero profit makes the two coincide for uncapped technologies."""
    v = d["value_table"]
    v = v.reindex([t for t in RECOVERY_ORDER if t in v.index])
    r = d["cost_recovery"]
    lines = [
        "%% GENERATED by pipeline/build.py from results/greenfield_value_table.csv",
        "%% -- do not edit; rerun the pipeline instead.",
        r"\begin{tabular}{@{} l r r r r r l @{}}",
        r"\toprule",
        r"Technology & Capacity & Full-load hours & LCOE & Capture price"
        r" & Value factor & \\",
        r" & \footnotesize{GW} & \footnotesize{h/yr} & \footnotesize{€/MWh}"
        r" & \footnotesize{€/MWh} & & \\",
        r"\midrule",
    ]
    for tech, row in v.iterrows():
        tag = recovery_tag(r, tech)
        lines.append(
            rf"{RECOVERY_LABELS.get(tech, tech)} & {row['capacity_mw'] / 1000:.1f}"
            rf" & {row['full_load_hours']:,.0f} & {row['lcoe_eur_mwh']:.1f}"
            rf" & {row['capture_price_eur_mwh']:.1f} & {row['value_factor']:.2f}"
            rf" & \footnotesize{{{tag}}} \\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    (TABLES / "greenfield_value_table.tex").write_text("\n".join(lines), encoding="utf-8")


def values_greenfield(d):
    s = d["summary"]
    sweep = d["sweep"].set_index("carbon_price").sort_index()
    scr = d["screening"]
    tau_ref = s["reference_tax_eur_t"]
    ref = sweep.loc[tau_ref]
    zero = sweep.loc[0.0] if 0.0 in sweep.index else ref
    top = sweep.iloc[-1]
    switch = s["switch_price_eur_t"]
    # The first price on the grid at which the biomethane peaker is built,
    # and the last at which the fossil one still is.
    biogas_in = sweep.index[sweep["cap_ocgt_biogas_mw"] > 1.0]
    gas_out = sweep.index[sweep["cap_ocgt_mw"] > 1.0]
    macros = {
        "InvHours": f"{s['hours']}",
        "InvDiscountRatePct": f"{100 * s['discount_rate']:.0f}",
        "InvHorizon": f"{s['forward_horizon']}",
        "InvWeatherYear": f"{s.get('reference_weather_year', 2024)}",
        "InvReferenceTax": f"{tau_ref:.0f}",
        "InvTaxMin": f"{sweep.index.min():.0f}",
        "InvTaxMax": f"{sweep.index.max():.0f}",
        "InvTaxPoints": f"{len(sweep)}",
        "InvSwitchPrice": f"{switch:.0f}",
        "InvBiogasEntersAt": f"{biogas_in.min():.0f}" if len(biogas_in) else "--",
        "InvGasLastAt": f"{gas_out.max():.0f}" if len(gas_out) else "--",
        # Emissions along the sweep: Danish territorial and twelve-zone.
        "InvEmissionsZeroTaxMt": f"{zero['emissions_t'] / 1e6:.2f}",
        "InvEmissionsRefMt": f"{ref['emissions_t'] / 1e6:.2f}",
        "InvEmissionsTopMt": f"{top['emissions_t'] / 1e6:.2f}",
        "InvSystemEmissionsZeroTaxMt": f"{zero['emissions_total_t'] / 1e6:.0f}",
        "InvSystemEmissionsRefMt": f"{ref['emissions_total_t'] / 1e6:.0f}",
        "InvSystemEmissionsTopMt": f"{top['emissions_total_t'] / 1e6:.0f}",
        "InvDKCutRefPct": f"{100 * (1 - ref['emissions_t'] / zero['emissions_t']):.0f}",
        "InvSystemCutRefPct": f"{100 * (1 - ref['emissions_total_t'] / zero['emissions_total_t']):.0f}",
        # Fixed costs of the candidates, for the screening discussion.
        "InvOnshoreFixed": f"{scr.loc['wind_onshore', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        "InvOffshoreFixed": f"{scr.loc['wind_offshore', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        "InvSolarFixed": f"{scr.loc['solar_pv', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        "InvCCGTFixed": f"{scr.loc['ccgt', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        "InvOCGTFixed": f"{scr.loc['ocgt', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        "InvNuclearFixed": f"{scr.loc['nuclear', 'fixed_eur_mw_yr'] / 1e3:.0f}",
        # One decimal, so that the switching price the text derives from
        # these two, (biomethane - gas) / emission rate, comes out as printed.
        "InvBiogasMC": f"{scr.loc['ocgt_biogas', 'marginal_cost']:.1f}",
        "InvOCGTMC": f"{scr.loc['ocgt', 'marginal_cost']:.1f}",
        "InvOCGTEmissionRate": f"{scr.loc['ocgt', 'emission_rate']:.2f}",
        # The reference mix.
        "InvSolarCapRef": f"{ref['cap_solar_pv_mw'] / 1000:.1f}",
        "InvOnshoreCapRef": f"{ref['cap_wind_onshore_mw'] / 1000:.1f}",
        "InvOffshoreCapRef": f"{ref['cap_wind_offshore_mw'] / 1000:.1f}",
        "InvOCGTCapRef": f"{ref['cap_ocgt_mw'] / 1000:.1f}",
        "InvBiogasCapRef": f"{ref['cap_ocgt_biogas_mw'] / 1000:.1f}",
        "InvCCGTCapRef": f"{ref['cap_ccgt_mw'] / 1000:.1f}",
        "InvBatteryCapRef": f"{ref['cap_battery_mw'] / 1000:.1f}",
        "InvBatteryEightRef": f"{ref.get('cap_battery_8h_mw', 0.0) / 1000:.1f}",
        "InvBatteryFourRef": f"{ref.get('cap_battery_4h_mw', 0.0) / 1000:.1f}",
        "InvBatteryTwoRef": f"{ref.get('cap_battery_2h_mw', 0.0) / 1000:.1f}",
        "InvNuclearCapMax": f"{sweep['cap_nuclear_mw'].max():.0f}",
        "InvPeakerCapRef": f"{ref['cap_peaker_mw'] / 1000:.1f}",
        # The same at zero and at the top of the sweep.
        "InvSolarCapZeroTax": f"{zero['cap_solar_pv_mw'] / 1000:.1f}",
        "InvOffshoreCapZeroTax": f"{zero['cap_wind_offshore_mw'] / 1000:.1f}",
        "InvOnshoreCapZeroTax": f"{zero['cap_wind_onshore_mw'] / 1000:.1f}",
        "InvPeakerCapZeroTax": f"{zero['cap_peaker_mw'] / 1000:.1f}",
        "InvCCGTCapZeroTax": f"{zero['cap_ccgt_mw'] / 1000:.1f}",
        "InvBatteryCapZeroTax": f"{zero['cap_battery_mw'] / 1000:.1f}",
        "InvOffshoreCapTop": f"{top['cap_wind_offshore_mw'] / 1000:.1f}",
        "InvSolarCapTop": f"{top['cap_solar_pv_mw'] / 1000:.1f}",
        "InvBatteryCapTop": f"{top['cap_battery_mw'] / 1000:.1f}",
        "InvBiogasCapTop": f"{top['cap_ocgt_biogas_mw'] / 1000:.1f}",
        "InvOCGTCapTop": f"{top['cap_ocgt_mw'] / 1000:.1f}",
        "InvSolarPotentialGW": f"{sum(z['solar_pv'] for z in s['p_nom_max'].values()) / 1000:.1f}",
        "InvOnshorePotentialGW": f"{sum(z['wind_onshore'] for z in s['p_nom_max'].values()) / 1000:.1f}",
        "InvOffshorePotentialGW": f"{sum(z['wind_offshore'] for z in s['p_nom_max'].values()) / 1000:.1f}",
        # Bills and trade at the reference.
        "InvSystemCostRefBn": f"{ref['dk_system_cost'] / 1e9:.1f}",
        "InvObjectiveRefBn": f"{ref['system_cost'] / 1e9:.1f}",
        "InvRefTradeRevenueBn": f"{ref['dk_trade_revenue'] / 1e9:.2f}",
        "InvRefNetCostBn": f"{ref['dk_net_cost'] / 1e9:.2f}",
        "InvRefPriceDKOne": f"{ref['avg_price_dk1']:.0f}",
        "InvPriceDKOneZeroTax": f"{zero['avg_price_dk1']:.0f}",
        "InvPriceDKOneTop": f"{top['avg_price_dk1']:.0f}",
    }
    # How much of the reference bill is fixed: the annuity a lower discount
    # rate acts on, plus fixed upkeep (`capex_eur` is the annual fixed cost).
    breakdown = d.get("breakdown")
    if breakdown is not None:
        capex = float(breakdown["capex_eur"].sum())
        macros["InvFixedCostSharePct"] = (
            f"{100 * capex / (capex + float(breakdown['opex_eur'].sum())):.0f}")
    # Danish generation at the reference: the import share, which is what
    # a territorial budget can lean on.
    gen_cols = [c for c in sweep.columns if c.startswith("gen_")]
    if gen_cols and "dk_load_mwh" in sweep.columns:
        gen = float(ref[gen_cols].fillna(0.0).sum())
        macros |= {
            "InvDKGenerationTWh": f"{gen / 1e6:.1f}",
            "InvDKLoadTWh": f"{ref['dk_load_mwh'] / 1e6:.1f}",
            "InvDKNetExportPct": f"{100 * (gen / ref['dk_load_mwh'] - 1):.0f}",
            "InvDKGenerationZeroTaxTWh": f"{float(zero[gen_cols].fillna(0.0).sum()) / 1e6:.1f}",
        }
    # What the reference system's plants do with their year.
    duty = d.get("duty")
    if duty is not None:
        for tech, name in [("solar_pv", "Solar"), ("wind_offshore", "Offshore"),
                           ("wind_onshore", "Onshore"), ("ccgt", "CCGT"),
                           ("ocgt", "OCGT"), ("ocgt_biogas", "Biogas")]:
            if tech in duty.index:
                hours = duty.loc[tech, "full_load_hours"]
                if pd.notna(hours):
                    macros[f"Inv{name}HoursRef"] = f"{hours:,.0f}".replace(",", "{,}")
    if "snapshot_hours" in s:
        sh = s["snapshot_hours"]
        macros |= {
            "InvSnapshotMinHours": f"{sh['min']:.0f}",
            "InvSnapshotMedianHours": f"{sh['median']:.0f}",
            "InvSnapshotMaxHours": f"{sh['max']:.0f}",
        }
    # The time-aggregation check: the reference case solved once at full
    # hourly resolution.
    res = d.get("resolution")
    # Only a check written by the current pipeline (it records the carbon
    # price it was run at) is quoted; an older file is ignored, and the
    # macros print a question mark so the note still compiles while the
    # check is being re-run.
    macros |= {name: "?" for name in [
        "InvHoursSampled", "InvBatteryFullGW", "InvBatterySampledGW",
        "InvOffshoreFullGW", "InvOffshoreSampledGW", "InvNetCostFullBn",
        "InvNetCostSampledBn", "InvEmissionsFullMt", "InvEmissionsSampledMt",
        "InvBatteryFullTwoGW", "InvBatteryFullFourGW", "InvBatteryFullEightGW"]}
    if res is not None and "carbon_price" in res:
        macros |= {
            "InvHoursSampled": f"{res['hours_sampled']}",
            "InvBatteryFullGW": f"{res['battery_mw_full'] / 1e3:.1f}",
            "InvBatterySampledGW": f"{res['battery_mw_sampled'] / 1e3:.1f}",
            "InvOffshoreFullGW": f"{res['offshore_mw_full'] / 1e3:.1f}",
            "InvOffshoreSampledGW": f"{res['offshore_mw_sampled'] / 1e3:.1f}",
            "InvNetCostFullBn": f"{res['dk_net_cost_full'] / 1e9:.2f}",
            "InvNetCostSampledBn": f"{res['dk_net_cost_sampled'] / 1e9:.2f}",
            "InvEmissionsFullMt": f"{res['emissions_full_t'] / 1e6:.2f}",
            "InvEmissionsSampledMt": f"{res['emissions_sampled_t'] / 1e6:.2f}",
        }
        by_full = res.get("battery_by_duration_full", {})
        if by_full:
            macros |= {
                "InvBatteryFullTwoGW": f"{by_full.get('battery_2h', 0.0) / 1e3:.1f}",
                "InvBatteryFullFourGW": f"{by_full.get('battery_4h', 0.0) / 1e3:.1f}",
                "InvBatteryFullEightGW": f"{by_full.get('battery_8h', 0.0) / 1e3:.1f}",
            }
    # Flexible demand: the blocks, and what the reference solution sheds.
    shed_cols = [c for c in sweep.columns if c.startswith("shed_")]
    blocks = {c: (share, wtp) for c, share, wtp in s["demand_blocks"]}
    macros |= {
        "InvVoLLkEUR": f"{s['voll_eur_mwh'] / 1e3:.1f}",
        "InvFlexBlockSharePct": f"{100 * blocks['shed_flex'][0]:.0f}",
        "InvFlexBlockWTP": f"{blocks['shed_flex'][1]:,.0f}",
        "InvIndustryBlockSharePct": f"{100 * blocks['shed_industry'][0]:.0f}",
        "InvIndustryBlockWTP": f"{blocks['shed_industry'][1]:,.0f}",
    }
    if shed_cols and "dk_load_mwh" in sweep.columns:
        shed_ref = float(ref[shed_cols].fillna(0.0).sum())
        macros |= {
            "InvShedRefGWh": f"{shed_ref / 1e3:.1f}",
            "InvShedRefPct": f"{100 * shed_ref / ref['dk_load_mwh']:.2f}",
        }
    # The scenarios.
    scen = d.get("scenarios")
    if scen is not None:
        for name, key in [("autarky", "Autarky"), ("expensive gas", "ExpensiveGas"),
                          ("cheap capital", "CheapCapital"), ("Danish budget", "DKBudget")]:
            if name not in scen.index:
                continue
            row = scen.loc[name]
            macros |= {
                f"Inv{key}OffshoreGW": f"{row['cap_wind_offshore_mw'] / 1000:.1f}",
                f"Inv{key}OnshoreGW": f"{row['cap_wind_onshore_mw'] / 1000:.1f}",
                f"Inv{key}SolarGW": f"{row['cap_solar_pv_mw'] / 1000:.1f}",
                f"Inv{key}BatteryGW": f"{row['cap_battery_mw'] / 1000:.1f}",
                f"Inv{key}PeakerGW": f"{row['cap_peaker_mw'] / 1000:.1f}",
                f"Inv{key}BiogasGW": f"{row['cap_ocgt_biogas_mw'] / 1000:.1f}",
                f"Inv{key}CCGTGW": f"{row['cap_ccgt_mw'] / 1000:.1f}",
                f"Inv{key}CostBn": f"{row['dk_system_cost'] / 1e9:.1f}",
                f"Inv{key}NetCostBn": f"{row['dk_net_cost'] / 1e9:.2f}",
                f"Inv{key}PriceDKOne": f"{row['avg_price_dk1']:.0f}",
                f"Inv{key}EmissionsMt": f"{row['emissions_t'] / 1e6:.2f}",
            }
        if "cheap capital" in scen.index:
            # Net of trade, like the autarky comparison below.
            macros["InvCheapCapitalCostCutPct"] = (
                f"{100 * (1 - scen.loc['cheap capital', 'dk_net_cost'] / ref['dk_net_cost']):.0f}")
        if "autarky" in scen.index and shed_cols:
            shed_aut = float(scen.loc["autarky", shed_cols].fillna(0.0).sum())
            shed_ref = float(ref[shed_cols].fillna(0.0).sum())
            macros |= {
                "InvAutarkyShedTWh": f"{shed_aut / 1e6:.2f}",
                "InvAutarkyShedRatio": f"{shed_aut / max(shed_ref, 1.0):.0f}",
                "InvAutarkyNetCostPct":
                    f"{100 * (scen.loc['autarky', 'dk_net_cost'] / ref['dk_net_cost'] - 1):.0f}",
            }
        # The territorial budget: its dual, and the leakage against the
        # unpriced world it was set in.
        if "Danish budget" in scen.index and "no carbon price" in scen.index:
            dkb = scen.loc["Danish budget"]
            base = scen.loc["no carbon price"]
            dk_cut = base["emissions_t"] - dkb["emissions_t"]
            system_cut = base["emissions_total_t"] - dkb["emissions_total_t"]
            macros |= {
                "InvDKBudgetSigma": f"{dkb['co2_price']:.0f}",
                "InvDKBudgetPct": f"{100 * (1 - s['dk_budget_fraction']):.0f}",
                "InvDKBudgetBaseMt": f"{base['emissions_t'] / 1e6:.2f}",
                "InvDKBudgetMt": f"{dkb['emissions_t'] / 1e6:.2f}",
                "InvDKBudgetCutMt": f"{dk_cut / 1e6:.2f}",
                "InvDKBudgetSystemCutMt": f"{system_cut / 1e6:.2f}",
                "InvDKBudgetLeakagePct": f"{100 * (1 - system_cut / dk_cut):.0f}" if dk_cut > 0 else "--",
                "InvDKBudgetSystemBaseMt": f"{base['emissions_total_t'] / 1e6:.0f}",
                "InvNoTaxPriceDKOne": f"{base['avg_price_dk1']:.0f}",
            }
            # The common price that brings Danish emissions as low as the
            # budget does: the first point of the sweep at or below it.
            low_enough = sweep.index[sweep["emissions_t"] <= 1.001 * dkb["budget_t"]]
            macros["InvDKBudgetCommonTax"] = (
                f"{low_enough.min():.0f}" if len(low_enough) else "--")
            if "dk_load_mwh" in scen.columns:
                gen_b = float(dkb[gen_cols].fillna(0.0).sum()) if gen_cols and all(c in scen.columns for c in gen_cols) else None
                if gen_b is not None:
                    macros["InvDKBudgetNetImportPct"] = f"{100 * (1 - gen_b / dkb['dk_load_mwh']):.0f}"
    # Result 6 in numbers: rents against fixed cost, per candidate as the
    # figure shows it (recovery_by_tech), and zone by zone where the text
    # needs to say why a fleet earns more than its cost.
    r = d.get("cost_recovery")
    if r is not None:
        by_tech = recovery_by_tech(r)

        def ratio(tech, zone=None):
            """Rent over fixed cost, in per cent: in `zone` if one is named,
            otherwise as recovery_by_tech reports it."""
            if zone is None:
                return f"{100 * by_tech[tech]:.0f}" if tech in by_tech.index else "--"
            rows = r[(r["tech"] == tech) & (r["zone"] == zone)]
            return f"{100 * rows['rent_over_fixed'].iloc[0]:.0f}" if len(rows) else "--"
        macros |= {
            "InvRecoverySolarPct": ratio("solar_pv"),
            "InvRecoveryOnshorePct": ratio("wind_onshore"),
            "InvRecoveryOffshorePct": ratio("wind_offshore"),
            "InvRecoveryBiogasPct": ratio("ocgt_biogas"),
            "InvRecoveryOCGTPct": ratio("ocgt"),
            "InvRecoveryCCGTPct": ratio("ccgt"),
            "InvRecoveryNuclearPct": ratio("nuclear"),
            "InvRecoveryBatteryEightPct": ratio("battery_8h"),
            "InvRecoveryBatteryFourPct": ratio("battery_4h"),
            "InvRecoveryBatteryTwoPct": ratio("battery_2h"),
        }
        # The land rent, where a technology sits on its cap: zone by zone,
        # and capacity-weighted over the zones where it does.
        for tech, key in [("wind_onshore", "Onshore"), ("solar_pv", "Solar")]:
            capped = r[(r["tech"] == tech) & r["at_cap"]]
            for zone, zkey in [("DK1", "DKOne"), ("DK2", "DKTwo")]:
                macros[f"InvRecovery{key}{zkey}Pct"] = ratio(tech, zone)
                at = capped[capped["zone"] == zone]
                if len(at):
                    rent = float((at["rent_eur_mw_yr"] - at["fixed_eur_mw_yr"]).iloc[0])
                    macros[f"Inv{key}LandRent{zkey}"] = f"{rent / 1e3:.0f}"
            if len(capped):
                excess = (capped["rent_eur_mw_yr"] - capped["fixed_eur_mw_yr"]) * capped["capacity_mw"]
                macros[f"Inv{key}LandRent"] = f"{excess.sum() / capped['capacity_mw'].sum() / 1e3:.0f}"
    v = d.get("value_table")
    if v is not None:
        def vt(tech, col, fmt):
            return format(v.loc[tech, col], fmt) if tech in v.index else "--"
        macros |= {
            "InvBasePriceRef": f"{v['base_price_eur_mwh'].iloc[0]:.1f}",
            "InvSolarLCOE": vt("solar_pv", "lcoe_eur_mwh", ".1f"),
            "InvSolarCapture": vt("solar_pv", "capture_price_eur_mwh", ".1f"),
            "InvSolarVF": vt("solar_pv", "value_factor", ".2f"),
            "InvOffshoreLCOE": vt("wind_offshore", "lcoe_eur_mwh", ".1f"),
            "InvOffshoreCapture": vt("wind_offshore", "capture_price_eur_mwh", ".1f"),
            "InvOffshoreVF": vt("wind_offshore", "value_factor", ".2f"),
            "InvOnshoreLCOE": vt("wind_onshore", "lcoe_eur_mwh", ".1f"),
            "InvOnshoreCapture": vt("wind_onshore", "capture_price_eur_mwh", ".1f"),
            "InvOnshoreVF": vt("wind_onshore", "value_factor", ".2f"),
            "InvOCGTLCOE": vt("ocgt", "lcoe_eur_mwh", ".0f"),
            "InvOCGTCarbonCost": vt("ocgt", "carbon_cost_eur_mwh", ".0f"),
            "InvOCGTCapture": vt("ocgt", "capture_price_eur_mwh", ".0f"),
            "InvOCGTVF": vt("ocgt", "value_factor", ".1f"),
        }
    # How the peakers get paid, in the zone where they stand.
    sc = s.get("scarcity")
    if sc:
        macros["InvDKMaxPrice"] = f"{sc['dk_max_price']:,.0f}"
    if sc and sc.get("peaker_zone"):
        macros |= {
            "InvPeakerZone": sc["peaker_zone"],
            "InvPeakerRunningCost": f"{sc['peaker_running_cost']:.0f}",
            "InvPeakerTopHundredPct": f"{100 * sc['share_in_top_100_hours']:.0f}",
            "InvPeakerTopFiveHundredPct": f"{100 * sc['share_in_top_500_hours']:.0f}",
            "InvHoursAboveFlexBlock": f"{sc['hours_price_above_flex_block']}",
            "InvHoursAboveIndustryBlock": f"{sc['hours_price_above_industry_block']}",
            "InvHoursAtVoLL": f"{sc['hours_price_at_voll']}",
            "InvPeakerZoneMaxPrice": f"{sc['max_price_peaker_zone']:,.0f}",
        }
        # The scarce hours come in spells; their lengths set against the
        # longest battery on the menu. A summary written before
        # run_greenfield recorded them prints question marks.
        spells = {
            "InvScarcitySpells": ("scarcity_spells", "{:.0f}", 1),
            "InvScarcitySpellShortestHours": ("scarcity_spell_shortest_hours", "{:.0f}", 1),
            "InvScarcitySpellMedianHours": ("scarcity_spell_median_hours", "{:.0f}", 1),
            "InvScarcitySpellLongestHours": ("scarcity_spell_longest_hours", "{:.0f}", 1),
            "InvScarcityBeyondBatteryPct": (
                "scarcity_hours_in_spells_beyond_battery_share", "{:.0f}", 100),
        }
        macros |= {name: fmt.format(scale * sc[key]) if key in sc else "?"
                   for name, (key, fmt, scale) in spells.items()}
        b = d.get("price_bands")
        if b is not None and len(b):
            # The hours below the peakers' running cost, and the scarcity
            # hours: every band above the flexible block's willingness to pay.
            flex = {c: wtp for c, _, wtp in s["demand_blocks"]}["shed_flex"]
            idle = b[b["lower_eur_mwh"] == float("-inf")]
            top = b[b["lower_eur_mwh"] > flex]
            macros |= {
                "InvPeakerIdleHoursPct": f"{100 * idle['hours_share'].sum():.0f}",
                "InvPeakerScarcityThreshold": f"{top['lower_eur_mwh'].min():,.0f}",
                "InvPeakerScarcityHours": f"{int(top['hours'].sum())}",
                "InvPeakerScarcityHoursPct": f"{100 * top['hours_share'].sum():.2f}",
                "InvPeakerScarcityMarginPct": f"{100 * top['margin_share'].sum():.0f}",
            }
    _write_values("greenfield_values.tex", macros, "results/greenfield_summary.json")


# --------------------------------------------------------------------------
# Section 9 — uncertainty
# --------------------------------------------------------------------------

# The middle cost scenario is the very cost table sections 7 and 9 solve on,
# so the reference line of the variability figure is the reference system
# itself: the reference year of the weather sweep and the middle point of
# the cost sweep.
COSTS_REFERENCE_SCENARIO = "baseline"

# The outputs the variability figure sets side by side, each in its own unit:
# label, results column, divisor, unit. Onshore wind is left out because it
# sits at its potential in every run, which the text says.
VARIABILITY_PANELS = [
    ("solar", "cap_solar_pv_mw", 1e3, "GW"),
    ("offshore wind", "cap_wind_offshore_mw", 1e3, "GW"),
    ("batteries", "cap_battery_mw", 1e3, "GW"),
    ("gas turbines", "cap_peaker_mw", 1e3, "GW"),
    ("Danish bill", "dk_net_cost", 1e9, "bn€/yr"),
    ("Danish emissions", "emissions_t", 1e6, "Mt"),
]
COST_MARKERS = {"pessimistic": ("v", "pess."), "optimistic": ("^", "opt.")}


def fig_uncertainty_variability(weather, costs):
    """Figure (fig:uncertainty:variability): six outputs of the section 7
    model across the weather years, beside the same outputs across the cost
    scenarios.

    One small panel per output, each in its own unit, because gigawatts,
    billions of euros and megatonnes share no axis. Put on one axis as
    shares of the reference system, an output the reference holds little of
    (the turbines, the emissions) runs to several hundred per cent and
    flattens every other range. Each panel has two strips: a dot per weather
    year, spread a little in year order so that years with the same value
    stay countable, and a marker per cost scenario. The Danish bill is net
    of trade, the measure section 7 compares systems by."""
    w_mix, c_mix = weather["mix"], costs["mix"]
    fig, axes = plt.subplots(2, 3, figsize=(6.3, 4.3))
    for k, (ax, (name, col, scale, unit)) in enumerate(
            zip(axes.flat, VARIABILITY_PANELS)):
        w = w_mix[col] / scale
        c = c_mix[col] / scale
        top = max(w.max(), c.max())
        ax.axhline(c[COSTS_REFERENCE_SCENARIO], color="#888888", lw=0.8,
                   ls=(0, (4, 3)), zorder=1)
        # The weather years: the range, and a dot per year.
        xs = [-0.16 + 0.32 * i / max(len(w) - 1, 1) for i in range(len(w))]
        ax.plot([0, 0], [w.min(), w.max()], color=BLUE, lw=6, alpha=0.18,
                solid_capstyle="butt", zorder=2)
        ax.scatter(xs, w.to_numpy(), s=14, color=BLUE, alpha=0.85,
                   edgecolor="white", linewidth=0.4, zorder=3, clip_on=False)
        # The year at each end of the range, in a column left of the dots,
        # where one year alone holds it and the range is wide enough for the
        # two labels to stand apart. The text names the top year.
        if w.max() - w.min() > 0.12 * top:
            for year in (w.idxmax(), w.idxmin()):
                if (w == w[year]).sum() == 1:
                    ax.annotate(f"{year}", xy=(-0.2, w[year]), ha="right",
                                va="center", fontsize=6.5, color="#666666")
        # The cost scenarios: the range, and a marker per scenario.
        ax.plot([1, 1], [c.min(), c.max()], color=VERMILLION, lw=6,
                alpha=0.18, solid_capstyle="butt", zorder=2)
        for scenario, value in c.items():
            marker, label = COST_MARKERS.get(scenario, ("o", None))
            ax.scatter([1], [value], s=26, marker=marker, color=VERMILLION,
                       edgecolor="white", linewidth=0.4, zorder=3,
                       clip_on=False)
            if label:
                ax.annotate(label, xy=(1, value), xytext=(6, 0),
                            textcoords="offset points", va="center",
                            fontsize=7, color=VERMILLION)
        ax.set_ylim(0, top * 1.15 if top > 0 else 1.0)
        ax.set_xlim(-0.75, 1.6)
        ax.set_xticks([0, 1], ["weather\nyears", "cost\nscenarios"],
                      fontsize=7.5)
        ax.tick_params(axis="x", length=0)
        ax.grid(axis="y")
        ax.set_title(f"({'abcdef'[k]}) {name} ({unit})", loc="left",
                     fontsize=8.5, color=INK)
    handles = [
        plt.Line2D([], [], ls="none", marker="o", color=BLUE, ms=4.5,
                   label=f"one weather year, {w_mix.index.min()}–"
                         f"{w_mix.index.max()}"),
        plt.Line2D([], [], ls="none", marker="v", color=VERMILLION, ms=5,
                   label="pessimistic costs"),
        plt.Line2D([], [], ls="none", marker="^", color=VERMILLION, ms=5,
                   label="optimistic costs"),
        plt.Line2D([], [], color="#888888", lw=0.8, ls=(0, (4, 3)),
                   label="the reference system"),
    ]
    fig.legend(handles=handles, loc="outside lower center", ncol=4,
               frameon=False, fontsize=7.5)
    fig.savefig(FIGURES / "uncertainty_variability.pdf")
    plt.close(fig)


def spread_pct(series):
    """Max less min as a percentage of the mean, the definition run_weather
    and run_costs use for cost_spread_pct."""
    return 100.0 * (series.max() - series.min()) / series.mean()


def values_weather(d):
    s = d["summary"]
    mix = d["mix"]
    macros = {
        "WeatherYearsCount": f"{len(s['years'])}",
        "WeatherFirstYear": f"{s['years'][0]}",
        "WeatherReferenceYear": f"{s.get('reference_year', 2024)}",
        "WeatherLastYear": f"{s['years'][-1]}",
        # On the bill net of trade, the measure section 7 compares systems
        # by: the gross bill counts capacity built for export as a Danish
        # cost and leaves out what the exports earn.
        "WeatherNetCostSpreadPct": f"{spread_pct(mix['dk_net_cost']):.1f}",
        "WeatherSolarMinGW": f"{mix['cap_solar_pv_mw'].min() / 1000:.1f}",
        "WeatherSolarMaxGW": f"{mix['cap_solar_pv_mw'].max() / 1000:.1f}",
        "WeatherPeakerMaxGW": f"{mix['cap_peaker_mw'].max() / 1000:.1f}",
        "WeatherEmissionsMaxMt": f"{mix['emissions_t'].max() / 1e6:.2f}",
        # The years at the top of the turbines' and the emissions' ranges,
        # which the variability figure labels and the text names.
        "WeatherPeakerMaxYear": f"{mix['cap_peaker_mw'].idxmax()}",
        "WeatherEmissionsMaxYear": f"{mix['emissions_t'].idxmax()}",
    }
    _write_values("weather_values.tex", macros, "results/weather_summary.json")


def values_costs(d):
    s = d["summary"]
    mix = d["mix"]
    macros = {
        "CostHorizon": f"{s['horizon']}",
        # The trend the scenarios are built out of: technology-data's own
        # path from its near vintage to the horizon section 7 solves on,
        # scaled by CostTrendScalePct of it in each direction.
        "CostTrendFirstYear": f"{s['trend_base_year']}",
        "CostTrendLastYear": f"{s['horizon']}",
        "CostTrendScalePct": f"{100 * s['trend_scale']:.0f}",
        # Net of trade, as in section 7 and WeatherNetCostSpreadPct.
        "CostNetCostSpreadPct": f"{spread_pct(mix['dk_net_cost']):.1f}",
        "CostSolarMinGW": f"{mix['cap_solar_pv_mw'].min() / 1000:.1f}",
        "CostSolarMaxGW": f"{mix['cap_solar_pv_mw'].max() / 1000:.1f}",
    }
    # How far the scenarios move a machine's investment cost, as a share of
    # the projection: the same in both directions by construction, and very
    # different across machines, because the projected declines are.
    examples = s.get("scenario_examples", {})
    for tech, name in [("solar-utility", "Solar"), ("onwind", "Onshore")]:
        row = examples.get(tech)
        if row:
            change = row["pessimistic_eur_per_kw"] / row["baseline_eur_per_kw"] - 1
            macros[f"Cost{name}ChangePct"] = f"{100 * change:.0f}"
    _write_values("costs_values.tex", macros, "results/costs_summary.json")


# --------------------------------------------------------------------------
# Section 8 — the European expansion ladder
# --------------------------------------------------------------------------

# Section 7's palette plus what section 8 adds. Kept separate so the two
# sections' figures cannot drift: nothing here changes a colour section 7
# already uses.
LADDER_COLORS = dict(TECH_COLORS)
LADDER_COLORS |= {
    "smr": "#8C510A",
    "electrolyser": "#7B3294",
    "h2_turbine": "#C2A5CF",
}
LADDER_LABELS = dict(TECH_LABELS)
LADDER_LABELS |= {
    "smr": "reformer",
    "electrolyser": "electrolyser",
    "h2_turbine": "H$_2$ turbine",
}
# The order the scenarios are read in, and how a figure names them, as the
# section does. Vehicle-to-grid and hydrogen each add one ingredient to
# smart charging, so the order is not cosmetic.
RUNG_LABELS = {
    "basic": "baseline",
    "ev": "smart charging",
    "ev_v2g": "vehicle-to-grid",
    "ev_h2": "hydrogen",
}


# The rungs' colours, the same in every figure that compares them: the
# baseline grey, smart charging blue, vehicle-to-grid vermillion and the
# hydrogen scenario in the electrolyser's purple.
RUNG_COLORS = {"basic": "#7f7f7f", "ev": BLUE, "ev_v2g": VERMILLION,
               "ev_h2": LADDER_COLORS["electrolyser"]}


def _ladder_rungs(ladder):
    """The rungs present in the results, in the argument's order."""
    return [r for r in RUNG_LABELS if r in set(ladder["rung"])]


def _budget_axis(frame):
    """Constrained budget points, tightest last, with their labels as cuts:
    a budget of a quarter of the unconstrained emissions is a 75 % cut."""
    points = sorted(frame["budget_share"].dropna().unique(), reverse=True)
    return points, [f"$-{100 * (1 - p):.0f}\\%$" for p in points]


def fig_expansion_ladder(d):
    """Figure (fig:expansion:ladder): what each ingredient does to the
    carbon price and to the bill as the budget tightens, with the carbon
    price at which a gas plant is indifferent between natural gas and
    biomethane."""
    ladder = d["ladder"]
    rungs = _ladder_rungs(ladder)
    points, labels = _budget_axis(ladder)
    x = range(len(points))

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.1))
    for rung in rungs:
        sub = ladder[ladder["rung"] == rung].set_index("budget_share")
        sigma = [sub.loc[p, "co2_price_eur_t"] for p in points]
        cost = [sub.loc[p, "system_cost_eur"] / 1e9 for p in points]
        style = dict(color=RUNG_COLORS[rung], linewidth=1.6, marker="o",
                     markersize=3.5, label=RUNG_LABELS[rung])
        # The hydrogen rung is a different system on its own baseline, so
        # its line is not commensurable with the others. Dash it to say
        # that in the figure rather than only in the caption.
        if rung == "ev_h2":
            style |= dict(linestyle="--")
        axes[0].plot(list(x), sigma, **style)
        axes[1].plot(list(x), cost, **style)
    switch = d["summary"].get("switch_price_eur_t")
    if switch:
        axes[0].axhline(switch, color="#999999", linestyle=":", linewidth=1.0)
        axes[0].annotate("gas switches to biomethane", xy=(0, switch), xytext=(0, 3),
                         textcoords="offset points", fontsize=7, color=INK)

    # Panel titles as in every other two-panel figure: the caption reads
    # the panels as (a) and (b).
    for ax, ylabel, title in zip(axes,
                                 ["carbon tax τ (€/t)", "system cost (bn€ / year)"],
                                 ["(a) the carbon price", "(b) the annual system cost"]):
        ax.set_xticks(list(x), labels, fontsize=8)
        ax.set_xlabel("cut in CO$_2$ emissions")
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left", fontsize=9, color=INK)
        ax.grid(axis="y")
    axes[1].legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.savefig(FIGURES / "expansion_ladder.pdf")
    plt.close(fig)


# Where section 8's electricity comes from, bottom to top: the firm and
# fossil plants, the low-carbon fuels, then wind and solar. The few
# sources too small to see share a bar with their neighbour.
SOURCE_ORDER = ["nuclear", "hydro", "lignite", "coal", "gas", "biomethane",
                "hydrogen", "biomass", "wind_onshore", "wind_offshore", "solar"]
SOURCE_GROUP = {"oil": "coal", "waste": "biomass", "geothermal": "biomass"}
SOURCE_COLORS = {
    "nuclear": LADDER_COLORS["nuclear"], "hydro": "#332288",
    "lignite": "#7F4F24", "coal": "#4D4D4D", "gas": LADDER_COLORS["ccgt"],
    "biomethane": LADDER_COLORS["ocgt_biogas"],
    "hydrogen": LADDER_COLORS["h2_turbine"], "biomass": "#A6D854",
    "wind_onshore": LADDER_COLORS["wind_onshore"],
    "wind_offshore": LADDER_COLORS["wind_offshore"],
    "solar": LADDER_COLORS["solar_pv"],
}
SOURCE_LABELS = {
    "nuclear": "nuclear", "hydro": "hydro", "lignite": "lignite",
    "coal": "coal, oil", "gas": "natural gas", "biomethane": "biomethane",
    "hydrogen": "hydrogen", "biomass": "biomass, waste",
    "wind_onshore": "onshore wind", "wind_offshore": "offshore wind",
    "solar": "solar",
}
# What is built, in the order of the stack; the two gas turbines share the
# gas colour of the generation panel, so one colour means one fuel family.
# The hydrogen scenario's machines come last, so that the rest of the stack
# compares directly with the scenario it adds to; the reformers' capacity is
# hydrogen, everything else's electricity.
BUILT = [("solar_pv", "solar", ["solar_pv"]),
         ("wind_onshore", "onshore wind", ["wind_onshore"]),
         ("wind_offshore", "offshore wind", ["wind_offshore"]),
         ("battery", "battery", ["battery"]),
         ("ccgt", "gas turbines", ["ccgt", "ocgt"]),
         ("transmission_new", "interconnectors", ["transmission_new"]),
         ("electrolyser", "electrolysers", ["electrolyser"]),
         ("h2_turbine", "hydrogen turbines", ["h2_turbine"]),
         ("smr", "reformers", ["smr"])]
BUILT_COLORS = {**LADDER_COLORS, "transmission_new": "#AA4499"}
# The cars and the flexible demand block, in the figures that show them
# beside the plants: the cars in smart charging's blue, which no plant in
# those figures uses.
CARS_COLOR, DEMAND_COLOR = BLUE, "#CC6677"
# What sets the price, as the prices figures group it (run_expansion.py,
# SETTER_GROUP), in the order the bars stack: the setters of the cheap hours
# first, the plants of the dear ones last.
SETTER_STYLE = [
    ("wind_solar", "wind, solar", SOURCE_COLORS["solar"]),
    ("hydro", "hydro", SOURCE_COLORS["hydro"]),
    ("battery", "batteries", BUILT_COLORS["battery"]),
    ("cars", "cars", CARS_COLOR),
    ("electrolyser", "electrolysers", LADDER_COLORS["electrolyser"]),
    ("nuclear", "nuclear", SOURCE_COLORS["nuclear"]),
    ("biomass", "biomass", SOURCE_COLORS["biomass"]),
    ("coal", "coal", SOURCE_COLORS["coal"]),
    ("gas", "gas plants", SOURCE_COLORS["gas"]),
    ("demand", "flexible demand", DEMAND_COLOR),
    ("unattributed", "not attributed", "#DDDDDD"),
]
# What covers the scarcest hours, as the margins figures group it
# (run_expansion.py, scarce_hours()), in the order the bars stack: the firm
# plants, the fossil ones, then the margins the last quarter of the cut is
# about.
COVER_STYLE = [
    ("nuclear", "nuclear", SOURCE_COLORS["nuclear"]),
    ("hydro", "hydro", SOURCE_COLORS["hydro"]),
    ("biomass", "biomass", SOURCE_COLORS["biomass"]),
    ("coal", "coal", SOURCE_COLORS["coal"]),
    ("gas", "natural gas", SOURCE_COLORS["gas"]),
    ("biomethane", "biomethane", SOURCE_COLORS["biomethane"]),
    ("hydrogen", "hydrogen", SOURCE_COLORS["hydrogen"]),
    ("battery", "batteries", BUILT_COLORS["battery"]),
    ("cars", "cars", CARS_COLOR),
    ("demand", "flexible demand", DEMAND_COLOR),
]


def _figure_budgets(e):
    """The figures' three budget points, no budget first, with their labels
    as cuts and their keys as the tables write them."""
    s = e["summary"]
    points = [None, s["mid_fraction"], s["reference_fraction"]]
    labels = ["no budget"] + [f"$-{100 * (1 - p):.0f}\\%$" for p in points[1:]]
    keys = ["none"] + [str(p) for p in points[1:]]
    return points, keys, labels


def _ladder_at(e, rung):
    """One rung's ladder rows, indexed by budget key."""
    ladder = e["ladder"]
    frame = ladder[ladder["rung"] == rung].copy()
    frame["key"] = frame["budget_fraction"].astype(str)
    return frame.set_index("key")


def _system_figure(e, cases, name, widths=(1.25, 1.1, 0.75)):
    """Three panels for a set of cases, as (rung, budget key, tick label):
    (a) where the electricity comes from, existing plants solid and new ones
    hatched, (b) what is built, with tau above each bar, and (c) what the
    year costs. Scenario names need a wider cost panel than budgets do."""
    import numpy as np
    from matplotlib.patches import Patch
    gen = e["generation"].copy()
    gen["group"] = gen["source"].map(lambda s: SOURCE_GROUP.get(s, s))
    rows = pd.DataFrame([_ladder_at(e, rung).loc[key] for rung, key, _ in cases])
    xs = np.arange(len(cases))

    fig, axes = plt.subplots(1, 3, figsize=(6.4, 3.7),
                             gridspec_kw={"width_ratios": list(widths)})
    ax = axes[0]
    bottom = np.zeros(len(cases))
    handles = []
    for source in SOURCE_ORDER:
        drawn = False
        for vintage, hatch in [("existing", None), ("new", "////")]:
            pick = gen[(gen["group"] == source) & (gen["vintage"] == vintage)]
            twh = np.array([_case_rows(pick, rung, key)["mwh"].sum()
                            for rung, key, _ in cases]) / 1e6
            if twh.max() < 0.5:
                continue
            ax.bar(xs, twh, bottom=bottom, width=0.62, color=SOURCE_COLORS[source],
                   edgecolor="white", linewidth=0.6, hatch=hatch)
            bottom += twh
            drawn = True
        if drawn:
            handles.append(Patch(facecolor=SOURCE_COLORS[source], label=SOURCE_LABELS[source]))
    ax.set_ylabel("generation (TWh / year)")
    ax.set_title("(a) where the power comes from", loc="left", fontsize=9, color=INK)

    ax = axes[1]
    bottom = np.zeros(len(cases))
    for key, label, techs in BUILT:
        cols = [f"cap_{t}_mw" for t in techs if f"cap_{t}_mw" in rows.columns]
        gw = rows[cols].astype(float).fillna(0.0).sum(axis=1).to_numpy() / 1e3
        if gw.max() < 0.05:
            continue
        ax.bar(xs, gw, bottom=bottom, width=0.62, color=BUILT_COLORS[key],
               edgecolor="white", linewidth=0.6)
        bottom += gw
        if key not in ("solar_pv", "wind_onshore", "wind_offshore"):
            handles.append(Patch(facecolor=BUILT_COLORS[key], label=label))
    for i, tau in enumerate(rows["co2_price_eur_t"].astype(float)):
        if pd.notna(tau):
            ax.annotate(f"τ = {tau:.0f}", xy=(i, bottom[i]), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=7.5, color=INK)
    ax.set_ylim(0, bottom.max() * 1.12)
    ax.set_ylabel("new capacity (GW)")
    ax.set_title("(b) what is built", loc="left", fontsize=9, color=INK)

    ax = axes[2]
    capital = rows["capital_cost_eur"].astype(float).to_numpy() / 1e9
    running = rows["operating_cost_eur"].astype(float).to_numpy() / 1e9
    ax.bar(xs, capital, width=0.62, color="#7f7f7f", edgecolor="white", label="capital")
    ax.bar(xs, running, bottom=capital, width=0.62, color="#c7c7c7", edgecolor="white",
           label="operating")
    ax.set_ylabel("system cost (bn€ / year)")
    ax.set_title("(c) what it costs", loc="left", fontsize=9, color=INK)
    # The key goes above the shorter of the two outer bars.
    total = capital + running
    ax.legend(frameon=False, fontsize=7,
              loc="upper left" if total[0] <= total[-1] else "upper right")
    for ax in axes:
        ax.set_xticks(xs, [label for _, _, label in cases], fontsize=8)
        ax.grid(axis="y")
    handles.append(Patch(facecolor="white", edgecolor="#666666", hatch="////",
                         label="new plant"))
    fig.legend(handles=handles, frameon=False, fontsize=7, ncol=5,
               loc="outside lower center")
    fig.savefig(FIGURES / name)
    plt.close(fig)


def fig_expansion_baseline(d):
    """Figure (fig:expansion:baseline): the baseline at no budget and at the
    two budgets the section reads, (a) where its electricity comes from,
    (b) what it builds and (c) what the year costs."""
    _, keys, labels = _figure_budgets(d)
    cases = [("basic", key, label) for key, label in zip(keys, ["none"] + labels[1:])]
    _system_figure(d, cases, "expansion_baseline.pdf")


# The top of the price-duration panels' axis, EUR/MWh; the scarcity hours
# above it would flatten everything else.
PRICES_CUTOFF = 350
# Two-line names for the scenarios where a bar's tick label has little room.
SHORT_LABELS = {"no budget": "no\nbudget", "smart charging": "smart\ncharging",
                "vehicle-to-grid": "vehicle-\nto-grid"}


def _case_rows(frame, rung, key):
    """One case's rows of a figure table, by scenario and budget key."""
    return frame[(frame["rung"] == rung) & (frame["budget_fraction"].astype(str) == key)]


def _section_cases(e, section):
    """The cases a section's prices and margins figures compare, as (rung,
    budget key, label, colour): the baseline at the figures' three budgets
    in section 8.2, and each scenario beside the one it adds to at the
    reference budget in sections 8.3 and 8.4."""
    _, keys, labels = _figure_budgets(e)
    ref = keys[-1]
    if section == "baseline":
        return [("basic", key, label, color) for key, label, color
                in zip(keys, ["no budget"] + labels[1:], ["#9e9e9e", BLUE, VERMILLION])]
    rungs = ["basic", "ev", "ev_v2g"] if section == "ev" else ["ev", "ev_h2"]
    return [(rung, ref, RUNG_LABELS[rung], RUNG_COLORS[rung]) for rung in rungs]


def _prices_figure(e, cases, name):
    """Two panels for a set of cases: (a) the system's price duration curve,
    the zonal prices weighted by demand, and (b) what sets the price, as
    shares of the year's demand (run_expansion.py, system_setters())."""
    import numpy as np
    from matplotlib.patches import Patch
    duration, setters = e["price_duration"], e["price_setters"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.3),
                             gridspec_kw={"width_ratios": [1.3, 1.0]})
    ax = axes[0]
    share = 100 * (np.arange(len(duration)) + 0.5) / len(duration)
    peak = 0.0
    for rung, key, label, color in cases:
        tau = _ladder_at(e, rung).at[key, "co2_price_eur_t"]
        series = duration[f"{rung}|{key}"]
        ax.plot(share, series, color=color, linewidth=1.5,
                label=label + ("" if pd.isna(tau) else f" (τ = {tau:.0f} €/t)"))
        peak = max(peak, float(series.max()))
    if peak > PRICES_CUTOFF:
        ax.annotate(f"peaks reach {peak:,.0f} €/MWh (cut off)", xy=(99, PRICES_CUTOFF - 6),
                    ha="right", va="top", fontsize=7, color=INK)
    ax.set_ylim(0, PRICES_CUTOFF)
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("system price (€/MWh)")
    ax.set_title("(a) the price duration curve", loc="left", fontsize=9, color=INK)
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=7, loc="upper right", bbox_to_anchor=(1.0, 0.92))

    ax = axes[1]
    ys = np.arange(len(cases))[::-1]
    present = set()
    for y, (rung, key, _, _) in zip(ys, cases):
        sub = _case_rows(setters, rung, key).set_index("setter")["share"]
        left = 0.0
        for group, _, color in SETTER_STYLE:
            value = 100 * float(sub.get(group, 0.0))
            if value < 0.05:
                continue
            ax.barh(y, value, left=left, height=0.62, color=color,
                    edgecolor="white", linewidth=0.5)
            left += value
            present.add(group)
    ax.set_yticks(ys, [SHORT_LABELS.get(c[2], c[2]) for c in cases], fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of demand (%)")
    ax.set_title("(b) what sets the price", loc="left", fontsize=9, color=INK)
    handles = [Patch(facecolor=color, label=label)
               for group, label, color in SETTER_STYLE if group in present]
    fig.legend(handles=handles, frameon=False, fontsize=7, ncol=6,
               loc="outside lower center")
    fig.savefig(FIGURES / name)
    plt.close(fig)


def _margins_figure(e, cases, name):
    """Two panels for a set of cases: (a) what covers the tenth of the year
    with the highest residual demand, as shares of what was delivered in it
    (run_expansion.py, scarce_hours()), and (b) what one more MW of storage
    of each duration would earn against its annual cost, in the zone where
    it earns the most (marginal_storage())."""
    import numpy as np
    from matplotlib.patches import Patch
    scarce, storage = e["scarce_hours"], e["marginal_storage"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4),
                             gridspec_kw={"width_ratios": [0.9, 1.3]})
    ax = axes[0]
    xs = np.arange(len(cases))
    bottom = np.zeros(len(cases))
    present = set()
    shares = [_case_rows(scarce, rung, key).set_index("source")["share"]
              for rung, key, _, _ in cases]
    for group, _, color in COVER_STYLE:
        values = np.array([100 * float(s.get(group, 0.0)) for s in shares])
        if values.max() < 0.05:
            continue
        ax.bar(xs, values, bottom=bottom, width=0.62, color=color,
               edgecolor="white", linewidth=0.5)
        bottom += values
        present.add(group)
    ax.set_xticks(xs, [SHORT_LABELS.get(c[2], c[2]) for c in cases], fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("share of what is delivered (%)")
    ax.set_title("(a) the scarcest tenth of the year", loc="left", fontsize=9, color=INK)

    ax = axes[1]
    for rung, key, label, color in cases:
        sub = _case_rows(storage, rung, key)
        best = (sub["revenue_eur_mw"] / sub["cost_eur_mw"]).groupby(sub["hours"]).max()
        ax.plot(best.index, best.to_numpy(), color=color, linewidth=1.5, marker="o",
                markersize=3, label=label)
    ax.axhline(1.0, color="#999999", linestyle=":", linewidth=1.0)
    ax.annotate("revenue covers the cost", xy=(700, 1.0), xytext=(0, 3),
                textcoords="offset points", ha="right", fontsize=7, color=INK)
    ax.set_xscale("log")
    ax.set_xticks([8, 24, 168, 720], ["8 hours", "1 day", "1 week", "1 month"], fontsize=8)
    ax.minorticks_off()
    ax.set_ylim(0, 1.12)
    ax.set_xlabel("duration of the storage facility")
    ax.set_ylabel("revenue / annual cost")
    ax.set_title("(b) one more MW of storage", loc="left", fontsize=9, color=INK)
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=7, loc="center right")
    handles = [Patch(facecolor=color, label=label)
               for group, label, color in COVER_STYLE if group in present]
    fig.legend(handles=handles, frameon=False, fontsize=7, ncol=5,
               loc="outside lower center")
    fig.savefig(FIGURES / name)
    plt.close(fig)


def fig_expansion_prices(d):
    """Figure (fig:expansion:prices): the baseline's system price at the
    figures' three budgets, and what sets it."""
    _prices_figure(d, _section_cases(d, "baseline"), "expansion_prices.pdf")


def fig_expansion_margins(d):
    """Figure (fig:expansion:margins): the baseline's margins at the
    figures' three budgets."""
    _margins_figure(d, _section_cases(d, "baseline"), "expansion_margins.pdf")


def _section_system_cases(e, section):
    """A section's cases as _system_figure() takes them, with two-line tick
    labels where the name is long."""
    return [(rung, key, SHORT_LABELS.get(label, label))
            for rung, key, label, _ in _section_cases(e, section)]


# The panel widths of the scenario figures: three names under the cost
# panel's bars need about a third more room than three budgets.
SCENARIO_WIDTHS = (1.1, 1.0, 1.0)


def fig_expansion_ev_system(d):
    """Figure (fig:expansion:ev-system): the cars' two scenarios beside the
    baseline at the reference budget, as fig:expansion:baseline reads the
    baseline."""
    _system_figure(d, _section_system_cases(d, "ev"), "expansion_ev_system.pdf",
                   widths=SCENARIO_WIDTHS)


def fig_expansion_hydrogen_system(d):
    """Figure (fig:expansion:hydrogen-system): the hydrogen scenario beside
    smart charging, the scenario it adds to, at the reference budget."""
    _system_figure(d, _section_system_cases(d, "hydrogen"),
                   "expansion_hydrogen_system.pdf", widths=SCENARIO_WIDTHS)


def fig_expansion_ev_prices(d):
    """Figure (fig:expansion:ev-prices): the cars' two scenarios beside the
    baseline at the reference budget, as figure fig:expansion:prices reads
    the baseline."""
    _prices_figure(d, _section_cases(d, "ev"), "expansion_ev_prices.pdf")


def fig_expansion_ev_margins(d):
    """Figure (fig:expansion:ev-margins): the cars' two scenarios beside the
    baseline at the reference budget, as fig:expansion:margins reads the
    baseline."""
    _margins_figure(d, _section_cases(d, "ev"), "expansion_ev_margins.pdf")


def fig_expansion_hydrogen_prices(d):
    """Figure (fig:expansion:hydrogen-prices): the hydrogen scenario beside
    smart charging, the scenario it adds to, at the reference budget."""
    _prices_figure(d, _section_cases(d, "hydrogen"), "expansion_hydrogen_prices.pdf")


def fig_expansion_hydrogen_margins(d):
    """Figure (fig:expansion:hydrogen-margins): the hydrogen scenario beside
    smart charging at the reference budget."""
    _margins_figure(d, _section_cases(d, "hydrogen"), "expansion_hydrogen_margins.pdf")


H2_ROUTES = [("reformed_gas", "reformed, natural gas", LADDER_COLORS["smr"], None),
             ("reformed_biomethane", "reformed, biomethane", LADDER_COLORS["smr"], "////"),
             ("imported", "imported", "#CC79A7", None),
             ("electrolysed", "electrolysed", LADDER_COLORS["electrolyser"], None)]


def fig_expansion_hydrogen(d):
    """Figure (fig:expansion:hydrogen): (a) where the hydrogen comes from at
    the figures' three budgets, with tau above each bar; (b) the whole
    system at the reference budget, month by month."""
    import numpy as np
    _, keys, labels = _figure_budgets(d)
    row = _ladder_at(d, "ev_h2")
    smr = row.loc[keys, "h2_from_smr_mwh"].to_numpy()
    bio = row.loc[keys, "h2_from_smr_biomethane_mwh"].to_numpy()
    routes = {"reformed_gas": smr - bio, "reformed_biomethane": bio,
              "imported": row.loc[keys, "h2_imported_mwh"].to_numpy(),
              "electrolysed": row.loc[keys, "h2_from_electrolysis_mwh"].to_numpy()}
    months = d["hydrogen_months"]
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.5),
                             gridspec_kw={"width_ratios": [0.9, 1.3]})
    xs = np.arange(len(keys))
    bottom = np.zeros(len(keys))
    for key, label, color, hatch in H2_ROUTES:
        twh = routes[key] / 1e6
        axes[0].bar(xs, twh, bottom=bottom, width=0.62, color=color, hatch=hatch,
                    edgecolor="white", linewidth=0.6, label=label)
        bottom += twh
    for i, key in enumerate(keys):
        sigma = row.at[key, "co2_price_eur_t"]
        if pd.notna(sigma):
            axes[0].annotate(f"τ = {sigma:.0f}", xy=(i, bottom[i]), xytext=(0, 3),
                             textcoords="offset points", ha="center", fontsize=7.5,
                             color=INK)
    axes[0].set_xticks(xs, ["none"] + labels[1:], fontsize=8)
    axes[0].set_ylim(0, bottom.max() * 1.12)
    axes[0].set_ylabel("hydrogen supplied (TWh / year)")
    axes[0].set_title("(a) by route", loc="left", fontsize=9, color=INK)
    mx = np.arange(len(months))
    bottom = np.zeros(len(months))
    for key, label, color, hatch in H2_ROUTES:
        twh = months[f"{key}_mwh"].to_numpy() / 1e6
        if twh.max() < 0.05:
            continue
        axes[1].bar(mx, twh, bottom=bottom, width=0.75, color=color, hatch=hatch,
                    edgecolor="white", linewidth=0.6)
        bottom += twh
    axes[1].set_xticks(mx, ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    axes[1].set_ylabel("hydrogen supplied (TWh / month)")
    axes[1].set_title(f"(b) at {labels[-1]}, by month", loc="left", fontsize=9,
                      color=INK)
    for ax in axes:
        ax.grid(axis="y")
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=7, ncol=4,
               loc="outside lower center")
    fig.savefig(FIGURES / "expansion_hydrogen.pdf")
    plt.close(fig)


# A system price below this is "near zero" in the text, EUR/MWh: the hours
# when wind and solar are curtailed.
NEAR_ZERO_PRICE = 5


def _expansion_figure_values(e):
    """What the section quotes about its prices and margins figures, read
    off their tables, and the numbers of the ladder the text reads beside
    them. Results older than the tables lack them, and so does this. The
    cases are named as the figures pair them: the baseline without a budget
    (NoCap) and at the reference budget (Ref), and each scenario at the
    reference budget (EVRef, VTwoGRef, HTwoRef)."""
    s, ladder = e["summary"], e["ladder"]
    ref, mid = s["reference_fraction"], s["mid_fraction"]
    cases = [("basic", "none", "NoCap"), ("basic", str(ref), "Ref"),
             ("ev", str(ref), "EVRef"), ("ev_v2g", str(ref), "VTwoGRef"),
             ("ev_h2", str(ref), "HTwoRef")]
    macros = {"ExpNearZeroPrice": f"{NEAR_ZERO_PRICE}"}

    def count(x):
        return f"{x:,.0f}".replace(",", "{,}")

    duration = e.get("price_duration")
    dear = s.get("flex_block_wtp_eur_mwh")
    if duration is not None and dear is not None:
        for rung, key, case in cases:
            p = duration[f"{rung}|{key}"]
            macros |= {f"ExpPriceMean{case}": f"{p.mean():.0f}",
                       f"ExpHoursFree{case}": count((p < NEAR_ZERO_PRICE).sum()),
                       f"ExpHoursDear{case}": count((p > dear).sum())}

    def shares(frame, column, rung, key):
        sub = _case_rows(frame, rung, key).set_index(column)["share"]
        return lambda *groups: f"{100 * float(sum(sub.get(g, 0.0) for g in groups)):.0f}"

    setters = e.get("price_setters")
    if setters is not None:
        for rung, key, case in cases:
            pct = shares(setters, "setter", rung, key)
            macros |= {f"ExpSetterPlants{case}Pct": pct("gas", "coal", "biomass", "nuclear"),
                       f"ExpSetterGas{case}Pct": pct("gas"),
                       f"ExpSetterStorage{case}Pct": pct("battery", "cars", "hydro"),
                       f"ExpSetterBattery{case}Pct": pct("battery"),
                       f"ExpSetterCars{case}Pct": pct("cars"),
                       f"ExpSetterElectrolyser{case}Pct": pct("electrolyser")}
    scarce = e.get("scarce_hours")
    if scarce is not None:
        for rung, key, case in cases:
            pct = shares(scarce, "source", rung, key)
            macros |= {f"ExpScarceFossil{case}Pct": pct("gas", "coal"),
                       f"ExpScarceHydro{case}Pct": pct("hydro"),
                       f"ExpScarceBiomethane{case}Pct": pct("biomethane"),
                       f"ExpScarceBattery{case}Pct": pct("battery"),
                       f"ExpScarceCars{case}Pct": pct("cars"),
                       f"ExpScarceDemand{case}Pct": pct("demand")}
    storage = e.get("marginal_storage")
    if storage is not None:
        for rung, key, case in cases:
            sub = _case_rows(storage, rung, key).assign(
                ratio=lambda f: f["revenue_eur_mw"] / f["cost_eur_mw"])
            best = sub.loc[sub.groupby("hours")["ratio"].idxmax()].set_index("hours")
            for hours, name in [(8, "Eight"), (24, "Day"), (168, "Week"), (720, "Month")]:
                if hours in best.index:
                    macros[f"ExpStorage{name}{case}Pct"] = f"{100 * best.at[hours, 'ratio']:.0f}"
            if case == "Ref" and 168 in best.index:
                # What a week-long facility earns per MWh of its energy
                # capacity, against what a MWh of battery capacity costs: the
                # cost line's two parts, from the costs of two durations.
                energy = ((best["cost_eur_mw"].iloc[-1] - best["cost_eur_mw"].iloc[0])
                          / (best.index[-1] - best.index[0]))
                power = best["cost_eur_mw"].iloc[0] - energy * best.index[0]
                macros |= {
                    "ExpStorageWeekCycles": f"{best.at[168, 'cycles']:.0f}",
                    "ExpStorageWeekEnergyPct":
                        f"{100 * (best.at[168, 'revenue_eur_mw'] - power) / 168 / energy:.0f}",
                }

    # The ladder's deep end beside the figures: the first budget point past
    # the middle one, where the flexible demand block starts to give way.
    rows = ladder.dropna(subset=["budget_share"])
    at = {p: rows[rows["budget_share"] == p].set_index("rung")
          for p in rows["budget_share"].unique()}
    deeper = [p for p in at if ref < p < mid]
    if deeper:
        deep = max(deeper)
        macros["ExpDeepCutPct"] = f"{100 * (1 - deep):.0f}"
        for rung, name in [("basic", "Basic"), ("ev", "EV"), ("ev_v2g", "VTwoG")]:
            if rung in at[deep].index:
                macros[f"ExpSigmaDeep{name}"] = f"{at[deep].loc[rung, 'co2_price_eur_t']:.0f}"
                if "shed_flex_hours" in rows.columns:
                    macros[f"ExpFlexHoursDeep{name}"] = count(
                        round(at[deep].loc[rung, "shed_flex_hours"], -2))
    if "shed_flex_hours" in rows.columns:
        basic = rows[rows["rung"] == "basic"].set_index("budget_share")
        macros |= {
            "ExpFlexHoursMid": count(round(basic.at[mid, "shed_flex_hours"], -2)),
            "ExpFlexHoursRef": count(round(basic.at[ref, "shed_flex_hours"], -2)),
            "ExpFlexTWhRef": f"{basic.at[ref, 'shed_flex_mwh'] / 1e6:.0f}",
        }
        for rung, name in [("basic", ""), ("ev", "EV"), ("ev_v2g", "VTwoG"), ("ev_h2", "HTwo")]:
            if rung in at[ref].index:
                macros[f"ExpCurtailed{name}Pct"] = (
                    f"{100 * at[ref].loc[rung, 'curtailed_share']:.0f}")
    bio = at[ref]["biomethane_total_mwh"]
    for rung, name in [("ev", "EV"), ("ev_v2g", "VTwoG")]:
        if rung in bio.index and bio.get("basic", 0.0) > 0:
            macros[f"ExpBiomethaneSaved{name}Pct"] = f"{100 * (1 - bio[rung] / bio['basic']):.0f}"
    return macros


def values_expansion(d):
    ladder = d["ladder"]
    s = d["summary"]
    reference = s["reference_fraction"]
    at_ref = ladder[ladder["budget_share"] == reference].set_index("rung")
    basic = at_ref.loc["basic"]

    def gw(rung, column):
        if rung not in at_ref.index or column not in at_ref.columns:
            return 0.0
        return float(at_ref.loc[rung, column] or 0.0) / 1000.0

    macros = {
        "ExpHours": f"{s['hours']}",
        "ExpZones": f"{len(d['zones'])}",
        "ExpUnconstrainedMt":
            f"{s['unconstrained_emissions_t']['basic'] / 1e6:.0f}",
        "ExpUnconstrainedHTwoMt":
            f"{s['unconstrained_emissions_t']['ev_h2'] / 1e6:.0f}",
        "ExpReferenceCutPct": f"{100 * (1 - reference):.0f}",
        "ExpSigmaBasic": f"{basic['co2_price_eur_t']:.0f}",
        "ExpCostBasicBn": f"{basic['system_cost_eur'] / 1e9:.1f}",
        "ExpBatteryBasicGW": f"{gw('basic', 'cap_battery_mw'):.1f}",
        "ExpBiomethaneBasicGW": f"{gw('basic', 'cap_ocgt_biogas_mw'):.1f}",
        "ExpHorizon": f"{s['forward_horizon']}",
        "ExpBiomethanePotentialTWh":
            f"{s['biomethane_potential_twh']:.0f}",
        "ExpCavernZones": ", ".join(s.get("cavern_zones", [])),
        # Unconstrained emissions of the EV rung. It shares the basic rung's
        # BUDGET (they are the same system, so their carbon prices compare)
        # but not its unconstrained level, and the section says so.
        "ExpUnconstrainedEVMt":
            f"{s['unconstrained_emissions_t']['ev'] / 1e6:.0f}",
        # Transmission is a decision in every rung, so how much of what is
        # offered actually gets bought is a result.
        "ExpGridOfferedGW": f"{basic['grid_offered_mw'] / 1000:.0f}",
        "ExpGridBuiltGW": f"{basic['grid_built_mw'] / 1000:.1f}",
        # The shadow price on the biomethane ceiling. It is zero, which is
        # the point: this result is not a biomethane-constrained one, and
        # the section would have to say so if it were.
        "ExpBiomethaneShadow":
            f"{abs(float(basic.get('biomethane_shadow_eur_mwh', 0.0) or 0.0)):.0f}",
    }
    # What the unconstrained system builds, for the "carbon policy is not
    # what makes renewables enter" comparison section 7 also makes.
    nocap = ladder[ladder["budget_share"].isna()].set_index("rung")
    if "basic" in nocap.index:
        macros |= {
            "ExpBatteryNoCapGW":
                f"{nocap.loc['basic', 'cap_battery_mw'] / 1000:.1f}",
            "ExpSolarNoCapGW":
                f"{nocap.loc['basic', 'cap_solar_pv_mw'] / 1000:.0f}",
        }
    if "ev_h2" in nocap.index:
        macros["ExpSMRNoCapGW"] = f"{nocap.loc['ev_h2', 'cap_smr_mw'] / 1000:.1f}"

    # The mid-budget point, where the section's comparison with section 7's
    # carbon price lives. Stage 2 names it; results written before it did
    # fall back to the first budget point above the reference.
    mids = sorted(p for p in ladder["budget_share"].dropna().unique()
                  if p > reference)
    if s.get("mid_fraction") in set(ladder["budget_share"].dropna()):
        mids = [s["mid_fraction"]]
    if mids:
        mid = mids[0]
        at_mid = ladder[ladder["budget_share"] == mid].set_index("rung")
        macros |= {
            "ExpMidCutPct": f"{100 * (1 - mid):.0f}",
            "ExpSigmaMidBasic": f"{at_mid.loc['basic', 'co2_price_eur_t']:.0f}",
            "ExpCostMidBasicBn":
                f"{at_mid.loc['basic', 'system_cost_eur'] / 1e9:.1f}",
        }
        if "ev" in at_mid.index:
            macros |= {
                "ExpSigmaMidEV": f"{at_mid.loc['ev', 'co2_price_eur_t']:.0f}",
                "ExpCostMidEVBn":
                    f"{at_mid.loc['ev', 'system_cost_eur'] / 1e9:.1f}",
                "ExpBatteryMidBasicGW":
                    f"{at_mid.loc['basic', 'cap_battery_mw'] / 1000:.1f}",
                "ExpBatteryMidEVGW":
                    f"{at_mid.loc['ev', 'cap_battery_mw'] / 1000:.1f}",
                "ExpBatteryMidDisplacedPct": (
                    f"{100 * (1 - at_mid.loc['ev', 'cap_battery_mw'] / at_mid.loc['basic', 'cap_battery_mw']):.0f}"
                    if at_mid.loc["basic", "cap_battery_mw"] else "0"
                ),
                "ExpCostMidSavedPct":
                    f"{100 * (1 - at_mid.loc['ev', 'system_cost_eur'] / at_mid.loc['basic', 'system_cost_eur']):.0f}",
            }
        # The hydrogen rung at the same budget point, where the electrolyser
        # is already built but not yet at scale -- the section reads the two
        # points against each other to make the utilisation argument.
        if "ev_h2" in at_mid.index:
            macros |= {
                "ExpSigmaMidPTwoX":
                    f"{at_mid.loc['ev_h2', 'co2_price_eur_t']:.0f}",
                "ExpElectrolyserMidGW":
                    f"{at_mid.loc['ev_h2', 'cap_electrolyser_mw'] / 1000:.1f}",
                "ExpElectrolyserMidHours":
                    f"{at_mid.loc['ev_h2', 'electrolyser_flh']:,.0f}".replace(",", "{,}"),
                "ExpSMRMidGW":
                    f"{at_mid.loc['ev_h2', 'cap_smr_mw'] / 1000:.1f}",
            }

    if "ev" in at_ref.index:
        ev = at_ref.loc["ev"]
        macros |= {
            "ExpSigmaEV": f"{ev['co2_price_eur_t']:.0f}",
            "ExpCostEVBn": f"{ev['system_cost_eur'] / 1e9:.1f}",
            "ExpBatteryEVGW": f"{gw('ev', 'cap_battery_mw'):.1f}",
            "ExpBatteryDisplacedPct": (
                f"{100 * (1 - ev['cap_battery_mw'] / basic['cap_battery_mw']):.0f}"
                if basic["cap_battery_mw"] else "0"
            ),
        }

    # The hydrogen sector: the reason the ladder has a second rung at all.
    if "h2_demand_mwh" in at_ref.columns and "ev_h2" in at_ref.index:
        macros |= {
            "ExpHTwoDemandTWh":
                f"{at_ref.loc['ev_h2', 'h2_demand_mwh'] / 1e6:.0f}",
            "ExpSMRGW": f"{gw('ev_h2', 'cap_smr_mw'):.1f}",
        }
    if "ev_h2" in at_ref.index:
        p2x = at_ref.loc["ev_h2"]
        supplied = (p2x.get("h2_from_smr_mwh", 0.0)
                    + p2x.get("h2_from_electrolysis_mwh", 0.0))
        macros |= {
            "ExpElectrolyserGW": f"{gw('ev_h2', 'cap_electrolyser_mw'):.1f}",
            "ExpHTwoTurbineGW": f"{gw('ev_h2', 'cap_h2_turbine_mw'):.1f}",
            "ExpHTwoStoreTWh": f"{float(p2x['h2_store_mwh'] or 0.0) / 1e6:.2f}",
            # Running hours to the nearest hundred: the text reads them as
            # "about", and the last digits are segment noise.
            "ExpElectrolyserHours":
                f"{round(float(p2x.get('electrolyser_flh', 0.0) or 0.0), -2):,.0f}".replace(",", "{,}"),
            "ExpElectrolyticSharePct": (
                f"{100 * p2x.get('h2_from_electrolysis_mwh', 0.0) / supplied:.0f}"
                if supplied else "0"
            ),
            # Solver noise can leave this a hair below zero, which would
            # print "-0.0"; adding 0.0 to the rounded value drops the sign.
            "ExpHTwoToPowerTWh":
                f"{round(float(p2x.get('h2_to_power_mwh', 0.0) or 0.0) / 1e6, 1) + 0.0:.1f}",
            "ExpSigmaPTwoX": f"{p2x['co2_price_eur_t']:.0f}",
            "ExpCostPTwoXBn": f"{p2x['system_cost_eur'] / 1e9:.1f}",
            # What the four countries cannot make themselves and buy in.
            # Imports are a step supply curve with corridors only into
            # Germany, so this is also the corridors' capacity.
            "ExpHTwoImportedTWh":
                f"{(p2x['h2_demand_mwh'] - supplied) / 1e6:.0f}",
        }
    # Where it all gets built. Germany takes an order of magnitude more than
    # anyone else, which is figure 8.3's whole point, so the section quotes
    # the concentration rather than asking the reader to measure a bar.
    zones = d["zones"]
    build_cols = [c for c in zones.columns
                  if c not in ("h2_store_mwh", "transmission_new")]
    total = zones[build_cols].sum(axis=1)
    if "DE" in total.index and total.sum():
        macros |= {
            "ExpGermanySharePct": f"{100 * total.loc['DE'] / total.sum():.0f}",
            "ExpSolarDEGW": f"{zones.loc['DE', 'solar_pv'] / 1000:.0f}",
            "ExpOnshoreDEGW": f"{zones.loc['DE', 'wind_onshore'] / 1000:.0f}",
            "ExpElectrolyserDEGW":
                f"{zones.loc['DE', 'electrolyser'] / 1000:.0f}",
        }

    # The time-aggregation check for this section: the hydrogen scenario's
    # reference case at all 8760 hours beside the aggregated answer, and
    # beside the every-k-th-hour answer at the same size, whose kept hours
    # are eight apart and so miss most of the daily cycle batteries earn on.
    res = d.get("resolution")
    if res is not None:
        full, samp = res["full"], res["sampled"]
        macros |= {
            "ExpHoursSampled": f"{res['hours_sampled']}",
            "ExpSigmaFullYear": f"{full['co2_price_eur_t']:.0f}",
            "ExpSigmaSampled": f"{samp['co2_price_eur_t']:.0f}",
            "ExpHTwoStoreFullTWh": f"{full['h2_store_mwh'] / 1e6:.2f}",
            "ExpHTwoStoreSampledTWh": f"{samp['h2_store_mwh'] / 1e6:.2f}",
            "ExpHTwoTurbineFullGW": f"{full['cap_h2_turbine_mw'] / 1e3:.1f}",
            "ExpBatteryFullGW": f"{full['cap_battery_mw'] / 1e3:.0f}",
            "ExpBatterySampledGW": f"{samp['cap_battery_mw'] / 1e3:.0f}",
            "ExpElectrolyserFullGW": f"{full['cap_electrolyser_mw'] / 1e3:.0f}",
        }
        stride = res.get("stride_same_hours")
        if stride:
            macros |= {
                "ExpHTwoStoreStrideTWh": f"{stride['h2_store_mwh'] / 1e6:.2f}",
                "ExpSigmaStride": f"{stride['co2_price_eur_t']:.0f}",
                "ExpBatteryStrideGW": f"{stride['cap_battery_mw'] / 1e3:.0f}",
                "ExpElectrolyserStrideGW": f"{stride['cap_electrolyser_mw'] / 1e3:.0f}",
            }

    # The vehicle-to-grid scenario: smart charging whose cars can also sell
    # back. It has the baseline's budget in tonnes, so its carbon price
    # compares with the baseline's directly.
    if "ev_v2g" in at_ref.index:
        v2g = at_ref.loc["ev_v2g"]
        macros |= {
            "ExpSigmaVTwoG": f"{v2g['co2_price_eur_t']:.0f}",
            "ExpCostVTwoGBn": f"{v2g['system_cost_eur'] / 1e9:.1f}",
            "ExpBatteryVTwoGGW": f"{gw('ev_v2g', 'cap_battery_mw'):.1f}",
        }
    if mids and "ev_v2g" in at_mid.index:
        macros |= {
            "ExpSigmaMidVTwoG": f"{at_mid.loc['ev_v2g', 'co2_price_eur_t']:.0f}",
            "ExpCostMidVTwoGBn":
                f"{at_mid.loc['ev_v2g', 'system_cost_eur'] / 1e9:.1f}",
            "ExpBatteryMidVTwoGGW":
                f"{at_mid.loc['ev_v2g', 'cap_battery_mw'] / 1000:.1f}",
        }

    # What flexibility saves against the baseline at the same budget, and
    # vehicle-to-grid's unconstrained emissions beside the other two.
    def saved_pct(at, rung):
        return f"{100 * (1 - at.loc[rung, 'system_cost_eur'] / at.loc['basic', 'system_cost_eur']):.0f}"

    if "ev" in at_ref.index:
        macros["ExpCostSavedPct"] = saved_pct(at_ref, "ev")
    if "ev_v2g" in at_ref.index:
        macros["ExpCostSavedVTwoGPct"] = saved_pct(at_ref, "ev_v2g")
        macros["ExpUnconstrainedVTwoGMt"] = (
            f"{s['unconstrained_emissions_t']['ev_v2g'] / 1e6:.0f}")
    if mids and "ev_v2g" in at_mid.index:
        macros["ExpCostMidSavedVTwoGPct"] = saved_pct(at_mid, "ev_v2g")
    macros["ExpPricesCutOff"] = f"{PRICES_CUTOFF}"

    # What the section quotes about its figures, written by run_expansion.py
    # beside the figures' tables; results older than those tables lack it.
    mid_key, ref_key = str(s.get("mid_fraction")), str(reference)
    if "switch_price_eur_t" in s:
        switch = s["switch_price_eur_t"]
        macros |= {
            "ExpSwitchPrice": f"{switch:.0f}",
            "ExpBiomethaneFuelPrice": f"{s['biomethane_price_eur_mwh']:.0f}",
            "ExpGasFuelPrice": f"{s['gas_price_eur_mwh']:.0f}",
        }
        # The baseline's plateau: the budget points whose carbon price is
        # the switch price, every gas plant indifferent between its fuels.
        basic_rows = ladder[ladder["rung"] == "basic"].dropna(subset=["budget_share"])
        plateau = basic_rows[(basic_rows["co2_price_eur_t"] - switch).abs() < 0.01]
        if len(plateau):
            macros["ExpPlateauCutPct"] = (
                f"{100 * (1 - plateau['budget_share'].max()):.0f}")
    # The first budget point at which the electrolysers stand at most of
    # their reference-budget capacity: where they arrive at scale.
    h2_rows = ladder[ladder["rung"] == "ev_h2"].dropna(subset=["budget_share"])
    if "cap_electrolyser_mw" in h2_rows.columns and len(h2_rows):
        ely_ref = float(h2_rows.loc[h2_rows["budget_share"] == reference,
                                    "cap_electrolyser_mw"].iloc[0] or 0.0)
        scaled = h2_rows[h2_rows["cap_electrolyser_mw"].fillna(0.0) >= 0.5 * ely_ref]
        if ely_ref > 0 and len(scaled):
            macros["ExpElectrolyserScaleCutPct"] = (
                f"{100 * (1 - scaled['budget_share'].max()):.0f}")
    # The reformer's cost and emissions, which with an import step's price
    # return the carbon price at the middle budget (eq:expansion:sigma-import).
    if "smr_marginal_cost_eur_mwh" in s:
        macros |= {
            "ExpSMRMC": f"{s['smr_marginal_cost_eur_mwh']:.2f}",
            "ExpSMRCapitalPerMWh": f"{s['smr_fixed_cost_eur_mw'] / 8760:.2f}",
            "ExpSMREmissionRate": f"{s['smr_emission_rate_t_mwh']:.3f}",
        }
    # The backup the deep end builds: open-cycle turbines that burn
    # biomethane, how many, and how many hours a year they run (to the
    # nearest hundred: the text reads them as "about").
    for rung, name in [("basic", ""), ("ev", "EV"), ("ev_v2g", "VTwoG"),
                       ("ev_h2", "HTwo")]:
        turbines = s.get(f"turbines_{rung}")
        if turbines:
            macros[f"ExpTurbine{name}GW"] = f"{turbines['gw']:.1f}"
            macros[f"ExpTurbine{name}Hours"] = (
                f"{round(turbines['full_load_hours'], -2):,.0f}".replace(",", "{,}"))
    macros |= _expansion_figure_values(d)
    # prop:wire in the numbers: how many corridors stop at their ceiling,
    # and how far above its fixed cost the rent of the dearest one goes.
    wires = s.get(f"wires_{ref_key}")
    if wires and wires.get("max_ratio_at_ceiling") is not None:
        macros |= {
            "ExpWireCeilingRatio": f"{wires['max_ratio_at_ceiling']:.1f}",
            "ExpWiresAtCeiling": f"{wires['at_ceiling']}",
            "ExpWiresBelowCeiling": f"{wires['below_ceiling']}",
        }
    # How the cars use their freedom at the middle budget.
    for rung, name in [("ev", "Smart"), ("ev_v2g", "VTwoG")]:
        cars = s.get(f"cars_{rung}_{mid_key}")
        if not cars:
            continue
        macros |= {
            f"ExpCars{name}MovedPct": f"{100 * cars['moved_share']:.0f}",
            f"ExpCars{name}PricePaid": f"{cars['price_paid_eur_mwh']:.0f}",
            f"ExpCars{name}PriceArrival": f"{cars['price_on_arrival_eur_mwh']:.0f}",
            f"ExpCars{name}StoreFullPct": f"{100 * cars['store_full_share']:.0f}",
            f"ExpCars{name}StoreFloorPct": f"{100 * cars['store_at_floor_share']:.0f}",
            f"ExpCars{name}ChargersLimitPct":
                f"{100 * cars['chargers_at_limit_share']:.0f}",
        }
        if "v2g_out_mwh" in cars:
            macros |= {
                f"ExpCars{name}OutTWh": f"{cars['v2g_out_mwh'] / 1e6:.0f}",
                f"ExpCars{name}Hours":
                    f"{cars['v2g_hours']:,.0f}".replace(",", "{,}"),
            }
    # The price of hydrogen at the middle budget, which is the price of the
    # dearest import step in use (eq:expansion:sigma-import), and the
    # system's hydrogen price, weighted by demand, at the reference budget.
    step, h2_ref = s.get(f"h2_import_step_{mid_key}"), s.get(f"h2_price_{ref_key}")
    if step is not None:
        macros["ExpHTwoPriceMid"] = f"{step:.0f}"
    if h2_ref:
        macros["ExpHTwoPriceRef"] = f"{h2_ref['mean']:.0f}"
    # How hard the electrolysers run in the scarcest hours, as a share of
    # their average over the year.
    scarce = s.get(f"electrolysers_scarce_{ref_key}")
    if scarce is not None:
        macros["ExpElectrolyserScarcePct"] = f"{100 * scarce:.0f}"
    # The vehicle-to-grid scenario's full-year check, posed as the hydrogen
    # scenario's is.
    res_v2g = d.get("resolution_v2g")
    if res_v2g is not None:
        full, samp = res_v2g["full"], res_v2g["sampled"]
        macros |= {
            "ExpVTwoGSigmaFullYear": f"{full['co2_price_eur_t']:.0f}",
            "ExpVTwoGSigmaSampled": f"{samp['co2_price_eur_t']:.0f}",
            "ExpVTwoGBatteryFullGW": f"{full['cap_battery_mw'] / 1e3:.1f}",
            "ExpVTwoGBatterySampledGW": f"{samp['cap_battery_mw'] / 1e3:.1f}",
            "ExpVTwoGOutFullTWh": f"{full['ev_v2g_out_mwh'] / 1e6:.0f}",
            "ExpVTwoGOutSampledTWh": f"{samp['ev_v2g_out_mwh'] / 1e6:.0f}",
            "ExpVTwoGCostGapPct":
                f"{100 * (samp['system_cost_eur'] / full['system_cost_eur'] - 1):.1f}",
        }
    _write_values("expansion_values.tex", macros,
                  "results/expansion_ladder.csv")


def _write_values(filename, macros, source):
    lines = [
        f"%% GENERATED by pipeline/build.py from {source}",
        "%% -- do not edit; rerun the pipeline instead.",
    ]
    lines += [rf"\providecommand{{\{name}}}{{{value}}}" for name, value in macros.items()]
    (TABLES / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Appendix A: the boots-and-Teslas example
#
# The only figures in the note that read nothing from results/ -- they draw a
# textbook example, not a model run. Its parameters live here and in the tex;
# if the example changes, change EXAMPLE and nothing else, because the
# feasible segment and the optimum below are derived rather than typed.

EXAMPLE = {
    "income": 3.0,       # euros to spend, the right-hand side of the budget
    "p_boots": 1.0,      # price of x1
    "p_teslas": 0.5,     # price of x2
    "cap": 5.0,          # Marie Kondo: x1 + x2 <= cap
    "x1_max": 2.0,       # two feet
    "weight": 3.0,       # utility is x1 + weight * ln(x2)
}


def _example_geometry(e=EXAMPLE):
    """Where the example's feasible bundles are, and which one is best.

    The budget holds with equality, so the choice set is a segment of the
    budget line rather than an area: find the endpoints the inequality
    constraints leave, then maximise utility along it. Returns everything the
    two figures need, in the note's own notation.
    """
    import numpy as np

    def budget(x1):
        return (e["income"] - e["p_boots"] * x1) / e["p_teslas"]

    def utility(x1):
        return x1 + e["weight"] * np.log(budget(x1))

    # Along the budget line, the item cap x1 + x2 <= cap reads
    # x1 * (1 - p1/p2) <= cap - income/p2. Teslas are the cheaper good here,
    # so the coefficient is negative and the cap sets a lower bound on boots.
    slope = 1.0 - e["p_boots"] / e["p_teslas"]
    bound = e["cap"] - e["income"] / e["p_teslas"]
    lo, hi = 0.0, min(e["x1_max"], e["income"] / e["p_boots"])
    if slope > 0:
        hi = min(hi, bound / slope)
    elif slope < 0:
        lo = max(lo, bound / slope)

    # Utility along the budget line is single-peaked, with its peak where the
    # marginal utility of a Tesla equals its relative price. The optimum is
    # that peak if it survives the constraints, and the nearest endpoint if
    # it does not.
    x2_peak = e["weight"] * e["p_boots"] / e["p_teslas"]
    x1_peak = (e["income"] - e["p_teslas"] * x2_peak) / e["p_boots"]
    x1_star = min(max(x1_peak, lo), hi)

    return {
        "budget": budget,
        "utility": utility,
        "segment": (lo, hi),
        "guess": (x1_peak, budget(x1_peak)),      # ignores the item cap
        "optimum": (x1_star, budget(x1_star)),
        "u_star": utility(x1_star),
        "x1_lim": e["income"] / e["p_boots"] * 1.06,
        "x2_lim": budget(0.0) * 1.12,
    }


def _clip_halfplane(poly, a, b, c):
    """Sutherland--Hodgman clip of a convex polygon to a*x + b*y <= c."""
    out = []
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        d1, d2 = a * x1 + b * y1 - c, a * x2 + b * y2 - c
        if d1 <= 1e-12:
            out.append((x1, y1))
        if (d1 > 1e-12) != (d2 > 1e-12):
            t = d1 / (d1 - d2)
            out.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
    return out


def _feasible_region(e=EXAMPLE):
    """Every bundle that satisfies every constraint: nothing negative, at
    most `x1_max` boots, at most `cap` items, and nothing unaffordable.

    Built by clipping a box with one half-plane per constraint rather than by
    listing corners, so it stays right if the parameters change. The budget
    enters as `<=`: the note's example spends the whole budget, and with a
    utility increasing in both goods it would anyway, so the feasible set is
    this region and the choice is made on its upper-right edge.
    """
    box_top = e["income"] / e["p_teslas"] + e["cap"]
    poly = [(0.0, 0.0), (e["x1_max"], 0.0),
            (e["x1_max"], box_top), (0.0, box_top)]
    poly = _clip_halfplane(poly, 1.0, 1.0, e["cap"])
    return _clip_halfplane(poly, e["p_boots"], e["p_teslas"], e["income"])


def _example_axes(g, e=EXAMPLE, constraints=True):
    """The common ground of both appendix figures: the feasible set, shaded.

    With `constraints`, the three constraints are drawn across the picture
    and named, and the stretch of budget line that bounds the feasible set is
    picked out. Without, only the shading survives — the second figure is
    about the two candidate bundles, and the lines would be three more things
    to disentangle before getting to them."""
    import numpy as np

    fig, ax = plt.subplots(figsize=(4.4, 3.8))
    lo, hi = g["segment"]

    ax.add_patch(plt.Polygon(_feasible_region(e), closed=True,
                             facecolor="#e4e4e4", edgecolor="none", zorder=0))

    if constraints:
        # Each constraint is drawn across the whole picture, so it reads as a
        # constraint rather than as an edge of the shading.
        xs = np.linspace(0.0, g["x1_lim"], 2)
        ax.plot(xs, e["cap"] - xs, color=VERMILLION, lw=1.2, zorder=2)
        ax.annotate("item cap", (0.05, e["cap"] - 0.05), color=VERMILLION,
                    fontsize=8, ha="left", va="bottom")

        ax.axvline(e["x1_max"], color="#999999", lw=1.0, ls=(0, (4, 3)),
                   zorder=2)
        ax.annotate(r"$x_1 \leq 2$", (e["x1_max"] - 0.06, g["x2_lim"] * 0.86),
                    color="#777777", fontsize=8, ha="right", va="center")

        # The budget line, thick where it bounds the feasible set.
        full = np.linspace(0.0, e["income"] / e["p_boots"], 200)
        ax.plot(full, g["budget"](full), color=BLUE, lw=1.0, ls=(0, (3, 2)),
                zorder=3)
        seg = np.linspace(lo, hi, 50)
        ax.plot(seg, g["budget"](seg), color=BLUE, lw=3.0,
                solid_capstyle="round", zorder=4)
        ax.annotate("budget", (0.12, g["budget"](0.12) + 0.12), color=BLUE,
                    fontsize=8, ha="left", va="bottom")

    # A hair of room left of the axis, so a marker sitting at x1 = 0 -- the
    # first guess does -- is drawn whole rather than sliced by the spine.
    ax.set_xlim(-0.045, g["x1_lim"])
    ax.set_ylim(0.0, g["x2_lim"])
    ax.set_xticks([0, 1, 2, 3])
    ax.set_yticks([0, 2, 4, 6])
    ax.set_xlabel(r"$x_1$ (boots)")
    ax.set_ylabel(r"$x_2$ (Teslas)")
    ax.grid(True, lw=0.5)
    return fig, ax


def fig_appendix_feasible():
    """Figure A.1: the three constraints, and the feasible set they leave."""
    g = _example_geometry()
    fig, ax = _example_axes(g)
    ax.annotate("feasible", (0.42, 1.25), fontsize=8, color="#666666",
                ha="left", va="center")
    fig.savefig(FIGURES / "app_example_feasible.pdf")
    plt.close(fig)


def fig_appendix_solution():
    """Figure A.2: the feasible set with the two candidates on it. The first
    guess ignores the item cap and lands outside it; the optimum is the
    feasible bundle on the highest indifference curve. The constraint lines
    are dropped — the shape of the shading already carries them."""
    import numpy as np

    g = _example_geometry()
    e = EXAMPLE
    fig, ax = _example_axes(g, constraints=False)

    # The indifference curve through the optimum: x1 = u* - weight * ln(x2).
    # It is cut off where it leaves the picture on the left, and well before
    # the right-hand edge, where it would run alongside the item cap and add
    # nothing but a second line to disentangle.
    x2_top = float(np.exp(g["u_star"] / e["weight"]))       # where x1 = 0
    x2 = np.linspace(2.6, x2_top, 300)
    x1 = g["u_star"] - e["weight"] * np.log(x2)
    ax.plot(x1, x2, color="#888888", lw=0.9, zorder=3)
    ax.annotate(r"$u^\ast$", (0.06, x2_top - 0.06), color="#777777",
                fontsize=8, ha="left", va="top")

    gx, gy = g["guess"]
    ox, oy = g["optimum"]
    ax.plot([gx], [gy], marker="o", ms=6, mfc="white", mec=INK, mew=1.2,
            zorder=5)
    ax.annotate(f"first guess $({gx:g},{gy:g})$", (gx, gy),
                xytext=(gx + 0.18, gy + 0.02), fontsize=8, color=INK,
                ha="left", va="center")
    ax.plot([ox], [oy], marker="o", ms=6, color=INK, zorder=5)
    ax.annotate(rf"optimum $({ox:g},{oy:g})$", (ox, oy),
                xytext=(ox + 0.22, oy + 0.55), fontsize=8, color=INK,
                ha="left", va="center",
                arrowprops=dict(arrowstyle="-", color=INK, lw=0.8,
                                shrinkA=2, shrinkB=4))
    fig.savefig(FIGURES / "app_example_solution.pdf")
    plt.close(fig)


def build_figures(results):
    FIGURES.mkdir(parents=True, exist_ok=True)
    # The appendix schematic depends on nothing in results/, so it is
    # built unconditionally.
    fig_appendix_feasible()
    fig_appendix_solution()
    if "dispatch" in results:
        fig_dispatch_merit_order(results["dispatch"])
        fig_dispatch_carbon_tax(results["dispatch"])
        fig_dispatch_cap_sweep(results["dispatch"])
        fig_dispatch_mac(results["dispatch"])
    else:
        print("skipping dispatch figures — run pipeline/run_dispatch.py first")
    if "dispatch_t" in results:
        fig_intermittency_profiles(results["dispatch_t"])
        fig_intermittency_fleet(results["dispatch_t"])
        fig_intermittency_residual(results["dispatch_t"])
        fig_intermittency_price_duration(results["dispatch_t"])
        fig_intermittency_value(results["dispatch_t"])
        fig_intermittency_ratio(results["dispatch_t"])
        fig_intermittency_week(results["dispatch_t"])
        if "actual_duration" in results["dispatch_t"]:
            fig_intermittency_validation(results["dispatch_t"])
    else:
        print("skipping intermittency figures — run pipeline/run_dispatch_t.py first")
    if "storage" in results:
        fig_storage_week(results["storage"])
        fig_storage_pdc(results["storage"])
        fig_storage_ramp(results["storage"])
        fig_storage_recovery(results["storage"])
    else:
        print("skipping storage figures — run pipeline/run_storage.py first")
    if "heat" in results:
        fig_heat_cop(results["heat"])
        fig_heat_dispatch(results["heat"])
        fig_heat_rollout(results["heat"])
    else:
        print("skipping heat figures — run pipeline/run_heat.py first")
    if "network" in results:
        fig_network_prices(results["network"])
        fig_network_rents(results["network"])
        fig_network_smoothing(results["network"])
        fig_network_expansion(results["network"])
        if "actual_market" in results["network"]["summary"]:
            fig_network_validation(results["network"])
        if "geography" in results["network"]:
            fig_network_map(results["network"])
            fig_network_topology(results["network"])
        if "accounts" in results["network"]:
            fig_network_distribution(results["network"])
    else:
        print("skipping network figures — run pipeline/run_network.py first")
    if "greenfield" in results:
        fig_greenfield_screening(results["greenfield"])
        fig_greenfield_mix(results["greenfield"])
        fig_greenfield_scenarios(results["greenfield"])
        if results["greenfield"].get("cost_recovery") is not None:
            fig_greenfield_recovery(results["greenfield"])
            table_greenfield_values(results["greenfield"])
        if results["greenfield"].get("price_bands") is not None:
            fig_greenfield_scarcity(results["greenfield"])
        fig_greenfield_spell(results["greenfield"])
    else:
        print("skipping greenfield figures — run pipeline/run_greenfield.py first")
    if "weather" in results and "costs" in results:
        fig_uncertainty_variability(results["weather"], results["costs"])
    else:
        print("skipping the variability figure — run pipeline/run_weather.py "
              "and pipeline/run_costs.py first")
    if "expansion" in results:
        e = results["expansion"]
        fig_expansion_ladder(e)
        prices, margins = ["price_duration", "price_setters"], ["scarce_hours", "marginal_storage"]
        for figure, tables in [(fig_expansion_baseline, ["generation"]),
                               (fig_expansion_prices, prices),
                               (fig_expansion_margins, margins),
                               (fig_expansion_ev_system, ["generation"]),
                               (fig_expansion_ev_prices, prices),
                               (fig_expansion_ev_margins, margins),
                               (fig_expansion_hydrogen, ["hydrogen_months"]),
                               (fig_expansion_hydrogen_system, ["generation"]),
                               (fig_expansion_hydrogen_prices, prices),
                               (fig_expansion_hydrogen_margins, margins)]:
            if all(e.get(t) is not None for t in tables):
                figure(e)
            else:
                print(f"skipping {figure.__name__} — its tables are missing; re-run "
                      "pipeline/run_expansion.py (every solve is cached)")
    else:
        print("skipping section 8 figures — run pipeline/run_expansion.py first")


def build_tables(results):
    TABLES.mkdir(parents=True, exist_ok=True)
    if "dispatch" in results:
        table_dispatch_tech(results["dispatch"])
        values_dispatch(results["dispatch"])
    if "dispatch_t" in results:
        values_dispatch_t(results["dispatch_t"])
    if "storage" in results:
        values_storage(results["storage"])
    if "heat" in results:
        values_heat(results["heat"])
    if "network" in results:
        values_network(results["network"])
    if "greenfield" in results:
        values_greenfield(results["greenfield"])
    if "weather" in results:
        values_weather(results["weather"])
    if "costs" in results:
        values_costs(results["costs"])
    if "expansion" in results:
        values_expansion(results["expansion"])


def main():
    _forbid_model_imports()
    results = load_results()
    build_figures(results)
    build_tables(results)
    print("built writing/generated/ from results/")


if __name__ == "__main__":
    main()
