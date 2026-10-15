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
| DES / UPAg crop statistics | `yields.py` | district area, production, yield | district | about 1997 to 2023 | manual download | yearly |

## Known problems

- **Open-Meteo and NASA POWER are models, not measurements.** For Latur kharif 2023 they
  differ by 88 mm of season rain (623 vs 535 mm) and their daily rain correlates only 0.71.
  IMD, built from rain gauges, is the closest to ground truth among the free sources.
- **IMD** files arrive months after the year ends, and its server is slow. Cells with no data
  (sea, outside India) are -999 and become blank. Files are cached and never re-downloaded.
- **NASA POWER** uses -999 for missing values; these become blank.
- **SoilGrids** is a 250 m model estimate. Black cotton soils (Vertisols) near 50 to 60 percent
  clay sit at the edge of the Saxton-Rawls equations used for field capacity and wilting point;
  rows above 60 percent clay are flagged. The service is sometimes offline; failed locations are
  recorded and the rest continue.
- **Mandi prices**: commodity and market names are inconsistent across years and need mapping.
  The API resource only holds recent days; older history comes from Agmarknet report downloads.
- **Yields**: the IRIS dataset found the whole of 2007 at about 1/100 scale for area. Any new yield
  file is run through `yields.year_scale_flags()` before use, and kept in its own labelled file.

## Licences

Open-Meteo: CC BY 4.0, free for non-commercial use. NASA POWER: public, cite NASA LaRC POWER.
IMD gridded data: free for research, cite Pai et al. (2014). SoilGrids: CC BY 4.0, cite Poggio
et al. (2021). data.gov.in: Government Open Data Licence India.
