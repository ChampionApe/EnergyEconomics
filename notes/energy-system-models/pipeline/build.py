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
            # Result 7.1 in numbers, the LCOE-against-capture-price table and
            # the scarcity curve: written by run_greenfield.py from the
            # reference solve.
            **{key: (pd.read_csv(RESULTS / f"greenfield_{key}.csv", **kw)
                     if (RESULTS / f"greenfield_{key}.csv").exists() else None)
               for key, kw in [("cost_recovery", {"index_col": "tech"}),
                               ("value_table", {"index_col": "tech"}),
                               ("scarcity", {})]},
        }
    if (RESULTS / "weather_summary.json").exists():
        results["weather"] = {
            "mix": pd.read_csv(RESULTS / "weather_mix.csv", index_col="year"),
            "price_duration": pd.read_csv(RESULTS / "weather_price_duration.csv", index_col="pct_of_hours"),
            "summary": json.loads((RESULTS / "weather_summary.json").read_text(encoding="utf-8")),
        }
    if (RESULTS / "taxcap_summary.json").exists():
        results["taxcap"] = {
            "table": pd.read_csv(RESULTS / "taxcap.csv", index_col="year"),
            "summary": json.loads((RESULTS / "taxcap_summary.json").read_text(encoding="utf-8")),
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
    ax.text(x + 0.05, price, rf"$\lambda = {price:.0f}$",
            ha="left", va="center", fontsize=8, color=INK)
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
    ax.annotate("same object, two derivations:\none assumes the shape,\n"
                "the other explains it",
                xy=(0.60 * (m0 - floor), 205), fontsize=8, color="#777777")

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
        lines.append(rf"\item[{letter}] {src.replace('CO2', 'CO$_2$')}.")
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
        ax.set_ylim(0, 1.02)
        ax.grid(axis="y")
        ax.margins(x=0)
        ax.tick_params(axis="x", labelsize=7)
    axes[0].legend(frameon=False, fontsize=8, ncol=4, loc="upper right")

    ax = axes[2]
    pct = (pd.RangeIndex(len(p)) + 0.5) / len(p) * 100.0
    for name, color in VRE_COLORS.items():
        sorted_pu = p[f"{name}_pu"].sort_values(ascending=False).to_numpy()
        ax.plot(pct, sorted_pu, color=color, linewidth=1.6)
    for name, x in [("wind_offshore", 30), ("wind_onshore", 40), ("solar", 18)]:
        y = p[f"{name}_pu"].sort_values(ascending=False).to_numpy()[
            int(x / 100 * len(p))
        ]
        ax.annotate(f"{VRE_LABELS[name]}  (CF {cf[name]:.2f})", xy=(x, y),
                    xytext=(6, 6), textcoords="offset points",
                    fontsize=8, color=VRE_COLORS[name])
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

    axes[0].annotate("wind capture price", xy=(43, 22), fontsize=8, color=BLUE)
    axes[0].annotate("base price,\nas wind grows", xy=(57, 38), fontsize=8,
                     color=BLUE, alpha=0.8)
    axes[0].annotate("solar capture price", xy=(11, 25), fontsize=8,
                     color=colors["solar"])
    axes[0].annotate("base price,\nas solar grows", xy=(24.5, 39.5), fontsize=8,
                     color=colors["solar"], alpha=0.8)
    axes[0].set_title(
        "(a) capture price (solid) and the base price it is divided by (dashed)",
        loc="left", fontsize=9, color=INK)
    axes[0].set_ylabel("€/MWh")
    axes[0].grid(axis="y")

    axes[1].axhline(1.0, color="#999999", linewidth=0.8, linestyle="--")
    axes[1].annotate("wind", xy=(45, 0.72), fontsize=8, color=BLUE)
    axes[1].annotate("solar", xy=(16, 0.55), fontsize=8, color=colors["solar"])
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
        # Figure 3.4 cuts its axis above the dearest domestic plant and says
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
    "ocgt_biogas": "OCGT (biogas)", "nuclear": "nuclear",
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
    axes[0].legend(frameon=False, fontsize=8, loc="upper right", ncol=2)
    axes[0].set_ylabel("price (€/MWh)")
    axes[0].grid(axis="y")
    axes[0].set_title("(a) the price path", loc="left", fontsize=9, color=INK)

    soc = hours.loc[window, "soc_mwh"] / 1000.0
    axes[1].fill_between(window, soc, color="#009E73", alpha=0.35, linewidth=0)
    axes[1].plot(window, soc, color="#009E73", linewidth=1.4)
    axes[1].set_ylabel("state of charge (GWh)")
    axes[1].grid(axis="y")
    axes[1].set_title("(b) the battery fills in cheap hours, empties in dear ones",
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
    """Figure 6.1: zonal price duration curves."""
    prices = d["prices"]
    pct = (pd.RangeIndex(len(prices)) + 0.5) / len(prices) * 100.0

    fig, ax = plt.subplots(figsize=(6.1, 3.7))
    for zone in ["DE", "DK1", "DK2", "NO2", "SE3"]:
        sorted_p = prices[zone].sort_values(ascending=False).to_numpy()
        ax.plot(pct, sorted_p, color=ZONE_COLORS[zone], linewidth=1.6)
        x = {"DE": 12, "DK1": 30, "DK2": 45, "NO2": 68, "SE3": 84}[zone]
        ax.annotate(zone, xy=(x, sorted_p[int(x / 100 * len(prices))]),
                    xytext=(0, 6), textcoords="offset points",
                    fontsize=8, color=ZONE_COLORS[zone])
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
    axes[0].set_xlabel("DK1 onshore wind (p.u.)")
    axes[0].set_ylabel("DK2 onshore wind (p.u.)")
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
    ax.annotate("congestion rent on the corridor",
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
    "DK1–SE3 DC": (300e3, 90e3),
    "DK1–DK2 DC": (-300e3, -120e3),
    "DE–NO2 DC": (-380e3, -280e3),
    "DE–DK2 DC": (400e3, -140e3),
    "DE–SE4 DC": (430e3, 10e3),
    "SE3–SE4 DC": (330e3, 20e3),
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
        Line2D([0], [0], color=INK, linewidth=1.5, label="AC corridor"),
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
    """Figure 6.5: who wins and who loses from the Skagerrak corridor, by
    country: consumers, producers and the countries' halves of the rent,
    for the corridor as built against none, and for a doubling."""
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.3))
    titles = {"Built": "(a) the corridor as built, against none",
              "Double": "(b) a second corridor of the same size"}
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
    axes[0].legend(frameon=False, fontsize=7, loc="lower left")
    fig.savefig(FIGURES / "network_distribution.pdf")
    plt.close(fig)


def _write_network_calibration_table(d):
    """Appendix C: what each calibration of the shipped network does to
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
                    fontsize=8, color=TECH_COLORS[tech],
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
                    "in the reference system of figure 7.2",
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
    """Figure 7.2: (a) the optimal Danish mix as the common carbon price
    rises, with Danish emissions above each bar; (b) Danish and system
    emissions against the price -- the marginal abatement curve read from
    the tax side, with the fuel-switching price marked."""
    sweep = d["sweep"].copy().sort_values("carbon_price")
    s = d["summary"]
    sweep.index = [f"{t:.0f}" for t in sweep["carbon_price"]]
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.9),
                             gridspec_kw={"width_ratios": [1.5, 1.0]})
    top = _stacked_mix(axes[0], sweep)
    for i, (_, row) in enumerate(sweep.iterrows()):
        axes[0].annotate(f"{row['emissions_t'] / 1e6:.2f} Mt", xy=(i, top.iloc[i]),
                         xytext=(0, 4), textcoords="offset points", ha="center",
                         fontsize=7, color=INK)
    axes[0].legend(frameon=False, fontsize=7, ncol=3, loc="upper left")
    axes[0].set_ylim(0, top.max() * 1.6)
    axes[0].set_xlabel("common carbon price (€/t)")
    axes[0].set_title("(a) what Denmark builds", loc="left", fontsize=9, color=INK)
    ax = axes[1]
    ax.plot(sweep["carbon_price"], sweep["emissions_t"] / 1e6, marker="o",
            color=BLUE, linewidth=1.5, label="Danish generation")
    ax.set_xlabel("common carbon price (€/t)")
    ax.set_ylabel("Danish emissions (Mt)", color=BLUE)
    ax2 = ax.twinx()
    ax2.plot(sweep["carbon_price"], sweep["emissions_total_t"] / 1e6, marker="s",
             color="#D55E00", linewidth=1.5, label="twelve zones")
    ax2.set_ylabel("system emissions (Mt)", color="#D55E00")
    ax.axvline(s["switch_price_eur_t"], color=INK, linewidth=0.8, linestyle=":")
    ax.annotate("fuel switch", xy=(s["switch_price_eur_t"], ax.get_ylim()[1]),
                xytext=(3, -10), textcoords="offset points", fontsize=7, color=INK)
    ax.set_ylim(bottom=0)
    ax2.set_ylim(bottom=0)
    ax.grid(axis="y")
    ax.set_title("(b) emissions", loc="left", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(FIGURES / "greenfield_mix.pdf")
    plt.close(fig)


def fig_greenfield_breakdown(d):
    """Figure 7.3: the annual bill at the reference budget — capital versus
    operating cost by technology."""
    b = d["breakdown"].sort_values("capex_eur", ascending=True)
    b = b[(b["capex_eur"] + b["opex_eur"]) > 0]
    y = range(len(b))
    fig, ax = plt.subplots(figsize=(6.1, 3.2))
    ax.barh(y, b["capex_eur"] / 1e6, color=BLOCK_FILL, edgecolor="white",
            label="capital (annuitised)")
    ax.barh(y, b["opex_eur"] / 1e6, left=b["capex_eur"] / 1e6, color="#D55E00",
            alpha=0.75, edgecolor="white", label="operations")
    ax.set_yticks(list(y), [TECH_LABELS.get(t, t) for t in b.index])
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.grid(axis="x")
    ax.set_xlabel("annual cost (M€)")
    fig.savefig(FIGURES / "greenfield_breakdown.pdf")
    plt.close(fig)


def fig_greenfield_scenarios(d):
    """Figure 7.4: the same question under different worlds."""
    scen = d["scenarios"].drop(index="no carbon price", errors="ignore")
    fig, ax = plt.subplots(figsize=(6.1, 3.9))
    top = _stacked_mix(ax, scen)
    for i, (name, row) in enumerate(scen.iterrows()):
        label = (f"σ = {row['co2_price']:.0f} €/t" if pd.notna(row.get("co2_price"))
                 else f"{row['emissions_t'] / 1e6:.2f} Mt")
        ax.annotate(label, xy=(i, top.iloc[i]), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=7, color=INK)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    ax.set_ylim(0, top.max() * 1.3)
    fig.savefig(FIGURES / "greenfield_scenarios.pdf")
    plt.close(fig)


RECOVERY_ORDER = ["solar_pv", "wind_onshore", "wind_offshore", "battery_8h",
                  "battery_4h", "battery_2h", "ocgt_biogas", "ocgt", "ccgt",
                  "nuclear"]
RECOVERY_LABELS = {**TECH_LABELS, "battery_2h": "battery 2h",
                   "battery_4h": "battery 4h", "battery_8h": "battery 8h"}


def fig_greenfield_recovery(d):
    """Figure: long-run zero profit in numbers. Per Danish candidate, what a
    MW earns in scarcity rents against what it costs to hold for a year.
    Built and uncapped: equal. At the land cap: rents above cost, the gap
    the land rent. Not built: rents below cost."""
    r = d["cost_recovery"]
    r = r.reindex([t for t in RECOVERY_ORDER if t in r.index])
    x = range(len(r))
    width = 0.38
    fig, ax = plt.subplots(figsize=(6.1, 3.6))
    ax.bar([i - width / 2 for i in x], r["fixed_eur_mw_yr"] / 1e3, width,
           color=BLOCK_FILL, edgecolor="white", label="annualised fixed cost")
    ax.bar([i + width / 2 for i in x], r["rent_eur_mw_yr"] / 1e3, width,
           color="#D55E00", alpha=0.8, edgecolor="white",
           label="scarcity rents a MW earns")
    for i, (tech, row) in enumerate(r.iterrows()):
        tag = ("at cap" if row["at_cap"] else "built" if row["built"]
               else "not built")
        ax.annotate(tag, xy=(i, max(row["fixed_eur_mw_yr"], row["rent_eur_mw_yr"]) / 1e3),
                    xytext=(0, 4), textcoords="offset points", ha="center",
                    fontsize=7, color=INK)
    ax.set_xticks(list(x), [RECOVERY_LABELS.get(t, t) for t in r.index],
                  fontsize=8, rotation=20, ha="right")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(axis="y")
    ax.set_ylabel("k€ per MW per year")
    fig.savefig(FIGURES / "greenfield_recovery.pdf")
    plt.close(fig)


def fig_greenfield_scarcity(d):
    """Figure: how the peakers get paid. (a) the DK1 price duration curve of
    the reference system, in hours, on a log axis so the scarcity blocks and
    the body of the distribution are both visible; (b) the cumulative share
    of the peaking fleet's annual operating margin earned in its best hours."""
    c = d["scarcity"]
    s = d["summary"]["scarcity"]
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2))
    pct = (c["hour_rank"] - 0.5) / len(c) * 100.0
    axes[0].semilogy(pct, c["dk1_price_sorted"].clip(lower=1.0), color=BLUE,
                     linewidth=1.5)
    axes[0].set_xlim(0, 100)
    axes[0].set_xlabel("share of hours (%)")
    axes[0].set_ylabel("DK1 price (€/MWh, log scale)")
    axes[0].set_title("(a) price duration curve", loc="left", fontsize=9, color=INK)
    axes[0].grid(axis="y", which="major")
    hours = c["hour_rank"]
    axes[1].plot(hours, 100 * c["peaker_margin_cum_share"], color="#D55E00",
                 linewidth=1.5)
    axes[1].set_xscale("log")
    axes[1].set_xlim(1, len(c))
    axes[1].set_ylim(0, 100)
    axes[1].set_xlabel("best hours of the year (log scale)")
    axes[1].set_ylabel("share of peakers' annual margin (%)")
    axes[1].set_title("(b) where the peakers earn", loc="left", fontsize=9, color=INK)
    axes[1].grid(axis="y")
    if s.get("share_in_top_100_hours") is not None:
        axes[1].plot([100], [100 * s["share_in_top_100_hours"]], marker="o",
                     markersize=5, color="#D55E00")
        axes[1].annotate(f"{100 * s['share_in_top_100_hours']:.0f}% in the best 100 hours",
                         xy=(100, 100 * s["share_in_top_100_hours"]),
                         xytext=(8, -14), textcoords="offset points", ha="left",
                         fontsize=7.5, color=INK)
    fig.tight_layout()
    fig.savefig(FIGURES / "greenfield_scarcity.pdf")
    plt.close(fig)


def table_greenfield_values(d):
    """Table: levelised cost against capture price at the reference optimum,
    per built Danish technology -- section 3's statistics evaluated where
    zero profit makes the two coincide for uncapped technologies."""
    v = d["value_table"]
    v = v.reindex([t for t in RECOVERY_ORDER if t in v.index])
    r = d["cost_recovery"]
    lines = [
        "%% GENERATED by pipeline/build.py from results/greenfield_value_table.csv",
        "%% -- do not edit; rerun the pipeline instead.",
        r"\begin{tabular}{l r r r r r l}",
        r"\toprule",
        r"Technology & Capacity & Full-load hours & LCOE & Capture price"
        r" & Value factor & \\",
        r" & \footnotesize{GW} & \footnotesize{h/yr} & \footnotesize{€/MWh}"
        r" & \footnotesize{€/MWh} & & \\",
        r"\midrule",
    ]
    for tech, row in v.iterrows():
        tag = ""
        if tech in r.index:
            tag = "at its cap" if bool(r.loc[tech, "at_cap"]) else "interior"
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
        "InvBiogasMC": f"{scr.loc['ocgt_biogas', 'marginal_cost']:.0f}",
        "InvOCGTMC": f"{scr.loc['ocgt', 'marginal_cost']:.0f}",
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
            if "dk_load_mwh" in scen.columns:
                gen_b = float(dkb[gen_cols].fillna(0.0).sum()) if gen_cols and all(c in scen.columns for c in gen_cols) else None
                if gen_b is not None:
                    macros["InvDKBudgetNetImportPct"] = f"{100 * (1 - gen_b / dkb['dk_load_mwh']):.0f}"
    # Result 7.1 in numbers: rents against fixed cost, per candidate.
    r = d.get("cost_recovery")
    if r is not None:
        def ratio(tech):
            return f"{100 * r.loc[tech, 'rent_over_fixed']:.0f}" if tech in r.index else "--"
        macros |= {
            "InvRecoverySolarPct": ratio("solar_pv"),
            "InvRecoveryOnshorePct": ratio("wind_onshore"),
            "InvRecoveryOffshorePct": ratio("wind_offshore"),
            "InvRecoveryBiogasPct": ratio("ocgt_biogas"),
            "InvRecoveryOCGTPct": ratio("ocgt"),
            "InvRecoveryCCGTPct": ratio("ccgt"),
            "InvRecoveryNuclearPct": ratio("nuclear"),
            "InvRecoveryBatteryEightPct": ratio("battery_8h"),
        }
        for tech, key in [("wind_onshore", "Onshore"), ("solar_pv", "Solar")]:
            if tech in r.index and bool(r.loc[tech, "at_cap"]):
                macros[f"Inv{key}LandRent"] = (
                    f"{(r.loc[tech, 'rent_eur_mw_yr'] - r.loc[tech, 'fixed_eur_mw_yr']) / 1e3:.0f}")
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
    sc = s.get("scarcity")
    if sc:
        macros |= {
            "InvPeakerTopHundredPct": (
                f"{100 * sc['share_in_top_100_hours']:.0f}"
                if sc.get("share_in_top_100_hours") is not None else "--"),
            "InvPeakerTopFiveHundredPct": (
                f"{100 * sc['share_in_top_500_hours']:.0f}"
                if sc.get("share_in_top_500_hours") is not None else "--"),
            "InvHoursAboveFlexBlock": f"{sc['hours_price_above_flex_block']}",
            "InvHoursAboveIndustryBlock": f"{sc['hours_price_above_industry_block']}",
            "InvHoursAtVoLL": f"{sc['hours_price_at_voll']}",
            "InvDKOneMaxPrice": f"{sc['dk1_max_price']:,.0f}",
        }
    _write_values("greenfield_values.tex", macros, "results/greenfield_summary.json")


# --------------------------------------------------------------------------
# Section 9 — uncertainty
# --------------------------------------------------------------------------

def fig_weather_mix(d):
    """Figure 9.1: the optimal mix, re-solved per weather year."""
    mix = d["mix"]
    fig, ax = plt.subplots(figsize=(6.1, 3.9))
    top = _stacked_mix(ax, mix)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    ax.set_ylim(0, top.max() * 1.25)
    ax.set_xlabel("weather year")
    fig.savefig(FIGURES / "weather_mix.pdf")
    plt.close(fig)


def fig_weather_cost(d):
    """Figure 9.2: the Danish bill and the CO2 shadow price by weather year.

    The bill, not the solver's objective: eleven of the twelve zones are
    fixed in this section, and dividing a Danish movement by a European
    total flattens the panel into a straight line."""
    mix = d["mix"]
    x = range(len(mix))
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.0))
    axes[0].bar(x, mix["dk_system_cost"] / 1e9, color=BLOCK_FILL,
                edgecolor="white", width=0.6)
    axes[0].set_xticks(list(x), mix.index, fontsize=8)
    axes[0].grid(axis="y")
    axes[0].set_ylabel("Danish system cost (bn € / yr)")
    axes[0].set_title("(a) the Danish bill", loc="left", fontsize=9, color=INK)
    low = (mix["dk_system_cost"] / 1e9).min()
    axes[0].set_ylim(low * 0.9, None)

    axes[1].plot(x, mix["emissions_t"] / 1e6, color=VERMILLION, linewidth=1.6,
                 marker="o", markersize=5)
    axes[1].set_xticks(list(x), mix.index, fontsize=8)
    axes[1].grid(axis="y")
    axes[1].set_ylim(bottom=0)
    axes[1].set_ylabel("Danish emissions (Mt)")
    axes[1].set_title("(b) emissions at the fixed price", loc="left",
                      fontsize=9, color=INK)
    fig.savefig(FIGURES / "weather_cost.pdf")
    plt.close(fig)


def fig_weather_pdc(d):
    """Figure 9.3: DK1 price duration curves across weather years."""
    duration = d["price_duration"]
    shades = ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c"]
    fig, ax = plt.subplots(figsize=(6.1, 3.6))
    for color, year in zip(shades, duration.columns):
        ax.plot(duration.index, duration[year], color=color, linewidth=1.4,
                label=year)
    # The tail spikes reach thousands of €/MWh in a fleet that must recover
    # its capital in a few scarcity hours; cap the axis so the body of the
    # distribution stays readable, and say what was cut.
    ax.set_ylim(0, 400)
    ax.annotate(
        f"scarcity peaks reach {duration.max().max():,.0f} €/MWh (cut off)",
        xy=(2, 392), fontsize=8, color=INK, va="top",
    )
    ax.legend(frameon=False, fontsize=8, ncol=3, title="weather year",
              title_fontsize=8, loc="center right")
    ax.set_xlim(0, 100)
    ax.grid(axis="y")
    ax.set_xlabel("share of hours (%)")
    ax.set_ylabel("DK1 price (€/MWh)")
    fig.savefig(FIGURES / "weather_price_duration.pdf")
    plt.close(fig)


def fig_weather_foresight(d_storage):
    """Figure 9.6: what perfect foresight is worth to the battery — system
    cost under the two operators."""
    f = d_storage["summary"]["foresight"]
    values = [f["system_cost_perfect_foresight"] / 1e6, f["system_cost_myopic"] / 1e6]
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.bar([0, 1], values, color=[BLUE, "#bbbbbb"], edgecolor="white", width=0.55)
    ax.set_xticks([0, 1], ["perfect foresight", "day-ahead myopia"])
    ax.set_ylim(min(values) * 0.995, max(values) * 1.003)
    delta = f["value_of_foresight"] / 1e6
    ax.annotate(f"foresight worth {delta:.1f} M€/yr",
                xy=(0.5, max(values)), xytext=(0, 8), textcoords="offset points",
                ha="center", fontsize=8, color=INK)
    ax.grid(axis="y")
    ax.set_ylabel("system cost (M€ / yr)")
    fig.savefig(FIGURES / "weather_foresight.pdf")
    plt.close(fig)


def values_weather(d):
    s = d["summary"]
    mix = d["mix"]
    off = mix["cap_wind_offshore_mw"] / 1000.0
    macros = {
        "WeatherYearsCount": f"{len(s['years'])}",
        "WeatherFirstYear": f"{s['years'][0]}",
        "WeatherReferenceYear": f"{s.get('reference_year', 2024)}",
        "WeatherLastYear": f"{s['years'][-1]}",
        "WeatherCostSpreadPct": f"{s['cost_spread_pct']:.1f}",
        "WeatherOffshoreMinGW": f"{off.min():.1f}",
        "WeatherOffshoreMaxGW": f"{off.max():.1f}",
        "WeatherSolarMinGW": f"{mix['cap_solar_pv_mw'].min() / 1000:.1f}",
        "WeatherSolarMaxGW": f"{mix['cap_solar_pv_mw'].max() / 1000:.1f}",
        "WeatherOnshoreMinGW": f"{mix['cap_wind_onshore_mw'].min() / 1000:.1f}",
        "WeatherOnshoreMaxGW": f"{mix['cap_wind_onshore_mw'].max() / 1000:.1f}",
        "WeatherBatteryMinGW": f"{mix['cap_battery_mw'].min() / 1000:.1f}",
        "WeatherBatteryMaxGW": f"{mix['cap_battery_mw'].max() / 1000:.1f}",
        "WeatherCarbonPrice": f"{s.get('carbon_price', 0):.0f}",
        "WeatherEmissionsMinMt": f"{mix['emissions_t'].min() / 1e6:.2f}",
        "WeatherEmissionsMaxMt": f"{mix['emissions_t'].max() / 1e6:.2f}",
        "WeatherPeakerMinGW": f"{mix['cap_peaker_mw'].min() / 1000:.1f}",
        "WeatherPeakerMaxGW": f"{mix['cap_peaker_mw'].max() / 1000:.1f}",
    }
    _write_values("weather_values.tex", macros, "results/weather_summary.json")


def fig_taxcap(d):
    """Figure: tax versus cap across weather years, on the European model.
    (a) under the cap, emissions are fixed and the carbon price moves; (b)
    under the tax, the price is fixed and emissions move."""
    t = d["table"]
    s = d["summary"]
    years = list(t.index)
    fig, axes = plt.subplots(1, 2, figsize=(6.1, 3.2), sharex=True)
    x = range(len(years))
    axes[0].bar(x, t["cap_co2_price_eur_t"], color=BLOCK_FILL, edgecolor="white")
    axes[0].axhline(s["tax_eur_t"], color="#D55E00", linewidth=1.2, linestyle="--")
    axes[0].annotate("the tax", xy=(0, s["tax_eur_t"]), xytext=(2, 4),
                     textcoords="offset points", fontsize=7.5, color="#D55E00")
    axes[0].set_ylabel("carbon price under the cap (€/t)")
    axes[0].set_title("(a) cap: emissions fixed, price moves", loc="left",
                      fontsize=9, color=INK)
    axes[1].bar(x, t["tax_emissions_t"] / 1e6, color="#D55E00", alpha=0.8,
                edgecolor="white")
    axes[1].axhline(s["budget_t"] / 1e6, color=BLUE, linewidth=1.2, linestyle="--")
    axes[1].annotate("the cap", xy=(0, s["budget_t"] / 1e6), xytext=(2, 4),
                     textcoords="offset points", fontsize=7.5, color=BLUE)
    axes[1].set_ylabel("emissions under the tax (Mt)")
    axes[1].set_title("(b) tax: price fixed, emissions move", loc="left",
                      fontsize=9, color=INK)
    for ax in axes:
        ax.set_xticks(list(x), [str(y)[2:] for y in years], fontsize=8)
        ax.grid(axis="y")
        ax.set_xlabel("weather year")
    fig.tight_layout()
    fig.savefig(FIGURES / "taxcap.pdf")
    plt.close(fig)


def values_taxcap(d):
    t = d["table"]
    s = d["summary"]
    budget = s["budget_t"]
    macros = {
        "TaxCapYears": f"{len(t)}",
        "TaxCapBudgetMt": f"{budget / 1e6:.1f}",
        "TaxCapTax": f"{s['tax_eur_t']:.0f}",
        "TaxCapSigmaMin": f"{s['sigma_min']:.0f}",
        "TaxCapSigmaMax": f"{s['sigma_max']:.0f}",
        "TaxCapSigmaRatio": f"{s['sigma_max'] / max(s['sigma_min'], 1.0):.1f}",
        "TaxCapEmissionsMinMt": f"{s['tax_emissions_min_t'] / 1e6:.1f}",
        "TaxCapEmissionsMaxMt": f"{s['tax_emissions_max_t'] / 1e6:.1f}",
        "TaxCapEmissionsSpreadPct": f"{s['tax_emissions_spread_pct_of_budget']:.0f}",
        "TaxCapOvershootMaxPct": f"{100 * (s['tax_emissions_max_t'] / budget - 1):.0f}",
        "TaxCapUndershootMaxPct": f"{100 * (1 - s['tax_emissions_min_t'] / budget):.0f}",
        "TaxCapReferenceYear": f"{s['reference_year']}",
    }
    _write_values("taxcap_values.tex", macros, "results/taxcap_summary.json")


def fig_costs_uncertainty(d, weather=None):
    """Figure 9.4: the same question asked of technology costs, and the two
    uncertainties put side by side.

    (a) the optimal mix in each cost scenario; (b) how far each output moves
    across weather years against how far it moves across cost scenarios,
    every range normalised to the reference system so the panel can hold
    gigawatts and euros on one axis."""
    mix = d["mix"]

    fig, axes = plt.subplots(1, 2, figsize=(6.9, 3.9),
                             gridspec_kw={"width_ratios": [1.0, 1.05]})

    ax = axes[0]
    _stacked_mix(ax, mix)  # sets ticks, labels and the y-axis itself
    ax.set_xticklabels([str(s) for s in mix.index], rotation=0, ha="center")
    ax.set_xlabel("cost scenario")
    ax.set_title("(a) the mix in each cost scenario", loc="left",
                 fontsize=9, color=INK)
    ax.set_ylim(top=ax.get_ylim()[1] * 1.42)  # headroom for the legend
    ax.legend(frameon=False, fontsize=6.5, ncol=2, loc="upper left")

    ax = axes[1]
    metrics = [
        ("Danish system cost", "dk_system_cost", 1.0),
        ("Danish emissions", "emissions_t", 1.0),
        ("solar", "cap_solar_pv_mw", 1.0),
        ("offshore wind", "cap_wind_offshore_mw", 1.0),
        ("battery", "cap_battery_mw", 1.0),
        ("peakers", "cap_peaker_mw", 1.0),
    ]
    labels, ypos = [], []
    for i, (label, col, _) in enumerate(metrics):
        if col not in mix.columns:
            continue
        ref = (float(mix.loc[COSTS_REFERENCE_SCENARIO, col])
               if COSTS_REFERENCE_SCENARIO in mix.index
               else float(mix[col].median()))
        if ref == 0:
            continue
        y = len(metrics) - i
        lo, hi = mix[col].min() / ref * 100, mix[col].max() / ref * 100
        ax.plot([lo, hi], [y + 0.14, y + 0.14], color=VERMILLION, lw=3,
                solid_capstyle="butt")
        if weather is not None and col in weather.columns:
            wlo, whi = weather[col].min() / ref * 100, weather[col].max() / ref * 100
            ax.plot([wlo, whi], [y - 0.14, y - 0.14], color=BLUE, lw=3,
                    solid_capstyle="butt")
        labels.append(label)
        ypos.append(y)
    ax.axvline(100, color="#999999", lw=0.8, linestyle="--")
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("range, % of the baseline-cost reference")
    ax.set_title("(b) which uncertainty dominates?", loc="left",
                 fontsize=9, color=INK)
    ax.grid(axis="x")
    ax.plot([], [], color=BLUE, lw=3, label="across weather years")
    ax.plot([], [], color=VERMILLION, lw=3, label="across cost scenarios")
    ax.legend(frameon=False, fontsize=7.5, loc="lower right")

    fig.tight_layout()
    fig.savefig(FIGURES / "costs_uncertainty.pdf")
    plt.close(fig)


# The middle scenario, which is the very cost table sections 7 and 9 solve
# on -- so panel (b) measures both spreads against the reference system
# rather than against a point that appears in neither sweep.
COSTS_REFERENCE_SCENARIO = "baseline"


def values_costs(d, weather=None):
    s = d["summary"]
    mix = d["mix"]
    scenarios = s["scenarios"]
    examples = s.get("scenario_examples", {})
    macros = {
        "CostScenarioCount": f"{len(scenarios)}",
        "CostHorizon": f"{s['horizon']}",
        # The trend the scenarios are built out of: technology-data's own
        # path from its near vintage to the horizon section 7 solves on,
        # scaled by CostTrendScalePct of it in each direction.
        "CostTrendFirstYear": f"{s['trend_base_year']}",
        "CostTrendLastYear": f"{s['horizon']}",
        "CostTrendScalePct": f"{100 * s['trend_scale']:.0f}",
        "CostSpreadPct": f"{s['cost_spread_pct']:.1f}",
        # The DANISH bill, in bn EUR/year: annualised capital plus operating
        # cost of the candidates this section chooses. The solver's objective
        # spans twelve zones of which eleven are fixed here, so quoting it
        # would report a European total and call it Denmark's bill.
        "CostSystemCostMinBn": f"{mix['dk_system_cost'].min() / 1e9:.1f}",
        "CostSystemCostMaxBn": f"{mix['dk_system_cost'].max() / 1e9:.1f}",
        "CostEmissionsMinMt": f"{mix['emissions_t'].min() / 1e6:.2f}",
        "CostEmissionsMaxMt": f"{mix['emissions_t'].max() / 1e6:.2f}",
        "CostSolarMinGW": f"{mix['cap_solar_pv_mw'].min() / 1000:.1f}",
        "CostSolarMaxGW": f"{mix['cap_solar_pv_mw'].max() / 1000:.1f}",
        "CostOffshoreMinGW": f"{mix['cap_wind_offshore_mw'].min() / 1000:.1f}",
        "CostOffshoreMaxGW": f"{mix['cap_wind_offshore_mw'].max() / 1000:.1f}",
        "CostBatteryMinGW": f"{mix['cap_battery_mw'].min() / 1000:.1f}",
        "CostBatteryMaxGW": f"{mix['cap_battery_mw'].max() / 1000:.1f}",
    }
    # What the scenarios actually did to a few headline machines, so the
    # prose can say how wide the band is in euros rather than describing it
    # only as "half the trend". EUR/kW, as the cost tables carry it.
    for tech, name in [("solar-utility", "Solar"), ("onwind", "Onshore"),
                       ("offwind", "Offshore"), ("battery storage", "Battery")]:
        row = examples.get(tech) or {}
        for key, suffix in [("pessimistic_eur_per_kw", "Pess"),
                            ("baseline_eur_per_kw", "Base"),
                            ("optimistic_eur_per_kw", "Opt")]:
            if key in row:
                macros[f"CostCapex{name}{suffix}"] = f"{row[key]:.0f}"
    if weather is not None:
        # The headline comparison: whose range is wider, as a share of the
        # reference system, averaged over the capacity metrics.
        cols = ["cap_solar_pv_mw", "cap_wind_offshore_mw", "cap_battery_mw"]
        ref = (mix.loc[COSTS_REFERENCE_SCENARIO]
               if COSTS_REFERENCE_SCENARIO in mix.index else mix.median())
        def width(frame):
            spans = [(frame[c].max() - frame[c].min()) / ref[c] * 100
                     for c in cols if c in frame.columns and ref[c] > 0]
            return sum(spans) / len(spans) if spans else float("nan")
        macros["CostCapacityRangePct"] = f"{width(mix):.0f}"
        macros["WeatherCapacityRangePct"] = f"{width(weather):.0f}"

        # The quoted comparisons of section 9's panel-(b) discussion, so the
        # prose cannot go stale against the figure: per-output ranges as a
        # share of the reference system, and the carbon-price ratios.
        def range_pct(frame, col):
            if col not in frame.columns or not ref.get(col, 0) > 0:
                return float("nan")
            return (frame[col].max() - frame[col].min()) / ref[col] * 100

        for name, col in [("Battery", "cap_battery_mw"),
                          ("OCGT", "cap_peaker_mw")]:
            macros[f"Cost{name}RangePct"] = f"{range_pct(mix, col):.0f}"
            macros[f"Weather{name}RangePct"] = f"{range_pct(weather, col):.0f}"
        for name, frame in [("Cost", mix), ("Weather", weather)]:
            prices = frame["emissions_t"]
            if prices.min() > 0:
                macros[f"{name}EmissionsRatio"] = f"{prices.max() / prices.min():.1f}"
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
# The hydrogen sector's own capacity, kept out of the electricity mix bars:
# a reformer and an electrolyser are not generating capacity and adding them
# to a stack of power plants would be a category error.
H2_TECHS = ["smr", "electrolyser", "h2_turbine"]

# The order the rungs are read in, and how they are named in a figure. The
# ladder is an argument, so the order is not cosmetic.
RUNG_LABELS = {
    "basic": "basic",
    "ev": "+ flexible EV",
    "ev_h2": "+ hydrogen",
}


def _ladder_rungs(ladder):
    """The rungs present in the results, in the argument's order."""
    return [r for r in RUNG_LABELS if r in set(ladder["rung"])]


def _budget_axis(frame):
    """Constrained budget points, tightest last, with their axis labels."""
    points = sorted(frame["budget_share"].dropna().unique(), reverse=True)
    return points, [f"{100 * p:.0f}%" for p in points]


def fig_expansion_ladder(d):
    """Figure 8.1: what each ingredient does to the carbon price and to the
    bill, as the system-wide budget tightens."""
    ladder = d["ladder"]
    rungs = _ladder_rungs(ladder)
    points, labels = _budget_axis(ladder)
    x = range(len(points))
    colors = [BLUE, VERMILLION, "#009E73", "#7B3294"]

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.1))
    for i, rung in enumerate(rungs):
        sub = ladder[ladder["rung"] == rung].set_index("budget_share")
        sigma = [sub.loc[p, "co2_price_eur_t"] for p in points]
        cost = [sub.loc[p, "system_cost_eur"] / 1e9 for p in points]
        style = dict(color=colors[i % len(colors)], linewidth=1.6,
                     marker="o", markersize=3.5, label=RUNG_LABELS[rung])
        # The hydrogen rung is a different system on its own baseline, so
        # its line is not commensurable with the other two. Dash it to say
        # that in the figure rather than only in the caption.
        if rung == "ev_h2":
            style |= dict(linestyle="--", linewidth=2.4, alpha=0.9)
        axes[0].plot(list(x), sigma, **style)
        axes[1].plot(list(x), cost, **style)

    for ax, ylabel in zip(axes, ["carbon price σ (€/t)",
                                 "system cost (bn€ / year)"]):
        ax.set_xticks(list(x), labels)
        ax.set_xlabel("CO$_2$ budget (share of unconstrained)")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y")
    axes[0].legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.savefig(FIGURES / "expansion_ladder.pdf")
    plt.close(fig)


VRE_TECHS = ["solar_pv", "wind_onshore", "wind_offshore"]


def _ladder_bars(ax, frame, techs, annotate=None):
    """Stacked capacity bars in GW, one per rung. Returns the bar tops."""
    xs = range(len(frame))
    bottom = pd.Series(0.0, index=frame.index)
    for tech in techs:
        col = f"cap_{tech}_mw"
        if col not in frame.columns:
            continue
        values = frame[col].fillna(0.0) / 1000.0
        if values.abs().max() < 1e-6:
            continue          # never built: keep it out of the legend too
        ax.bar(xs, values, bottom=bottom, color=LADDER_COLORS[tech],
               edgecolor="white", linewidth=0.8, width=0.6,
               label=LADDER_LABELS[tech])
        bottom = bottom + values.to_numpy()
    if annotate is not None:
        for i, value in enumerate(annotate):
            ax.annotate(f"σ = {value:.0f}", xy=(i, bottom.iloc[i]),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=7.5, color=INK)
    ax.set_xticks(list(xs), frame.index)
    ax.set_ylim(0, bottom.max() * 1.18)
    ax.grid(axis="y")
    return bottom


def fig_expansion_mix(d):
    """Figure 8.2: what each rung builds at the reference budget.

    Two panels, because one would hide the answer: solar is two thirds of
    every bar, so the differences between the rungs — which are entirely in
    the firm and flexible layer — are invisible at the scale of the whole
    mix. Panel (a) is the scale; panel (b) is the argument.
    """
    ladder = d["ladder"]
    reference = d["summary"]["reference_fraction"]
    rungs = _ladder_rungs(ladder)
    at_ref = ladder[ladder["budget_share"] == reference].set_index("rung")
    frame = at_ref.loc[[r for r in rungs if r in at_ref.index]].copy()
    sigma = frame["co2_price_eur_t"].to_numpy()
    frame.index = [RUNG_LABELS[r] for r in frame.index]

    every = [t for t in LADDER_COLORS
             if f"cap_{t}_mw" in frame.columns and not t.startswith("battery_")
             and t not in H2_TECHS]
    flexible = [t for t in every if t not in VRE_TECHS]

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.5))
    _ladder_bars(axes[0], frame, every, annotate=sigma)
    _ladder_bars(axes[1], frame, flexible)
    axes[0].set_ylabel("capacity built (GW)")
    axes[0].set_title("(a) the whole mix", fontsize=8.5, color=INK)
    axes[1].set_title("(b) firm and flexible only", fontsize=8.5, color=INK)

    handles, labels = [], []
    for ax in axes:
        for handle, label in zip(*ax.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    fig.legend(handles, labels, frameon=False, fontsize=7.5, ncol=4,
               loc="outside lower center")
    fig.savefig(FIGURES / "expansion_mix.pdf")
    plt.close(fig)


def _zone_bars(ax, zones, order):
    ys = range(len(zones))
    left = pd.Series(0.0, index=zones.index)
    for tech in order:
        values = zones[tech].fillna(0.0) / 1000.0
        if values.abs().max() < 1e-6:
            continue
        ax.barh(ys, values, left=left, color=LADDER_COLORS[tech],
                edgecolor="white", linewidth=0.6, height=0.68,
                label=LADDER_LABELS[tech])
        left = left + values.to_numpy()
    ax.set_yticks(list(ys), zones.index)
    ax.grid(axis="x")
    return left


def fig_expansion_zones(d):
    """Figure 8.3: where the system chooses to build it.

    Germany takes an order of magnitude more than anyone else, which is
    itself the finding — but on one axis it leaves eleven zones as slivers.
    So the second panel drops Germany and lets the rest be read.
    """
    zones = d["zones"].copy()
    zones["battery"] = zones[[c for c in zones.columns
                              if c.startswith("battery_")]].sum(axis=1)
    order = [c for c in LADDER_COLORS
             if c in zones.columns and not c.startswith("battery_")
             and c not in H2_TECHS]
    zones = zones.loc[zones[order].sum(axis=1).sort_values().index]
    rest = zones.drop(index="DE", errors="ignore")

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.8))
    _zone_bars(axes[0], zones, order)
    _zone_bars(axes[1], rest, order)
    axes[0].set_title("(a) all twelve zones", fontsize=8.5, color=INK)
    axes[1].set_title("(b) without Germany", fontsize=8.5, color=INK)
    for ax in axes:
        ax.set_xlabel("capacity built (GW)")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=7.5, ncol=4,
               loc="outside lower center")
    fig.savefig(FIGURES / "expansion_zones.pdf")
    plt.close(fig)


def fig_expansion_hydrogen(d):
    """Figure 8.4: what the hydrogen sector does as the budget tightens.

    (a) where the hydrogen comes from, reformed or electrolysed, at the
    reference budget; (b) the electrolysers' running hours across the
    budget, which is the quantity that decides whether the route pays --
    an electrolyser is cheap per MWh only when it is not standing idle.
    """
    ladder = d["ladder"]
    reference = d["summary"]["reference_fraction"]
    rungs = _ladder_rungs(ladder)
    points, labels = _budget_axis(ladder)

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.3))

    at_ref = ladder[ladder["budget_share"] == reference].set_index("rung")
    frame = at_ref.loc[[r for r in rungs if r in at_ref.index]]
    xs = range(len(frame))
    smr = frame["h2_from_smr_mwh"].fillna(0.0) / 1e6
    ely = frame.get("h2_from_electrolysis_mwh",
                    pd.Series(0.0, index=frame.index)).fillna(0.0) / 1e6
    axes[0].bar(xs, smr, color=LADDER_COLORS["smr"], edgecolor="white",
                width=0.6, label="reformed from gas")
    axes[0].bar(xs, ely, bottom=smr, color=LADDER_COLORS["electrolyser"],
                edgecolor="white", width=0.6, label="electrolysed")
    axes[0].set_xticks(list(xs), [RUNG_LABELS[r] for r in frame.index])
    axes[0].set_ylabel("hydrogen supplied (TWh)")
    axes[0].set_title("(a) where the hydrogen comes from", fontsize=8.5,
                      color=INK)
    axes[0].grid(axis="y")
    axes[0].legend(frameon=False, fontsize=7.5, loc="upper left")

    colors = [BLUE, VERMILLION, "#009E73"]
    for i, rung in enumerate(rungs):
        sub = ladder[ladder["rung"] == rung].set_index("budget_share")
        flh = [sub.loc[p_, "electrolyser_flh"] if "electrolyser_flh" in sub
               else 0.0 for p_ in points]
        if max(flh) <= 0:
            continue
        axes[1].plot(list(range(len(points))), flh, marker="o", markersize=3.5,
                     linewidth=1.6, color=colors[i % len(colors)],
                     label=RUNG_LABELS[rung])
    axes[1].set_xticks(list(range(len(points))), labels)
    axes[1].set_xlabel("CO$_2$ budget (share of unconstrained)")
    axes[1].set_ylabel("electrolyser running hours (h/year)")
    axes[1].set_title("(b) how hard they run", fontsize=8.5, color=INK)
    axes[1].grid(axis="y")
    if axes[1].get_legend_handles_labels()[0]:
        axes[1].legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.savefig(FIGURES / "expansion_hydrogen.pdf")
    plt.close(fig)


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

    # The mid-budget point, where the section's headline comparison with
    # section 7's Danish carbon price lives.
    mids = sorted(p for p in ladder["budget_share"].dropna().unique()
                  if p > reference)
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
            "ExpElectrolyserHours":
                f"{float(p2x.get('electrolyser_flh', 0.0) or 0.0):,.0f}".replace(",", "{,}"),
            "ExpElectrolyticSharePct": (
                f"{100 * p2x.get('h2_from_electrolysis_mwh', 0.0) / supplied:.0f}"
                if supplied else "0"
            ),
            "ExpHTwoToPowerTWh":
                f"{float(p2x.get('h2_to_power_mwh', 0.0) or 0.0) / 1e6:.1f}",
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

    # The time-aggregation check for this section: the top rung's reference
    # case at all 8760 hours beside the aggregated answer, and beside the
    # every-k-th-hour answer at the same size, which is what earlier drafts
    # used and what over-stated the seasonal store several-fold.
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
                "ExpHTwoStoreStrideRatio":
                    f"{stride['h2_store_mwh'] / max(full['h2_store_mwh'], 1.0):.1f}",
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
        fig_weather_foresight(results["storage"])
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
        fig_greenfield_breakdown(results["greenfield"])
        fig_greenfield_scenarios(results["greenfield"])
        if results["greenfield"].get("cost_recovery") is not None:
            fig_greenfield_recovery(results["greenfield"])
            table_greenfield_values(results["greenfield"])
        if results["greenfield"].get("scarcity") is not None:
            fig_greenfield_scarcity(results["greenfield"])
    else:
        print("skipping greenfield figures — run pipeline/run_greenfield.py first")
    if "weather" in results:
        fig_weather_mix(results["weather"])
        fig_weather_cost(results["weather"])
        fig_weather_pdc(results["weather"])
    if "taxcap" in results:
        fig_taxcap(results["taxcap"])
        values_taxcap(results["taxcap"])
    else:
        print("skipping weather figures — run pipeline/run_weather.py first")
    if "costs" in results:
        fig_costs_uncertainty(
            results["costs"],
            weather=results.get("weather", {}).get("mix"),
        )
    else:
        print("skipping cost-vintage figure — run pipeline/run_costs.py first")
    if "expansion" in results:
        fig_expansion_ladder(results["expansion"])
        fig_expansion_mix(results["expansion"])
        fig_expansion_zones(results["expansion"])
        fig_expansion_hydrogen(results["expansion"])
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
        values_costs(
            results["costs"],
            weather=results.get("weather", {}).get("mix"),
        )
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
