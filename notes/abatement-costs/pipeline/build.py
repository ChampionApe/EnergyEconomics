"""Stage 3: turn results into the note's figures and quoted numbers.

    python pipeline/build.py

Reads `results/`, writes `writing/generated/`. It reads **nothing else**: no
model code, no recomputation, no solving. Two guards enforce that rather than
trusting discipline — an import blocker that fails on `import model`, and a
`read()` helper that is the only way a file enters this script.

If a figure needs a number that is not in `results/`, the fix is to have
`pipeline/run_simple.py` or `pipeline/run_technical.py` write it.

Writes:

    writing/generated/figures/baseline.pdf                  fig 1.1
    writing/generated/figures/mac_curve.pdf                 fig 1.2
    writing/generated/figures/optimum.pdf                   fig 1.3
    writing/generated/figures/technical_marginal_cost.pdf   fig 2.1
    writing/generated/figures/technical_mac.pdf             fig 2.2
    writing/generated/numbers.tex                           quoted-number macros
"""

import json
import os
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


def _forbid_model_imports():
    """Fail loudly if anything pulls in model code.

    Importing a model module for a constant or an axis label is the usual way
    this stage quietly turns into a solve. Make it an error rather than a
    slowdown nobody notices.
    """

    class _Blocker:
        # find_spec, not find_module: the latter is not called at all from
        # Python 3.12 onwards, so a blocker written against it does nothing.
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {"model", "models"}:
                raise ImportError(
                    f"build.py must not import {name!r}. This stage reads only "
                    f"results/. If you need a value from the model, have a "
                    f"run_* script write it into results/.")
            return None

    sys.meta_path.insert(0, _Blocker())


_OPENED = []


def read(name: str):
    """The only way a file enters this script. Refuses anything outside results/."""
    path = RESULTS / name
    if not path.exists():
        raise FileNotFoundError(
            f"{name} is not in results/ -- run pipeline/run_simple.py and "
            "pipeline/run_technical.py first. Stage 3 may not compute it.")
    _OPENED.append(name)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------
# One restrained style, shared with the other notes in the series: recessive
# axes and grid, colour only where it carries meaning, and the two hues
# colourblind-safe (Okabe-Ito). Identity is always also carried by a label.
BLUE = "#0072B2"
VERMILLION = "#D55E00"
INK = "#333333"
AXIS = "#666666"

plt.rcParams.update({
    "figure.figsize": (7.2, 3.6),
    "figure.dpi": 160,
    "savefig.bbox": "tight",
    "font.size": 9,
    "axes.labelsize": 9.5,
    "legend.fontsize": 8.5,
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK,
    "xtick.color": AXIS,
    "ytick.color": AXIS,
    "axes.grid": True,
    "grid.color": "#e0e0e0",
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "lines.linewidth": 1.8,
})

CARBON = "EUR/ton CO$_2$"
ABATED = "Abated emissions, ton CO$_2$"


def save(fig, name: str):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    if os.environ.get("FIGURE_PNG"):
        fig.savefig(Path(os.environ["FIGURE_PNG"]) / f"{name}.png", dpi=140)
    plt.close(fig)
    print(f"wrote writing/generated/figures/{name}.pdf")


def _origin_lines(ax, vertical=True):
    """The thin black axes through the origin the note's figures all carry."""
    ax.axhline(0.0, linewidth=0.8, color="black", alpha=0.5, zorder=1)
    if vertical:
        ax.axvline(0.0, linewidth=0.8, color="black", alpha=0.5, zorder=1)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def figure_baseline():
    """Figure 1.1: consumption and emissions as fossil energy use rises.

    Consumption is single-peaked because F is concave and extraction is
    linear; emissions are the straight line through the origin with slope
    phi. The baseline is where the hump peaks, and it is marked on both
    curves so that E0, C0 and M0 can be read off one picture.
    """
    grid = read("simple_baseline.csv")
    summary = read("simple_summary.json")
    base = summary["baseline"]

    fig, ax = plt.subplots()
    ax.plot(grid.energy, grid.consumption, color=BLUE, label="$C$")
    ax.plot(grid.energy, grid.emissions, color=VERMILLION, linestyle="--",
            label="$M$")
    _origin_lines(ax, vertical=False)

    ax.plot([base["energy"], base["energy"]],
            [base["consumption"], base["emissions"]],
            "o", markersize=5.5, color="black", zorder=5)
    ax.annotate("$(E^0, C^0)$", (base["energy"], base["consumption"]),
                textcoords="offset points", xytext=(0, -16), ha="center",
                fontsize=9, color=INK)
    ax.annotate("$(E^0, M^0)$", (base["energy"], base["emissions"]),
                textcoords="offset points", xytext=(-6, 8), ha="right",
                fontsize=9, color=INK)

    ax.set_xlabel("$E$")
    ax.set_xlim(0.0, summary["energy_grid_max"])
    ax.legend(loc="upper left")
    save(fig, "baseline")


def figure_mac_curve():
    """Figure 1.2: the marginal abatement cost curve.

    Zero at the baseline by construction, negative to the left of it (where
    burning more energy would still pay), and vertical as abatement
    approaches M0, since the last tonne means giving up fossil energy
    altogether.
    """
    mac = read("simple_mac.csv")
    summary = read("simple_summary.json")
    baseline_emissions = summary["baseline"]["emissions"]

    fig, ax = plt.subplots()
    ax.plot(mac.abatement, mac.marginal_abatement_cost, color=BLUE)
    _origin_lines(ax)

    ax.axvline(baseline_emissions, linewidth=1.0, color=INK, linestyle=":")
    ax.annotate("$M^0$", (baseline_emissions, 0.0),
                textcoords="offset points", xytext=(-5, 6), ha="right",
                fontsize=9, color=INK)

    ax.set_xlim(summary["abatement_grid_min"], baseline_emissions * 1.04)
    ax.set_ylim(-2.5, 10.0)
    ax.set_xlabel(ABATED)
    ax.set_ylabel(CARBON)
    save(fig, "mac_curve")


def figure_optimum():
    """Figure 1.3: marginal abatement cost against marginal damage.

    Both are drawn against abatement, so marginal damage slopes down: the
    more has been abated, the less harm the remaining tonne does. They cross
    once, at the optimal abatement A* and the carbon price tau* that
    supports it.
    """
    mac = read("simple_mac.csv")
    summary = read("simple_summary.json")
    optimum = summary["optimum"]
    baseline_emissions = summary["baseline"]["emissions"]

    fig, ax = plt.subplots()
    ax.plot(mac.abatement, mac.marginal_abatement_cost, color=BLUE,
            label="$MAC$")
    ax.plot(mac.abatement, mac.marginal_damages, color=VERMILLION,
            linestyle="--", label=r"$\partial D/\partial M$")
    _origin_lines(ax)

    ax.plot(optimum["abatement"], optimum["carbon_price"], "o", markersize=5.5,
            color="black", zorder=5)
    ax.annotate(r"$(A^*, \tau^*)$",
                (optimum["abatement"], optimum["carbon_price"]),
                textcoords="offset points", xytext=(-6, 20), ha="right",
                fontsize=9, color=INK)

    ax.set_xlim(0.0, baseline_emissions * 1.01)
    ax.set_ylim(0.0, 10.0)
    ax.set_xlabel(ABATED)
    ax.set_ylabel(CARBON)
    ax.legend(loc="upper left")
    save(fig, "optimum")


def figure_technical_marginal_cost():
    """Figure 2.1: what the technology menu does to the cost of emitting.

    Without a menu, emitting a tonne costs exactly the damage it does, so the
    line is the 45-degree line. With one, part of the tonne is removed
    instead of borne, and the cost of emitting falls below it — but only once
    the carbon price is high enough to make a technology worth running. The
    shaded gap is what the menu is worth.
    """
    costs = read("technical_marginal_cost.csv")

    fig, ax = plt.subplots()
    ax.plot(costs.marginal_damages, costs.without_abatement, color=BLUE,
            label="Without abatement")
    ax.plot(costs.marginal_damages, costs.with_abatement, color=VERMILLION,
            linestyle="--", label="With abatement")
    ax.fill_between(costs.marginal_damages, costs.with_abatement,
                    costs.without_abatement, color=BLUE, alpha=0.15,
                    linewidth=0)
    _origin_lines(ax)

    ax.set_xlim(0.0, costs.marginal_damages.max())
    ax.set_ylim(0.0, costs.without_abatement.max())
    ax.set_xlabel("$D'(M)$")
    ax.set_ylabel("Marginal cost of emissions")
    ax.legend(loc="upper left")
    save(fig, "technical_marginal_cost")


def figure_technical_mac():
    """Figure 2.2: the abatement cost curve, with and without the menu.

    The two curves start together — at a carbon price below every
    technology's cost, nothing is deployed and output reduction is again the
    only channel. As the price passes each technology's average cost the
    curve steps sideways: the same abatement is bought more cheaply, so the
    technology curve lies below and to the right of the other.
    """
    simple = read("simple_mac.csv")
    technical = read("technical_mac.csv")
    summary = read("technical_summary.json")

    fig, ax = plt.subplots()
    positive = simple[simple.abatement >= 0.0]
    ax.plot(positive.abatement, positive.marginal_abatement_cost, color=BLUE,
            label="Without technology")
    ax.plot(technical.abatement, technical.marginal_abatement_cost,
            color=VERMILLION, linestyle="--", label="With technology")
    _origin_lines(ax)

    ax.set_xlim(0.0, summary["max_abatement"] * 1.02)
    ax.set_ylim(0.0, 10.0)
    ax.set_xlabel(ABATED)
    ax.set_ylabel(CARBON)
    ax.legend(loc="upper left")
    save(fig, "technical_mac")


# ---------------------------------------------------------------------------
# Numbers quoted in the prose
# ---------------------------------------------------------------------------
def numbers():
    """Macros for every number the note could quote, so text cannot drift.

    The note as it stands quotes none of them in prose -- it is a note about
    shapes, not levels -- so this file is currently loaded and unused. It
    exists so that the first sentence that does want a number has somewhere
    to get it from, rather than typing one in and letting it go stale on the
    next rebuild.
    """
    simple = read("simple_summary.json")
    technical = read("technical_summary.json")
    menu = read("technical_menu.csv")

    # LaTeX command names may contain letters only, so any digit that ends up
    # in a generated macro name is spelled out. Getting this wrong produces a
    # "Missing \begin{document}" error several files away from the cause.
    DIGITS = str.maketrans({"0": "Zero", "1": "One", "2": "Two", "3": "Three",
                            "4": "Four", "5": "Five", "6": "Six", "7": "Seven",
                            "8": "Eight", "9": "Nine"})

    def macro(name, value):
        return f"\\newcommand{{\\{name.translate(DIGITS)}}}{{{value}}}"

    parameters = simple["parameters"]
    baseline = simple["baseline"]
    optimum = simple["optimum"]
    tech_optimum = technical["optimum"]

    lines = [
        "% Generated by pipeline/build.py. Do not edit.",
        "% Every number the note quotes in prose is defined here, so that the",
        "% text cannot drift away from the figure it describes.",
        "",
        "% Section 1: the parameters behind figures 1.1-1.3",
        macro("numAlpha", f"{parameters['output_elasticity']:.2f}"),
        macro("numGamma", f"{parameters['productivity']:.0f}"),
        macro("numEnergyPrice", f"{parameters['energy_price']:.0f}"),
        macro("numPhi", f"{parameters['emission_intensity']:.2f}"),
        macro("numDamageCurvature", f"{parameters['damage_curvature']:.0f}"),
        "",
        "% Section 1: the baseline and the optimum",
        macro("numBaselineEnergy", f"{baseline['energy']:.3f}"),
        macro("numBaselineConsumption", f"{baseline['consumption']:.3f}"),
        macro("numBaselineEmissions", f"{baseline['emissions']:.4f}"),
        macro("numOptEnergy", f"{optimum['energy']:.3f}"),
        macro("numOptConsumption", f"{optimum['consumption']:.3f}"),
        macro("numOptEmissions", f"{optimum['emissions']:.4f}"),
        macro("numOptAbatement", f"{optimum['abatement']:.4f}"),
        macro("numOptCarbonPrice", f"{optimum['carbon_price']:.2f}"),
        macro("numOptAbatementRate",
              f"{simple['abatement_rate_at_optimum']:.0%}".replace("%", r"\%")),
        "",
        "% Section 2: the technology menu",
        macro("numMenuPotential",
              f"{technical['total_potential']:.0%}".replace("%", r"\%")),
        macro("numMenuSize", f"{len(menu)}"),
    ]
    for row in menu.itertuples():
        lines += [
            macro(f"numTheta{row.technology}", f"{row.potential:.1f}"),
            macro(f"numCost{row.technology}", f"{row.average_cost:.1f}"),
            macro(f"numSigma{row.technology}", f"{row.cost_dispersion:.2f}"),
        ]
    lines += [
        "",
        "% Section 2: the optimum once the menu is available",
        macro("numTechOptCarbonPrice", f"{tech_optimum['carbon_price']:.2f}"),
        macro("numTechOptEnergy", f"{tech_optimum['energy']:.3f}"),
        macro("numTechOptEmissions", f"{tech_optimum['emissions']:.4f}"),
        macro("numTechOptAbatement", f"{tech_optimum['abatement']:.4f}"),
        macro("numTechOptAbatedShare",
              f"{tech_optimum['abated_share']:.0%}".replace("%", r"\%")),
        "",
    ]

    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "numbers.tex").write_text("\n".join(lines), encoding="utf-8")
    print("wrote writing/generated/numbers.tex")


def main():
    _forbid_model_imports()

    figure_baseline()
    figure_mac_curve()
    figure_optimum()
    figure_technical_marginal_cost()
    figure_technical_mac()
    numbers()

    print(f"\nstage 3 read only: {sorted(set(_OPENED))}")
    print("stage 3 complete")


if __name__ == "__main__":
    main()
