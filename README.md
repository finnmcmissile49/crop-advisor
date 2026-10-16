# Crop Advisor

A real-time crop and irrigation advisor for smallholder farmers in Maharashtra, with an on-farm
sensor station that corrects free public weather data.

**Research question:** how much does on-farm sensing improve crop and irrigation advice compared with
public data alone, and how often does it change the farmer's decision?

## Status: Module 1 (data pipeline)

| Step | What | Status |
|---|---|---|
| 1 | Locations table | done |
| 2 | Open-Meteo weather history | done, tested live |
| 3 | NASA POWER weather history | done, tested live |
| 4 | Open-Meteo forecast | done, tested live |
| 5 | IMD gridded rainfall | done, tested live |
| 6 | SoilGrids soil + water-holding capacity | done, tested live |
| 7 | Mandi prices | key works, but data.gov.in blocks Colab; run `scripts/fetch_prices_local.py` on your own computer |
| 8 | District yields | code ready, needs a manual DES/UPAg download |
| 9 | Merge, season features, quality checks | done, tested live |
| 10 | One-command refresh, pull log, source notes | done, tested live |

## First findings (live run, 5 locations, 2021-2023)

Our FAO-56 ET0 matches Open-Meteo's to within 0.03 mm/day on average (RMSE 0.19 mm/day).

Kharif rain (June to October), in mm. IMD is built from rain gauges; the others are models.

| Location | Year | IMD | Open-Meteo | NASA POWER |
|---|---|---|---|---|
| Latur | 2023 | 582 | 623 | 535 |
| Nagpur | 2022 | 1560 | 1966 | 1619 |
| Pune | 2022 | 1071 | 1066 | 2203 |
| Pune | 2023 | 484 | 702 | 1854 |
| Solapur | 2022 | 660 | 1068 | 710 |
| Solapur | 2023 | 358 | 631 | 439 |

- **NASA POWER is unusable for Pune as is.** Its grid cell (about 55 km wide) reaches into the
  Western Ghats, so it reports 2 to 4 times IMD's rain. Checked live for kharif 2022: 2662 mm at
  73.4 E (in the Ghats), 2203 mm at Pune, 1026 mm at 74.4 E, against IMD's 1071 mm.
- **Open-Meteo overestimates rain in the Solapur rain shadow**: 62 to 76 percent above IMD in
  2022 and 2023, enough to change any irrigation decision.
- 6 of the 15 kharif seasons have at least one pair of sources more than 30 percent apart. Free
  data is least reliable exactly where water is scarcest, which is the case for an on-farm station.
- All five locations' soils come out as clay or clay loam (Maharashtra) and loam (Delhi), with
  available water 115 to 139 mm per metre of soil.

## Layout

```
data/locations.csv              test districts (lat, lon, approximate elevation)
data/SOURCES.md                 every data source, coverage, licence and known problems
src/cropadvisor/
  common.py                     HTTP helper: retries, saves raw responses, never re-downloads
  openmeteo.py, nasapower.py    weather history and forecast
  imd.py                        IMD 0.25 degree gridded rainfall
  soil.py                       SoilGrids + Saxton-Rawls field capacity / wilting point
  et0.py                        FAO-56 Penman-Monteith reference evapotranspiration
  weather.py                    merged daily table, season features, QC, source disagreement
  prices.py, yields.py          mandi prices; yield standardisation and scale checks
  pipeline.py                   runs everything, writes CSVs and the pull log
scripts/refresh_data.py         one command: refresh all data
notebooks/01_weather_pipeline   steps 1-4, self-contained walkthrough
notebooks/02_full_pipeline      steps 5-10, runs the package from this repo
tests/                          offline tests (no internet needed)
```

## Run it

In Google Colab: open `notebooks/02_full_pipeline.ipynb` via File > Open notebook > GitHub.

Locally:

```
pip install -r requirements.txt
pytest
python scripts/refresh_data.py --start 2021 --end 2023
```

A full run for 5 locations and 3 years takes about 10 minutes in Colab (most of it IMD downloads
and NASA POWER). Soil points are saved in `data/locations.csv`, so SoilGrids needs one call per
location; a new location without `soil_lat`/`soil_lon` triggers a slower outward search.

Outputs land in `data/processed/`: `daily_weather.csv`, `seasons.csv`, `soil.csv`,
`qc_report.csv`, `pull_log.csv`. Raw API responses are kept in `data/raw/` (not committed).

## Data hygiene

Raw responses are saved before any cleaning, so nothing is downloaded twice. The IRIS yield
dataset is never modified: new years go in separate files with a `source` column, and combining
reports conflicts instead of overwriting.
