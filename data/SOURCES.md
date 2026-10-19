# Data sources

Each source, how it is fetched, how often it updates, and the problems to watch for.
Every pull is recorded in `data/processed/pull_log.csv` with a UTC timestamp and status.

| Source | Module | What | Resolution | Coverage | Key needed | Updates |
|---|---|---|---|---|---|---|
| Open-Meteo archive | `openmeteo.py` | temperature, rain, radiation, humidity, wind, FAO ET0 | about 25 km (ERA5) | 1940 onwards | no | daily, about 5 days behind |
| Open-Meteo forecast | `openmeteo.py` | same, next 16 days | about 10 km (best model mix) | rolling | no | hourly |
| NASA POWER | `nasapower.py` | temperature, rain, radiation, humidity, wind | 0.5 x 0.625 degrees | 1981 onwards | no | daily, a few days behind |
| IMD gridded rainfall | `imd.py` | daily rain from rain gauges | 0.25 degrees | 1901 onwards | no | yearly, months behind |
| ISRIC SoilGrids 2.0 | `soil.py` | clay, sand, silt, pH, organic carbon, bulk density, gravel, nitrogen | 250 m | static | no | rarely |
| data.gov.in mandi prices | `prices.py` | daily min, max, modal price per market | per market | recent days only | yes (free) | daily |
| CEDA Ashoka Agri Market Data (Agmarknet, DMI) | `scripts/fetch_ceda_prices.py` | monthly min, max, modal price (Rs/quintal); monthly arrivals | state and Census 2011 district | 2001 to Oct 2025 | no | monthly |
| ICRISAT DLD crops (TCI-ICRISAT) | Colab download | district area, production, yield, 1990 boundaries ("unapportioned") | district, 20 states | 1990 to 2019 | no | occasional |
| ICRISAT DLD farm harvest prices | Colab download | annual farm harvest price, 17 crops (no soybean) | district, 20 states | 1990 to 2020 | no | occasional |
| DES Area, Production & Yield report (data.desagri.gov.in) | browser download, see agri-project README | district area, production, yield, all crops and seasons | district (names, no codes) | 1997-98 to 2022-23 (downloaded 2015-16 to 2022-23) | no login | yearly |
| Soil Health Card nutrient dashboard (soilhealth.dac.gov.in) | browser download, see agri-project README | samples rated low/medium/high for N, P, K, OC; deficient/sufficient for S, Zn, Fe, Cu, B, Mn; pH and EC classes | district (LGD codes) | cycles 2023-24 to 2026-27 | no login | continuous |

CEDA and ICRISAT both use Census 2011 state and district codes, so they join on those ids
rather than on spelled names. Cite CEDA, Ashoka University and DMI (Agmarknet) for prices,
and ICRISAT and TCI for the district database. CEDA states no licence on the site.

## Known problems

- **Open-Meteo and NASA POWER are models, not measurements.** For Latur kharif 2023 they
  differ by 88 mm of season rain (623 vs 535 mm) and their daily rain correlates only 0.71.
  IMD, built from rain gauges, is the closest to ground truth among the free sources.
- **NASA POWER near the Western Ghats.** POWER's 0.5 x 0.625 degree cell for Pune includes Ghats
  slopes, so it reports 2 to 4 times IMD's kharif rain (2022: 2203 vs 1071 mm). One cell east
  (74.4 E) gives 1026 mm. Do not use POWER rain for locations within about 60 km of the Ghats.
- **Open-Meteo in rain-shadow areas.** For Solapur it was 62 to 76 percent above IMD in kharif
  2022 and 2023.
- **IMD** files arrive months after the year ends, and its server is slow. Cells with no data
  (sea, outside India) are -999 and become blank. Files are cached and never re-downloaded.
- **NASA POWER** uses -999 for missing values; these become blank.
- **SoilGrids** is a 250 m model estimate. Black cotton soils (Vertisols) near 50 to 60 percent
  clay sit at the edge of the Saxton-Rawls equations used for field capacity and wilting point;
  rows above 60 percent clay are flagged. The service is sometimes offline; failed locations are
  recorded and the rest continue. SoilGrids leaves towns blank, so each location uses the nearest farmland
  point (all five were found 3 km from the town centre). These points are saved in
  `locations.csv` so later runs skip the search.
- **Mandi prices**: commodity and market names are inconsistent across years and need mapping.
  The API resource only holds recent days; older history comes from Agmarknet report downloads.
- **Yields**: the IRIS dataset found the whole of 2007 at about 1/100 scale for area. Any new yield
  file is run through `yields.year_scale_flags()` before use, and kept in its own labelled file.

## Licences

Open-Meteo: CC BY 4.0, free for non-commercial use. NASA POWER: public, cite NASA LaRC POWER.
IMD gridded data: free for research, cite Pai et al. (2014). SoilGrids: CC BY 4.0, cite Poggio
et al. (2021). data.gov.in: Government Open Data Licence India.

## Multi-state table (`src/cropadvisor/multistate.py`)

Built in Colab from the full files; outputs go to Google Drive, `crop-advisor/03_data_processed/` (raw inputs in `01_data_raw/`, lookups in `02_data_reference/`, notebooks in `04_notebooks/`):

| File | What |
|---|---|
| `rainfall_district_monthly_2009_2024.csv` | rain, normal, days with data and coverage per district-month (628 districts) |
| `rainfall_district_seasons_2009_2024.csv` | kharif (Jun-Sep), rabi (Oct-Feb), agri year (Jun-May) totals and departure from normal |
| `multistate_yield_rain_2009_2019.csv` | ICRISAT district yields joined to that district's seasonal rain, 20 states, 29 crops |

Matching (`data/reference/district_match_icrisat_to_rain.csv`): the rainfall file uses LGD
district codes, ICRISAT uses its own and Census codes, so districts are matched by name within
each state: 409 exact, 91 alias (spellings such as Yeotmal/Yavatmal), 36 fuzzy (all checked by
hand), and 66 "parent": districts created after about 2012 (most of Telangana's 33, new
Chhattisgarh and Gujarat districts) have no rainfall series, so they use the district they were
carved from. Undivided Burdwan uses Paschim Bardhaman, the only Bardhaman in the rainfall file.

Data fixes, all flagged rather than silent:
- Rainfall: Leh Ladakh has two disagreeing copies of 3,451 days (correlation 0.35); averaged,
  `dup_averaged = True`. No other district has duplicates. Months with missing days are scaled
  up by 1/coverage, and a season is `complete` only if every month has at least 80 percent of days.
- ICRISAT: -1 means missing. About 7,300 rows have a yield with no area, or zero yield on a sown
  area; their yield is set to missing with `flag = "area/yield contradict"`. 1.2 percent of rows
  have a yield more than 25 percent away from production / area (`yield_check`).
- Sugarcane in ICRISAT is gur equivalent (about 6,800 kg/ha), not cane (about 70,000 kg/ha).
- All-India file: cotton (lint) and jute/mesta are in bales and are converted at 170 and 180 kg;
  coconut is in nuts and its production is dropped.

## Post-2019 yields and soil nutrients

DES district yields match ICRISAT exactly where both exist (Latur soybean 2015-16: 340,800 ha, 0.32 t/ha in both), so DES extends the ICRISAT series to 2022-23. The public Soil Health Card dashboard gives counts of samples per rating class for each district, not individual sample values.

## North India pilot (Haryana, Punjab)

`src/cropadvisor/northindia.py` and `scripts/build_north_india_table.py` build `north_india_*.csv`
from the files above (45 districts, wheat, rice, cotton, 2009 to 2022); `north_india_NOTES.md` next
to the output lists the caveats. Pilot districts (`PILOT`): Sirsa, Hisar, Kurukshetra, Bathinda,
Sangrur, Tarn Taran. Their weather and soil pull is
`python scripts/refresh_data.py --start 2021 --end 2023 --locations data/locations_north_india.csv --data-dir data_north_india`.

Pilot coordinates are the district town, not a farm: Wikipedia infoboxes for Sirsa, Kurukshetra,
Bathinda and Sangrur; latlong.net for Hisar (Wikipedia's Hisar page gives two inconsistent sets);
worldatlas.com for Tarn Taran. Elevations: Wikipedia for Sirsa, Hisar, Bathinda and
Sangrur; kurukshetra.gov.in (district figure) for Kurukshetra; worldatlas.com for Tarn Taran. Two
elevations are uncertain by a few metres, which does not matter for ET0: Sirsa (201 m infobox, 205 m
article text) and Bathinda (210 m infobox, 201 m article text). Replace them with the real farm's
coordinates and elevation when a station is placed.

Known problems:
- **DES Haryana cotton 2020-21** has production about 1,000 times too small (likely a thousand-bales
  unit slip); excluded with a note, not rescaled. `northindia.yield_scale_flags` catches this kind of error.
- **Cotton bale weight.** DES is converted at 170 kg per bale; ICRISAT cotton is about 5 percent higher
  (implied about 180 kg per bale) and rounded to the nearest 1,000. Joining them shows a false step at 2014-15.
- **Soil Health Card is sparse and unstable in Haryana and Punjab**: 9 of 45 districts have a cycle with
  500 or more samples, and Bathinda potassium rated low goes 96, 40, 8 percent over three cycles.
  Use as background only.
- **Delhi** has no district yields (ICRISAT none, DES one state total) and no usable Soil Health Card samples.
- **IMD July 2020** has 16 of 31 days for every district, so kharif 2020 season rain is scaled up.
- **Season definitions differ.** The district rainfall file uses rabi = Oct to Feb; `weather.py` uses
  rabi = Nov to Mar. For wheat, `season_rain_mm` in the North India table (Oct to Feb) misses March rain,
  so do not compare it directly with `seasons.csv` from the weather pipeline.
