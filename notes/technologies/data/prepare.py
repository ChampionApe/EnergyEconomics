"""Turn raw downloads into the processed inputs the pipeline reads.

    python data/prepare.py

Stage 1 of the pipeline. Reads `data/raw/`, writes `data/processed/`.
Deterministic and re-runnable. Never reads `results/`.

`data/raw/` is read-only: never edit a download in place, or the pipeline
stops being reproducible from the original source. Every transformation
belongs here, in code. A raw file that already exists is not fetched again, so
re-running this script is cheap and offline once the downloads are in place;
delete the raw file to force a fresh download.

Only `data/processed/` is published, so anything needed to reproduce a figure
has to survive this stage. Provenance for every dataset is in data/README.md,
and Appendix D of the note is built from that file.

Prepares:

    processed/technology_costs_{2025..2050}.csv
        the note's subset of PyPSA/technology-data, one file per cost
        projection vintage, FETCHED AT A PINNED TAG and reshaped. All money is
        in EUR2020 (the dataset's `eur_year`). Never vendored raw: the
        compiled outputs carry no single stated licence.
    processed/technology_meta.csv
        hand-authored, written from a literal in this file: display names,
        ordering, fuel, reference capacity factor, dispatchability class, and
        the qualitative High/Medium/Low ratings of the note's Table 3.1.
        Every entry here is an assumption or a judgement, and is labelled as
        such in the note's Appendix D.
    processed/fuel_assumptions.csv
        fuel price and CO2 intensity per carrier, with BOTH the dataset's own
        value and the value the note uses, so the difference is visible rather
        than buried. The note's fuel prices are stylised 2025 forward levels,
        chosen to match the rest of the course material.
    processed/cost_vintages.csv
        investment cost for a handful of technologies as it stood in each
        annual release of technology-data, 2020-2025. Evidence for the note's
        claim that a published catalogue is revised much less than one might
        expect.
    processed/solar_learning.csv
        world solar PV module price and cumulative installed PV capacity, from
        Our World in Data (CC-BY 4.0). The experience curve of section 5.
    processed/geography_assumptions.csv
        hand-authored, written from a literal in this file: the regional
        inputs of the note's section 6. EVERY ROW IS AN ASSUMPTION. Section 6
        does not quote regional cost levels from anywhere; it re-prices the
        note's own European technology under these inputs. See the GEOGRAPHY
        block below for why.

Not prepared here: nothing. Everything the note plots comes from one of the
six files above.
"""

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

NOTE = Path(__file__).resolve().parent.parent
RAW = NOTE / "data" / "raw"
PROCESSED = NOTE / "data" / "processed"

# ---------------------------------------------------------------------------
# Pins.
#
# The pin is what makes this reproducible: an unpinned fetch would let the
# note's numbers drift silently between builds. It is also how this note stays
# consistent with the other course material, which reads the same source at
# the same tag -- two independent fetches at one pin agree, and neither note
# has to reach into the other's directories.
# ---------------------------------------------------------------------------
TECHNOLOGY_DATA_TAG = "v0.13.2"
EUR_YEAR = 2020  # the dataset's `eur_year`: all money below is in 2020 euros
COST_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]
REFERENCE_YEAR = 2025  # the vintage the note's tables and figures report

# One release per year, for the "how much does a catalogue get revised?"
# comparison. Dates are the tag's commit date.
VINTAGE_TAGS = [
    ("v0.1.0", "2020-08"),
    ("v0.3.0", "2021-10"),
    ("v0.4.0", "2022-07"),
    ("v0.6.0", "2023-05"),
    ("v0.9.0", "2024-05"),
    ("v0.12.0", "2025-05"),
    ("v0.13.2", "2025-06"),
]
VINTAGE_TECHS = ["solar-utility", "onwind", "offwind", "battery storage",
                 "nuclear", "CCGT", "OCGT"]
VINTAGE_TARGET = 2030

# The technologies of the tour. Order is the order they appear in the note.
KEEP_TECHS = [
    "solar-utility", "solar-rooftop", "onwind", "offwind",
    "hydro", "ror", "PHS",
    "nuclear", "coal", "CCGT", "OCGT", "oil",
    "central solid biomass CHP", "waste CHP",
    "battery inverter", "battery storage",
    "central air-sourced heat pump", "central gas boiler",
]
KEEP_PARAMS = ["investment", "FOM", "VOM", "efficiency", "efficiency-heat",
               "lifetime", "fuel", "CO2 intensity"]
# Carriers whose fuel price and carbon content the note quotes.
FUEL_CARRIERS = ["gas", "coal", "lignite", "oil", "solid biomass", "uranium"]
# Carriers with no technology-data row of their own, priced off another.
# "wood pellets" is solid biomass at a higher price -- the same plant, a more
# expensive fuel. "biomethane" is technology-data's "biogas" fuel after
# upgrading to grid quality. Kept here so this block stays identical to the
# one in the energy-system-models note, which does use both.
DERIVED_CARRIERS = {"wood pellets": "solid biomass", "biomethane": "biogas"}


# ---------------------------------------------------------------------------
# Hand-authored metadata.
#
# Everything in this block is a judgement or an assumption of mine, not a
# measurement, and the note says so. It lives in code rather than in a
# spreadsheet so that it is versioned alongside the figures it produces.
# ---------------------------------------------------------------------------
#
# capacity_factor: a reference annual utilisation for a north-west European
#   system, used ONLY to put the cost decomposition of figure 3.1 on a
#   comparable per-MWh basis and to fill the "typical duty" column of table
#   5.1. Nothing else in the note depends on it. For the variable technologies
#   it is roughly what Danish sites deliver; for the dispatchable ones it is
#   roughly the duty they are conventionally built for, not a model result.
#
# The four qualitative columns reproduce the lecture's Table 1 for the eight
# technologies it covered, and extend it to the rest on the same convention:
#   adjustment = how hard it is to deliver a chosen output profile, so a
#   technology that cannot raise output on command scores High.
#
META = {
    # tech: (label, family, fuel, capacity_factor, class, role,
    #        investment, running, adjustment, time_to_build)
    "solar-utility": ("Solar PV, utility", "Variable", None, 0.115, "variable",
                      "Variable", "Medium", "Low", "High", "Low"),
    "solar-rooftop": ("Solar PV, rooftop", "Variable", None, 0.100, "variable",
                      "Variable", "High", "Low", "High", "Low"),
    "onwind": ("Onshore wind", "Variable", None, 0.330, "variable",
               "Variable", "Medium", "Low", "High", "Medium"),
    "offwind": ("Offshore wind", "Variable", None, 0.500, "variable",
                "Variable", "High", "Low", "High", "High"),
    "hydro": ("Hydro, reservoir", "Hydro", None, 0.400, "dispatchable",
              "Mid-merit / flexible", "High", "Low", "Low", "High"),
    "ror": ("Hydro, run-of-river", "Hydro", None, 0.450, "variable",
            "Variable", "High", "Low", "High", "High"),
    "PHS": ("Pumped hydro storage", "Storage", None, 0.120, "store",
            "Storage", "High", "Low", "Low", "High"),
    "nuclear": ("Nuclear", "Thermal", "uranium", 0.900, "dispatchable",
                "Baseload", "Very high", "Low", "High", "Very high"),
    "coal": ("Coal", "Thermal", "coal", 0.500, "dispatchable",
             "Baseload", "High", "Medium", "High", "High"),
    "CCGT": ("Gas CCGT", "Thermal", "gas", 0.400, "dispatchable",
             "Mid-merit", "Medium", "Medium", "Medium", "Medium"),
    "OCGT": ("Gas OCGT (peaker)", "Thermal", "gas", 0.050, "dispatchable",
             "Peaker", "Low", "High", "Low", "Low"),
    "oil": ("Oil peaker", "Thermal", "oil", 0.020, "dispatchable",
            "Peaker", "Low", "Very high", "Low", "Low"),
    "central solid biomass CHP": ("Biomass CHP", "Thermal", "solid biomass",
                                  0.600, "dispatchable", "Baseload / heat",
                                  "High", "Medium", "High", "Medium"),
    "waste CHP": ("Waste CHP", "Thermal", "waste", 0.850, "dispatchable",
                  "Baseload / heat", "Very high", "High", "High", "Medium"),
    "battery inverter": ("Battery inverter", "Storage", None, 0.100, "store",
                         "Storage", "Medium", "Low", "Very low", "Low"),
    "battery storage": ("Battery cells", "Storage", None, 0.100, "store",
                        "Storage", "Medium", "Low", "Very low", "Low"),
    "central air-sourced heat pump": ("Heat pump, district", "Heat",
                                      "electricity", 0.350, "demand",
                                      "Heat, flexible demand",
                                      "Medium", "Medium", "Low", "Low"),
    "central gas boiler": ("Gas boiler, district", "Heat", "gas", 0.080,
                           "dispatchable", "Heat, peaking",
                           "Very low", "Medium", "Very low", "Low"),
}

# Fuel prices the note uses, in EUR per MWh of thermal energy.
#
# These are stylised 2025 forward-market levels rather than the dataset's own
# fuel prices, which are inherited from a 2013 study and are well below what
# European plants have paid recently. Using them keeps this note's marginal
# costs consistent with the rest of the course material. The dataset's value
# is carried alongside in fuel_assumptions.csv so the reader can see exactly
# what was changed and by how much -- which is the standard the note's
# section 4 asks of everybody else.
FUEL_PRICE_NOTE = {
    "gas": 35.0,
    "coal": 12.0,
    "lignite": 5.0,
    "oil": 55.0,
    "solid biomass": 25.0,
    "wood pellets": 38.0,  # the same plant, a more expensive fuel
    "biomethane": 90.0,    # grid-quality upgraded biogas, 2025 forward level
    "uranium": None,       # None: keep the dataset's value
    "waste": 0.0,          # gate fees ignored; the plant is paid to take it
}
# Biogenic carbon is conventionally counted as zero in this accounting.
CO2_ZERO_CARRIERS = ["solid biomass", "wood pellets", "biomethane"]
# Municipal waste is only partly biogenic: roughly half of it by energy
# content is plastics, and that half is fossil carbon like any other. Counting
# waste as carbon-free is a common shortcut and a wrong one, so the fossil
# fraction is carried explicitly.
CO2_OVERRIDE = {"waste": 0.15}

# Discount rate and technology-specific risk premia used in section 4.
DISCOUNT_RATE = 0.07


# ---------------------------------------------------------------------------
# Section 6: the same machine in a different place.
#
# READ THIS BEFORE CHANGING ANYTHING BELOW.
#
# Section 6 does NOT compare published levelised costs across regions. That
# comparison cannot be made honestly from public sources -- the boundaries,
# the currency years and the capital costs all differ, and the result is a
# comparison of methodologies rather than of technologies, which is precisely
# what section 5 teaches students to distrust.
#
# What it does instead is take the note's OWN European technology and re-price
# it through the note's own equation (4.2) under changed inputs, one input at
# a time. Every level in section 6 is therefore computed by this repository at
# this note's boundary and in this note's currency year. Only the *deltas*
# come from outside, and each one is a deliberately round, deliberately
# illustrative figure chosen to be defensible rather than precise.
#
# Consequently: every row below is an ASSUMPTION, not a measurement, and the
# note says so in the section, in the table and in appendix D. They are round
# numbers on purpose. If you sharpen one, sharpen the source note with it.
#
# `basis` records what the figure is anchored to. `source` is the shortest
# honest statement of where it comes from.
GEOGRAPHY_REGIONS = ["Europe", "United States", "China"]

GEOGRAPHY = [
    # (region, parameter, value, unit, basis, source)
    ("Europe", "discount_rate", 0.07, "real",
     "the note's own assumption throughout",
     "Section 5; a conventional central value for a European project."),
    ("United States", "discount_rate", 0.06, "real",
     "one point below the European figure",
     "Illustrative. Surveyed equity and debt costs for mature US renewable "
     "projects sit slightly below European ones; the IEA Cost of Capital "
     "Observatory tracks the spread."),
    ("China", "discount_rate", 0.045, "real",
     "two and a half points below the European figure",
     "Illustrative. State-directed lending at administered rates; widely "
     "reported to be the single largest source of the Chinese cost "
     "advantage in capital-intensive generation."),

    ("Europe", "solar_capacity_factor", 0.115, "share of nameplate",
     "the note's own Danish reference",
     "Table 5.1; roughly what Danish sites deliver."),
    ("United States", "solar_capacity_factor", 0.24, "share of nameplate",
     "a good south-western site",
     "Illustrative. Round figure for the US south-west, roughly twice the "
     "Danish resource."),
    ("China", "solar_capacity_factor", 0.17, "share of nameplate",
     "a mid-latitude northern Chinese site",
     "Illustrative. Between the Danish and the south-western US figure."),

    ("Europe", "solar_capex_index", 1.00, "index, Europe = 1",
     "the note's own catalogue value",
     "Table 3.2, from the pinned catalogue."),
    ("United States", "solar_capex_index", 1.15, "index, Europe = 1",
     "fifteen per cent above the European figure",
     "Illustrative. Identical modules at a world price; the difference is "
     "labour, permitting, interconnection and tariffs on imported cells."),
    ("China", "solar_capex_index", 0.65, "index, Europe = 1",
     "about two thirds of the European figure",
     "Illustrative. Same modules again; the difference is balance-of-system "
     "labour and installation, not the panel."),

    ("Europe", "gas_price", 35.0, "EUR/MWh_th",
     "the note's own fuel assumption",
     "Table D.1; a European forward level."),
    ("United States", "gas_price", 12.0, "EUR/MWh_th",
     "about a third of the European figure",
     "Illustrative. Henry Hub has traded at a persistent two- to fourfold "
     "discount to European TTF since 2022."),
    ("China", "gas_price", 40.0, "EUR/MWh_th",
     "slightly above the European figure",
     "Illustrative. A net LNG importer competing for the same cargoes."),

    ("Europe", "carbon_price", 80.0, "EUR/tCO2",
     "the note's own illustrative carbon price",
     "Section 3; the EU emissions trading system."),
    ("United States", "carbon_price", 0.0, "EUR/tCO2",
     "no economy-wide price",
     "Illustrative. No federal carbon price; some states price carbon."),
    ("China", "carbon_price", 10.0, "EUR/tCO2",
     "an order of magnitude below the European figure",
     "Illustrative. The national ETS has traded far below EU allowances."),

    ("Europe", "nuclear_capex_index", 1.00, "index, Europe = 1",
     "the note's own catalogue value",
     "Table 3.2. Note that this row is itself US-derived; see appendix D."),
    ("United States", "nuclear_capex_index", 1.15, "index, Europe = 1",
     "fifteen per cent above the European figure",
     "Illustrative, and the widest uncertainty band in this table. Recent "
     "Western first-of-a-kind projects have overrun heavily and the range "
     "across them is far larger than the difference shown here."),
    ("China", "nuclear_capex_index", 0.35, "index, Europe = 1",
     "roughly a third of the European figure",
     "Illustrative. Serial construction of a repeated design; reported "
     "costs per kW are a small fraction of recent Western projects, though "
     "the accounting is not directly comparable."),
]


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------
def _get(url: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _cached(url: str, path: Path) -> bytes:
    """Fetch `url` unless `path` already holds it. Raw files are never rewritten."""
    if path.exists():
        print(f"raw exists, not fetching: {path.relative_to(NOTE)}")
        return path.read_bytes()
    print(f"fetching {url}")
    payload = _get(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    print(f"wrote {path.relative_to(NOTE)}")
    return payload


def _costs_csv(tag: str, year: int) -> pd.DataFrame:
    raw = RAW / "technology-data" / f"costs_{year}_{tag}.csv"
    url = ("https://raw.githubusercontent.com/PyPSA/technology-data/"
           f"{tag}/outputs/costs_{year}.csv")
    return pd.read_csv(io.BytesIO(_cached(url, raw)))


# ---------------------------------------------------------------------------
# The shared battery-cost override.
#
# THIS BLOCK IS SHARED WITH THE ENERGY-SYSTEM-MODELS NOTE and must stay
# identical to the one in notes/energy-system-models/data/prepare.py, for
# the same reason as the fuel block above: the two notes price the same
# machines and publish independently. tools/check_note_consistency.py
# compares the generated battery_assumptions.csv files.
#
# technology-data's battery trajectory (DEA-derived) has fallen well behind
# the world market: its 2040 vintage costs roughly what turnkey systems sold
# for on the 2025 world market. Every vintage's 4-hour system cost is
# therefore capped at BNEF's 2025 European average turnkey price. The split
# between inverter (EUR/kW) and cells (EUR/kWh) keeps technology-data's own
# ratio: both investment numbers are scaled by one common factor until the
# 4-hour system hits the cap, and vintages already below the cap are left
# alone -- min(technology-data, BNEF) keeps the vintage sweep monotone.
#
# Source: BloombergNEF, Energy Storage System Cost Survey 2025 (December
# 2025; press-release figures): global average turnkey system price
# 117 $/kWh (down 31% on 2024); Europe 177 $/kWh; China 73 $/kWh; global
# average for 4-hour systems 110 $/kWh. The note anchors on the European
# figure -- a Danish buyer does not pay Chinese prices -- converted at
# ~1.07 USD/EUR to a round 165 EUR/kWh. The conversion, and reading a
# nominal-2025 dollar price against technology-data's EUR-2020 basis, are
# part of the assumption; source and used values are both recorded in
# battery_assumptions.csv so the override is visible rather than buried.
BATTERY_BNEF_EUROPE_USD_PER_KWH = 177.0
BATTERY_CAP_EUR_PER_KWH = 165.0
BATTERY_CAP_HOURS = 4.0


# ---------------------------------------------------------------------------
# Offshore wind, which technology-data prices in a way neither note can use.
#
# DUPLICATED VERBATIM in the energy-system-models note and compared by
# tools/check_note_consistency.py. It is duplicated rather than imported
# because the two notes publish independently and neither may read the
# other's directories; what they share is a source, not a file.
#
# PyPSA's `offwind` is not the cost of an offshore wind farm. The Danish
# Energy Agency's sheet 21 gives a total nominal investment; technology-data
# subtracts one line from it -- the INSTALLATION half of grid connection --
# because PyPSA-Eur puts distance-specific cabling back on per wind farm.
# The equipment half stays in. Verified against the catalogue:
#
#     DEA total 2050              1.64274 MEUR/MW
#     less installation: grid     0.11881
#     =                           1.52393  = technology-data's offwind, exactly
#
# Neither note adds cabling of its own, so both must use the DEA total.
DEA_CATALOGUE_URL = (
    "https://raw.githubusercontent.com/PyPSA/technology-data/"
    "{tag}/inputs/technology_data_for_el_and_dh.xlsx"
)
DEA_CATALOGUE = "technology_data_for_el_and_dh_{tag}.xlsx"
DEA_OFFSHORE_SHEET = "21 Offshore turbines"
DEA_OFFSHORE_YEAR_ROW = 2
DEA_OFFSHORE_TOTAL_ROW = 19
DEA_OFFSHORE_GRID_INSTALL_ROW = 33


def _dea_offshore_rows() -> tuple:
    """(years, total, installation-grid-connection) from the DEA catalogue,
    MEUR/MW in 2020 euros."""
    import openpyxl

    path = RAW / "technology-data" / DEA_CATALOGUE.format(
        tag=TECHNOLOGY_DATA_TAG)
    if not path.exists():
        url = DEA_CATALOGUE_URL.format(tag=TECHNOLOGY_DATA_TAG)
        print(f"fetching {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(url))
        print(f"wrote {path.relative_to(NOTE)}")
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book[DEA_OFFSHORE_SHEET]
    rows = {i: list(r) for i, r in enumerate(
        sheet.iter_rows(min_row=1, max_row=40, max_col=8, values_only=True), 1)}
    years = [int(v) for v in rows[DEA_OFFSHORE_YEAR_ROW][2:7]]
    total = [float(v) for v in rows[DEA_OFFSHORE_TOTAL_ROW][2:7]]
    install = [float(v) for v in rows[DEA_OFFSHORE_GRID_INSTALL_ROW][2:7]]
    book.close()
    return years, total, install


def offshore_override(wide: pd.DataFrame, cost_year: int) -> dict:
    """Restore the DEA total to `offwind`, in place. Returns the record row."""
    import numpy as np

    years, total, install = _dea_offshore_rows()
    add = float(np.interp(cost_year, years, install)) * 1e3    # MEUR/MW->EUR/kW
    source = float(wide.at["offwind", "investment"])
    used = source + add
    wide.at["offwind", "investment"] = used
    return {
        "cost_year": cost_year,
        "offwind_source_eur_per_kw": round(source, 4),
        "grid_connection_installation_eur_per_kw": round(add, 4),
        "offwind_used_eur_per_kw": round(used, 4),
        "dea_total_eur_per_kw": round(
            float(np.interp(cost_year, years, total)) * 1e3, 4),
    }


def battery_override(wide: pd.DataFrame, cost_year: int) -> dict:
    """Cap the 4-hour battery system cost at the BNEF 2025 European level,
    keeping technology-data's inverter/cells split. Mutates `wide` in place
    and returns the record row for battery_assumptions.csv."""
    inverter = float(wide.loc["battery inverter", "investment"])
    cells = float(wide.loc["battery storage", "investment"])
    system = (inverter + BATTERY_CAP_HOURS * cells) / BATTERY_CAP_HOURS
    scale = min(1.0, BATTERY_CAP_EUR_PER_KWH / system)
    wide.loc[["battery inverter", "battery storage"], "investment"] *= scale
    return {
        "cost_year": cost_year,
        "inverter_source_eur_per_kw": round(inverter, 4),
        "cells_source_eur_per_kwh": round(cells, 4),
        "system_source_eur_per_kwh": round(system, 4),
        "inverter_used_eur_per_kw": round(inverter * scale, 4),
        "cells_used_eur_per_kwh": round(cells * scale, 4),
        "system_used_eur_per_kwh": round(system * scale, 4),
        "is_override": scale < 1.0,
    }


def write_battery_assumptions(rows: list) -> None:
    """One row per cost vintage: technology-data's value beside the note's."""
    frame = pd.DataFrame(rows).set_index("cost_year")
    out = PROCESSED / "battery_assumptions.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Battery investment costs: technology-data's published value\n")
        handle.write("# (*_source) beside the value the note uses (*_used), per cost\n")
        handle.write("# vintage. Every vintage's 4-hour turnkey system cost is capped\n")
        handle.write(f"# at {BATTERY_CAP_EUR_PER_KWH:.0f} EUR/kWh -- BNEF's 2025 European average turnkey\n")
        handle.write(f"# price ({BATTERY_BNEF_EUROPE_USD_PER_KWH:.0f} $/kWh, Energy Storage System Cost Survey 2025,\n")
        handle.write("# at ~1.07 USD/EUR) -- keeping technology-data's inverter/cells\n")
        handle.write("# split. Rows with is_override=False are technology-data's own\n")
        handle.write("# numbers. Identical to the block in the energy-system-models\n")
        handle.write("# note.\n")
        frame.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} vintages)")


def write_offshore_assumptions(rows: list) -> None:
    """One row per cost vintage: technology-data's `offwind` beside the DEA
    total the note uses. The same source-beside-used record as the battery
    and fuel blocks, and for the same reason -- an override that is not
    written down is an override nobody can check."""
    frame = pd.DataFrame(rows).set_index("cost_year")
    out = PROCESSED / "offshore_assumptions.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Offshore wind investment cost: technology-data's published\n")
        handle.write("# `offwind` (*_source) beside the value the note uses (*_used),\n")
        handle.write("# per cost vintage. technology-data subtracts the INSTALLATION\n")
        handle.write("# half of grid connection from the Danish Energy Agency total\n")
        handle.write("# because PyPSA-Eur adds distance-specific cabling back per farm;\n")
        handle.write("# this note adds no cabling, so the DEA total is restored. The\n")
        handle.write("# difference is the grid_connection_installation column, and\n")
        handle.write("# *_used equals dea_total by construction. Source: the DEA\n")
        handle.write("# technology catalogue for electricity and district heating,\n")
        handle.write(f"# sheet '{DEA_OFFSHORE_SHEET}', at the pinned technology-data tag.\n")
        handle.write("# Identical to the block in the energy-system-models note.\n")
        frame.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} vintages)")


# ---------------------------------------------------------------------------
# Stage 1 steps
# ---------------------------------------------------------------------------
def prepare_costs(cost_year: int) -> dict:
    """The note's subset of PyPSA/technology-data for one projection vintage.

    Battery investment costs pass through `battery_override` (the BNEF cap
    above); the returned record row goes to battery_assumptions.csv."""
    df = _costs_csv(TECHNOLOGY_DATA_TAG, cost_year)
    subset = df[df["technology"].isin(KEEP_TECHS)
                & df["parameter"].isin(KEEP_PARAMS)]
    wide = subset.pivot_table(index="technology", columns="parameter",
                             values="value")
    wide = wide.reindex(KEEP_TECHS)
    battery_row = battery_override(wide, cost_year)
    offshore_row = offshore_override(wide, cost_year)
    wide["eur_year"] = EUR_YEAR
    wide["cost_year"] = cost_year
    wide["source_tag"] = TECHNOLOGY_DATA_TAG

    out = PROCESSED / f"technology_costs_{cost_year}.csv"
    wide.to_csv(out, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)} ({len(wide)} technologies)")
    return {"battery": battery_row, "offshore": offshore_row}


def prepare_meta():
    """Hand-authored metadata: labels, assumptions and qualitative ratings."""
    columns = ["label", "family", "fuel", "capacity_factor", "class", "role",
               "q_investment", "q_running", "q_adjustment", "q_time_to_build"]
    frame = pd.DataFrame.from_dict(META, orient="index", columns=columns)
    frame.index.name = "technology"
    frame["order"] = range(len(frame))

    out = PROCESSED / "technology_meta.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Hand-authored. Every column here is an assumption or a\n")
        handle.write("# judgement, not a measurement. capacity_factor is a reference\n")
        handle.write("# annual utilisation for a north-west European system, used only\n")
        handle.write("# for the per-MWh cost decomposition and the 'typical duty' column.\n")
        handle.write("# The four q_* columns reproduce and extend the lecture's Table 1;\n")
        handle.write("# adjustment = difficulty of delivering a CHOSEN output profile,\n")
        handle.write("# so a technology that cannot raise output on command scores High.\n")
        frame.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} technologies)")


def prepare_fuels():
    """Fuel prices and carbon contents: the dataset's, and the note's."""
    df = _costs_csv(TECHNOLOGY_DATA_TAG, REFERENCE_YEAR)
    rows = []
    for carrier in FUEL_CARRIERS + ["waste"] + list(DERIVED_CARRIERS):
        lookup = DERIVED_CARRIERS.get(carrier, carrier)
        sub = df[df["technology"] == lookup]
        price_source = sub.loc[sub["parameter"] == "fuel", "value"]
        co2_source = sub.loc[sub["parameter"] == "CO2 intensity", "value"]
        price_source = float(price_source.iloc[0]) if len(price_source) else None
        co2_source = float(co2_source.iloc[0]) if len(co2_source) else None

        override = FUEL_PRICE_NOTE.get(carrier)
        price_used = price_source if override is None else override
        if carrier in CO2_ZERO_CARRIERS:
            co2_used = 0.0
        elif carrier in CO2_OVERRIDE:
            co2_used = CO2_OVERRIDE[carrier]
        else:
            co2_used = co2_source or 0.0

        rows.append({
            "carrier": carrier,
            "price_source_eur_per_mwh_th": price_source,
            "price_used_eur_per_mwh_th": price_used,
            "price_is_assumption": override is not None,
            "co2_source_t_per_mwh_th": co2_source,
            "co2_used_t_per_mwh_th": co2_used,
            "co2_is_assumption": (carrier in CO2_ZERO_CARRIERS
                                  or carrier in CO2_OVERRIDE),
        })

    frame = pd.DataFrame(rows).set_index("carrier")
    out = PROCESSED / "fuel_assumptions.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# price_source / co2_source: as published in technology-data\n")
        handle.write(f"# ({TECHNOLOGY_DATA_TAG}, EUR{EUR_YEAR}).\n")
        handle.write("# price_used / co2_used: what the note uses. Where these differ,\n")
        handle.write("# the note's value is a stylised 2025 forward level chosen for\n")
        handle.write("# consistency with the rest of the course; biogenic carbon is\n")
        handle.write("# conventionally counted as zero.\n")
        frame.to_csv(handle, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} carriers)")


def prepare_geography():
    """Section 6's regional input deltas.

    No fetch: every row is a stated assumption, written down in code so it is
    versioned with the figure it produces. See the GEOGRAPHY block above for
    why this note carries deltas rather than published regional levels.
    """
    frame = pd.DataFrame(
        GEOGRAPHY,
        columns=["region", "parameter", "value", "unit", "basis", "source"])

    out = PROCESSED / "geography_assumptions.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Regional input assumptions for section 6.\n")
        handle.write("# EVERY ROW IS AN ASSUMPTION, NOT A MEASUREMENT. The note\n")
        handle.write("# re-prices its own European technology through equation (4.2)\n")
        handle.write("# under these inputs; it does not quote regional levels from\n")
        handle.write("# any external source, because those cannot be harmonised.\n")
        frame.to_csv(handle, index=False, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)} "
          f"({len(frame)} rows, {frame.region.nunique()} regions)")


def prepare_vintages():
    """Investment cost for a fixed target year, as each release stated it."""
    rows = []
    for tag, date in VINTAGE_TAGS:
        df = _costs_csv(tag, VINTAGE_TARGET)
        sub = df[(df["parameter"] == "investment")
                 & (df["technology"].isin(VINTAGE_TECHS))]
        for _, record in sub.iterrows():
            rows.append({
                "release": tag,
                "released": date,
                "target_year": VINTAGE_TARGET,
                "technology": record["technology"],
                "investment_eur_per_kw": record["value"],
            })

    frame = pd.DataFrame(rows)
    out = PROCESSED / "cost_vintages.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# The same projection, as successive releases of the same\n")
        handle.write("# catalogue stated it. Money is nominal EUR as published; the\n")
        handle.write("# step between the 2023 and 2024 releases is largely a currency\n")
        handle.write("# rebasing, which is itself part of the point.\n")
        frame.to_csv(handle, index=False, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} rows)")


def prepare_solar_learning():
    """World PV module price and cumulative installed capacity, from OWID."""
    def owid(slug: str) -> pd.DataFrame:
        raw = RAW / "owid" / f"{slug}.csv"
        url = (f"https://ourworldindata.org/grapher/{slug}.csv"
               "?csvType=full&useColumnShortNames=true")
        return pd.read_csv(io.BytesIO(_cached(url, raw)))

    price = owid("solar-pv-prices")
    capacity = owid("installed-solar-PV-capacity")

    price = price[price["entity"] == "World"][["year", "cost"]]
    price = price.rename(columns={"cost": "module_price_usd_per_w"})
    capacity = capacity[capacity["entity"] == "World"][["year", "solar__total_gw"]]
    capacity = capacity.rename(columns={"solar__total_gw": "cumulative_capacity_gw"})

    # Outer join: the price series starts in 1975 and the capacity series in
    # 2000, and section 4 uses both the long price history and the overlap.
    frame = price.merge(capacity, on="year", how="outer").sort_values("year")

    out = PROCESSED / "solar_learning.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Our World in Data (CC-BY 4.0), retrieved at build time.\n")
        handle.write("# module_price_usd_per_w: world average PV module price, constant\n")
        handle.write("#   USD per watt of capacity (OWID after Nemet and IRENA).\n")
        handle.write("# cumulative_capacity_gw: world cumulative installed PV capacity.\n")
        handle.write("# The price series starts in 1975, the capacity series in 2000.\n")
        frame.to_csv(handle, index=False, float_format="%.6f")
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} years)")


def write_manifest():
    """A machine-readable record of what was fetched, and from where."""
    manifest = {
        "technology_data_tag": TECHNOLOGY_DATA_TAG,
        "eur_year": EUR_YEAR,
        "cost_years": COST_YEARS,
        "reference_year": REFERENCE_YEAR,
        "discount_rate": DISCOUNT_RATE,
        "vintage_releases": [{"tag": t, "released": d} for t, d in VINTAGE_TAGS],
        "vintage_target_year": VINTAGE_TARGET,
        "battery_override": {
            "cap_eur_per_kwh_system": BATTERY_CAP_EUR_PER_KWH,
            "cap_hours": BATTERY_CAP_HOURS,
            "source_usd_per_kwh_europe": BATTERY_BNEF_EUROPE_USD_PER_KWH,
            "source": ("BloombergNEF, Energy Storage System Cost Survey 2025 "
                       "(December 2025, press-release figures); see "
                       "battery_assumptions.csv"),
        },
        # Section 6 fetches nothing. Its inputs are stated assumptions, and
        # recording that here keeps the manifest an honest account of what is
        # measured and what is not.
        "geography": {
            "regions": GEOGRAPHY_REGIONS,
            "source": ("No dataset. Every row of geography_assumptions.csv is "
                       "an illustrative assumption; section 6 re-prices the "
                       "note's own European technology under them rather than "
                       "quoting regional levels from any external source."),
        },
        "sources": {
            "technology-data": (
                "https://github.com/PyPSA/technology-data at tag "
                f"{TECHNOLOGY_DATA_TAG}; outputs/costs_YYYY.csv; EUR{EUR_YEAR}"),
            "solar-pv-prices": (
                "https://ourworldindata.org/grapher/solar-pv-prices (CC-BY 4.0)"),
            "installed-solar-PV-capacity": (
                "https://ourworldindata.org/grapher/installed-solar-PV-capacity"
                " (CC-BY 4.0)"),
        },
    }
    out = PROCESSED / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(NOTE)}")


def main():
    PROCESSED.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    cost_rows = [prepare_costs(year) for year in COST_YEARS]
    write_battery_assumptions([r["battery"] for r in cost_rows])
    write_offshore_assumptions([r["offshore"] for r in cost_rows])
    prepare_meta()
    prepare_fuels()
    prepare_geography()
    prepare_vintages()
    prepare_solar_learning()
    write_manifest()
    print("\nstage 1 complete")


if __name__ == "__main__":
    main()
