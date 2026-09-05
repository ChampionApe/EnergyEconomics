# Data

Stage 1 of the pipeline: `raw/` → `processed/`, via `prepare.py`.

    raw/         as downloaded. NEVER published, never edited in place.
    processed/   what the pipeline reads. Published.

**Fetch at a pinned version.** An unpinned fetch lets the note's numbers drift
silently between builds, which is the failure this note can least afford. It
is also how this note stays consistent with the energy-system-models note,
which reads the same source at the same pin: two independent fetches at one
pin agree, and neither note has to reach into the other's directories.

## Sources

### PyPSA `technology-data`, tag `v0.13.2`

<https://github.com/PyPSA/technology-data> — `outputs/costs_YYYY.csv`.

A compilation, not a primary source: most entries used here originate in the
Danish Energy Agency's technology catalogue, with coal, lignite and nuclear
from other published compilations. All money is converted by the project to
**2020 euros** (`eur_year` in its config).

The compiled outputs carry no single stated licence, so they are fetched and
reshaped, never vendored raw.

`prepare.py` keeps 18 technologies × 8 parameters per vintage, for vintages
2025–2050, and writes `processed/technology_costs_YYYY.csv`.

**One override: battery investment costs.** The dataset's battery trajectory
has fallen well behind the world market — its 2040 vintage costs roughly
what turnkey systems sold for in 2025. `prepare.py` therefore caps every
vintage's 4-hour system cost at **165 €/kWh**, BNEF's 2025 European average
turnkey price (177 $/kWh, *Energy Storage System Cost Survey 2025*, Dec 2025
press-release figures, converted at ~1.07 USD/EUR; global average
117 $/kWh, China 73 $/kWh), keeping the dataset's inverter/cells split.
Vintages already below the cap are untouched (the cap binds for 2025 and
2030 only), and `processed/battery_assumptions.csv` records the dataset's
value beside the value used, per vintage. **This block is shared verbatim
with the energy-system-models note** — if you change it here, change it
there, and re-run `tools/check_note_consistency.py`.

### Our World in Data (CC-BY 4.0)

- `solar-pv-prices` — world average PV module price, constant USD per watt,
  1975 onwards, compiled by OWID after Nemet (2009) and IRENA.
- `installed-solar-PV-capacity` — world cumulative installed PV capacity,
  2000 onwards.

Joined on year into `processed/solar_learning.csv`. The learning fit uses only
the overlap (2000–2024); the long price series is plotted on its own.

### Cost vintages

`processed/cost_vintages.csv` takes the *same* file — `outputs/costs_2030.csv`
— from seven successive releases of `technology-data` between August 2020 and
June 2025, to show how much a published catalogue is actually revised. Money
is as published in each release, which is what makes the 2024 currency
rebasing visible. That is the point of the figure, so do not "fix" it.

## Hand-authored inputs

Three processed files are written from literals in `prepare.py` rather than
fetched, and all are labelled as assumptions in the note's Appendix D:

- `technology_meta.csv` — display names and order, fuel carrier, reference
  capacity factor, dispatchability class, conventional role, and the
  qualitative High/Medium/Low ratings of the note's Table 1.
- `fuel_assumptions.csv` — fuel prices and carbon contents, carrying **both**
  the dataset's published value and the value the note uses. The note's fuel
  prices are stylised 2025 forward levels, chosen for consistency with the
  rest of the course; the dataset's own are inherited from a 2013 study and
  sit well below what European plants have paid recently. Keeping both columns
  is deliberate — the note's §4 asks everybody else to show their working.
- `geography_assumptions.csv` — the regional inputs of the note's §6: a
  discount rate, a solar capacity factor, two investment-cost indices, a gas
  price and a carbon price for each of three regions, each with a `basis` and
  a `source` field.

**Every row of `geography_assumptions.csv` is an assumption, not a
measurement**, and §6 is built that way on purpose. Published levelised costs
cannot be compared across regions — the boundaries, currency years and capital
costs all differ — so the note imports regional *inputs* and computes its own
levels through its own equation, at one boundary and in one currency year.
Only the deltas come from outside, and they are round numbers chosen to be
right in direction and rough magnitude. If you sharpen one, sharpen its
`source` field with it.

`processed/manifest.json` records the pins and the assumptions in
machine-readable form, including the fact that §6 fetches nothing.
