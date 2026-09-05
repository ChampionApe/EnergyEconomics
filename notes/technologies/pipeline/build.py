"""Stage 3: turn results into the note's figures, tables and quoted numbers.

    python pipeline/build.py

Reads `results/`, writes `writing/generated/`. It reads **nothing else**: no
model code, no `data/`, no recomputation. The guard below enforces that at
runtime rather than trusting discipline, because the invariant is easy to
break by reaching for one convenient constant.

If a figure needs a number that is not in `results/`, the fix is to have
`pipeline/run_costs.py` write it.

Writes:

    writing/generated/figures/tech_decomposition.pdf
    writing/generated/figures/lcoe_capacityfactor.pdf
    writing/generated/figures/lcoe_discountrate.pdf
    writing/generated/figures/lcoe_projections.pdf
    writing/generated/figures/lcoe_learning.pdf
    writing/generated/tables/tech_qualitative.tex
    writing/generated/tables/tech_quantitative.tex
    writing/generated/tables/heat_storage.tex
    writing/generated/tables/planttypes_mapping.tex
    writing/generated/numbers.tex
"""

import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

NOTE = Path(__file__).resolve().parent.parent
RESULTS = NOTE / "results"
GENERATED = NOTE / "writing" / "generated"
FIGURES = GENERATED / "figures"
TABLES = GENERATED / "tables"


_OPENED = []


def read(name: str) -> pd.DataFrame:
    path = RESULTS / name
    if not path.exists():
        raise FileNotFoundError(
            f"{name} is not in results/. Stage 3 may not compute it -- have "
            "pipeline/run_costs.py write it instead.")
    _OPENED.append(name)
    return pd.read_csv(path)


def read_summary() -> dict:
    _OPENED.append("summary.json")
    return json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "figure.figsize": (7.2, 4.4),
    "figure.dpi": 160,
    "savefig.bbox": "tight",
    "font.size": 9,
    "axes.titlesize": 9.5,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "legend.frameon": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "lines.linewidth": 1.6,
})

# One colour per cost category, used identically in every figure that splits a
# cost. Chosen to stay distinguishable in greyscale, since the note is printed.
CATEGORY_COLOURS = {
    "capital": "#1F4E79",
    "fixed_om": "#6FA8DC",
    "fuel": "#B25900",
    "variable_om": "#E8B76A",
}
CATEGORY_LABELS = {
    "capital": "Annuitised investment",
    "fixed_om": "Fixed O\\&M",
    "fuel": "Fuel",
    "variable_om": "Variable O\\&M",
}
CATEGORY_LABELS_PLAIN = {
    "capital": "Annuitised investment",
    "fixed_om": "Fixed O&M",
    "fuel": "Fuel",
    "variable_om": "Variable O&M",
}

TECH_COLOURS = {
    "nuclear": "#7B3294",
    "coal": "#4D4D4D",
    "CCGT": "#B25900",
    "OCGT": "#E8853A",
    "oil": "#8C4A2F",
    "onwind": "#2E7D57",
    "offwind": "#1B6E8C",
    "solar-utility": "#D4A017",
    "hydro": "#3B6EA5",
}


def save(fig, name: str):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}.pdf")
    if os.environ.get("FIGURE_PNG"):
        fig.savefig(Path(os.environ["FIGURE_PNG"]) / f"{name}.png", dpi=140)
    plt.close(fig)
    print(f"wrote writing/generated/figures/{name}.pdf")


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def figure_decomposition():
    """One euro per MWh, split into the cost categories that have a per-MWh form.

    Three of section 2's four categories appear, with the variable category
    split into its fuel and non-fuel halves because the split is the whole
    point of the figure. Adjustment costs are absent and cannot be added: they
    are a cost of a *pattern* of operation, so they have no value at a single
    utilisation, which is the only thing this axis knows about.
    """
    data = read("decomposition.csv")
    data = data[~data.family.isin(["Storage"])].copy()
    data = data.sort_values("total")
    # Two rows produce heat rather than electricity. They belong in the figure
    # -- the cost anatomy is the same -- but the axis is not the same good, so
    # the label says so rather than leaving the reader to notice.
    data["label"] = np.where(data.family == "Heat",
                             data.label + " *", data.label)

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    left = np.zeros(len(data))
    for key in ["capital", "fixed_om", "fuel", "variable_om"]:
        ax.barh(data.label, data[key], left=left, height=0.68,
                color=CATEGORY_COLOURS[key], label=CATEGORY_LABELS_PLAIN[key],
                edgecolor="white", linewidth=0.5)
        left = left + data[key].to_numpy()

    for y, (total, cf) in enumerate(zip(data.total, data.capacity_factor)):
        ax.text(total + 3, y, f"{total:.0f}  ({cf:.0%})", va="center",
                fontsize=7.5, color="#333333")

    ax.set_xlabel("EUR per MWh of output, at the reference utilisation\n"
                  "* per MWh of heat, not electricity")
    ax.set_xlim(0, data.total.max() * 1.22)
    ax.legend(loc="lower right", ncol=1)
    ax.grid(axis="y", visible=False)
    save(fig, "tech_decomposition")


def figure_geography():
    """Section 6: how a European levelised cost becomes a foreign one.

    A waterfall rather than a bar chart of regional levels, deliberately. A
    reader can take a level away from a bar chart and leave the caveats
    behind; a waterfall cannot be read at all without reading the channels.
    """
    steps = read("geography_waterfall.csv")
    regions = [r for r in steps.region.unique()]

    fig, axes = plt.subplots(1, len(regions), figsize=(7.2, 3.9), sharey=True)
    axes = np.atleast_1d(axes)

    for ax, region in zip(axes, regions):
        sub = steps[steps.region == region].reset_index(drop=True)
        x = np.arange(len(sub))
        for i, row in sub.iterrows():
            if row.step in ("start", "end"):
                ax.bar(i, row.level, width=0.62, color="#1F4E79",
                       edgecolor="white", linewidth=0.5)
                ax.text(i, row.level + 1.2, f"{row.level:.0f}", ha="center",
                        va="bottom", fontsize=8, fontweight="bold")
            else:
                bottom = row.level - row.delta
                colour = "#2E7D57" if row.delta < 0 else "#B25900"
                ax.bar(i, row.delta, bottom=bottom, width=0.62, color=colour,
                       edgecolor="white", linewidth=0.5)
                offset = -2.0 if row.delta < 0 else 1.2
                va = "top" if row.delta < 0 else "bottom"
                ax.text(i, min(bottom, row.level) + offset if row.delta < 0
                        else max(bottom, row.level) + offset,
                        f"{row.delta:+.0f}", ha="center", va=va, fontsize=7.5,
                        color=colour)
            # the dotted connector that makes a waterfall readable
            if i < len(sub) - 1:
                ax.plot([i + 0.31, i + 1 - 0.31], [row.level, row.level],
                        color="#999999", linewidth=0.7, linestyle=":")
        ax.set_xticks(x)
        ax.set_xticklabels(sub.label, rotation=35, ha="right", fontsize=7.5)
        ax.set_title(f"Europe to {region}", fontsize=9)
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, steps.level.max() * 1.25)

    axes[0].set_ylabel("Utility solar, EUR/MWh")
    save(fig, "geography_waterfall")


def figure_capacityfactor():
    """Levelised cost against how much the plant runs."""
    grid = read("lcoe_capacityfactor.csv")
    envelope = read("lcoe_envelope.csv")
    costs = read("technology_costs.csv").set_index("technology")

    fig, (left, right) = plt.subplots(1, 2, figsize=(7.6, 3.9),
                                      gridspec_kw={"width_ratios": [1.15, 1]})

    # Left: the thermal dispatchables, whose utilisation is a choice. The
    # shaded bands say which technology owns which duty -- the lower envelope
    # read back onto the horizontal axis, which is the whole point of the
    # panel and is hard to see when it is drawn as one more line.
    bands, previous, start = [], None, 0.0
    for row in envelope.itertuples():
        if row.cheapest != previous:
            if previous is not None:
                bands.append((start, row.full_load_hours, previous))
            previous, start = row.cheapest, row.full_load_hours
    bands.append((start, 8760.0, previous))

    for lower, upper, tech in bands:
        if lower > 500:
            left.axvline(lower, color="#999999", linestyle=":", linewidth=0.9,
                         zorder=0)
            left.annotate(f"{lower:,.0f} h", (lower, 316),
                          textcoords="offset points", xytext=(3, 0),
                          ha="left", va="top", fontsize=7, color="#777777")
        if upper - lower > 1100:
            left.text((lower + upper) / 2, 12, costs.loc[tech, "label"],
                      ha="center", va="bottom", fontsize=7.5,
                      color=TECH_COLOURS[tech],
                      bbox=dict(facecolor="white", edgecolor="none",
                                pad=1.2, alpha=0.85))

    for tech in ["nuclear", "coal", "CCGT", "OCGT", "oil"]:
        series = grid[grid.technology == tech]
        left.plot(series.full_load_hours, series.lcoe,
                  color=TECH_COLOURS[tech], label=costs.loc[tech, "label"])
    left.plot(envelope.full_load_hours, envelope.lcoe, color="black",
              linewidth=3.0, alpha=0.30, zorder=1)
    left.set_xlim(0, 8760)
    left.set_ylim(0, 320)
    left.set_xlabel("Full-load hours per year")
    left.set_ylabel("Levelised cost, EUR/MWh")
    left.set_title("Dispatchable: utilisation is a choice", loc="left")
    left.legend(loc="upper right", fontsize=7.5)

    # Right: the same curves for the weather-driven technologies, with a marker
    # where their own site actually puts them. The point of the panel is that
    # the marker is not a decision.
    for tech in ["onwind", "offwind", "solar-utility", "hydro"]:
        series = grid[grid.technology == tech]
        right.plot(series.full_load_hours, series.lcoe, alpha=0.45,
                   color=TECH_COLOURS[tech], label=costs.loc[tech, "label"])
        cf = costs.loc[tech, "capacity_factor"]
        hours, lcoe = cf * 8760, costs.loc[tech, "lcoe_reference"]
        right.vlines(hours, 0, lcoe, color=TECH_COLOURS[tech],
                     linestyle=":", linewidth=1.0, alpha=0.7)
        right.plot(hours, lcoe, "o", color=TECH_COLOURS[tech], markersize=6.5,
                   markeredgecolor="white", markeredgewidth=0.9, zorder=5)
        # The label goes at the axis, not at the marker: four markers sit close
        # together in cost and would collide.
        right.annotate(f"{hours:,.0f} h", (hours, 4), rotation=90,
                       ha="center", va="bottom", fontsize=7,
                       color=TECH_COLOURS[tech])
    right.set_xlim(0, 8760)
    right.set_ylim(0, 320)
    right.set_xlabel("Full-load hours per year")
    right.set_title("Weather-driven: it is not", loc="left")
    right.legend(loc="upper right", fontsize=7.5)

    save(fig, "lcoe_capacityfactor")


def figure_discountrate():
    """What financing does to the ranking."""
    grid = read("lcoe_discountrate.csv")
    costs = read("technology_costs.csv").set_index("technology")
    summary = read_summary()

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for tech in ["nuclear", "offwind", "onwind", "solar-utility", "coal",
                 "CCGT", "OCGT"]:
        series = grid[grid.technology == tech]
        ax.plot(series.discount_rate * 100, series.lcoe,
                color=TECH_COLOURS[tech], label=costs.loc[tech, "label"])

    crossover = summary.get("nuclear_ccgt_rate_crossover")
    if crossover:
        ax.axvline(crossover * 100, color="#999999", linestyle=":", linewidth=1.2)
        ax.annotate(f"nuclear and CCGT\nswap places at {crossover:.1%}",
                    xy=(crossover * 100, 130), xytext=(crossover * 100 - 2.9, 140),
                    fontsize=7.5, color="#555555")

    ax.axvline(summary["discount_rate"] * 100, color="#333333",
               linestyle="--", linewidth=1.0)
    ax.annotate("the note's\nreference rate",
                xy=(summary["discount_rate"] * 100, 20),
                xytext=(summary["discount_rate"] * 100 + 0.25, 12),
                fontsize=7.5, color="#333333")

    ax.set_xlabel("Real discount rate, per cent")
    ax.set_ylabel("Levelised cost, EUR/MWh")
    ax.set_xlim(2, 12)
    ax.set_ylim(0, 280)
    ax.legend(loc="upper left", ncol=2, fontsize=7.5)
    save(fig, "lcoe_discountrate")


def figure_projections():
    """What costs have done, and what the catalogue expects them to do."""
    learning = read("learning.csv")
    projections = read("cost_projections.csv")
    vintages = read("cost_vintages.csv")
    costs = read("technology_costs.csv").set_index("technology")

    fig, (left, right) = plt.subplots(1, 2, figsize=(7.6, 3.7))

    price = learning.dropna(subset=["module_price_usd_per_w"])
    left.semilogy(price.year, price.module_price_usd_per_w, color="#D4A017",
                  marker="o", markersize=2.5, linewidth=1.4)
    left.set_ylabel("Solar module price, USD per watt (log scale)")
    left.set_xlabel("Year")
    left.set_title("Realised: what solar modules cost", loc="left")
    left.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{v:g}" if v >= 1 else f"{v:.2f}"))

    for tech in ["solar-utility", "onwind", "offwind", "CCGT", "nuclear"]:
        series = projections[projections.technology == tech]
        if series.empty:
            continue
        right.plot(series.cost_year, series.index_2025,
                   color=TECH_COLOURS.get(tech, "#666666"),
                   marker="o", markersize=3, label=costs.loc[tech, "label"])
    battery = projections[projections.technology == "battery storage"]
    if not battery.empty:
        right.plot(battery.cost_year, battery.index_2025, color="#7B3294",
                   marker="o", markersize=3, linestyle="--",
                   label="Battery cells")
    right.axhline(100, color="#333333", linewidth=0.8)
    right.set_ylabel("Investment cost, 2025 = 100")
    right.set_xlabel("Projection year")
    right.set_title("Projected: what the catalogue expects", loc="left")
    right.legend(loc="lower left")

    save(fig, "lcoe_projections")

    # A small companion: the same projection, as successive releases stated it.
    # Several series lie exactly on top of each other, which is the finding
    # rather than a plotting problem: the catalogue simply did not revise them.
    # A small horizontal jitter keeps the overlapping lines visible.
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ordered = sorted(vintages.technology.unique())
    for offset, tech in enumerate(ordered):
        sub = vintages[vintages.technology == tech].sort_values("released")
        jitter = (offset - (len(ordered) - 1) / 2) * 0.055
        ax.plot(np.arange(len(sub)) + jitter, sub.index_first_release,
                marker="o", markersize=3.5,
                color=TECH_COLOURS.get(tech, "#888888"),
                label=costs.loc[tech, "label"] if tech in costs.index else tech)
    ax.set_xticks(np.arange(len(sub)))
    ax.set_xticklabels(sub.released.tolist())
    ax.axhline(100, color="#333333", linewidth=0.8)
    ax.set_ylabel("Investment cost for 2030,\nfirst release = 100")
    ax.set_xlabel("Release of the catalogue")
    ax.legend(loc="upper left", ncol=4, fontsize=7.5)
    ax.set_ylim(86, 122)
    save(fig, "cost_vintages")


def figure_learning():
    """The experience curve, and the fit the note quotes."""
    fit = read("learning_fit.csv")
    summary = read_summary()
    learning = summary["learning"]

    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    ax.loglog(fit.cumulative_capacity_gw, fit.module_price_usd_per_w, "o",
              color="#D4A017", markersize=5, markeredgecolor="white",
              markeredgewidth=0.7, label="Observed, one point per year")
    order = np.argsort(fit.cumulative_capacity_gw.to_numpy())
    ax.loglog(fit.cumulative_capacity_gw.to_numpy()[order],
              fit.fitted_price.to_numpy()[order], color="#333333",
              linewidth=1.4,
              label=(f"Fitted: {learning['learning_rate']:.0%} per doubling"
                     f"  ($R^2$ = {learning['r_squared']:.2f})"))

    offsets = {int(fit.year.min()): (10, 4), 2010: (10, 4),
               int(fit.year.max()): (-4, 12)}
    for year, offset in offsets.items():
        row = fit[fit.year == year]
        if row.empty:
            continue
        ax.annotate(str(int(year)),
                    (row.cumulative_capacity_gw.iloc[0],
                     row.module_price_usd_per_w.iloc[0]),
                    textcoords="offset points", xytext=offset, fontsize=8,
                    color="#555555")

    ax.set_xlim(fit.cumulative_capacity_gw.min() * 0.7,
                fit.cumulative_capacity_gw.max() * 1.6)
    ax.set_xlabel("Cumulative installed solar PV capacity, GW (log scale)")
    ax.set_ylabel("Module price, USD per watt (log scale)")
    ax.legend(loc="lower left")
    save(fig, "lcoe_learning")


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def _write_table(name: str, body: str):
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{name}.tex").write_text(body, encoding="utf-8")
    print(f"wrote writing/generated/tables/{name}.tex")


def table_qualitative():
    costs = read("technology_costs.csv")
    costs = costs[~costs.family.isin(["Storage", "Heat"])]

    lines = [r"\begin{tabular}{lcccc}", r"\toprule",
             r"Technology & Investment & Running & Adjustment & Time to build \\",
             r"\midrule"]
    previous = None
    for row in costs.itertuples():
        if previous is not None and row.family != previous:
            lines.append(r"\addlinespace")
        previous = row.family
        lines.append(f"{row.label} & {row.q_investment} & {row.q_running} & "
                     f"{row.q_adjustment} & {row.q_time_to_build} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    _write_table("tech_qualitative", "\n".join(lines) + "\n")


def table_quantitative():
    costs = read("technology_costs.csv")
    electricity = costs[~costs.family.isin(["Storage", "Heat"])]

    lines = [r"\begin{tabular}{lrrrrrrrr}", r"\toprule",
             (r"Technology & Investment & Fixed O\&M & Life & $\eta$ & "
              r"$c$ & $e$ & Duty & LCoE \\"),
             (r" & \small EUR/kW & \small \%/yr & \small yr & & "
              r"\small EUR/MWh & \small t/MWh & \small h/yr & "
              r"\small EUR/MWh \\"),
             r"\midrule"]
    previous = None
    for row in electricity.itertuples():
        if previous is not None and row.family != previous:
            lines.append(r"\addlinespace")
        previous = row.family
        eta = "--" if pd.isna(row.fuel) else f"{row.efficiency:.2f}"
        # A dash and a starred zero are different claims. Nothing arrives at
        # the plant to burn; wood arrives and is counted as zero anyway.
        if row.carbon_is_convention:
            emission = r"0.00$^{*}$"
        elif row.emission_rate < 1e-9:
            emission = "--"
        else:
            emission = f"{row.emission_rate:.2f}"
        lcoe = "--" if pd.isna(row.lcoe_reference) else f"{row.lcoe_reference:.0f}"
        lines.append(
            f"{row.label} & {row.investment:,.0f} & {row.fom_rate * 100:.1f} & "
            f"{row.lifetime:.0f} & {eta} & {row.marginal_cost:.1f} & "
            f"{emission} & {row.capacity_factor * 8760:,.0f} & {lcoe} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    _write_table("tech_quantitative", "\n".join(lines) + "\n")


def table_heat_storage():
    costs = read("technology_costs.csv").set_index("technology")
    other = costs[costs.family.isin(["Storage", "Heat"])]

    lines = [r"\begin{tabular}{llrrrrr}", r"\toprule",
             (r"Technology & Product & Investment & Fixed O\&M & Life & "
              r"$\eta$ / COP & $c$ \\"),
             (r" & & \small EUR/kW(h) & \small \%/yr & \small yr & & "
              r"\small EUR/MWh \\"),
             r"\midrule"]
    # Kept short: the table gained a column and the caption already explains
    # the power/energy split, so the words do not have to.
    product = {"PHS": "Electricity",
               "battery inverter": "Electricity (power)",
               "battery storage": "Electricity (energy)",
               "central air-sourced heat pump": "Heat",
               "central gas boiler": "Heat"}
    for tech, row in other.iterrows():
        # The heat pump's COP is the parameter that generates its running
        # cost, so leaving it out made the row impossible to reconstruct.
        eta = "--" if pd.isna(row["fuel"]) else f"{row['efficiency']:.2f}"
        lines.append(
            f"{row['label']} & {product.get(tech, '')} & "
            f"{row['investment']:,.0f} & {row['fom_rate'] * 100:.1f} & "
            f"{row['lifetime']:.0f} & {eta} & {row['marginal_cost']:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    _write_table("heat_storage", "\n".join(lines) + "\n")


def table_fuels():
    """What the source says a fuel costs, and what the note assumes."""
    fuels = read("fuel_assumptions.csv").set_index("carrier")
    names = {"gas": "Natural gas", "coal": "Hard coal", "lignite": "Lignite",
             "oil": "Fuel oil", "solid biomass": "Wood chips",
             "wood pellets": "Wood pellets",
             "biomethane": "Biomethane (upgraded biogas)",
             "uranium": "Uranium", "waste": "Municipal waste"}

    lines = [r"\begin{tabular}{lrrcrr}", r"\toprule",
             (r" & \multicolumn{2}{c}{Price, EUR/MWh$_{\text{th}}$} & & "
              r"\multicolumn{2}{c}{CO$_2$, t/MWh$_{\text{th}}$} \\"),
             r"\cmidrule(lr){2-3}\cmidrule(lr){5-6}",
             r"Carrier & Published & Used here & & Published & Used here \\",
             r"\midrule"]
    for carrier, row in fuels.iterrows():
        def cell(value, flagged):
            if pd.isna(value):
                return "--"
            text = f"{value:.1f}" if abs(value) >= 1 else f"{value:.3f}"
            return f"\\textit{{{text}}}" if flagged else text
        lines.append(
            f"{names.get(carrier, carrier)} & "
            f"{cell(row['price_source_eur_per_mwh_th'], False)} & "
            f"{cell(row['price_used_eur_per_mwh_th'], row['price_is_assumption'])} & & "
            f"{cell(row['co2_source_t_per_mwh_th'], False)} & "
            f"{cell(row['co2_used_t_per_mwh_th'], row['co2_is_assumption'])} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    _write_table("fuel_assumptions", "\n".join(lines) + "\n")


def table_geography():
    """Section 6's inputs and what the note's own equation makes of them."""
    geo = read("geography.csv").set_index("region")

    def row(label, key, fmt, unit=""):
        cells = " & ".join(fmt(geo.loc[r, key]) for r in geo.index)
        return f"{label} & {cells} \\\\"

    pct = lambda v: f"{v:.1%}".replace("%", r"\%")
    idx = lambda v: f"{v:.2f}"
    eur = lambda v: f"{v:.0f}"

    lines = [r"\begin{tabular}{lrrr}", r"\toprule",
             "Input or result & " + " & ".join(geo.index) + r" \\",
             r"\midrule",
             r"\multicolumn{4}{l}{\emph{Inputs --- assumptions, see "
             r"Appendix~\ref{app:provenance}}} \\",
             row(r"\quad Real discount rate", "discount_rate", pct),
             row(r"\quad Solar capacity factor", "solar_capacity_factor", pct),
             row(r"\quad Solar investment (Europe = 1)", "solar_capex_index", idx),
             row(r"\quad Nuclear investment (Europe = 1)", "nuclear_capex_index", idx),
             row(r"\quad Gas price, EUR/MWh$_{\text{th}}$", "gas_price", eur),
             row(r"\quad Carbon price, EUR/tCO$_2$", "carbon_price", eur),
             r"\addlinespace",
             r"\multicolumn{4}{l}{\emph{Computed here from "
             r"\Cref{eq:lcoe:annuitised}, EUR/MWh}} \\",
             row(r"\quad Utility solar", "lcoe_solar", eur),
             row(r"\quad Nuclear", "lcoe_nuclear", eur),
             row(r"\quad Gas CCGT", "lcoe_ccgt", eur),
             row(r"\quad Gas CCGT, marginal cost", "mc_ccgt", eur),
             row(r"\quad \quad with carbon", "mc_ccgt_with_carbon", eur),
             r"\bottomrule", r"\end{tabular}"]
    _write_table("geography", "\n".join(lines) + "\n")


def table_mapping():
    costs = read("technology_costs.csv").set_index("technology")
    summary = read_summary()
    shares = summary["capital_share_at_reference"]

    label = {"variable": "Variable", "dispatchable": "Dispatchable",
             "store": "Store", "demand": "Demand-side"}

    lines = [r"\begin{tabular}{llrrl}", r"\toprule",
             (r"Technology & Controllability & Capital share & "
              r"Typical duty & Conventional role \\"),
             r" & & \small \% of cost & \small h/yr & \\",
             r"\midrule"]
    previous = None
    for tech, row in costs.iterrows():
        if previous is not None and row["family"] != previous:
            lines.append(r"\addlinespace")
        previous = row["family"]
        share = shares.get(tech)
        share_text = "--" if share is None else f"{share * 100:.0f}"
        lines.append(
            f"{row['label']} & {label.get(row['class'], row['class'])} & "
            f"{share_text} & {row['capacity_factor'] * 8760:,.0f} & "
            f"{row['role']} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    _write_table("planttypes_mapping", "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Numbers quoted in the prose
# ---------------------------------------------------------------------------
def numbers():
    """Macros for every number the text quotes, so text and figures agree."""
    summary = read_summary()
    costs = read("technology_costs.csv").set_index("technology")
    learning = summary["learning"]

    # LaTeX command names may contain letters only, so any digit that ends up
    # in a generated macro name is spelled out. Getting this wrong produces a
    # "Missing \begin{document}" error three files away from the cause.
    DIGITS = str.maketrans({"0": "Zero", "1": "One", "2": "Two", "3": "Three",
                            "4": "Four", "5": "Five", "6": "Six", "7": "Seven",
                            "8": "Eight", "9": "Nine"})

    def macro(name, value):
        return f"\\newcommand{{\\{name.translate(DIGITS)}}}{{{value}}}"

    lines = [
        "% Generated by pipeline/build.py. Do not edit.",
        "% Every number the note quotes in prose is defined here, so that the",
        "% text cannot drift away from the figure it describes.",
        "",
        macro("numRefYear", summary["reference_year"]),
        macro("numEurYear", summary["eur_year"]),
        macro("numSourceTag", summary["source_tag"].replace("_", r"\_")),
        macro("numDiscountRate", f"{summary['discount_rate']:.0%}".replace("%", r"\%")),
        macro("numCarbonPrice", f"{summary['carbon_price']:.0f}"),
        macro("numElecPrice", f"{summary['electricity_price']:.0f}"),
        "",
        "% Marginal costs, EUR/MWh",
    ]
    for tech in ["CCGT", "OCGT", "coal", "oil", "nuclear"]:
        lines.append(macro(f"numMC{tech.replace('-', '').capitalize()}",
                           f"{summary['marginal_cost'][tech]:.0f}"))
    lines += ["", "% Plant parameters the tour quotes in prose. These used to",
              "% be typed into section 3, and the coal emission rate had",
              "% already drifted."]
    plant = {"OCGT": "Ocgt", "CCGT": "Ccgt", "coal": "Coal",
             "nuclear": "Nuclear", "central solid biomass CHP": "BiomassChp",
             "waste CHP": "WasteChp", "central gas boiler": "GasBoiler",
             "central air-sourced heat pump": "HeatPump", "hydro": "Hydro",
             "solar-utility": "SolarPv", "battery inverter": "BatteryInverter",
             "oil": "Oil", "onwind": "Onwind", "offwind": "Offwind"}
    for tech, name in plant.items():
        row = costs.loc[tech]
        lines.append(macro(f"numInv{name}", f"{row['investment']:,.0f}"))
        if not pd.isna(row["fuel"]):
            lines.append(macro(f"numEta{name}", f"{row['efficiency']:.2f}"))
            lines.append(macro(f"numEtaPct{name}",
                               f"{row['efficiency']:.0%}".replace("%", r"\%")))
        lines.append(macro(f"numLife{name}", f"{row['lifetime']:.0f}"))
        lines.append(macro(f"numDuty{name}",
                           f"{row['capacity_factor'] * 8760:,.0f}"))
        lines.append(macro(f"numCf{name}",
                           f"{row['capacity_factor']:.1%}".replace("%", r"\%")))
    lines.append(macro("numEmisCoal",
                       f"{costs.loc['coal', 'emission_rate']:.2f}"))
    lines.append(macro("numCopHeatPump",
                       f"{costs.loc['central air-sourced heat pump', 'efficiency']:.2f}"))

    lines.append("")
    lines.append("% Levelised cost at the reference utilisation, EUR/MWh.")
    lines.append("% Every technology the table prices, not only those plotted.")
    naming = {"solar-utility": "SolarPv", "solar-rooftop": "SolarRooftop",
              "onwind": "Onwind", "offwind": "Offwind", "hydro": "Hydro",
              "ror": "Ror", "nuclear": "Nuclear", "coal": "Coal",
              "CCGT": "Ccgt", "OCGT": "Ocgt", "oil": "Oil",
              "central solid biomass CHP": "BiomassChp", "waste CHP": "WasteChp",
              "central air-sourced heat pump": "HeatPump",
              "central gas boiler": "GasBoiler"}
    for tech, name in naming.items():
        value = costs.loc[tech, "lcoe_reference"]
        if not pd.isna(value):
            lines.append(macro(f"numLcoe{name}", f"{value:.0f}"))

    lines += ["", "% Where the cheapest dispatchable technology changes"]
    for switch in summary["envelope_switches"]:
        key = switch["technology"].replace("-", "").replace(" ", "")
        lines.append(macro(f"numSwitch{key.capitalize()}",
                           f"{switch['full_load_hours']:,.0f}"))

    lines += ["", "% Financing"]
    if summary.get("nuclear_ccgt_rate_crossover"):
        lines.append(macro("numRateCrossover",
                           f"{summary['nuclear_ccgt_rate_crossover']:.1%}"
                           .replace("%", r"\%")))
    for rate in ("0.03", "0.11"):
        if rate in summary.get("lcoe_by_rate", {}):
            block = summary["lcoe_by_rate"][rate]
            tag = rate.replace("0.", "")
            lines.append(macro(f"numNuclearAt{tag}", f"{block['nuclear']:.0f}"))
            lines.append(macro(f"numOffwindAt{tag}", f"{block['offwind']:.0f}"))
            lines.append(macro(f"numCcgtAt{tag}", f"{block['CCGT']:.0f}"))

    lines += ["", "% Site quality: the same machine, a different place"]
    for key, value in summary["site_quality"].items():
        tag = key.replace("_at_0.", "At").replace(".", "").replace("-", "")
        lines.append(macro(f"num{tag[0].upper()}{tag[1:]}", f"{value:.0f}"))

    lines += ["", "% Carbon, at the stated price"]
    lines.append(macro("numCarbonCoal", f"{summary['carbon_cost_coal']:.0f}"))
    lines.append(macro("numCarbonCcgt", f"{summary['carbon_cost_ccgt']:.0f}"))

    lines += ["", "% Learning"]
    lines += [
        macro("numLearningRate", f"{learning['learning_rate']:.0%}".replace("%", r"\%")),
        macro("numLearningRsq", f"{learning['r_squared']:.2f}"),
        macro("numLearningFrom", learning["first_year"]),
        macro("numLearningTo", learning["last_year"]),
        macro("numLearningPriceFrom", f"{learning['first_price']:.2f}"),
        macro("numLearningPriceTo", f"{learning['last_price']:.2f}"),
        macro("numLearningCapFrom", f"{learning['first_capacity']:.1f}"),
        macro("numLearningCapTo", f"{learning['last_capacity']:,.0f}"),
        macro("numLearningDoublings", f"{learning['doublings']:.1f}"),
        macro("numLearningSeriesStart", learning["price_series_start"]),
        macro("numLearningPriceSeriesStart", f"{learning['price_at_series_start']:.0f}"),
    ]

    lines += ["", "% What the catalogue expects by 2050 (2025 = 100)"]
    for tech, value in summary["projection_2050_index"].items():
        key = tech.replace("-", "").replace(" ", "")
        lines.append(macro(f"numProj{key[0].upper()}{key[1:]}", f"{value:.0f}"))

    lines += ["", "% How much the catalogue itself moved, first to last release"]
    for tech, block in summary["vintage_spread"].items():
        key = tech.replace("-", "").replace(" ", "")
        lines.append(macro(f"numVintage{key[0].upper()}{key[1:]}",
                           f"{block['change_pct']:+.0f}"))

    # The two places the note does arithmetic in front of the reader. Both
    # assert that they land on a figure printed elsewhere, so both have to be
    # generated or the assertion rots on the next rebuild.
    we = summary["worked_example"]
    lines += ["", "% Appendix A's worked conversion, step by step"]
    lines += [
        macro("numWeLabel", we["label"]),
        macro("numWeInvestment", f"{we['investment']:,.0f}"),
        macro("numWeFom", f"{we['fom_rate']:.1%}".replace("%", r"\%")),
        macro("numWeFomRate", f"{we['fom_rate']:.4f}"),
        macro("numWeEta", f"{we['efficiency']:.2f}"),
        macro("numWeVom", f"{we['vom']:.2f}"),
        macro("numWeLife", f"{we['lifetime']:.0f}"),
        macro("numWeFuelPrice", f"{we['fuel_price']:.0f}"),
        macro("numWeCf", f"{we['capacity_factor']:.0%}".replace("%", r"\%")),
        macro("numWeCfDecimal", f"{we['capacity_factor']:.2f}"),
        macro("numWeAnnuity", f"{we['annuity_factor']:.4f}"),
        macro("numWeAnnualCapacity", f"{we['annual_capacity_cost']:.0f}"),
        macro("numWeEnergy", f"{we['energy_per_kw_mwh']:.2f}"),
        macro("numWeCapacityPerMwh", f"{we['capacity_cost_per_mwh']:.0f}"),
        macro("numWeMc", f"{we['marginal_cost']:.1f}"),
        macro("numWeLcoe", f"{we['lcoe']:.0f}"),
    ]

    mc = summary["mc_example"]
    lines += ["", "% Section 2's marginal-cost example, on the note's own coal"]
    lines += [
        macro("numMcExFuelPrice", f"{mc['fuel_price']:.0f}"),
        # Three decimals, not two: the reader is invited to do this sum, and
        # coal's efficiency is 0.356. Rounding it to 0.36 in the display would
        # make the arithmetic on the page fail to reproduce the answer.
        macro("numMcExEta", f"{mc['efficiency']:.3f}"),
        macro("numMcExEtaPct", f"{mc['efficiency']:.0%}".replace("%", r"\%")),
        macro("numMcExVom", f"{mc['vom']:.2f}"),
        macro("numMcExPhi", f"{mc['co2_intensity_fuel']:.3f}"),
        macro("numMcExMc", f"{mc['marginal_cost']:.1f}"),
        macro("numMcExEmis", f"{mc['emission_rate']:.2f}"),
        macro("numMcExEtaHalved", f"{mc['efficiency_halved']:.3f}"),
        macro("numMcExEtaHalvedPct",
              f"{mc['efficiency_halved']:.0%}".replace("%", r"\%")),
        macro("numMcExMcHalved", f"{mc['marginal_cost_halved']:.1f}"),
        macro("numMcExEmisHalved", f"{mc['emission_rate_halved']:.2f}"),
    ]

    lines += ["", "% Section 6: the same machine, a different country"]
    geo = summary["geography"]
    region_tag = {"Europe": "Europe", "United States": "Us", "China": "China"}
    for region, block in geo["levels"].items():
        tag = region_tag[region]
        lines += [
            macro(f"numGeoSolar{tag}", f"{block['lcoe_solar']:.0f}"),
            macro(f"numGeoNuclear{tag}", f"{block['lcoe_nuclear']:.0f}"),
            macro(f"numGeoCcgt{tag}", f"{block['lcoe_ccgt']:.0f}"),
            macro(f"numGeoMcCcgt{tag}", f"{block['mc_ccgt']:.0f}"),
            macro(f"numGeoGasPrice{tag}", f"{block['gas_price']:.0f}"),
            macro(f"numGeoCarbonPrice{tag}", f"{block['carbon_price']:.0f}"),
            macro(f"numGeoRate{tag}",
                  f"{block['discount_rate']:.1%}".replace("%", r"\%")),
            # One decimal, to match \numCfSolarPv elsewhere in the note: the
            # European figure is 11.5%, and rounding it to 12% here would make
            # two sentences about the same site disagree.
            macro(f"numGeoSolarCf{tag}",
                  f"{block['solar_capacity_factor']:.1%}".replace("%", r"\%")),
            macro(f"numGeoSolarCapex{tag}", f"{block['solar_capex_index']:.2f}"),
            macro(f"numGeoNuclearCapex{tag}",
                  f"{block['nuclear_capex_index']:.2f}"),
        ]
    for region, block in geo["waterfall"].items():
        tag = region_tag[region]
        for step, name in (("solar_capacity_factor", "Resource"),
                           ("solar_capex_index", "Capex"),
                           ("discount_rate", "Wacc")):
            if block.get(step) is not None:
                lines.append(macro(f"numGeoStep{name}{tag}",
                                   f"{block[step]:+.0f}"))
    for region, channel in geo["largest_channel"].items():
        lines.append(macro(f"numGeoLargest{region_tag[region]}",
                           channel.lower()))

    lines += ["", "% Appendix B: what lifetime does to the annuity factor"]
    for name, block in summary["annuity_illustration"].items():
        tag = name.capitalize()
        lines += [
            macro(f"numAnnuity{tag}From", f"{block['from']:.0f}"),
            macro(f"numAnnuity{tag}To", f"{block['to']:.0f}"),
            macro(f"numAnnuity{tag}FactorFrom", f"{block['factor_from']:.3f}"),
            macro(f"numAnnuity{tag}FactorTo", f"{block['factor_to']:.3f}"),
        ]

    lines += ["", "% Grid endpoints and the points the prose reads off them"]
    for key, value in summary["grids"].items():
        tag = "".join(part.capitalize() for part in key.split("_"))
        lines.append(macro(f"numGrid{tag}",
                           f"{value:.0%}".replace("%", r"\%")))

    lines += ["", "% Capital share of the levelised cost, at the reference duty"]
    for tech, name in plant.items():
        share = summary["capital_share_at_reference"].get(tech)
        if share is not None and np.isfinite(share):
            lines.append(macro(f"numCapShare{name}",
                               f"{share:.0%}".replace("%", r"\%")))

    lines.append("")
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "numbers.tex").write_text("\n".join(lines), encoding="utf-8")
    print("wrote writing/generated/numbers.tex")


def main():
    figure_decomposition()
    figure_capacityfactor()
    figure_discountrate()
    figure_projections()
    figure_learning()
    figure_geography()

    table_qualitative()
    table_quantitative()
    table_heat_storage()
    table_fuels()
    table_geography()
    table_mapping()
    numbers()

    print(f"\nstage 3 read only: {sorted(set(_OPENED))}")
    print("stage 3 complete")


if __name__ == "__main__":
    main()
