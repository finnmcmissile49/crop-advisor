# Builds notebooks/01_weather_pipeline.ipynb from the same source modules, so the notebook
# and the repo code can never drift apart. Run from the repo root: python tools/build_notebook.py
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = root / "src" / "cropadvisor"


def module_text(name):
    text = (src / name).read_text()
    lines = [l for l in text.splitlines() if not l.startswith("from cropadvisor")]
    return "\n".join(lines).strip() + "\n"


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": s.strip("\n").splitlines(True)}


cells = [
    md("""
# 01: Weather data pipeline

Steps 1 to 4 of Module 1. Run the cells top to bottom. Every cell is self-contained, so this
notebook works in Google Colab with no repository checkout.

What you get at the end:
- a locations table (step 1)
- daily weather history from Open-Meteo and NASA POWER (steps 2 and 3)
- a forecast (step 4)
- a comparison of the two history sources, and an ET0 check against Open-Meteo
"""),
    code("""
# Install anything Colab might be missing (usually nothing)
!pip -q install requests pandas numpy matplotlib
"""),
    md("## Step 1: Locations"),
    code("""
import io
import pandas as pd

LOCATIONS_CSV = '''name,state,lat,lon,elevation_m
Latur,Maharashtra,18.4088,76.5604,636
Nagpur,Maharashtra,21.1458,79.0882,310
Pune,Maharashtra,18.5204,73.8567,560
Solapur,Maharashtra,17.6599,75.9064,458
Delhi,Delhi,28.6139,77.2090,216
'''
locations = pd.read_csv(io.StringIO(LOCATIONS_CSV)).set_index('name')
locations
"""),
    md("## Helpers (HTTP, Open-Meteo, NASA POWER, ET0)"),
    code(module_text("common.py")),
    code(module_text("et0.py")),
    code("import pandas as pd  # used by the modules below\n" + module_text("openmeteo.py")),
    code(module_text("nasapower.py").replace("def fetch_history", "def fetch_history_power")
         .replace("POWER_URL", "POWER_URL")),
    md("""
## Steps 2 and 3: One test case, both sources

Soybean in Latur, kharif season 2023 (1 June to 31 October). One district and one season keeps
everything checkable. Raw responses are saved to `data/raw/` so you never re-download them.
"""),
    code("""
city = 'Latur'
lat, lon, elev = locations.loc[city, ['lat', 'lon', 'elevation_m']]
start, end = '2023-06-01', '2023-10-31'

om = fetch_history(lat, lon, start, end, raw_path=f'data/raw/openmeteo_{city}_{start}_{end}.json')
pw = fetch_history_power(lat, lon, start, end, raw_path=f'data/raw/nasapower_{city}_{start}_{end}.json')

import os
os.makedirs('data/processed', exist_ok=True)
om.to_csv(f'data/processed/openmeteo_{city}_2023_kharif.csv', index=False)
pw.to_csv(f'data/processed/nasapower_{city}_2023_kharif.csv', index=False)
print(len(om), 'Open-Meteo days;', len(pw), 'NASA POWER days')
om.head()
"""),
    md("""
## Compare the two sources

Where the free sources disagree at the same point is early evidence for the project's research question.
"""),
    code("""
import matplotlib.pyplot as plt

m = om.merge(pw, on='date', suffixes=('_om', '_pw'))
print('Total rain (mm):  Open-Meteo %.0f   NASA POWER %.0f' % (m.rain_mm_om.sum(), m.rain_mm_pw.sum()))
print('Mean Tmax (C):    Open-Meteo %.1f   NASA POWER %.1f' % (m.tmax_om.mean(), m.tmax_pw.mean()))
print('Daily rain correlation: %.2f' % m.rain_mm_om.corr(m.rain_mm_pw))

fig, ax = plt.subplots(1, 2, figsize=(12, 4))
ax[0].plot(m.date, m.rain_mm_om.cumsum(), label='Open-Meteo')
ax[0].plot(m.date, m.rain_mm_pw.cumsum(), label='NASA POWER')
ax[0].set_title(f'{city}: cumulative rain (mm)'); ax[0].legend()
ax[1].plot(m.date, m.tmax_om, label='Open-Meteo')
ax[1].plot(m.date, m.tmax_pw, label='NASA POWER')
ax[1].set_title(f'{city}: daily max temperature (C)'); ax[1].legend()
plt.tight_layout(); plt.show()
"""),
    md("""
## ET0 check

Compute FAO-56 ET0 ourselves from the raw weather variables and compare with the value Open-Meteo
publishes. If they agree closely, the calculation can be trusted as the base of the water-balance engine.
"""),
    code("""
mine = add_et0(om, lat, elev)
d = mine.dropna(subset=['et0_calc_mm', 'et0_openmeteo_mm'])
err = d.et0_calc_mm - d.et0_openmeteo_mm
print('Mean ET0  mine: %.2f   Open-Meteo: %.2f  (mm/day)' % (d.et0_calc_mm.mean(), d.et0_openmeteo_mm.mean()))
print('Mean error %.2f mm/day,  RMSE %.2f mm/day,  correlation %.2f' % (err.mean(), (err**2).mean()**0.5, d.et0_calc_mm.corr(d.et0_openmeteo_mm)))
plt.figure(figsize=(5, 5))
plt.scatter(d.et0_openmeteo_mm, d.et0_calc_mm, s=8)
lim = [0, max(d.et0_openmeteo_mm.max(), d.et0_calc_mm.max()) + 0.5]
plt.plot(lim, lim, 'k--'); plt.xlim(lim); plt.ylim(lim)
plt.xlabel('Open-Meteo ET0 (mm/day)'); plt.ylabel('My ET0 (mm/day)'); plt.show()
"""),
    md("""
## Step 4: Forecast

Next 7 days for the same location, plus the last 3 days for context. The in-season engine will use
this for decisions like "rain is coming, do not irrigate today".
"""),
    code("""
fc = fetch_forecast(lat, lon, days=7, past_days=3, raw_path=f'data/raw/openmeteo_forecast_{city}.json')
fc[['date', 'tmax', 'tmin', 'rain_mm', 'et0_openmeteo_mm']]
"""),
    md("""
## What next

Step 5 onwards: IMD gridded rainfall, soil from SoilGrids, then the FAO-56 water balance for the soybean season.
"""),
]

nb = {"cells": cells, "metadata": {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
    "colab": {"provenance": []}}, "nbformat": 4, "nbformat_minor": 5}

out = root / "notebooks" / "01_weather_pipeline.ipynb"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(nb, indent=1))
print("wrote", out)
