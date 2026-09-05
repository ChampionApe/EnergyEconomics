"""Turn raw downloads into the processed inputs the pipeline reads.

    python data/prepare.py                 everything (slow; needs the network)
    python data/prepare.py --costs-only     only the cost tables that are not shipped

Stage 1 of the pipeline. Reads `data/raw/`, writes `data/processed/`.
Deterministic and re-runnable. Never reads `results/`.

`data/raw/` is read-only: never edit a download in place, or the pipeline stops
being reproducible from the original source. Every transformation belongs here,
in code. A raw file that already exists is not fetched again, so re-running
this script is cheap and offline once the downloads are in place; delete the
raw file to force a fresh download.

Only `data/processed/` is published, so anything a student needs in order to
reproduce a figure has to survive this stage. Record every dataset's
provenance in data/README.md.

Currently prepares:

    processed/profiles_{dk1,dk2}_{year}.csv/.json
        hourly load and wind/solar availability profiles per price area
        (section 3, and the model-vs-market comparisons; DK1 and DK2 for
        2019-2024) from Energi Data Service's validated settlement data
        (CC-BY 4.0, no API key, no registration)
    processed/actual_dispatch_dk1_2024.csv
        what DK1 actually generated, hour by hour and by category, in MW,
        plus net imports — the realised counterpart the note holds a week of
        modelled dispatch against (section 3)
    processed/weather_zones_{2015..2024}.csv  + weather_zones.json
        per-unit wind and solar availability for all twelve bidding zones on
        one consistent weather year, from Open-Meteo's ERA5 archive (CC-BY
        4.0, no key) — what section 8's sweep re-solves over
    processed/temperature_dk_2024.csv
        hourly 2m temperature for Aarhus (section 5's heat pump COP) from
        the Open-Meteo historical archive (CC-BY 4.0, no key)
    processed/technology_costs_full_{2025..2050}.csv
        the note's subset of PyPSA/technology-data, one file per cost
        projection vintage, FETCHED AT A PINNED TAG and reshaped; never
        vendored from this repository in raw form. 2030 is section 7's
        reference; section 8 sweeps the rest
    processed/spot_2024.csv
        actual day-ahead prices per bidding zone (Elspotprices: DK1, DK2,
        DE, NO2, SE3, SE4) — the real-world counterparts the note holds its
        model prices against
    processed/exchange_{dk1,dk2}_2024.csv
        actual cross-border exchange flows of the Danish zones, for the
        realised congestion-rent comparison of section 6
    processed/transmission_costs.csv
        what a wire costs: technology-data's rows for overhead AC, overhead
        and submarine DC and the DC converter pair (section 6's
        introduction to transmission grids)
    processed/bidding_zones.json
        Europe's bidding zones as projected polygons, assembled from Natural
        Earth (public domain) subdivisions, plus the network's zone
        coordinates — section 6's map and topology figures
    processed/transmission_ntc_reference.csv
        TYNDP's reference-grid transfer capacities between the zones, both
        directions; section 6 derates the network's internal Nordic
        corridors (thermal ratings) to them
    processed/hydro_calibration.csv
        the network's hydro energy beside the published production of its
        year; section 6 scales Norwegian reservoir inflow to it

Not prepared here: processed/network_eur_bz_2024.nc — the 12-bidding-zone
network of sections 6-8 is the exported product of the PyPSA-Eur stage-0 run
(documented in the note's Appendix C) and is vendored directly.
"""

import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd


def _get(url: str, timeout: int = 300) -> bytes:
    """GET with polite retry — the EDS API rate-limits bursts of year-sized
    requests with HTTP 429."""
    for wait in [0, 10, 30, 90, 300, 600, 900]:
        if wait:
            print(f"  rate-limited, retrying in {wait}s...")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
    raise SystemExit(f"still rate-limited after retries: {url[:80]}")

NOTE = Path(__file__).resolve().parent.parent
RAW = NOTE / "data" / "raw"
PROCESSED = NOTE / "data" / "processed"

EDS_API = "https://api.energidataservice.dk/dataset"

# The note's reference year (2024, a leap year: 8784 hours), and the weather
# years of section 8's sweep.
YEAR = 2024
WEATHER_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

# The pin is what makes the technology-data fetch reproducible: an unpinned
# fetch would make the note's numbers drift silently. See PLAN.md.
TECHNOLOGY_DATA_TAG = "v0.13.2"
TECHNOLOGY_DATA_YEAR = 2030

# The cost vintages section 8 sweeps. These are *projections* of what a
# technology will cost in a given year, not draws from a distribution, and the
# note is careful to say so — but the spread between the earliest and the
# latest is a fair picture of how much the answer depends on the cost
# assumptions rather than on the energy system.
COST_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


# Every wire out of a Danish price area, in the EDS convention where a
# positive value is an import. This list must be complete or the area does
# not balance: DK1 gained COBRAcable to the Netherlands and Viking Link to
# Great Britain, and leaving the two out made 2024 look like a 4.5 TWh net
# import (it was 0.06) and left 34% of load unaccounted for in the realised
# dispatch of figure 3.8. Anything summing exchange sums *this*.
EXCHANGE_COLUMNS = [
    "ExchangeNO_MWh",       # Skagerrak, to southern Norway
    "ExchangeSE_MWh",       # Konti-Skan, to Sweden
    "ExchangeGE_MWh",       # the Jutland interconnectors, to Germany
    "ExchangeNL_MWh",       # COBRAcable, to the Netherlands (DK1 only)
    "ExchangeGB_MWh",       # Viking Link, to Great Britain (DK1 only)
    "ExchangeGreatBelt_MWh",  # the Great Belt link, DK1 to DK2
]

# The settlement columns we ask EDS for. Kept as a module constant because the
# raw cache is validated against it: adding a column here makes every cached
# file stale, and fetch_settlement re-downloads rather than silently serving an
# old file that lacks the new field. That failure mode cost an afternoon once.
SETTLEMENT_COLUMNS = [
    "HourUTC",
    "GrossConsumptionMWh",
    # variable renewables -> the availability profiles
    "OnshoreWindLt50kW_MWh",
    "OnshoreWindGe50kW_MWh",
    "OffshoreWindLt100MW_MWh",
    "OffshoreWindGe100MW_MWh",
    "SolarPowerLt10kW_MWh",
    "SolarPowerGe10Lt40kW_MWh",
    "SolarPowerGe40kW_MWh",
    "SolarPowerSelfConMWh",
    # thermal and trade -> the realised-dispatch comparison of section 3
    "CentralPowerMWh",
    "LocalPowerMWh",
    "LocalPowerSelfConMWh",
    "CommercialPowerMWh",
] + EXCHANGE_COLUMNS


def fetch_settlement(area: str, year: int) -> Path:
    """Download one year of hourly settlement data for one price area.

    Dataset: ProductionConsumptionSettlement — validated hourly production by
    category and gross consumption, per price area. The API needs no key; the
    start/end parameters are in Danish local time.
    """
    out = RAW / "energidataservice" / f"ProductionConsumptionSettlement_{area}_{year}.json"
    if out.exists():
        try:
            cached = json.loads(out.read_text(encoding="utf-8"))["records"]
        except (ValueError, KeyError):
            cached = []
        have = set(cached[0]) if cached else set()
        missing = [c for c in SETTLEMENT_COLUMNS if c not in have]
        if not missing:
            print(f"raw exists, not fetching: {out.relative_to(NOTE)}")
            return out
        print(
            f"raw is stale ({len(missing)} column(s) missing, e.g. "
            f"{missing[0]}), re-fetching: {out.relative_to(NOTE)}"
        )

    params = {
        "start": f"{year}-01-01T00:00",
        "end": f"{year + 1}-01-01T00:00",
        "filter": json.dumps({"PriceArea": [area]}),
        "columns": ",".join(SETTLEMENT_COLUMNS),
        "sort": "HourUTC ASC",
        "limit": "0",  # no limit: the full year in one response
    }
    url = f"{EDS_API}/ProductionConsumptionSettlement?{urllib.parse.urlencode(params)}"
    print(f"fetching {url[:100]}...")
    payload = _get(url)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(f"wrote {out.relative_to(NOTE)} ({len(payload) / 1e6:.1f} MB)")
    return out


def prepare_profiles(raw_file: Path, area: str, year: int):
    """Reshape the settlement data into the profiles the models read.

    Output columns:

        load_mw           gross consumption, MW
        wind_onshore_pu   production divided by its maximum over the year
        wind_offshore_pu             --  ""  --
        solar_pu                     --  ""  --

    Normalising production by its annual maximum is a proxy for the
    availability profile per unit of capacity: it ignores that installed
    capacity grows within the year and that the fleet's true peak need not
    reach nameplate. It is the standard classroom shortcut, and the note says
    so where the profiles are introduced. The maxima are written alongside so
    the normalisation is visible.
    """
    records = json.loads(raw_file.read_text(encoding="utf-8"))["records"]
    df = pd.DataFrame.from_records(records).set_index("HourUTC")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    out = pd.DataFrame(index=df.index)
    out["load_mw"] = df["GrossConsumptionMWh"]
    groups = {
        "wind_onshore": ["OnshoreWindLt50kW_MWh", "OnshoreWindGe50kW_MWh"],
        "wind_offshore": ["OffshoreWindLt100MW_MWh", "OffshoreWindGe100MW_MWh"],
        "solar": [
            "SolarPowerLt10kW_MWh",
            "SolarPowerGe10Lt40kW_MWh",
            "SolarPowerGe40kW_MWh",
            "SolarPowerSelfConMWh",
        ],
    }
    maxima = {}
    for name, cols in groups.items():
        production = df[cols].sum(axis=1)
        maxima[name] = float(production.max())
        out[f"{name}_pu"] = production / production.max()

    if out.isna().any().any():
        raise SystemExit("missing hours in the settlement data — inspect the raw file")

    stem = f"profiles_{area.lower()}_{year}"
    csv = PROCESSED / f"{stem}.csv"
    out.to_csv(csv, index_label="time", float_format="%.6f")
    print(f"wrote {csv.relative_to(NOTE)} ({len(out)} hours)")

    meta = {
        "source": f"Energi Data Service, ProductionConsumptionSettlement, {area}",
        "licence": "CC-BY 4.0",
        "year": year,
        "hours": len(out),
        "normalisation_max_mw": maxima,
        "capacity_factor_of_profile": {
            name: float(out[f"{name}_pu"].mean()) for name in groups
        },
        "load_mean_mw": float(out["load_mw"].mean()),
        "load_max_mw": float(out["load_mw"].max()),
    }
    (PROCESSED / f"{stem}.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"wrote {(PROCESSED / f'{stem}.json').relative_to(NOTE)}")


def prepare_actual_dispatch(raw_file: Path, area: str, year: int):
    """What the real system actually did, hour by hour, by category.

    The profiles above normalise production away, because the models want
    availability per unit of capacity. This keeps the levels, in MW, so the
    note can hold a week of modelled dispatch against a week of the real
    thing (figure 3.8).

    Output columns, all MW:

        wind, solar            as in the profiles, but not normalised
        central_power          large central thermal plants
        local_power            decentralised CHP (incl. self-consumption)
        commercial_power       industrial/commercial generation
        net_imports            imports minus exports across all borders

    The exchange columns are signed imports in the EDS convention, so their
    sum is net imports and goes negative when the area exports. That column
    is the interesting one: the note's single-zone model has no trade at all,
    and this is the size of what it is missing.
    """
    records = json.loads(raw_file.read_text(encoding="utf-8"))["records"]
    df = pd.DataFrame.from_records(records).set_index("HourUTC")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index().fillna(0.0)

    out = pd.DataFrame(index=df.index)
    out["load_mw"] = df["GrossConsumptionMWh"]
    out["wind"] = df[
        ["OnshoreWindLt50kW_MWh", "OnshoreWindGe50kW_MWh",
         "OffshoreWindLt100MW_MWh", "OffshoreWindGe100MW_MWh"]
    ].sum(axis=1)
    out["solar"] = df[
        ["SolarPowerLt10kW_MWh", "SolarPowerGe10Lt40kW_MWh",
         "SolarPowerGe40kW_MWh", "SolarPowerSelfConMWh"]
    ].sum(axis=1)
    out["central_power"] = df["CentralPowerMWh"]
    out["local_power"] = df[["LocalPowerMWh", "LocalPowerSelfConMWh"]].sum(axis=1)
    out["commercial_power"] = df["CommercialPowerMWh"]
    out["net_imports"] = df[EXCHANGE_COLUMNS].sum(axis=1)

    csv = PROCESSED / f"actual_dispatch_{area.lower()}_{year}.csv"
    out.to_csv(csv, index_label="time", float_format="%.2f")
    print(f"wrote {csv.relative_to(NOTE)} ({len(out)} hours)")


def prepare_temperature():
    """Hourly 2m temperature for Aarhus, for the heat pump COP of section 5.

    Source: Open-Meteo historical weather archive (ERA5-derived), CC-BY 4.0,
    no API key. One inland-ish Danish location is enough — the COP curve, not
    the geography, is the lesson.
    """
    out_csv = PROCESSED / f"temperature_dk_{YEAR}.csv"
    raw_file = RAW / "openmeteo" / f"temperature_aarhus_{YEAR}.json"
    if not raw_file.exists():
        params = {
            "latitude": "56.16",
            "longitude": "10.20",
            "start_date": f"{YEAR}-01-01",
            "end_date": f"{YEAR}-12-31",
            "hourly": "temperature_2m",
            "timezone": "UTC",
        }
        url = f"https://archive-api.open-meteo.com/v1/archive?{urllib.parse.urlencode(params)}"
        print(f"fetching {url[:100]}...")
        payload = _get(url)
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
        print(f"wrote {raw_file.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {raw_file.relative_to(NOTE)}")

    data = json.loads(raw_file.read_text(encoding="utf-8"))["hourly"]
    df = pd.DataFrame(
        {"temperature_c": data["temperature_2m"]},
        index=pd.to_datetime(data["time"]),
    )
    df.to_csv(out_csv, index_label="time", float_format="%.2f")
    print(f"wrote {out_csv.relative_to(NOTE)} ({len(df)} hours)")


# --- Zonal weather for section 8's sweep -----------------------------------
# The decade the sweep runs over. Open-Meteo's ERA5 archive reaches back to
# 1940, so this is a choice about how many greenfield solves we want, not a
# data limit.
SWEEP_YEARS = list(range(2015, 2025))

# Wind speed -> capacity factor. The textbook idealisation: nothing below
# cut-in, cubic between cut-in and rated, flat at rated, nothing above cut-out.
# It is a shape, not a machine: the *level* of every profile is rescaled in
# model/network.py to preserve the capacity factor the network already
# carries, so what this curve has to get right is the timing, not the height.
WIND_CUT_IN_MS = 3.0
WIND_RATED_MS = 12.0
WIND_CUT_OUT_MS = 25.0

# Radiation at which a panel is taken to be at nameplate (W/m2), standard
# test conditions. Same remark: only the shape survives rescaling.
SOLAR_REFERENCE_WM2 = 1000.0


def _wind_capacity_factor(speed):
    """Piecewise power curve, applied to a pandas Series of m/s at 100 m."""
    v = speed.clip(lower=0.0)
    below = v < WIND_CUT_IN_MS
    ramp = (v >= WIND_CUT_IN_MS) & (v < WIND_RATED_MS)
    rated = (v >= WIND_RATED_MS) & (v <= WIND_CUT_OUT_MS)
    cf = pd.Series(0.0, index=v.index)
    cf[ramp] = ((v[ramp] ** 3 - WIND_CUT_IN_MS ** 3)
                / (WIND_RATED_MS ** 3 - WIND_CUT_IN_MS ** 3))
    cf[rated] = 1.0
    cf[below] = 0.0
    return cf.clip(0.0, 1.0)


# How far to spread the sampling points around a zone's centre, in degrees
# (lat, lon). A real fleet is spread over its zone's geography, and that
# spreading is what makes two *countries* more correlated than two points:
# each country's series is smoothed toward the synoptic weather both share.
# Sampling one point per zone gets this badly wrong -- it leaves DK1 and DE
# correlated at about 0.33 where the network's own profiles say 0.58. So each
# zone is sampled on a five-point cross whose width reflects how large the
# zone is. It is a crude stand-in for the proper aggregation, and the achieved
# correlations are checked against the network's own profiles rather than
# assumed (see the note's Appendix C).
ZONE_SPREAD_DEG = {
    "DE": (2.5, 3.5),
    "DK1": (0.7, 1.0), "DK2": (0.5, 0.8),
    "NO1": (1.5, 2.0), "NO2": (1.5, 2.0), "NO3": (1.5, 2.5),
    "NO4": (1.8, 4.0), "NO5": (1.2, 1.8),
    "SE1": (1.8, 3.0), "SE2": (1.8, 3.0),
    "SE3": (1.2, 2.5), "SE4": (0.8, 1.2),
}
DEFAULT_SPREAD_DEG = (1.2, 2.0)


def zone_sample_points(zone: str, lat: float, lon: float):
    """The five points a zone's availability is averaged over."""
    dlat, dlon = ZONE_SPREAD_DEG.get(zone, DEFAULT_SPREAD_DEG)
    return [
        (lat, lon),
        (min(lat + dlat, 71.0), lon),
        (max(lat - dlat, 47.0), lon),
        (lat, lon + dlon),
        (lat, lon - dlon),
    ]


def fetch_zone_weather(zone: str, index: int, lat: float, lon: float) -> Path:
    """One request per sampling point for the whole decade: wind at 100 m and
    surface radiation, hourly, from Open-Meteo's ERA5 archive.

    CC-BY 4.0, no API key and no registration — the same source and the same
    terms as the temperature series of section 5.
    """
    out = (RAW / "openmeteo" /
           f"zone_weather_{zone}_p{index}_{SWEEP_YEARS[0]}_{SWEEP_YEARS[-1]}.json")
    if out.exists():
        return out
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": f"{SWEEP_YEARS[0]}-01-01",
        "end_date": f"{SWEEP_YEARS[-1]}-12-31",
        "hourly": "wind_speed_100m,shortwave_radiation",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    url = f"https://archive-api.open-meteo.com/v1/archive?{urllib.parse.urlencode(params)}"
    print(f"  fetching {zone} point {index} ({lat:.2f}, {lon:.2f})")
    payload = _get(url)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return out


def prepare_zone_weather():
    """Per-unit wind and solar availability for all twelve bidding zones, one
    file per year, on a single consistent weather year across the whole map.

    This is what section 8's sweep needs and what the Danish-only EDS profiles
    could never give: when the sweep asks what a 2021 system looks like, every
    zone gets 2021 weather, so a Danish calm spell is matched by whatever
    Germany and Norway were doing at the same hour. Getting that correlation
    right is the point — a becalmed Denmark that can always import from a
    windy Germany makes trade look better than it is.

    The representative point for each zone is the zone's own bus coordinate in
    the network the models solve, so the weather is sampled where the model
    thinks the zone is.
    """
    import pypsa

    network_file = PROCESSED / "network_eur_bz_2024.nc"
    if not network_file.exists():
        print(f"note: {network_file.name} missing — skipping zonal weather")
        return
    buses = pypsa.Network(str(network_file)).buses[["x", "y"]]

    series = {}
    for zone, row in buses.iterrows():
        points = zone_sample_points(zone, lat=row.y, lon=row.x)
        print(f"{zone}: averaging {len(points)} points")
        winds, rads = [], []
        for i, (lat, lon) in enumerate(points):
            raw = fetch_zone_weather(zone, i, lat, lon)
            hourly = json.loads(raw.read_text(encoding="utf-8"))["hourly"]
            idx = pd.to_datetime(hourly["time"])
            speed = pd.Series(hourly["wind_speed_100m"], index=idx,
                              dtype="float64").interpolate()
            rad = pd.Series(hourly["shortwave_radiation"], index=idx,
                            dtype="float64").interpolate()
            # Convert each point to a capacity factor *before* averaging: the
            # power curve is nonlinear, so averaging wind speeds first and
            # converting once would misstate the fleet's output.
            winds.append(_wind_capacity_factor(speed))
            rads.append((rad / SOLAR_REFERENCE_WM2).clip(0.0, 1.0))
        series[f"{zone}_wind_pu"] = pd.concat(winds, axis=1).mean(axis=1)
        series[f"{zone}_solar_pu"] = pd.concat(rads, axis=1).mean(axis=1)

    frame = pd.DataFrame(series).sort_index()
    for year in SWEEP_YEARS:
        block = frame.loc[str(year)]
        out = PROCESSED / f"weather_zones_{year}.csv"
        block.to_csv(out, index_label="time", float_format="%.4f")
        print(f"wrote {out.relative_to(NOTE)} ({len(block)} hours, "
              f"{len(buses)} zones)")

    meta = {
        "source": "Open-Meteo historical weather archive (ERA5)",
        "licence": "CC-BY 4.0",
        "url": "https://open-meteo.com/en/docs/historical-weather-api",
        "years": SWEEP_YEARS,
        "variables": ["wind_speed_100m", "shortwave_radiation"],
        "zone_sample_points": {
            z: zone_sample_points(z, float(r.y), float(r.x))
            for z, r in buses.iterrows()
        },
        "wind_power_curve": {"cut_in_ms": WIND_CUT_IN_MS,
                             "rated_ms": WIND_RATED_MS,
                             "cut_out_ms": WIND_CUT_OUT_MS},
        "solar_reference_wm2": SOLAR_REFERENCE_WM2,
        "note": ("Shapes only. model/network.py rescales each series so the "
                 "swapped year preserves the capacity factor the network's "
                 "own atlite-derived profile carries."),
    }
    (PROCESSED / "weather_zones.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"wrote {(PROCESSED / 'weather_zones.json').relative_to(NOTE)}")


# ---------------------------------------------------------------------------
# The shared battery-cost override.
#
# THIS BLOCK IS SHARED WITH THE TECHNOLOGIES NOTE and must stay identical to
# the one in notes/technologies/data/prepare.py, for the same reason as the
# fuel block below: the two notes price the same machines and publish
# independently. tools/check_note_consistency.py compares the generated
# battery_assumptions.csv files.
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
        handle.write("# numbers. Identical to the block in the technologies note.\n")
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
        handle.write("# Identical to the block in the technologies note.\n")
        frame.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} vintages)")


# ---------------------------------------------------------------------------
# Offshore wind, which technology-data prices in a way this note cannot use.
#
# PyPSA's `offwind` is NOT the cost of an offshore wind farm. The Danish
# Energy Agency's sheet 21 gives a total nominal investment; technology-data
# subtracts one line from it -- the INSTALLATION half of grid connection --
# because PyPSA-Eur puts distance-specific cabling back on per wind farm.
# The equipment half stays in. Verified against the catalogue itself:
#
#     DEA total 2050              1.64274 MEUR/MW
#     less installation: grid     0.11881
#     =                           1.52393  = technology-data's offwind, exactly
#
# This note adds no cabling of its own, so it must use the DEA total. Without
# this correction offshore is 7.8% too cheap, and since offshore competes
# against onshore on VALUE rather than on cost per MW, a few per cent decides
# which one a zone builds.
DEA_CATALOGUE = "technology_data_for_el_and_dh_v0.13.2.xlsx"
DEA_OFFSHORE_SHEET = "21 Offshore turbines"
DEA_OFFSHORE_YEAR_ROW = 2
DEA_OFFSHORE_TOTAL_ROW = 19
DEA_OFFSHORE_GRID_INSTALL_ROW = 33


def _dea_offshore_rows() -> tuple:
    """(years, total, installation-grid-connection) from the DEA catalogue,
    MEUR/MW in 2020 euros."""
    import openpyxl

    path = RAW / "technology-data" / DEA_CATALOGUE
    if not path.exists():
        # The Danish Energy Agency sheet technology-data itself is built
        # from, fetched from the same pinned tag as the compiled outputs.
        url = (
            "https://raw.githubusercontent.com/PyPSA/technology-data/"
            f"{TECHNOLOGY_DATA_TAG}/inputs/technology_data_for_el_and_dh.xlsx"
        )
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


def prepare_costs_full(cost_year: int = None) -> dict:
    """The note's subset of PyPSA/technology-data, fetched at a pinned tag.

    The compiled output CSVs carry no single stated licence, so they are
    fetched and reshaped, never vendored raw (see PLAN.md and data/README.md).
    The subset kept: the investment-relevant parameters for the greenfield
    candidates of section 7 plus the storage and heat technologies of
    sections 4-5. Battery investment costs pass through `battery_override`
    (the BNEF cap above); the returned record row goes to
    battery_assumptions.csv.

    `cost_year` selects the projection vintage. 2030 is the note's reference
    and what section 7 solves on; section 8 sweeps the rest to ask how much of
    a capacity expansion answer is a statement about technology costs rather
    than about the energy system.
    """
    cost_year = TECHNOLOGY_DATA_YEAR if cost_year is None else cost_year
    raw_file = RAW / "technology-data" / f"costs_{cost_year}_{TECHNOLOGY_DATA_TAG}.csv"
    if not raw_file.exists():
        url = (
            "https://raw.githubusercontent.com/PyPSA/technology-data/"
            f"{TECHNOLOGY_DATA_TAG}/outputs/costs_{cost_year}.csv"
        )
        print(f"fetching {url}")
        payload = _get(url)
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
        print(f"wrote {raw_file.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {raw_file.relative_to(NOTE)}")

    df = pd.read_csv(raw_file)
    keep_techs = [
        "solar-utility", "onwind", "offwind", "CCGT", "OCGT",
        "central solid biomass CHP", "waste CHP",
        "battery inverter", "battery storage",
        "central air-sourced heat pump", "central gas boiler",
        "coal", "lignite", "nuclear", "gas", "oil", "solid biomass",
        # The hydrogen chain of section 9. `electrolysis` and `fuel cell`
        # are the machines; the two storage rows are the decision that
        # matters -- a cavern is a factor of twenty cheaper per kWh than a
        # tank, and only some of the twelve zones have salt geology
        # (Caglayan et al. 2020). Both are kept so the choice is visible in
        # the data rather than buried in the model.
        "electrolysis", "fuel cell",
        "hydrogen storage underground",
        "hydrogen storage tank type 1 including compressor",
        # Reforming: the incumbent way to make hydrogen, and the alternative
        # section 9's every rung has to the electrolytic route.
        "H2 production natural gas steam reforming",
    ]
    keep_params = ["investment", "lifetime", "FOM", "VOM", "efficiency", "fuel", "CO2 intensity"]
    subset = df[df["technology"].isin(keep_techs) & df["parameter"].isin(keep_params)]
    wide = subset.pivot_table(index="technology", columns="parameter", values="value")
    battery_row = battery_override(wide, cost_year)
    offshore_row = offshore_override(wide, cost_year)
    wide["unit_note"] = "investment EUR/kW(h); FOM %/year; VOM EUR/MWh; fuel EUR/MWh_th"

    out_csv = PROCESSED / f"technology_costs_full_{cost_year}.csv"
    wide.to_csv(out_csv, float_format="%.4f")
    print(f"wrote {out_csv.relative_to(NOTE)} (tag {TECHNOLOGY_DATA_TAG})")
    return {"battery": battery_row, "offshore": offshore_row}


# ---------------------------------------------------------------------------
# The shared fuel block.
#
# THIS BLOCK IS SHARED WITH THE TECHNOLOGIES NOTE and must stay identical to
# the one in notes/technologies/data/prepare.py. It is duplicated rather than
# imported on purpose: the two notes publish independently and neither may
# depend on the other's directories. What they share is a source and a set of
# assumptions, not a file.
#
# Prices are stylised 2025 forward levels rather than technology-data's own,
# which are inherited from a 2013 study and sit well below what European
# plants have paid recently. Carbon contents are technology-data's, with two
# deliberate exceptions recorded below.
FUEL_PRICE = {
    "gas": 35.0,
    "coal": 12.0,
    "lignite": 5.0,
    "oil": 55.0,
    "solid biomass": 25.0,
    "wood pellets": 38.0,   # the same plant, a more expensive fuel
    "biomethane": 90.0,     # grid-quality upgraded biogas, 2025 forward level
    "uranium": None,        # None: keep the dataset's own value
    "waste": 0.0,           # gate fees ignored; the plant is paid to take it
}
# Biogenic carbon is conventionally counted as zero in this accounting.
CO2_ZERO_CARRIERS = ["solid biomass", "wood pellets", "biomethane"]
# Municipal waste is only partly biogenic: roughly half of it by energy
# content is plastics, and that half is fossil carbon like any other.
CO2_OVERRIDE = {"waste": 0.15}

FUEL_CARRIERS = ["gas", "coal", "lignite", "oil", "solid biomass", "uranium"]
# Carriers with no technology-data row of their own, priced off another:
# "wood pellets" is solid biomass at a higher price; "biomethane" is
# technology-data's "biogas" fuel after upgrading to grid quality.
DERIVED_CARRIERS = {"wood pellets": "solid biomass", "biomethane": "biogas"}


def prepare_fuels():
    """Fuel prices and carbon contents: the dataset's, and the note's.

    One file, read by all three tiers of the note's data -- the small table of
    sections 2-5, the re-pricing of the shipped network in sections 6-8, and
    the greenfield candidates of section 7. Before this existed the three
    disagreed: the network ran on gas at roughly 23 EUR/MWh_th while section 2
    told the reader it cost 35, and nothing in the pipeline noticed.
    """
    raw_file = RAW / "technology-data" / f"costs_{TECHNOLOGY_DATA_YEAR}_{TECHNOLOGY_DATA_TAG}.csv"
    df = pd.read_csv(raw_file)

    rows = []
    for carrier in FUEL_CARRIERS + ["waste"] + list(DERIVED_CARRIERS):
        lookup = DERIVED_CARRIERS.get(carrier, carrier)
        sub = df[df["technology"] == lookup]
        price_source = sub.loc[sub["parameter"] == "fuel", "value"]
        co2_source = sub.loc[sub["parameter"] == "CO2 intensity", "value"]
        price_source = float(price_source.iloc[0]) if len(price_source) else None
        co2_source = float(co2_source.iloc[0]) if len(co2_source) else None

        override = FUEL_PRICE.get(carrier)
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
        handle.write("# Fuel prices and carbon contents used EVERYWHERE in this note:\n")
        handle.write("# the small table of sections 2-5, the re-pricing of the shipped\n")
        handle.write("# network in sections 6-8, and the greenfield candidates of\n")
        handle.write("# section 7. Identical to the block in the technologies note.\n")
        handle.write(f"# *_source: as published in technology-data {TECHNOLOGY_DATA_TAG}.\n")
        handle.write("# *_used: what the note assumes. Where they differ the note's\n")
        handle.write("# value is an assumption, flagged in the *_is_assumption columns.\n")
        frame.to_csv(handle, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} carriers)")


# The ten technologies of the small table: key -> (label, technology-data
# technology, fuel carrier). Every parameter is read from technology-data, so
# a machine named here is the SAME machine as in the technologies note, with
# the same efficiency and the same variable operating cost.
# The small table reports TODAY's plants, so it uses the 2025 vintage -- the
# same one the technologies note's catalogue reports, which is what makes the
# two tables identical rather than merely similar. Sections 7-8 keep the 2030
# vintage, because they are asking what it costs to BUILD for 2030, and
# section 8's sweep is about exactly that. run_greenfield's costs_check()
# surfaces the residual difference, which is under 2% on efficiency.
SMALL_TABLE_YEAR = 2025

SMALL_TABLE = {
    # key: (label, technology-data technology, fuel carrier, footnote)
    "solar_pv": (
        "Solar PV", "solar-utility", None,
        "Utility-scale photovoltaics. No fuel, and no variable operating "
        "cost in the source."),
    "wind_onshore": (
        "Onshore wind", "onwind", None,
        "Onshore wind turbines."),
    "wind_offshore": (
        "Offshore wind", "offwind", None,
        "Offshore wind turbines. The variable operating cost is nominal."),
    "waste_chp": (
        "Waste CHP", "waste CHP", "waste",
        "Waste-to-energy plant. The fuel is free at the gate (gate-fee "
        "revenue ignored) but the plant carries a large variable operating "
        "cost; only the fossil share of municipal waste is counted as "
        "emitting."),
    "coal_chp": (
        "Coal", "coal", "coal",
        "Hard-coal plant."),
    "wood_chips_chp": (
        "Wood-chip CHP", "central solid biomass CHP", "solid biomass",
        "District-heating biomass plant, priced on wood chips; biogenic "
        "CO$_2$ counted as zero."),
    "wood_pellets_chp": (
        "Wood-pellet CHP", "central solid biomass CHP", "wood pellets",
        "The same plant burning pellets: identical machine, more expensive "
        "fuel."),
    "ccgt": (
        "Gas CCGT", "CCGT", "gas",
        "Combined-cycle gas turbine."),
    "ocgt": (
        "Gas OCGT", "OCGT", "gas",
        "Open-cycle gas turbine -- the same fuel, a cheaper and less "
        "efficient machine."),
    "oil_peak": (
        "Oil peaker", "oil", "oil",
        "Oil-fired peaking plant."),
}


def prepare_costs_small():
    """The ten-technology table of sections 2-5, derived not hand-authored.

    It used to be a hand-compiled file, which is how it drifted away from both
    the shipped network and the technologies note. Every number here now comes
    from technology-data at the pinned tag plus the shared fuel block above, so
    the table students meet in section 2 and the one they meet in the
    technologies note are the same numbers for the same machines.

    Marginal costs and emission rates are still NOT stored: model code derives
    them, so table and model cannot disagree.
    """
    costs = pd.read_csv(
        PROCESSED / f"technology_costs_full_{SMALL_TABLE_YEAR}.csv",
        index_col="technology",
    )
    fuels = pd.read_csv(PROCESSED / "fuel_assumptions.csv", comment="#",
                        index_col="carrier")

    rows = {}
    for key, (label, name, carrier, footnote) in SMALL_TABLE.items():
        row = costs.loc[name]
        efficiency = row["efficiency"] if pd.notna(row["efficiency"]) else 1.0
        vom = row["VOM"] if pd.notna(row["VOM"]) else 0.0
        if carrier is None:
            price, carbon = 0.0, 0.0
        else:
            price = float(fuels.loc[carrier, "price_used_eur_per_mwh_th"])
            carbon = float(fuels.loc[carrier, "co2_used_t_per_mwh_th"])
        rows[key] = {
            "label": label,
            "fuel": carrier or "none",
            "fuel_price_eur_per_mwh_th": price,
            "efficiency": round(float(efficiency), 4),
            "vom_eur_per_mwh": round(float(vom), 4),
            "co2_t_per_mwh_th": carbon,
            "source": f"{footnote} Technology-data key \\texttt{{{name}}}.",
        }

    frame = pd.DataFrame(rows).T
    frame.index.name = "tech"
    out = PROCESSED / "technology_costs_small.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Small technology table for exposition (sections 2-5).\n")
        handle.write("# GENERATED by data/prepare.py -- do not edit by hand.\n")
        handle.write(f"# Every parameter is technology-data {TECHNOLOGY_DATA_TAG};\n")
        handle.write("# fuel prices and carbon contents come from\n")
        handle.write("# fuel_assumptions.csv, which the network re-pricing and the\n")
        handle.write("# greenfield candidates read too. Marginal costs and emission\n")
        handle.write("# rates are NOT stored here -- model code derives them, so table\n")
        handle.write("# and model cannot disagree:\n")
        handle.write("#   mc = fuel_price/efficiency + vom,  e = co2_fuel/efficiency.\n")
        handle.write("# Units: fuel_price_eur_per_mwh_th [EUR/MWh thermal],\n")
        handle.write("# efficiency [MWh_e/MWh_th], vom_eur_per_mwh [EUR/MWh_e],\n")
        handle.write("# co2_t_per_mwh_th [tCO2/MWh thermal].\n")
        frame.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} technologies)")


def prepare_spot(year: int):
    """Actual day-ahead prices per bidding zone (EUR/MWh), wide format.

    Dataset: Elspotprices — Nord Pool / EPEX day-ahead prices as published
    by Energinet, covering the Danish zones and the neighbouring zones the
    note models. These are the empirical counterparts of the model's
    zonal duals.
    """
    raw_file = RAW / "energidataservice" / f"Elspotprices_{year}.json"
    if not raw_file.exists():
        params = {
            "start": f"{year}-01-01T00:00",
            "end": f"{year + 1}-01-01T00:00",
            "columns": "HourUTC,PriceArea,SpotPriceEUR",
            "sort": "HourUTC ASC",
            "limit": "0",
        }
        url = f"{EDS_API}/Elspotprices?{urllib.parse.urlencode(params)}"
        print(f"fetching {url[:90]}...")
        payload = _get(url)
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
        print(f"wrote {raw_file.relative_to(NOTE)} ({len(payload) / 1e6:.1f} MB)")
    else:
        print(f"raw exists, not fetching: {raw_file.relative_to(NOTE)}")

    records = json.loads(raw_file.read_text(encoding="utf-8"))["records"]
    df = pd.DataFrame.from_records(records)
    wide = df.pivot_table(index="HourUTC", columns="PriceArea",
                          values="SpotPriceEUR")
    wide.index = pd.to_datetime(wide.index)
    keep = [c for c in ["DK1", "DK2", "DE", "NO2", "SE3", "SE4"]
            if c in wide.columns]
    out = PROCESSED / f"spot_{year}.csv"
    wide[keep].sort_index().to_csv(out, index_label="time", float_format="%.2f")
    print(f"wrote {out.relative_to(NOTE)} ({len(wide)} hours, zones {keep})")


def prepare_exchange(area: str, year: int):
    """Actual hourly cross-border exchange of a Danish zone (MWh, positive =
    import), from the settlement dataset — flow times price spread is the
    realised congestion rent section 6 compares against."""
    raw_file = (RAW / "energidataservice"
                / f"ProductionConsumptionSettlement_exchange_{area}_{year}.json")
    # Same staleness rule as fetch_settlement: a cache written before a wire
    # was added to EXCHANGE_COLUMNS is worse than no cache, because summing it
    # silently under-counts the area's trade.
    if raw_file.exists():
        try:
            cached = json.loads(raw_file.read_text(encoding="utf-8"))["records"]
        except (ValueError, KeyError):
            cached = []
        have = set(cached[0]) if cached else set()
        if [c for c in EXCHANGE_COLUMNS if c not in have]:
            print(f"raw is stale (missing a wire), re-fetching: "
                  f"{raw_file.relative_to(NOTE)}")
            raw_file.unlink()
    if not raw_file.exists():
        params = {
            "start": f"{year}-01-01T00:00",
            "end": f"{year + 1}-01-01T00:00",
            "filter": json.dumps({"PriceArea": [area]}),
            "columns": ",".join(["HourUTC"] + EXCHANGE_COLUMNS),
            "sort": "HourUTC ASC",
            "limit": "0",
        }
        url = f"{EDS_API}/ProductionConsumptionSettlement?{urllib.parse.urlencode(params)}"
        print(f"fetching exchange {area} {year}...")
        payload = _get(url)
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_bytes(payload)
    else:
        print(f"raw exists, not fetching: {raw_file.relative_to(NOTE)}")

    records = json.loads(raw_file.read_text(encoding="utf-8"))["records"]
    df = pd.DataFrame.from_records(records).set_index("HourUTC")
    df.index = pd.to_datetime(df.index)
    # DK2 has no Skagerrak, COBRAcable or Viking Link; EDS returns those
    # columns empty. Drop them rather than ship a column of nothing.
    df = df.dropna(axis=1, how="all")
    out = PROCESSED / f"exchange_{area.lower()}_{year}.csv"
    df.sort_index().to_csv(out, index_label="time", float_format="%.2f")
    print(f"wrote {out.relative_to(NOTE)} ({len(df)} hours)")


# ---------------------------------------------------------------------------
# The 12-zone network of sections 6-8 is NOT built here. It is the exported
# product of the PyPSA-Eur stage-0 run (see the note's Appendix C):
# vendored as processed/network_eur_bz_2024.nc together with
# network_zones.json and network_eur_bz_2024_fleet.csv. The upstream run and
# the export script live in scratch/pypsa-eur/ and are documented there.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Buildable potentials per zone, for the European expansion of section 9.
#
# Section 7 caps Danish buildout with the note's own stylised land limits.
# That does not generalise: section 9 lets all twelve zones build, so the
# cap has to come from a source rather than from us, and it has to treat
# Denmark exactly like its neighbours.
#
# Two sources, and the smaller of the two is used:
#
#   TYNDP     ENTSO-E/ENTSOG TYNDP 2024 Scenarios, "Supply Inputs",
#             sheets 1.1-1.3: the solar, onshore and offshore trajectories
#             the TSOs themselves collected, NECP-aligned, published per
#             bidding zone and CC-BY-4.0. The HIGH trajectory at 2040 is
#             read as "the most ambitious buildout anyone responsible has
#             put on paper" -- the right shape for a cap.
#   technical The land-availability potential the shipped PyPSA-Eur network
#             already carries in `p_nom_max` (atlite land eligibility).
#
# Used = min(TYNDP, technical), which is not a formality: TYNDP's HIGH
# column is a *potential* rather than a trajectory for some entries -- DK1
# offshore is 100 GW flat across 2030-2050, the Danish North Sea resource,
# not a plan -- and the technical bound is what stops that from becoming a
# licence to build the North Sea. Both numbers are recorded beside the used
# one, the same source-beside-used format as the fuel and battery blocks.
#
# Limitations, recorded in the note's Appendix D rather than smoothed over:
# the stage-0 export dropped generators with zero capacity, so a zone with
# no existing plant of a kind has neither a potential nor an availability
# profile for it, and therefore gets no candidate -- no offshore in NO1,
# NO3, NO4, SE1, SE2, SE3, and no solar in NO4 or SE1, whatever TYNDP says.
# Only `offwind-ac` survives anywhere, so floating and far-shore offshore
# are absent from the menu everywhere.
TYNDP_SUPPLY_URL = (
    "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/"
    "20231103-Final-Supply-Inputs-for-TYNDP-2024-Scenarios.xlsx.zip"
)
TYNDP_XLSX = "20231103 - Final Supply Inputs for TYNDP 2024 Scenarios.xlsx"
TYNDP_HORIZON = 2050
TYNDP_TRAJECTORY = "HIGH"

# sheet, and the column holding the HIGH trajectory at TYNDP_HORIZON. The
# sheets are shaped by hand rather than by a header row (three trajectory
# blocks side by side, each with its own set of horizons), so the column is
# pinned explicitly and checked against the header on read.
TYNDP_SHEETS = {
    "solar_pv": ("1.1.", 9),
    "wind_onshore": ("1.2.", 9),
    "wind_offshore": ("1.3.", 14),
}

# TYNDP's zones are ours, with three exceptions: Denmark's offshore hubs are
# separate zones there (the North Sea energy island, Kriegers Flak,
# Bornholm) and belong to the shore zone that lands them; Germany's Kriegers
# Flak share likewise; and Norway is three zones there against our five.
TYNDP_ZONES = {
    "DK1": ["DKW1", "DKNS"],
    "DK2": ["DKE1", "DKKF", "DKBH"],
    "DE": ["DE00", "DEKF"],
    "SE1": ["SE01"], "SE2": ["SE02"], "SE3": ["SE03"], "SE4": ["SE04"],
    "NO3": ["NOM1"], "NO4": ["NON1"],
    "NO1": ["NOS0"], "NO2": ["NOS0"], "NO5": ["NOS0"],
}
# Southern Norway is one TYNDP zone covering three of ours, so its
# trajectory is split between them in proportion to their technical
# potential -- land, not today's fleet, which in NO1 is sixteen megawatts of
# solar and would make the split meaningless.
TYNDP_SPLIT_ZONES = ["NO1", "NO2", "NO5"]

# The candidate names of section 7, and the network carriers each one's
# potential is read from.
POTENTIAL_CARRIERS = {
    "solar_pv": ["solar", "solar-hsat"],
    "wind_onshore": ["onwind"],
    "wind_offshore": ["offwind-ac", "offwind-dc", "offwind-float"],
}


def _tyndp_number(value) -> float:
    """MW from a workbook cell. Some are text: non-breaking spaces, thousands
    separators, the odd dash for "none"."""
    if pd.isna(value):
        return 0.0
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(",", "").strip()
        if cleaned in ("", "-", "n/a", "N/A"):
            return 0.0
        return float(cleaned)
    return float(value)


def _tyndp_trajectories() -> dict:
    """{technology: {tyndp zone: MW}} at the HIGH trajectory, TYNDP_HORIZON."""
    zip_path = RAW / "tyndp" / Path(TYNDP_SUPPLY_URL).name
    if not zip_path.exists():
        print(f"fetching {TYNDP_SUPPLY_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(TYNDP_SUPPLY_URL))
        print(f"wrote {zip_path.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist() if m.endswith(TYNDP_XLSX))
        with archive.open(name) as handle:
            payload = io.BytesIO(handle.read())

    out = {}
    for tech, (sheet, column) in TYNDP_SHEETS.items():
        payload.seek(0)
        frame = pd.read_excel(payload, sheet_name=sheet, header=None)
        label, horizon = frame.iloc[2].tolist(), frame.iloc[3, column]
        block = next(
            v for i, v in enumerate(label[: column + 1])
            if isinstance(v, str) and TYNDP_TRAJECTORY in v.upper()
            and i <= column
        )
        if int(horizon) != TYNDP_HORIZON:
            raise SystemExit(
                f"TYNDP sheet {sheet} column {column} is {horizon}, "
                f"not {TYNDP_HORIZON} -- the workbook layout has changed"
            )
        body = frame.iloc[4:]
        body = body[body[1].notna()]
        series = pd.Series(body[column].to_numpy(), index=body[1].astype(str))
        out[tech] = {zone: _tyndp_number(v) for zone, v in series.items()}
        print(f"  {sheet} {tech}: {block.strip()} {TYNDP_HORIZON}")
    return out


def _technical_potentials() -> dict:
    """{(zone, technology): MW} from the shipped network's own p_nom_max."""
    import pypsa

    n = pypsa.Network(PROCESSED / f"network_eur_bz_{YEAR}.nc")
    gens = n.generators
    out = {}
    for zone in n.buses.index:
        for tech, carriers in POTENTIAL_CARRIERS.items():
            rows = gens[(gens.bus == zone) & (gens.carrier.isin(carriers))]
            out[(zone, tech)] = float(rows.p_nom_max.sum()) if len(rows) else 0.0
    return out


def prepare_potentials():
    """Write the per-zone buildable potentials of section 9."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise SystemExit(
            "reading the TYNDP workbook needs openpyxl (pip install openpyxl). "
            "The processed file it produces is vendored, so this step is only "
            "needed to rebuild it from source."
        )
    tyndp = _tyndp_trajectories()
    technical = _technical_potentials()

    rows = []
    for zone in sorted({z for z, _ in technical}):
        for tech in POTENTIAL_CARRIERS:
            codes = TYNDP_ZONES[zone]
            published = sum(tyndp[tech].get(code, 0.0) for code in codes)
            if zone in TYNDP_SPLIT_ZONES:
                pool = sum(
                    technical[(other, tech)] for other in TYNDP_SPLIT_ZONES
                )
                share = technical[(zone, tech)] / pool if pool > 0 else 0.0
                published *= share
            limit = technical[(zone, tech)]
            used = min(published, limit) if limit > 0 else 0.0
            if limit <= 0:
                binds = "no candidate (not in the exported network)"
            elif used == published:
                binds = "TYNDP trajectory"
            else:
                binds = "technical potential"
            rows.append({
                "zone": zone,
                "technology": tech,
                "tyndp_zones": "+".join(codes),
                "tyndp_high_2040_mw": round(published, 1),
                "technical_potential_mw": round(limit, 1),
                "p_nom_max_used_mw": round(used, 1),
                "binding": binds,
            })

    out = PROCESSED / "potentials_zones.csv"
    header = (
        "# Buildable potential per zone for section 9's European expansion.\n"
        "# GENERATED by data/prepare.py -- do not edit by hand.\n"
        f"# tyndp_high_2040_mw: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Supply\n"
        f"#   Inputs, sheets 1.1-1.3, {TYNDP_TRAJECTORY} trajectory at\n"
        f"#   {TYNDP_HORIZON}, summed over the TYNDP zones named in\n"
        "#   tyndp_zones (CC-BY-4.0). Southern Norway is one TYNDP zone over\n"
        "#   three of ours and is split by technical potential.\n"
        "# technical_potential_mw: the land-availability potential the\n"
        "#   shipped PyPSA-Eur network carries in p_nom_max.\n"
        "# p_nom_max_used_mw: the smaller of the two -- the most ambitious\n"
        "#   published trajectory, never more than the land allows. Zero\n"
        "#   means the exported network has no generator of this kind in\n"
        "#   this zone, so there is no availability profile to build on.\n"
        "# Section 7's Danish caps are NOT these: they are the note's own\n"
        "# stylised land limits, and stay as they are.\n"
    )
    frame = pd.DataFrame(rows)
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        frame.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} ({len(frame)} rows)")
    return frame


# ---------------------------------------------------------------------------
# The flexible electric-vehicle block of section 9.
#
# Section 7 doubles Danish load to stand for electrification without saying
# what the extra demand *is*. Section 9 carves one identifiable piece of it
# back out and makes it flexible: the charging of an electrified road fleet,
# which has a daily energy requirement but not a fixed hour.
#
# Only the annual energy comes from data. The rest is a stated model
# assumption -- the block must meet its energy over a day, and may choose the
# hours within it -- which is what makes the block a teaching object rather
# than a fleet simulation. TYNDP's own EV inputs go much further (per-vehicle
# availability, minimum state of charge, charger ratings); using them here
# would buy realism the note cannot spend.
#
# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, "EV Modelling Inputs",
# EV_VEHICLES, electricity demand per bidding zone at 2040, summed over
# passenger cars, vans, buses and trucks (CC-BY-4.0). The Distributed Energy
# scenario is used: it is the one whose road electrification matches a note
# that has already doubled the load. Global Ambition is recorded beside it.
#
# Norway is not in that dataset. Its zones therefore take the mean EV share
# of load across the zones that are, flagged as such in the output rather
# than passed off as data.
EV_URL = (
    "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/"
    "EV-Modelling-Inputs.zip"
)
EV_MEMBER = "EV Modelling Inputs/EV_VEHICLES.xlsx"
EV_HORIZON = 2050
EV_SCENARIO = "Distributed Energy"
EV_SCENARIO_ALT = "Global Ambition"


def prepare_ev_demand():
    """Write the annual electric-vehicle electricity demand per zone."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise SystemExit(
            "reading the TYNDP workbooks needs openpyxl (pip install openpyxl). "
            "The processed file it produces is vendored, so this step is only "
            "needed to rebuild it from source."
        )
    import pypsa

    zip_path = RAW / "tyndp" / Path(EV_URL).name
    if not zip_path.exists():
        print(f"fetching {EV_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(EV_URL))
        print(f"wrote {zip_path.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist() if m.endswith(EV_MEMBER))
        with archive.open(name) as handle:
            payload = io.BytesIO(handle.read())
    frame = pd.read_excel(payload, header=0)
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame[frame["YEAR"] == EV_HORIZON]

    def demand(scenario: str, codes: list) -> float:
        rows = frame[
            (frame["SCENARIO"] == scenario) & (frame["NODE"].isin(codes))
        ]
        return float(rows["ELECTRICITY DEMAND [TWh]"].sum())

    n = pypsa.Network(PROCESSED / f"network_eur_bz_{YEAR}.nc")
    load_twh = {
        zone: float(n.loads_t.p_set[zone].sum()) / 1e6
        for zone in n.buses.index if zone in n.loads_t.p_set.columns
    }

    covered, rows = {}, []
    for zone in sorted(load_twh):
        codes = TYNDP_ZONES[zone]
        used = demand(EV_SCENARIO, codes)
        alt = demand(EV_SCENARIO_ALT, codes)
        if used > 0:
            # Southern Norway would be split here too, but it is not in the
            # dataset at all -- see below.
            covered[zone] = used / load_twh[zone]
        rows.append({
            "zone": zone, "tyndp_zones": "+".join(codes),
            "load_twh": round(load_twh[zone], 2),
            f"ev_twh_{EV_SCENARIO.split()[0].lower()}": round(used, 3),
            f"ev_twh_{EV_SCENARIO_ALT.split()[0].lower()}": round(alt, 3),
            "ev_twh_used": round(used, 3),
            "share_of_load": round(used / load_twh[zone], 4),
            "basis": f"TYNDP {EV_SCENARIO} {EV_HORIZON}",
        })

    fallback = sum(covered.values()) / len(covered)
    for row in rows:
        if row["ev_twh_used"] > 0:
            continue
        row["ev_twh_used"] = round(fallback * row["load_twh"], 3)
        row["share_of_load"] = round(fallback, 4)
        row["basis"] = "mean share of the covered zones (not in the dataset)"

    out = PROCESSED / "ev_assumptions.csv"
    header = "\n".join([
        "# Annual electric-vehicle electricity demand per zone, for the",
        "# flexible charging block of section 9.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, EV Modelling Inputs,",
        f"#   EV_VEHICLES at {EV_HORIZON}, summed over passenger cars, vans,",
        "#   buses and trucks (CC-BY-4.0). Both scenarios are recorded; the",
        f"#   {EV_SCENARIO} one is used.",
        "# The block is ADDED to the zone's load, never carved out of it:",
        "#   TYNDP counts vehicles outside its demand profiles, so the base",
        "#   load in demand_zones_*.csv does not already contain them.",
        "#   (It was carved out while the models ran on an assumed doubling",
        "#   of 2024 load, which did presume transport electrification.)",
        "# Only the energy is data. That the block must meet it daily, at",
        "#   hours of its choosing, is a model assumption.",
        "# load_twh is the shipped network's own 2024 annual load, kept here",
        "#   as the reference the share is measured against.",
        "",
    ])
    table = pd.DataFrame(rows)
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} zones, "
          f"{len(covered)} from data)")
    return table



# ---------------------------------------------------------------------------
# Hydrogen imports: the third way a zone can meet its hydrogen demand.
#
# Leaving imports out would decide section 9's answer before it was asked --
# with only reforming and electrolysis available, a tight carbon budget
# forces electrolysis whatever it costs. Putting them in *without a limit*
# decides it the other way, and just as artificially: a world that will sell
# any quantity of zero-carbon hydrogen at a flat price is a backstop, and a
# backstop caps the carbon price and supplies the whole market. A first
# version did exactly that and imported every terawatt-hour.
#
# So imports are taken as TYNDP takes them: a step supply curve of corridors,
# each with its own price and its own quantity. In the 2040 Distributed
# Energy scenario that is decisive for this note's geography -- only Germany
# has a corridor at all (from Norway, in two tranches: 5.2 GW at 41 EUR/MWh
# and 12.1 GW at 69), capped at roughly 151 TWh a year against a demand of
# 265. Denmark and Sweden have none, and must reform or electrolyse.
#
# One honest wrinkle, recorded in the output and in Appendix D: the corridor
# runs from Norway, which is inside this model's own footprint. Because the
# model carries no hydrogen network, Norwegian export cannot be represented
# as such, and TYNDP's corridor is used as exogenous supply into Germany
# instead. It is a stand-in for a hydrogen network, and the note says so.
H2_IMPORTS_URL = (
    "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/"
    "Hydrogen.zip"
)
H2_IMPORTS_MEMBER = "Hydrogen/H2 IMPORTS GENERATORS PROPERTIES.xlsx"

# TYNDP import node -> the note's zone that receives the corridor.
H2_IMPORT_NODES = {"DE": "DE"}


def prepare_h2_imports():
    """Write the hydrogen import supply curve available to each zone."""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise SystemExit(
            "reading the TYNDP workbooks needs openpyxl (pip install openpyxl). "
            "The processed file it produces is vendored, so this step is only "
            "needed to rebuild it from source."
        )
    zip_path = RAW / "tyndp" / Path(H2_IMPORTS_URL).name
    if not zip_path.exists():
        print(f"fetching {H2_IMPORTS_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(H2_IMPORTS_URL))
        print(f"wrote {zip_path.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist()
                    if m.endswith("H2 IMPORTS GENERATORS PROPERTIES.xlsx"))
        payload = io.BytesIO(archive.read(name))
    frame = pd.read_excel(payload, header=0)
    frame.columns = [str(c).strip() for c in frame.columns]
    price_col = next(c for c in frame.columns if "OFFER PRICE" in c)
    qty_col = next(c for c in frame.columns if "OFFER QUANTITY" in c)
    for col in (price_col, qty_col):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    subset = frame[(frame["YEAR"] == H2_HORIZON)
                   & (frame["SCENARIO"] == H2_SCENARIO)
                   & (frame["NODE TO"].astype(str).isin(H2_IMPORT_NODES))
                   & (frame[qty_col] > 0)
                   & (frame[price_col].notna())]

    rows = [{
        "zone": H2_IMPORT_NODES[str(row["NODE TO"])],
        "corridor": str(row["CORRIDOR"]),
        "p_nom_mw": round(float(row[qty_col]), 1),
        "price_eur_per_mwh_h2": round(float(row[price_col]), 2),
    } for _, row in subset.iterrows()]

    out = PROCESSED / "h2_imports.csv"
    header = "\n".join([
        "# Hydrogen import supply curve per zone, for section 9.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Hydrogen inputs,",
        f"#   H2 IMPORTS GENERATORS PROPERTIES, {H2_SCENARIO} {H2_HORIZON}",
        "#   (CC-BY-4.0). Each corridor is one step of a supply curve: a",
        "#   quantity at a price, not an unlimited offer.",
        "# Only Germany has a corridor in this scenario. Denmark and Sweden",
        "#   have none and must reform or electrolyse their own hydrogen.",
        "# The corridor runs from Norway, which is inside this model's own",
        "#   footprint; with no hydrogen network to represent that export,",
        "#   it enters as exogenous supply into Germany. See Appendix D.",
        "",
    ])
    table = pd.DataFrame(rows).sort_values(["zone", "price_eur_per_mwh_h2"])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} corridors, "
          f"{table.p_nom_mw.sum() / 1e3:.1f} GW)")
    return table

# ---------------------------------------------------------------------------
# Industrial hydrogen demand, for the hydrogen sector of section 9.
#
# Section 9 gives every rung a hydrogen demand and every rung a way to meet
# it, so that what rung (ii) adds is the *electrolytic route* rather than the
# demand itself. This is where the demand comes from.
#
# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, "Demand Profiles", the
# hydrogen demand workbook for the Distributed Energy scenario at 2040,
# climate year 2009 -- the same scenario and horizon as the EV block, and
# TYNDP's own reference climate year (CC-BY-4.0). Hydrogen used for HEATING
# is a separate workbook and is deliberately excluded: this note's heat
# sector is section 5's heat pumps, and mixing the two would put the same
# service in the note twice.
#
# Three things about the source worth knowing, all recorded per zone in the
# output rather than smoothed away:
#   * Denmark appears at a single node, so the national figure is split
#     between DK1 and DK2 in proportion to their electricity load. Norway and
#     Sweden are given at country level and split the same way.
#   * Norway's industrial hydrogen demand is zero in this scenario. That is
#     the data, not a gap: its zones simply get no hydrogen sector.
#   * Only three climate years are populated in the workbook (1995, 2008,
#     2009); the others are present but empty.
DEMAND_PROFILES_URL = (
    "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/"
    "Demand-Profiles.zip"
)
H2_MEMBER = "Demand Profiles/DE/2050/H2_ZONE_2.xlsx"
H2_HORIZON = 2050
H2_CLIMATE_YEAR = 2009
H2_SCENARIO = "Distributed Energy"

# TYNDP node -> the note's zones, with the split key. A single node covering
# several of our zones is divided by electricity load.
H2_NODE_ZONES = {
    "DE00": ["DE"],
    "DKE1": ["DK1", "DK2"],
    "SE00": ["SE1", "SE2", "SE3", "SE4"],
    "NO00": ["NO1", "NO2", "NO3", "NO4", "NO5"],
}


def prepare_h2_demand():
    """Write the annual industrial hydrogen demand per zone."""
    try:
        import openpyxl
    except ImportError:
        raise SystemExit(
            "reading the TYNDP workbooks needs openpyxl (pip install openpyxl). "
            "The processed file it produces is vendored, so this step is only "
            "needed to rebuild it from source."
        )
    import pypsa

    zip_path = RAW / "tyndp" / Path(DEMAND_PROFILES_URL).name
    if not zip_path.exists():
        print(f"fetching {DEMAND_PROFILES_URL} (about 1.2 GB, once)")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(DEMAND_PROFILES_URL, timeout=1800))
        print(f"wrote {zip_path.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        payload = io.BytesIO(archive.read(H2_MEMBER))
    book = openpyxl.load_workbook(payload, read_only=True, data_only=True)

    def annual_twh(node: str) -> float:
        """Sum one node's hourly hydrogen demand for the climate year."""
        if node not in book.sheetnames:
            return 0.0
        sheet = book[node]
        header = next(sheet.iter_rows(min_row=11, max_row=11, max_col=40,
                                      values_only=True))
        if H2_CLIMATE_YEAR not in header:
            raise SystemExit(
                f"climate year {H2_CLIMATE_YEAR} not in {node}'s columns "
                "-- the workbook layout has changed"
            )
        column = header.index(H2_CLIMATE_YEAR)
        total = 0.0
        for row in sheet.iter_rows(min_row=12, max_col=column + 1,
                                   values_only=True):
            value = row[column]
            if isinstance(value, (int, float)):
                total += value
        return total / 1e6            # MWh -> TWh

    n = pypsa.Network(PROCESSED / f"network_eur_bz_{YEAR}.nc")
    load_twh = {
        zone: float(n.loads_t.p_set[zone].sum()) / 1e6
        for zone in n.buses.index if zone in n.loads_t.p_set.columns
    }

    rows = []
    for node, zones in H2_NODE_ZONES.items():
        national = annual_twh(node)
        pool = sum(load_twh.get(z, 0.0) for z in zones)
        for zone in zones:
            share = load_twh.get(zone, 0.0) / pool if pool > 0 else 0.0
            rows.append({
                "zone": zone,
                "tyndp_node": node,
                "load_twh": round(load_twh.get(zone, 0.0), 2),
                "h2_twh_node": round(national, 3),
                "load_share_of_node": round(share, 4),
                "h2_twh_used": round(national * share, 3),
                "basis": (f"TYNDP {H2_SCENARIO} {H2_HORIZON}, climate year "
                          f"{H2_CLIMATE_YEAR}"
                          + ("" if len(zones) == 1 else ", split by load")),
            })

    out = PROCESSED / "h2_assumptions.csv"
    header = "\n".join([
        "# Annual industrial hydrogen demand per zone, TWh of hydrogen,",
        "# for the hydrogen sector of section 9.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Demand Profiles,",
        f"#   {H2_MEMBER}, {H2_SCENARIO} {H2_HORIZON}, climate year",
        f"#   {H2_CLIMATE_YEAR} (CC-BY-4.0).",
        "# Hydrogen for HEATING is a separate TYNDP workbook and is excluded:",
        "#   this note's heat sector is section 5's heat pumps.",
        "# A TYNDP node covering several of our zones is split between them",
        "#   in proportion to electricity load; the node total and the share",
        "#   used are both recorded so the split is visible.",
        "# Norway's demand is zero in this scenario -- the data, not a gap.",
        "",
    ])
    table = pd.DataFrame(rows).sort_values("zone")
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} "
          f"({table.h2_twh_used.sum():.1f} TWh over {len(table)} zones)")
    return table


# ---------------------------------------------------------------------------
# The forward horizon.
#
# Sections 2-6 describe the system as it is: 2024 weather, 2024 fleet, 2024
# fuel prices. Sections 7-9 ask what should be built, which is a question
# about a year that has not happened yet. Running the forward-looking
# sections on today's fuel prices was never defensible; it was simply what
# the one shared table happened to hold.
#
# So the forward sections get their own fuel table, at the same horizon as
# every other forward-looking input they read (potentials, hydrogen demand,
# EV demand). fuel_assumptions.csv is untouched, and sections 2-6 keep
# running on today's numbers -- which is what they are for.
FORWARD_HORIZON = 2050

# TYNDP's price matrix (Supply Inputs sheet 3.1) against this note's
# carriers. The matrix quotes EUR/GJ and the note works in EUR/MWh_th.
# Lignite is quoted per geology group; G2 is the German/Polish group, the
# only one inside these twelve zones. "oil" takes the light-oil row, the
# product the network's peaking units actually burn. Solid biomass and wood
# pellets have no row in the matrix, so they keep the note's own numbers and
# are marked as carried over rather than sourced.
GJ_PER_MWH_TH = 3.6
FORWARD_FUEL_ROWS = {
    "gas": "Natural Gas",
    "coal": "Hard coal",
    "lignite": "Lignite G2",
    "oil": "Light oil",
    "uranium": "Nuclear",
    "biomethane": "Biomethane",
}
FORWARD_CO2_ROW = "CO2 price"
TYNDP_PRICE_SHEET = "3.1."


def _tyndp_price_matrix() -> tuple:
    """{row label: EUR/GJ at FORWARD_HORIZON} from Supply Inputs sheet 3.1,
    plus the scenario CO2 price in EUR/t at the same horizon."""
    zip_path = RAW / "tyndp" / Path(TYNDP_SUPPLY_URL).name
    if not zip_path.exists():
        print(f"fetching {TYNDP_SUPPLY_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(TYNDP_SUPPLY_URL))
    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist() if m.endswith(TYNDP_XLSX))
        payload = io.BytesIO(archive.read(name))
    frame = pd.read_excel(payload, sheet_name=TYNDP_PRICE_SHEET, header=None)

    years = frame.iloc[2].tolist()
    column = next(
        (i for i, v in enumerate(years)
         if isinstance(v, (int, float)) and not pd.isna(v)
         and int(v) == FORWARD_HORIZON),
        None,
    )
    if column is None:
        raise SystemExit(
            f"TYNDP sheet {TYNDP_PRICE_SHEET} has no {FORWARD_HORIZON} column "
            "-- the workbook layout has changed"
        )

    prices, co2 = {}, None
    for _, row in frame.iloc[3:].iterrows():
        label = row[1]
        if not isinstance(label, str):
            continue
        value = row[column]
        if not isinstance(value, (int, float)) or pd.isna(value):
            continue
        if label.strip().startswith(FORWARD_CO2_ROW):
            co2 = float(value)
        prices[label.strip()] = float(value)
    if co2 is None:
        raise SystemExit(
            f"no '{FORWARD_CO2_ROW}' row on sheet {TYNDP_PRICE_SHEET}"
        )
    return prices, co2


def prepare_forward_fuels():
    """Write the fuel table sections 7-9 run on: today's carbon contents,
    TYNDP's prices at the forward horizon."""
    prices, co2_price = _tyndp_price_matrix()

    today = pd.read_csv(PROCESSED / "fuel_assumptions.csv", comment="#",
                        index_col="carrier")
    rows = []
    for carrier, row in today.iterrows():
        label = FORWARD_FUEL_ROWS.get(carrier)
        match = None
        if label is not None:
            match = next((k for k in prices if k.startswith(label)), None)
        if match is None:
            price_used = float(row["price_used_eur_per_mwh_th"])
            source = "carried over from fuel_assumptions.csv (no TYNDP row)"
            tyndp_eur_gj = None
        else:
            price_used = prices[match] * GJ_PER_MWH_TH
            source = f"TYNDP sheet {TYNDP_PRICE_SHEET}, '{match}'"
            tyndp_eur_gj = prices[match]
        rows.append({
            "carrier": carrier,
            "price_today_eur_per_mwh_th": row["price_used_eur_per_mwh_th"],
            "tyndp_eur_per_gj": (None if tyndp_eur_gj is None
                                 else round(tyndp_eur_gj, 4)),
            "price_used_eur_per_mwh_th": round(price_used, 4),
            "co2_used_t_per_mwh_th": row["co2_used_t_per_mwh_th"],
            "source": source,
        })

    table = pd.DataFrame(rows).set_index("carrier")
    out = PROCESSED / f"fuel_assumptions_{FORWARD_HORIZON}.csv"
    header = "\n".join([
        f"# Fuel prices for the FORWARD-LOOKING sections (7-9) at"
        f" {FORWARD_HORIZON}.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Sections 2-6 read fuel_assumptions.csv instead: they describe the",
        "#   system as it is, and today's prices are the right ones there.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Supply Inputs,",
        f"#   sheet {TYNDP_PRICE_SHEET} 'Commodity and CO2 prices', column"
        f" {FORWARD_HORIZON}",
        "#   (CC-BY-4.0). Underlying source there is IEA WEO 2022 APS; the",
        "#   matrix is the same for all three TYNDP scenarios.",
        "# price_today_* is kept beside price_used_* so the size of the move",
        "#   is visible: gas falls, biomethane falls, and both matter.",
        "# Carbon CONTENTS are physical and are carried over unchanged.",
        f"# TYNDP's own scenario CO2 price at {FORWARD_HORIZON} is"
        f" {co2_price:.0f} EUR/t.",
        "#   The models do not read it -- sections 7-9 derive the carbon",
        "#   price as the dual of a budget -- but it is the right external",
        "#   check on the sigma those models report.",
        "",
    ])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle)
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} carriers, "
          f"CO2 price {co2_price:.0f} EUR/t)")


# ---------------------------------------------------------------------------
# Electricity demand at the forward horizon.
#
# TYNDP splits electricity demand into pieces that must be added back up:
# ELECTRICITY_MARKET is what the market sees, ELECTRICITY_PROSUMER is what
# rooftop generation serves behind the meter, and electric vehicles and
# electrolysis are counted separately again. Read the market file alone and
# Denmark's 2050 demand comes out below its 2024 demand, which is not a
# forecast of anything -- it is two thirds of a number.
#
# So the base load here is MARKET + PROSUMER, and the EV and hydrogen
# sectors are added by the models on top of it, each from its own dataset.
DEMAND_CLIMATE_YEARS = [1995, 2008, 2009]
DEMAND_MEMBERS = {
    "market": "Demand Profiles/DE/{year}/ELECTRICITY_MARKET DE {year}.xlsx",
    "prosumer": "Demand Profiles/DE/{year}/ELECTRICITY_PROSUMER DE {year}.xlsx",
}


def prepare_demand_totals():
    """Write the annual electricity demand per zone at the forward horizon.

    Only the ANNUAL TOTAL is taken. The hourly shape stays the network's own
    2024 profile, because TYNDP's profiles are drawn on PECD climate years
    and this note's weather is 2024: pairing a 2009 demand profile with 2024
    wind would break the temperature-demand-weather correlation that makes
    a residual load curve mean anything.
    """
    try:
        import openpyxl
    except ImportError:
        raise SystemExit(
            "reading the TYNDP workbooks needs openpyxl (pip install openpyxl). "
            "The processed file it produces is vendored, so this step is only "
            "needed to rebuild it from source."
        )
    import pypsa

    zip_path = RAW / "tyndp" / Path(DEMAND_PROFILES_URL).name
    if not zip_path.exists():
        print(f"fetching {DEMAND_PROFILES_URL} (about 1.2 GB, once)")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(DEMAND_PROFILES_URL, timeout=1800))
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    n = pypsa.Network(PROCESSED / f"network_eur_bz_{YEAR}.nc")
    load_twh = {
        zone: float(n.loads_t.p_set[zone].sum()) / 1e6
        for zone in n.buses.index if zone in n.loads_t.p_set.columns
    }

    # A TYNDP node may cover several of our zones (southern Norway covers
    # three). Its demand is split between them in proportion to the load the
    # shipped network already gives them -- the same rule the hydrogen
    # sector uses, and the only one that conserves the total.
    sharers = {}
    for zone in load_twh:
        for code in TYNDP_ZONES[zone]:
            sharers.setdefault(code, []).append(zone)

    def node_totals(member_template: str) -> dict:
        """{tyndp node: mean TWh over the climate years}."""
        member = member_template.format(year=FORWARD_HORIZON)
        with zipfile.ZipFile(zip_path) as archive:
            if member not in archive.namelist():
                raise SystemExit(f"{member} not in the demand archive")
            book = openpyxl.load_workbook(
                io.BytesIO(archive.read(member)), read_only=True,
                data_only=True,
            )
        out = {}
        for code in sharers:
            if code not in book.sheetnames:
                out[code] = 0.0
                continue
            sheet = book[code]
            # The header sits on row 11 in the hydrogen workbooks and row 12
            # in the electricity ones, so find it rather than assume it.
            header, first_data_row = None, None
            for index, row in enumerate(
                sheet.iter_rows(min_row=1, max_row=20, max_col=40,
                                values_only=True), start=1
            ):
                if row and isinstance(row[0], str) and row[0].strip() == "Date":
                    header, first_data_row = row, index + 1
                    break
            if header is None:
                raise SystemExit(
                    f"no 'Date' header row in {code} on {member} "
                    "-- the workbook layout has changed"
                )
            columns = []
            for year in DEMAND_CLIMATE_YEARS:
                if year not in header:
                    raise SystemExit(
                        f"climate year {year} not in {code}'s columns on "
                        f"{member} -- the workbook layout has changed"
                    )
                columns.append(header.index(year))
            totals = [0.0] * len(columns)
            for row in sheet.iter_rows(min_row=first_data_row,
                                       max_col=max(columns) + 1,
                                       values_only=True):
                for i, column in enumerate(columns):
                    value = row[column]
                    if isinstance(value, (int, float)):
                        totals[i] += value
            out[code] = sum(totals) / len(totals) / 1e6      # MWh -> TWh
        book.close()
        return out

    pieces = {name: node_totals(template)
              for name, template in DEMAND_MEMBERS.items()}

    ev = pd.read_csv(PROCESSED / "ev_assumptions.csv", comment="#",
                     index_col="zone")["ev_twh_used"]

    rows = []
    for zone in sorted(load_twh):
        piece = {}
        for name, totals in pieces.items():
            value = 0.0
            for code in TYNDP_ZONES[zone]:
                covered = sharers[code]
                weight = (load_twh[zone] / sum(load_twh[z] for z in covered)
                          if len(covered) > 1 else 1.0)
                value += totals.get(code, 0.0) * weight
            piece[name] = value
        base = piece["market"] + piece["prosumer"]
        ev_twh = float(ev.get(zone, 0.0))
        rows.append({
            "zone": zone,
            "tyndp_zones": "+".join(TYNDP_ZONES[zone]),
            "load_twh_2024": round(load_twh[zone], 3),
            "market_twh": round(piece["market"], 3),
            "prosumer_twh": round(piece["prosumer"], 3),
            "base_twh": round(base, 3),
            "ev_twh": round(ev_twh, 3),
            "total_twh": round(base + ev_twh, 3),
            "scale_vs_2024": round((base + ev_twh) / load_twh[zone], 4),
        })

    table = pd.DataFrame(rows)
    out = PROCESSED / f"demand_zones_{FORWARD_HORIZON}.csv"
    header = "\n".join([
        f"# Annual electricity demand per zone at {FORWARD_HORIZON}, for the",
        "# forward-looking sections 7 and 9.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Demand Profiles,",
        f"#   Distributed Energy {FORWARD_HORIZON} (CC-BY-4.0), averaged over",
        f"#   climate years {DEMAND_CLIMATE_YEARS} -- the three the workbooks",
        "#   carry. The spread between them is under three per cent.",
        "# base_twh = market_twh + prosumer_twh. The prosumer half is demand",
        "#   served behind the meter by rooftop generation; leaving it out",
        "#   understates Danish demand by roughly a third.",
        "# ev_twh comes from ev_assumptions.csv and is listed here so the",
        "#   models can add it as a separate block: TYNDP counts vehicles",
        "#   OUTSIDE the demand profiles, so it must be added, never carved",
        "#   out. Electrolysis is likewise separate -- it is the hydrogen",
        "#   sector of section 9.",
        "# ONLY THE ANNUAL TOTAL IS USED. The hourly shape stays the shipped",
        "#   network's own 2024 profile; see the docstring for why.",
        "# load_twh_2024 and scale_vs_2024 record what the shipped network",
        "#   carries and how far the horizon moves it -- the number that",
        "#   used to be a flat assumed factor of two.",
        "",
    ])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} zones, "
          f"total {table['total_twh'].sum():.0f} TWh)")


# ---------------------------------------------------------------------------
# How much biomethane there is.
#
# Biomethane is the backstop in sections 7-9: the same peaker burning a
# zero-carbon fuel, which is what stops the carbon price running away. Left
# unlimited it is a very strong assumption -- a system that can always switch
# one more turbine to a carbon-free fuel can decarbonise its power sector at
# a bounded price, and the bound is roughly the fuel-price gap over the gas
# plant's emission rate. Whether that bound is real depends entirely on
# whether the fuel exists in the quantities the model helps itself to.
#
# TYNDP publishes a potential, from Guidehouse's "Gas for Climate": sheet 3.5,
# EU-wide, split between anaerobic digestion and thermal gasification. It is
# EU-WIDE ONLY -- there is no country breakdown anywhere in the archive -- so
# using it for twelve zones needs an allocation, and the allocation is ours
# rather than the source's.
#
# The key is each zone's share of EU-27 electricity demand at the same
# horizon, from the same TYNDP demand files. It is the defensible key
# available in this dataset, and it is not the physically right one:
# anaerobic digestion runs on agricultural residues and manure, so the
# resource follows farmland and livestock, not consumption. Denmark in
# particular produces far more biogas per unit of demand than this key
# credits it with. The number is therefore a stated assumption, recorded with
# its own limitation, and the models apply it as ONE system-wide ceiling on
# the twelve zones together rather than pretending to a per-country split.
#
# Norway is not in the EU and contributes no demand to the denominator; its
# own potential is outside the source and is not counted.
BIOMETHANE_SHEET = "3.5."
BIOMETHANE_TOTAL_LABEL = "Total"
# TYNDP node prefixes inside the EU-27. Non-members in the dataset are
# Albania, Bosnia, Switzerland, Montenegro, North Macedonia, Norway, Serbia,
# Turkey, Ukraine and the United Kingdom.
EU27_PREFIXES = (
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",
)


def _biomethane_eu_total() -> float:
    """EU-wide biomethane potential, TWh a year, at FORWARD_HORIZON."""
    zip_path = RAW / "tyndp" / Path(TYNDP_SUPPLY_URL).name
    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist() if m.endswith(TYNDP_XLSX))
        payload = io.BytesIO(archive.read(name))
    frame = pd.read_excel(payload, sheet_name=BIOMETHANE_SHEET, header=None)

    header_row = column = None
    for i in range(len(frame)):
        values = frame.iloc[i].tolist()
        for j, value in enumerate(values):
            if (isinstance(value, (int, float)) and not pd.isna(value)
                    and int(value) == FORWARD_HORIZON
                    and any(isinstance(v, str) and "Guidehouse" in v
                            for v in values)):
                header_row, column = i, j
        if header_row is not None:
            break
    if column is None:
        raise SystemExit(
            f"no Guidehouse {FORWARD_HORIZON} column on sheet "
            f"{BIOMETHANE_SHEET} -- the workbook layout has changed"
        )
    for i in range(header_row + 1, min(header_row + 8, len(frame))):
        label = frame.iloc[i, 1]
        if isinstance(label, str) and label.strip() == BIOMETHANE_TOTAL_LABEL:
            return float(frame.iloc[i, column])
    raise SystemExit(
        f"no '{BIOMETHANE_TOTAL_LABEL}' row under the Guidehouse block")


def prepare_biomethane_potential():
    """Write the biomethane ceiling the twelve zones share."""
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("reading the TYNDP workbooks needs openpyxl")

    eu_total = _biomethane_eu_total()

    zip_path = RAW / "tyndp" / Path(DEMAND_PROFILES_URL).name
    demand = {}
    for template in DEMAND_MEMBERS.values():
        member = template.format(year=FORWARD_HORIZON)
        with zipfile.ZipFile(zip_path) as archive:
            book = openpyxl.load_workbook(
                io.BytesIO(archive.read(member)), read_only=True,
                data_only=True,
            )
        for node in book.sheetnames:
            if not node.upper().startswith(EU27_PREFIXES):
                continue
            sheet = book[node]
            header = first_data_row = None
            for index, row in enumerate(
                sheet.iter_rows(min_row=1, max_row=20, max_col=40,
                                values_only=True), start=1
            ):
                if row and isinstance(row[0], str) and row[0].strip() == "Date":
                    header, first_data_row = row, index + 1
                    break
            if header is None:
                continue
            columns = [header.index(y) for y in DEMAND_CLIMATE_YEARS
                       if y in header]
            if not columns:
                continue
            totals = [0.0] * len(columns)
            for row in sheet.iter_rows(min_row=first_data_row,
                                       max_col=max(columns) + 1,
                                       values_only=True):
                for i, column in enumerate(columns):
                    value = row[column]
                    if isinstance(value, (int, float)):
                        totals[i] += value
            demand[node] = demand.get(node, 0.0) + (
                sum(totals) / len(totals) / 1e6)
        book.close()

    eu27_twh = sum(demand.values())
    ours = pd.read_csv(PROCESSED / f"demand_zones_{FORWARD_HORIZON}.csv",
                       comment="#", index_col="zone")
    # Only the EU members among our zones earn a share of an EU potential.
    eu_zones = [z for z in ours.index
                if any(c.upper().startswith(EU27_PREFIXES)
                       for c in TYNDP_ZONES[z])]
    ours_twh = float(ours.loc[eu_zones, "base_twh"].sum())
    share = ours_twh / eu27_twh
    allocated = share * eu_total

    out = PROCESSED / "biomethane_potential.csv"
    header = "\n".join([
        f"# Biomethane available to the twelve zones at {FORWARD_HORIZON},",
        "# TWh of fuel a year. ONE system-wide ceiling, not a per-zone split.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Supply Inputs, sheet",
        f"#   {BIOMETHANE_SHEET} 'Biomethane Cost Overview' (CC-BY-4.0), which",
        "#   quotes Guidehouse, 'Gas for Climate: biomethane production",
        "#   potentials in the EU'. EU-wide; there is no country breakdown.",
        "# ALLOCATION IS OURS, NOT THE SOURCE'S: the EU total times these",
        "#   zones' share of EU-27 electricity demand at the same horizon,",
        "#   from the same TYNDP demand files. Norway is not in the EU and",
        "#   is excluded from both the numerator and the potential.",
        "# The key is defensible but not physically right -- digestion runs",
        "#   on farmland and livestock, not on consumption, and Denmark in",
        "#   particular produces more biogas per unit of demand than this",
        "#   credits it with. Treat the ceiling as an order of magnitude.",
        "",
    ])
    table = pd.DataFrame([{
        "eu_potential_twh": round(eu_total, 1),
        "eu27_demand_twh": round(eu27_twh, 1),
        "zones_demand_twh": round(ours_twh, 1),
        "zones_eu_members": "+".join(eu_zones),
        "share_of_eu27_demand": round(share, 5),
        "potential_twh_used": round(allocated, 1),
    }])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)}: EU {eu_total:.0f} TWh x "
          f"{share:.1%} = {allocated:.0f} TWh for these zones")


# ---------------------------------------------------------------------------
# Transmission: what may be built between the zones.
#
# TYNDP does NOT publish a 2050 grid. It publishes a reference grid with no
# horizon on it at all, and a menu of investment candidates dated 2030-2040
# that its cost-benefit analysis chooses among -- every one of them marked
# scenario "All", because they are options rather than commitments.
#
# The reference grid is also not the same quantity as this network's line
# ratings, and must not be substituted for them. TYNDP quotes commercial
# NTCs, reduced for N-1 security, loop flows and internal bottlenecks; the
# shipped PyPSA-Eur network carries the thermal ratings of the circuits. On
# the point-to-point DC borders the two agree within 5% (DE-DK1 3500 against
# 3571). On the meshed Nordic AC borders TYNDP is three to five times
# smaller -- SE3-SE4 4500 against 17547 -- because a thermal rating is not a
# transfer capacity. Swapping one for the other would not move the model to
# 2050; it would make it far more congested than 2024.
#
# So the reference grid is left alone and only the CANDIDATES are taken:
# each one an increment the model may buy, at TYNDP's own capex. That is
# what makes transmission a decision here rather than an assumption.
TRANSMISSION_URL = (
    "https://2024-data.entsos-tyndp-scenarios.eu/files/scenarios-inputs/"
    "20231103-Electricity-and-Hydrogen-Reference-Grid-Investment-Candidates"
    ".xlsx.zip"
)
TRANSMISSION_SHEET = "3. Elec Invest Candidates"
# Southern Norway is one TYNDP node over three of our zones. Its
# interconnectors land in NO2 -- that is where NordLink and Skagerrak come
# ashore in the shipped network -- so candidate endpoints on NOS0 are put
# there rather than split, because a cable lands in one place.
TRANSMISSION_LANDING = {"NOS0": "NO2"}


def prepare_transmission_candidates():
    """Write the transmission increments the model may buy, per border."""
    zip_path = RAW / "tyndp" / Path(TRANSMISSION_URL).name
    if not zip_path.exists():
        print(f"fetching {TRANSMISSION_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(TRANSMISSION_URL))
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist()
                    if m.endswith(".xlsx") and not m.startswith("__MACOSX"))
        frame = pd.read_excel(io.BytesIO(archive.read(name)),
                              sheet_name=TRANSMISSION_SHEET)
    frame.columns = [str(c).strip() for c in frame.columns]

    node_to_zone = {}
    for zone, codes in TYNDP_ZONES.items():
        for code in codes:
            node_to_zone.setdefault(code, []).append(zone)

    def zone_of(node: str):
        if node in TRANSMISSION_LANDING:
            return TRANSMISSION_LANDING[node]
        zones = node_to_zone.get(node)
        return zones[0] if zones and len(zones) == 1 else None

    mw_col = next(c for c in frame.columns if c.startswith("DIRECT CAPACITY"))
    capex_col = next(c for c in frame.columns if c.startswith("CAPEX"))

    rows = []
    for _, row in frame.iterrows():
        z0, z1 = zone_of(str(row["FROM NODE"])), zone_of(str(row["TO NODE"]))
        if z0 is None or z1 is None or z0 == z1:
            continue
        mw = float(row[mw_col] or 0.0)
        capex = float(row[capex_col] or 0.0)
        if mw <= 0:
            continue
        name = str(row["BORDER"]).strip()
        # A candidate quoted at zero capex is not free, it is already paid
        # for: TYNDP carries committed projects through the menu so the
        # borders add up. Those belong in the fixed grid, not on the menu.
        if capex <= 0:
            kind = "committed"
        elif "Real" in name:
            kind = "real"
        else:
            kind = "concept"
        rows.append({
            "candidate": name,
            "zone0": min(z0, z1),
            "zone1": max(z0, z1),
            "kind": kind,
            "year": int(row["YEAR"]),
            "mw": round(mw, 1),
            "capex_meur": round(capex, 3),
            "capex_eur_per_mw": round(capex * 1e6 / mw, 1) if capex > 0 else 0.0,
        })

    table = pd.DataFrame(rows).sort_values(
        ["zone0", "zone1", "capex_eur_per_mw"]).reset_index(drop=True)
    out = PROCESSED / "transmission_candidates.csv"
    header = "\n".join([
        "# Transmission investment candidates between the twelve zones:",
        "# increments the section 9 model may BUY, at TYNDP's own capex.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, 'Electricity and",
        f"#   Hydrogen Reference Grid & Investment Candidates', sheet",
        f"#   '{TRANSMISSION_SHEET}' (CC-BY-4.0).",
        "# The REFERENCE grid from the same workbook is deliberately NOT",
        "#   used: it quotes commercial NTCs while the shipped network",
        "#   carries thermal circuit ratings, and the two differ by a factor",
        "#   of three to five on the meshed Nordic borders. See the comment",
        "#   in prepare.py for the comparison.",
        "# 'kind' separates identified projects (real) from the generic",
        "#   reinforcement blocks the CBA uses to price a border (concept),",
        "#   and both from projects quoted at zero capex (committed), which",
        "#   are already paid for and belong in the fixed grid.",
        "# 'year' is TYNDP's commissioning horizon; every candidate is dated",
        "#   2030-2040, so all of them are available by 2050.",
        "# Southern Norway is one TYNDP node over three of our zones; its",
        f"#   candidates land in {TRANSMISSION_LANDING['NOS0']}, where the",
        "#   shipped network's Norwegian interconnectors come ashore.",
        "",
    ])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} candidates, "
          f"{table.mw.sum() / 1e3:.1f} GW, "
          f"{table.capex_meur.sum() / 1e3:.1f} bn EUR if all built)")


# ---------------------------------------------------------------------------
# How much hydrogen a zone can store underground.
#
# The note used to decide this by hand: Germany and the two Danish zones got
# salt-cavern costs because they have salt geology, everyone else got tanks.
# The reasoning was sound and the CEILING was missing -- a cavern zone could
# store without limit, which is the assumption that decides how much seasonal
# hydrogen is worth holding.
#
# TYNDP publishes the ceiling. Its cost agrees with what the note already
# used (about 2 EUR/kWh against technology-data's 2.13), so the cost is not
# the news; MAX CAPACITY is. At 2050 it is 37.5 TWh for Germany, 0.23 for
# Denmark and 0.31 for Sweden, with Norway absent from the table entirely --
# which is Caglayan et al.'s crystalline-bedrock point in TYNDP's own numbers.
#
# Tanks stay on the menu everywhere, uncapped and expensive, so a zone
# without geology can still store at a price. That keeps "nobody builds
# tanks" a result rather than a restriction.
H2_STORAGE_MEMBER = "Hydrogen/H2 STORAGES.xlsx"
# The workbook carries two hydrogen zonings. ZONE 2 is the one this note's
# demand comes from (H2_ZONE_2.xlsx), and the only one with MAX CAPACITY.
H2_STORAGE_ZONE = "ZONE 2"
H2_STORAGE_SCENARIO = "All"


def prepare_h2_storage():
    """Write the underground hydrogen storage ceiling per zone, GWh."""
    zip_path = RAW / "tyndp" / Path(H2_IMPORTS_URL).name
    if not zip_path.exists():
        print(f"fetching {H2_IMPORTS_URL}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(_get(H2_IMPORTS_URL))
    else:
        print(f"raw exists, not fetching: {zip_path.relative_to(NOTE)}")

    with zipfile.ZipFile(zip_path) as archive:
        member = next(m for m in archive.namelist()
                      if m.endswith("H2 STORAGES.xlsx"))
        frame = pd.read_excel(io.BytesIO(archive.read(member)))
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame[(frame["YEAR"] == H2_HORIZON)
                  & (frame["SCENARIO"] == H2_STORAGE_SCENARIO)
                  & (frame["H2 ZONE"] == H2_STORAGE_ZONE)]
    ceiling = {str(r["NODE"]).strip(): float(r["MAX CAPACITY [GWh]"] or 0.0)
               for _, r in frame.iterrows()}

    # The storage table is by country; this note's zones are finer. A
    # country's ceiling is split between its zones in proportion to their
    # HYDROGEN demand -- storage is worth having where the hydrogen is used,
    # and it is the only split in the note's own data that is about hydrogen
    # rather than about electricity. Where a country has no hydrogen demand
    # at all its ceiling is split evenly, which costs nothing because a zone
    # with no demand builds no store.
    demand = pd.read_csv(PROCESSED / "h2_assumptions.csv", comment="#",
                         index_col="zone")["h2_twh_used"]
    zones_of = {}
    for zone in demand.index:
        zones_of.setdefault(zone[:2], []).append(zone)

    rows = []
    for country, zones in sorted(zones_of.items()):
        total = ceiling.get(country)
        shares = demand.loc[zones]
        for zone in zones:
            if total is None:
                share, basis = 0.0, f"{country} not in the TYNDP table"
            elif shares.sum() > 0:
                share = float(shares[zone]) / float(shares.sum())
                basis = f"{country} split by hydrogen demand"
            else:
                share = 1.0 / len(zones)
                basis = f"{country} split evenly (no hydrogen demand)"
            rows.append({
                "zone": zone,
                "country": country,
                "country_max_gwh": 0.0 if total is None else round(total, 1),
                "share_of_country": round(share, 4),
                "max_gwh": 0.0 if total is None else round(total * share, 1),
                "basis": basis,
            })

    table = pd.DataFrame(rows)
    out = PROCESSED / "h2_storage_potential.csv"
    header = "\n".join([
        f"# Underground hydrogen storage ceiling per zone at {H2_HORIZON},",
        "# GWh of hydrogen. The cap on the cheap store; tanks are uncapped.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        "# Source: ENTSO-E/ENTSOG TYNDP 2024 Scenarios, Hydrogen inputs,",
        f"#   'H2 STORAGES', MAX CAPACITY [GWh] at {H2_HORIZON},",
        f"#   scenario '{H2_STORAGE_SCENARIO}', {H2_STORAGE_ZONE} (CC-BY-4.0).",
        "# Norway is absent from the source table: crystalline bedrock, no",
        "#   salt caverns -- the same point Caglayan et al. (2020) make, in",
        "#   TYNDP's own numbers rather than on the note's say-so.",
        "# THE SPLIT TO ZONES IS OURS, NOT THE SOURCE'S: a country's ceiling",
        "#   in proportion to its zones' hydrogen demand. Geology does not",
        "#   follow demand, so treat a single zone's figure as indicative;",
        "#   the country totals are the sourced quantity.",
        "# TYNDP also caps injection and withdrawal power (MAX POWER and MAX",
        "#   LOAD EXPANSION). Those are NOT applied here -- the store sits",
        "#   directly on the hydrogen bus with no rating -- and are the next",
        "#   refinement if storage power turns out to bind.",
        "",
    ])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)} "
          f"({table.max_gwh.sum() / 1e3:.2f} TWh over {len(table)} zones)")


# ---------------------------------------------------------------------------
# Offshore wind costs the same everywhere in this model, and it should not.
#
# The DEA catalogue is DANISH: shallow North Sea, a mature supply chain, and
# the cheapest offshore conditions in Europe. IRENA's 2024 cost review puts
# Denmark's offshore LCOE at USD 53/MWh, the lowest on the continent, against
# Germany at 69 and a European average of 80. Applying the Danish number to
# twelve zones prices German, Norwegian and Swedish offshore as if it were
# Danish -- and four of those zones carry offshore potential, including SE4's
# 18.6 GW, the largest single block in the model.
#
# So each zone gets a premium on the Danish capital cost. It is built from
# IRENA's published country LCOEs, corrected for capacity factor:
#
#     premium(z) = LCOE(country) / LCOE(Denmark) x CF(z) / CF(Denmark)
#
# The correction matters. An LCOE gap is part capital cost and part resource
# quality, and this model already carries resource quality separately, in the
# zone's own wind profile. Using the raw LCOE ratio as a capital premium
# would count the resource twice. Multiplying it back by the capacity-factor
# ratio recovers the capital component: it asks what capital cost, at the
# resource quality THIS model assumes for the zone, reproduces the LCOE IRENA
# observed for that country.
#
# Denmark is the anchor at exactly 1.000, because the underlying cost is
# Denmark's. Zones with no published country figure take the European
# average. This is a construction, not a published series, and it is recorded
# as one.
IRENA_OFFSHORE_LCOE_USD_MWH = {
    "DK": 53.0,       # lowest in Europe
    "DE": 69.0,
    "UK": 59.0,       # not a zone here; kept as published context
}
IRENA_OFFSHORE_LCOE_EUROPE = 80.0
IRENA_OFFSHORE_ANCHOR = "DK"
IRENA_OFFSHORE_SOURCE = (
    "IRENA, Renewable Power Generation Costs in 2024 (2025), offshore wind")


def prepare_offshore_premium():
    """Write the per-zone multiplier on offshore wind capital cost."""
    import pypsa

    n = pypsa.Network(PROCESSED / f"network_eur_bz_{YEAR}.nc")
    network_hours = len(n.snapshots)
    potentials = pd.read_csv(PROCESSED / "potentials_zones.csv", comment="#")
    offshore_potential = potentials[
        potentials.technology == "wind_offshore"
    ].set_index("zone")["p_nom_max_used_mw"]

    def capacity_factor(zone: str):
        for carrier in ["offwind-ac", "offwind-dc", "offwind-float"]:
            match = n.generators.index[(n.generators.bus == zone)
                                       & (n.generators.carrier == carrier)]
            if len(match) and match[0] in n.generators_t.p_max_pu.columns:
                return float(n.generators_t.p_max_pu[match[0]].mean()), carrier
        return None, None

    anchor_zones = [z for z in n.buses.index
                    if z.startswith(IRENA_OFFSHORE_ANCHOR)]
    anchor_cfs = [capacity_factor(z)[0] for z in anchor_zones]
    anchor_cfs = [c for c in anchor_cfs if c]
    anchor_cf = sum(anchor_cfs) / len(anchor_cfs)

    rows = []
    for zone in sorted(n.buses.index):
        country = zone[:2]
        cf, carrier = capacity_factor(zone)
        potential = float(offshore_potential.get(zone, 0.0))
        published = IRENA_OFFSHORE_LCOE_USD_MWH.get(country)
        lcoe = published if published is not None else IRENA_OFFSHORE_LCOE_EUROPE
        if country == IRENA_OFFSHORE_ANCHOR:
            premium, basis = 1.0, "anchor: the DEA cost is Danish"
        elif cf is None:
            premium, basis = 1.0, "no offshore profile; premium unused"
        else:
            premium = (lcoe / IRENA_OFFSHORE_LCOE_USD_MWH[IRENA_OFFSHORE_ANCHOR]
                       ) * (cf / anchor_cf)
            basis = ("IRENA country LCOE" if published is not None
                     else "IRENA European average (no country figure)")
        rows.append({
            "zone": zone,
            "offshore_potential_mw": round(potential, 1),
            "capacity_factor": None if cf is None else round(cf, 4),
            "irena_lcoe_usd_mwh": lcoe,
            "premium": round(premium, 4),
            "basis": basis,
        })

    table = pd.DataFrame(rows)
    out = PROCESSED / "offshore_cost_premium.csv"
    header = "\n".join([
        "# Multiplier on offshore wind CAPITAL cost, per zone.",
        "# GENERATED by data/prepare.py -- do not edit by hand.",
        f"# Source: {IRENA_OFFSHORE_SOURCE}. Denmark USD 53/MWh (lowest in",
        f"#   Europe), Germany 69, European average"
        f" {IRENA_OFFSHORE_LCOE_EUROPE:.0f}.",
        "# THE CONSTRUCTION IS OURS, NOT IRENA'S:",
        "#   premium(z) = LCOE(country)/LCOE(DK) x CF(z)/CF(DK)",
        "#   The capacity-factor term is not decoration. An LCOE gap is part",
        "#   capital and part resource, and this model already carries the",
        "#   resource in each zone's wind profile; without the correction the",
        "#   resource would be counted twice.",
        "# Denmark is 1.000 by construction: the underlying DEA cost is the",
        "#   Danish one, and it is the cheapest offshore in Europe.",
        "# Zones with no published country LCOE take the European average.",
        "#   Sweden and Norway have essentially no offshore fleet for IRENA",
        "#   to observe, and SE4 carries the largest offshore potential in",
        "#   the model -- so that fallback is doing real work, and is the",
        "#   weakest number in this file.",
        "# capacity_factor is the shipped network's own annual mean for the",
        "#   zone, unweighted -- the same profile the model optimises on.",
        "",
    ])
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(header)
        table.to_csv(handle, index=False)
    used = table[table.offshore_potential_mw > 0]
    print(f"wrote {out.relative_to(NOTE)} "
          f"({len(used)} zones with offshore potential, premiums "
          f"{used.premium.min():.3f}-{used.premium.max():.3f}); "
          f"network has {network_hours} snapshots")


# ---------------------------------------------------------------------------
# Cost scenarios for section 8.
#
# Section 8 asks how much of a capacity expansion answer is a statement about
# the weather and how much is a statement about what the machines will cost.
# The weather half is honest: ten observed years, one per solve. The cost
# half used to re-solve on each of technology-data's published vintages,
# 2025 to 2050 -- and that was never the question. A vintage is a projection
# of what a machine costs in a stated year, not a draw from a distribution
# over 2050, so sweeping them asks "what if it were 2035?" rather than "what
# if 2050 turns out dearer than projected?".
#
# What replaces it keeps the horizon fixed at FORWARD_HORIZON and varies the
# projection instead. technology-data's own 2025 -> 2050 path is the only
# statement about the future this note has, so the scenarios are built out
# of it: for each technology,
#
#     trend  = investment(2025) - investment(2050)          (a fall, usually)
#     pessimistic = investment(2050) + x * trend
#     optimistic  = investment(2050) - x * trend
#
# at x = COST_SCENARIO_SCALE. The pessimistic world realises only half the
# projected decline by 2050; the optimistic one overshoots it by half again.
# Applied uniformly to every technology, so nothing is cherry-picked -- a
# machine technology-data expects to stay flat has trend ~ 0 and does not
# move, which is itself the right behaviour. Applied to `investment` only:
# FOM is a percentage of investment in this dataset and therefore follows.
#
# ---------------------------------------------------------------------------
# Transmission: what a wire costs, and where the bidding zones are.
#
# Both serve section 6's introduction to transmission grids. The costs are
# technology-data's own rows for overhead AC, overhead and submarine DC, and
# the converter pair a DC line needs at each end — the four numbers the
# note's "what a line is to the model" paragraph quotes. The geometry is
# Natural Earth (public domain), assembled into Europe's bidding zones so
# the note can draw a map with the model's twelve zones highlighted.
# ---------------------------------------------------------------------------

TRANSMISSION_TECHS = {
    # technology-data row -> (label, kind)
    "HVAC overhead": ("AC overhead line", "AC"),
    "HVDC overhead": ("DC overhead line", "DC"),
    "HVDC submarine": ("DC submarine cable", "DC"),
    "HVDC inverter pair": ("DC converter station pair", "DC"),
}


def prepare_transmission_costs():
    """technology-data's transmission rows at the pinned tag, one line per
    technology: investment (EUR/MW/km for lines, EUR/MW for the converter
    pair), lifetime and fixed O&M. Read from the raw 2030 file that
    prepare_costs_full() has already fetched."""
    raw_file = RAW / "technology-data" / f"costs_{TECHNOLOGY_DATA_YEAR}_{TECHNOLOGY_DATA_TAG}.csv"
    if not raw_file.exists():
        prepare_costs_full(TECHNOLOGY_DATA_YEAR)
    df = pd.read_csv(raw_file)
    rows = []
    for tech, (label, kind) in TRANSMISSION_TECHS.items():
        sub = df[df["technology"] == tech].set_index("parameter")
        rows.append({
            "technology": tech,
            "label": label,
            "kind": kind,
            "investment": float(sub.loc["investment", "value"]),
            "investment_unit": sub.loc["investment", "unit"],
            "lifetime_years": float(sub.loc["lifetime", "value"]),
            "fom_pct_per_year": float(sub.loc["FOM", "value"]),
            "source": sub.loc["investment", "source"],
        })
    out = PROCESSED / "transmission_costs.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Transmission investment costs: technology-data's rows for\n")
        handle.write("# overhead AC, overhead and submarine DC, and the converter\n")
        handle.write(f"# station pair a DC line needs, at tag {TECHNOLOGY_DATA_TAG}\n")
        handle.write(f"# (vintage {TECHNOLOGY_DATA_YEAR}). Lines are priced per MW\n")
        handle.write("# and km; the converter pair per MW. Quoted in section 6's\n")
        handle.write("# introduction to transmission grids.\n")
        pd.DataFrame(rows).to_csv(handle, index=False, float_format="%.4f")
    print(f"wrote {out.relative_to(NOTE)}")


REFERENCE_GRID_SHEET = "1. Elec Ref Grid"


def prepare_reference_ntc():
    """TYNDP's reference-grid transfer capacities between the twelve zones,
    both directions in MW, from the same workbook as the candidates.

    These are commercial NTCs for the 2030 reference grid, where the
    shipped network carries thermal circuit ratings that are three to five
    times larger on the meshed Nordic borders. Section 6 derates the
    network's internal Nordic corridors to these figures (never uprates:
    a 2030 reinforcement is not 2024's grid). Southern Norway is one TYNDP
    node (NOS0) over NO1, NO2 and NO5, so a border touching it is recorded
    against the group, and the run stage splits the figure over the lines
    that actually join the two groups."""
    zip_path = RAW / "tyndp" / Path(TRANSMISSION_URL).name
    if not zip_path.exists():
        prepare_transmission_candidates()
    with zipfile.ZipFile(zip_path) as archive:
        name = next(m for m in archive.namelist()
                    if m.endswith(".xlsx") and not m.startswith("__MACOSX"))
        frame = pd.read_excel(io.BytesIO(archive.read(name)),
                              sheet_name=REFERENCE_GRID_SHEET, header=None)
    header = frame.index[frame[0].astype(str).str.strip() == "Border"][0]
    frame = frame.iloc[header + 1:, :3]
    frame.columns = ["border", "dir1", "dir2"]

    group_of = {}
    for zone, codes in TYNDP_ZONES.items():
        for code in codes:
            group_of.setdefault(code, set()).add(zone)

    rows = []
    for _, row in frame.iterrows():
        border = str(row["border"]).strip()
        if "-" not in border:
            continue
        a, b = border.split("-", 1)
        ga, gb = group_of.get(a), group_of.get(b)
        if not ga or not gb or ga == gb:
            continue
        rows.append({
            "tyndp_border": border,
            "zones0": "+".join(sorted(ga)),
            "zones1": "+".join(sorted(gb)),
            "dir1_mw": _tyndp_number(row["dir1"]),
            "dir2_mw": _tyndp_number(row["dir2"]),
        })
    table = pd.DataFrame(rows)
    table["ntc_mw"] = table[["dir1_mw", "dir2_mw"]].max(axis=1)
    out = PROCESSED / "transmission_ntc_reference.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Reference-grid transfer capacities between the twelve zones,\n")
        handle.write("# both directions in MW, from ENTSO-E/ENTSOG TYNDP 2024\n")
        handle.write("# Scenarios, 'Electricity and Hydrogen Reference Grid &\n")
        handle.write(f"# Investment Candidates', sheet '{REFERENCE_GRID_SHEET}'\n")
        handle.write("# (CC-BY-4.0). GENERATED by data/prepare.py. ntc_mw is the\n")
        handle.write("# larger direction, since a symmetric line cannot carry an\n")
        handle.write("# asymmetric limit. Zones joined by '+' are one TYNDP node.\n")
        table.to_csv(handle, index=False, float_format="%.0f")
    print(f"wrote {out.relative_to(NOTE)} ({len(table)} borders)")


# Norway's 2024 hydro year, for section 6's calibration of the network's
# inflow. The shipped network normalises the 2024 runoff to an annual level
# by a regression (Appendix C), and lands 25-30 TWh short of what Norway's
# plants actually produced in a record year. Section 6, which is held
# against 2024, scales reservoir inflow so that reservoir output plus
# run-of-river equals the published production; sections 7-9, which look
# at 2050, keep the network's own level. Source value recorded beside use.
HYDRO_CALIBRATION = {
    "NO": {
        # SSB, Electricity (statistics), table 'Generation, imports, exports
        # and consumption of electricity', 2024: hydro 139,984 GWh of a
        # 157,136 GWh total; net export 18,439 GWh.
        "production_twh": 140.0,
        "net_export_twh": 18.4,
        # NVE's normal annual hydro production, reference period 1991-2020,
        # as stated at the start of 2025 (energifaktanorge.no, "Electricity
        # production"). Every section's network is put on this level when it
        # is loaded (model/network.py:normalise_hydro); section 6 then scales
        # further to the 2024 outcome above.
        "normal_production_twh": 137.6,
        "source": "Statistics Norway (SSB), Electricity, annual 2024: "
                  "hydro power production 139,984 GWh, net export "
                  "18,439 GWh; normal production 137.6 TWh from NVE "
                  "(energifaktanorge.no, reference 1991-2020)",
    },
}


def prepare_hydro_calibration():
    """One row per calibrated country: the published hydro production of
    the network's year, beside the inflow the network carries."""
    import pypsa
    n = pypsa.Network(PROCESSED / "network_eur_bz_2024.nc")
    rows = []
    for country, spec in HYDRO_CALIBRATION.items():
        units = n.storage_units.index[n.storage_units.bus.str.startswith(country)
                                      & (n.storage_units.carrier == "hydro")]
        inflow = float(n.storage_units_t.inflow.reindex(columns=units).fillna(0).sum().sum()) / 1e6
        ror = n.generators.index[n.generators.bus.str.startswith(country)
                                 & (n.generators.carrier == "ror")]
        ror_twh = float(n.generators_t.p_max_pu.reindex(columns=ror).fillna(0)
                        .mul(n.generators.loc[ror, "p_nom"]).sum().sum()) / 1e6
        rows.append({
            "country": country,
            "year": YEAR,
            "network_reservoir_inflow_twh": round(inflow, 1),
            "network_run_of_river_twh": round(ror_twh, 1),
            "published_hydro_production_twh": spec["production_twh"],
            "published_net_export_twh": spec["net_export_twh"],
            "normal_production_twh": spec["normal_production_twh"],
            "source": spec["source"],
        })
    out = PROCESSED / "hydro_calibration.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Hydro energy in the network's year beside the published\n")
        handle.write("# figure: what the shipped network carries (reservoir inflow\n")
        handle.write("# and run-of-river, TWh) and what the country's plants\n")
        handle.write("# actually produced, and NVE's normal-year production. Every\n")
        handle.write("# section's network is scaled to the normal level on load\n")
        handle.write("# (inflow plus run-of-river = normal production); section 6\n")
        handle.write("# scales further so that solved output equals the published\n")
        handle.write("# 2024 production. GENERATED by prepare.py.\n")
        pd.DataFrame(rows).to_csv(handle, index=False)
    print(f"wrote {out.relative_to(NOTE)}")


NATURAL_EARTH = {
    # file stem -> download URL (Natural Earth is public domain)
    "ne_50m_admin_0_countries":
        "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip",
    "ne_10m_admin_1_states_provinces":
        "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip",
}

# The bidding zones of Europe's day-ahead market, as an assembly of Natural
# Earth units. Most zones are countries. Four countries are split into
# several zones, and those are assembled from first-level subdivisions:
# Norway (five), Sweden (four), Denmark (two) and Italy (seven). Two zones
# straddle a border: Germany and Luxembourg form one, and the island of
# Ireland is one (SEM). The subdivision mapping follows county borders,
# which the real zone borders only approximately do (the SE2/SE3 and
# NO1/NO2 borders both cut through counties), so the map is a classroom
# map, not a legal one.
ZONE_OF_SUBDIVISION = {
    # Norway, by fylke (Natural Earth's pre-2020 counties)
    "NO1": ["Østfold", "Akershus", "Oslo", "Hedmark", "Oppland", "Buskerud",
            "Vestfold"],
    "NO2": ["Telemark", "Aust-Agder", "Vest-Agder", "Rogaland"],
    "NO3": ["Møre og Romsdal", "Sør-Trøndelag", "Nord-Trøndelag"],
    "NO4": ["Nordland", "Troms", "Finnmark"],
    "NO5": ["Hordaland", "Sogn og Fjordane"],
    # Sweden, by län
    "SE1": ["Norrbotten"],
    "SE2": ["Västerbotten", "Jämtland", "Västernorrland"],
    "SE3": ["Gävleborg", "Dalarna", "Värmland", "Uppsala", "Stockholm",
            "Västmanland", "Orebro", "Södermanland", "Östergötland",
            "Västra Götaland", "Gotland", "Jönköping"],
    "SE4": ["Halland", "Kronoberg", "Kalmar", "Blekinge", "Skåne"],
    # Denmark, by region
    "DK1": ["Nordjylland", "Midtjylland", "Syddanmark"],
    "DK2": ["Hovedstaden", "Sjaælland"],
}
# Italy, by region (Natural Earth's `region` field on its provinces)
ITALY_ZONE_OF_REGION = {
    "IT-North": ["Valle d'Aosta", "Piemonte", "Liguria", "Lombardia",
                 "Trentino-Alto Adige", "Veneto", "Friuli-Venezia Giulia",
                 "Emilia-Romagna"],
    "IT-CentreNorth": ["Toscana", "Umbria", "Marche"],
    "IT-CentreSouth": ["Lazio", "Abruzzo", "Campania"],
    "IT-South": ["Molise", "Apulia", "Basilicata"],
    "IT-Calabria": ["Calabria"],
    "IT-Sicily": ["Sicily"],
    "IT-Sardinia": ["Sardegna"],
}
# One zone per country, by ISO-3 code, for the rest of the coupled market
# and its neighbours (Great Britain and Switzerland trade with it without
# being in it; the Western Balkans are joining zone by zone).
ZONE_OF_COUNTRY = {
    "AUT": "AT", "BEL": "BE", "NLD": "NL", "FRA": "FR", "ESP": "ES",
    "PRT": "PT", "CHE": "CH", "CZE": "CZ", "POL": "PL", "SVK": "SK",
    "HUN": "HU", "SVN": "SI", "HRV": "HR", "ROU": "RO", "BGR": "BG",
    "GRC": "GR", "FIN": "FI", "EST": "EE", "LVA": "LV", "LTU": "LT",
    "BIH": "BA", "SRB": "RS", "MNE": "ME", "MKD": "MK", "ALB": "AL",
    "KOS": "XK",
}
# Land drawn as background only: outside the coupled market.
BACKGROUND_COUNTRIES = ["RUS", "BLR", "UKR", "MDA", "ISL", "TUR"]
MODEL_ZONES = ["DK1", "DK2", "DE-LU", "SE1", "SE2", "SE3", "SE4",
               "NO1", "NO2", "NO3", "NO4", "NO5"]
MAP_BBOX = (-12.0, 34.0, 60.0, 72.0)     # lon_min, lat_min, lon_max, lat_max
MAP_CRS = "EPSG:3034"                     # ETRS89 / LCC Europe, in metres
MAP_SIMPLIFY_M = 2500.0


def _fetch_natural_earth(stem: str) -> Path:
    out = RAW / "naturalearth" / f"{stem}.zip"
    if not out.exists():
        url = NATURAL_EARTH[stem]
        print(f"fetching {url}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_get(url))
        print(f"wrote {out.relative_to(NOTE)}")
    else:
        print(f"raw exists, not fetching: {out.relative_to(NOTE)}")
    return out


def _rings(geometry) -> list:
    """Exterior rings of a (multi)polygon as lists of [x, y] in metres,
    rounded to the metre. Holes (lakes) are dropped: invisible at map scale."""
    polygons = getattr(geometry, "geoms", [geometry])
    return [[[round(x), round(y)] for x, y in poly.exterior.coords]
            for poly in polygons if not poly.is_empty]


def prepare_bidding_zones():
    """Europe's bidding zones as projected polygons, for the map of
    section 6, plus the projected coordinates of the network's twelve zone
    nodes so the topology figure can be drawn from the same file.

    Needs geopandas (with shapely and pyproj), which the run and build
    stages do not: the geometry is written out as plain coordinate lists.
    """
    import geopandas as gpd
    from shapely.geometry import box

    a0 = gpd.read_file(f"zip://{_fetch_natural_earth('ne_50m_admin_0_countries')}")
    a1 = gpd.read_file(f"zip://{_fetch_natural_earth('ne_10m_admin_1_states_provinces')}")
    a0 = a0.set_index("ADM0_A3")
    window = box(*MAP_BBOX)

    features = []   # (zone, country, coupled, geometry in lon/lat)
    for zone, names in ZONE_OF_SUBDIVISION.items():
        iso3 = {"NO": "NOR", "SE": "SWE", "DK": "DNK"}[zone[:2]]
        sub = a1[(a1["adm0_a3"] == iso3) & a1["name"].isin(names)]
        missing = set(names) - set(sub["name"])
        if missing:
            raise SystemExit(f"{zone}: subdivisions not found in Natural Earth: {missing}")
        features.append((zone, zone[:2], True, sub.geometry.union_all()))
    italy = a1[a1["adm0_a3"] == "ITA"]
    for zone, regions in ITALY_ZONE_OF_REGION.items():
        sub = italy[italy["region"].isin(regions)]
        if sub.empty:
            raise SystemExit(f"{zone}: no Italian provinces matched {regions}")
        features.append((zone, "IT", True, sub.geometry.union_all()))
    gb = a1[a1["adm0_a3"] == "GBR"]
    features.append(("GB", "GB", True,
                     gb[gb["geonunit"] != "Northern Ireland"].geometry.union_all()))
    features.append(("SEM", "IE", True,
                     gb[gb["geonunit"] == "Northern Ireland"].geometry.union_all()
                     .union(a0.loc["IRL", "geometry"])))
    features.append(("DE-LU", "DE", True,
                     a0.loc["DEU", "geometry"].union(a0.loc["LUX", "geometry"])))
    for iso3, zone in ZONE_OF_COUNTRY.items():
        features.append((zone, zone, True, a0.loc[iso3, "geometry"]))
    for iso3 in BACKGROUND_COUNTRIES:
        features.append((None, iso3[:2], False, a0.loc[iso3, "geometry"]))

    frame = gpd.GeoDataFrame(
        {"zone": [f[0] for f in features], "country": [f[1] for f in features],
         "coupled": [f[2] for f in features]},
        geometry=[f[3].intersection(window) for f in features], crs="EPSG:4326",
    ).to_crs(MAP_CRS)
    frame = frame[~frame.geometry.is_empty]      # e.g. Iceland, outside the window
    frame["geometry"] = frame.geometry.simplify(MAP_SIMPLIFY_M)

    # The network's zone nodes, in the same projection.
    import pypsa
    buses = pypsa.Network(PROCESSED / "network_eur_bz_2024.nc").buses[["x", "y"]]
    nodes = gpd.GeoDataFrame(
        buses, geometry=gpd.points_from_xy(buses["x"], buses["y"]), crs="EPSG:4326"
    ).to_crs(MAP_CRS)

    zones = []
    for _, row in frame.iterrows():
        label = row.geometry.representative_point()
        zones.append({
            "zone": row["zone"], "country": row["country"],
            "coupled": bool(row["coupled"]),
            "in_model": row["zone"] in MODEL_ZONES,
            "label_xy": [round(label.x), round(label.y)],
            "rings": _rings(row.geometry),
        })
    out = PROCESSED / "bidding_zones.json"
    out.write_text(json.dumps({
        "crs": MAP_CRS,
        "source": "Natural Earth 50m admin-0 and 10m admin-1 (public domain), "
                  "assembled into bidding zones in data/prepare.py; the "
                  "subdivision-to-zone mapping is approximate",
        "bbox_lonlat": MAP_BBOX,
        "zones": zones,
        "nodes": {name: [round(p.x), round(p.y)]
                  for name, p in zip(nodes.index, nodes.geometry)},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out.relative_to(NOTE)} ({len(zones)} zones, "
          f"{out.stat().st_size / 1e3:.0f} kB)")


# The values scaled are the ones the note USES, after the BNEF battery cap
# and the DEA offshore restoration, because those are what the model pays.
COST_SCENARIO_SCALE = 0.5
COST_SCENARIO_BASE_YEAR = 2025   # the near end of technology-data's path


def prepare_cost_scenarios():
    """Write the pessimistic and optimistic cost tables section 8 re-solves on.

    Reads the two ends of the projection that prepare_costs_full() has
    already written, so this is deterministic and offline. Neither output
    replaces the baseline: `technology_costs_full_{horizon}.csv` stays what
    sections 7 and 9 read, and the scenarios sit beside it under a suffix.
    """
    base = pd.read_csv(
        PROCESSED / f"technology_costs_full_{COST_SCENARIO_BASE_YEAR}.csv",
        index_col="technology")
    horizon = pd.read_csv(
        PROCESSED / f"technology_costs_full_{FORWARD_HORIZON}.csv",
        index_col="technology")

    shared = horizon.index.intersection(base.index)
    missing = horizon.index.difference(base.index)
    if len(missing):
        raise SystemExit(
            f"technology_costs_full_{COST_SCENARIO_BASE_YEAR}.csv is missing "
            f"{list(missing)}, which the {FORWARD_HORIZON} table prices -- the "
            "two vintages must cover the same technologies for the trend to "
            "be defined")

    trend = (base.loc[shared, "investment"] - horizon.loc[shared, "investment"])
    record = pd.DataFrame({
        f"investment_{COST_SCENARIO_BASE_YEAR}_eur_per_kw":
            base.loc[shared, "investment"].round(4),
        f"investment_{FORWARD_HORIZON}_eur_per_kw":
            horizon.loc[shared, "investment"].round(4),
        "trend_eur_per_kw": trend.round(4),
    })
    # Carried as columns rather than left in the header comment: stage 2 reads
    # this file and passes the three of them on to results/, so the prose can
    # quote what was varied through a macro instead of a typed number.
    record["base_year"] = COST_SCENARIO_BASE_YEAR
    record["horizon"] = FORWARD_HORIZON
    record["trend_scale"] = COST_SCENARIO_SCALE

    for name, sign in [("pessimistic", +1.0), ("optimistic", -1.0)]:
        table = horizon.copy()
        # Clipped at zero: a technology whose projected fall is larger than
        # its 2050 cost would otherwise be given away, and a negative capital
        # cost is not a pessimistic or an optimistic world, it is a bug.
        table.loc[shared, "investment"] = (
            horizon.loc[shared, "investment"]
            + sign * COST_SCENARIO_SCALE * trend
        ).clip(lower=0.0)
        record[f"investment_{name}_eur_per_kw"] = (
            table.loc[shared, "investment"].round(4))
        out = PROCESSED / f"technology_costs_full_{FORWARD_HORIZON}_{name}.csv"
        table.to_csv(out, float_format="%.4f")
        print(f"wrote {out.relative_to(NOTE)} ({name}, "
              f"x={COST_SCENARIO_SCALE})")

    out = PROCESSED / "cost_scenarios.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# Section 8's cost scenarios. The trend is\n")
        handle.write(f"# investment({COST_SCENARIO_BASE_YEAR}) - "
                     f"investment({FORWARD_HORIZON}) on the values the note\n")
        handle.write("# uses (after the BNEF battery cap and the DEA offshore\n")
        handle.write("# restoration); pessimistic adds and optimistic subtracts\n")
        handle.write(f"# {COST_SCENARIO_SCALE:g} x trend, clipped at zero. So the\n")
        handle.write("# pessimistic world realises only half of technology-data's\n")
        handle.write("# projected decline and the optimistic one overshoots it by\n")
        handle.write("# half again. These are scenarios, not a distribution: the\n")
        handle.write("# note says so rather than reporting them as an interval.\n")
        record.to_csv(handle)
    moved = int((record["trend_eur_per_kw"].abs() > 1e-9).sum())
    print(f"wrote {out.relative_to(NOTE)} ({len(record)} technologies, "
          f"{moved} with a non-zero trend)")


def prepare_costs_only():
    """The one thing a student has to build: the technology-cost tables.

    Everything else in data/processed/ ships with the repository. These do
    not (their source's compiled outputs carry no single stated licence, so
    the reshaped subset is never redistributed from here), and the models of
    sections 7-9 read them at import time. One small download per vintage at
    the pinned tag, then the two cost scenarios of section 9 built from them.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    cost_rows = [prepare_costs_full(cost_year) for cost_year in COST_YEARS]
    write_battery_assumptions([r["battery"] for r in cost_rows])
    write_offshore_assumptions([r["offshore"] for r in cost_rows])
    prepare_cost_scenarios()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for year in WEATHER_YEARS:
        raw_dk1 = fetch_settlement("DK1", year)
        prepare_profiles(raw_dk1, "dk1", year)
        prepare_profiles(fetch_settlement("DK2", year), "dk2", year)
        if year == YEAR:
            prepare_actual_dispatch(raw_dk1, "dk1", year)
    prepare_temperature()
    prepare_zone_weather()
    cost_rows = [prepare_costs_full(cost_year) for cost_year in COST_YEARS]
    write_battery_assumptions([r["battery"] for r in cost_rows])
    write_offshore_assumptions([r["offshore"] for r in cost_rows])
    prepare_fuels()
    prepare_costs_small()
    prepare_spot(YEAR)
    prepare_exchange("DK1", YEAR)
    prepare_exchange("DK2", YEAR)
    prepare_potentials()
    prepare_ev_demand()
    prepare_h2_demand()
    prepare_h2_imports()
    # After prepare_fuels() and prepare_ev_demand(): the forward tables are
    # built on top of both.
    prepare_forward_fuels()
    prepare_demand_totals()
    prepare_biomethane_potential()
    prepare_transmission_candidates()
    prepare_transmission_costs()
    prepare_reference_ntc()
    prepare_hydro_calibration()
    prepare_bidding_zones()
    prepare_h2_storage()
    prepare_offshore_premium()
    # Last: it reads the cost tables prepare_costs_full() wrote above.
    prepare_cost_scenarios()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--costs-only", action="store_true",
        help="build only the technology-cost tables (the files that are not "
        "shipped with the repository); everything else is already in "
        "data/processed/",
    )
    args = parser.parse_args()
    prepare_costs_only() if args.costs_only else main()
