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
| 5 | IMD gridded rainfall | done |
| 6 | SoilGrids soil + water-holding capacity | done |
| 7 | Mandi prices | code ready, needs a free data.gov.in API key |
| 8 | District yields | code ready, needs a manual DES/UPAg download |
| 9 | Merge, season features, quality checks | done |
| 10 | One-command refresh, pull log, source notes | done |

First findings (Latur, kharif 2023): Open-Meteo and NASA POWER disagree by 88 mm of season rain
(623 vs 535 mm). Our FAO-56 ET0 matches Open-Meteo's to within 0.03 mm/day on average
(RMSE 0.19 mm/day).

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

Outputs land in `data/processed/`: `daily_weather.csv`, `seasons.csv`, `soil.csv`,
`qc_report.csv`, `pull_log.csv`. Raw API responses are kept in `data/raw/` (not committed).

## Data hygiene

Raw responses are saved before any cleaning, so nothing is downloaded twice. The IRIS yield
dataset is never modified: new years go in separate files with a `source` column, and combining
reports conflicts instead of overwriting.
