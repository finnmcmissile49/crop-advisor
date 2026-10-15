# Crop Advisor

A real-time crop and irrigation advisor for smallholder farmers in Maharashtra, with an on-farm
sensor station that corrects free public weather data.

**Research question:** how much does on-farm sensing improve crop and irrigation advice compared with
public data alone, and how often does it change the farmer's decision?

## Status

Module 1 (data pipeline), steps 1 to 4: locations table, Open-Meteo history and forecast,
NASA POWER history, and a FAO-56 Penman-Monteith ET0 check.

## Layout

```
data/locations.csv            test districts (lat, lon, approximate elevation)
src/cropadvisor/common.py     HTTP helper with retries and raw-response saving
src/cropadvisor/openmeteo.py  Open-Meteo history and forecast
src/cropadvisor/nasapower.py  NASA POWER history
src/cropadvisor/et0.py        FAO-56 Penman-Monteith reference evapotranspiration
tests/test_et0.py             checks ET0 against worked examples from FAO-56
notebooks/01_weather_pipeline.ipynb   runnable walkthrough (works in Google Colab)
```

## Run it

```
pip install -r requirements.txt
pytest                      # ET0 tests, no internet needed
```

Then open `notebooks/01_weather_pipeline.ipynb` in Google Colab (File > Open notebook > GitHub, or upload it).

## Data sources

| Source | What | Notes |
|---|---|---|
| Open-Meteo | daily weather, forecast, ET0 | no key, non-commercial use |
| NASA POWER | daily weather since 1981 | no key, lags a few days |

Elevations in `locations.csv` are approximate; replace them with surveyed values for field sites.

## Data hygiene

Raw API responses are saved to `data/raw/` before any cleaning so nothing needs re-downloading.
Keep any extended or new yield data in separate, clearly labelled files; never silently mix it with
older datasets.
