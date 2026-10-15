# Builds notebooks/02_full_pipeline.ipynb. Unlike notebook 01, this one clones the repo and imports
# the package, so the code always comes from one place. Run from repo root.
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent


def md(s):
    return {"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)}


def code(s):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": s.strip("\n").splitlines(True)}


cells = [
    md("""
# 02: Full Module 1 pipeline

Steps 5 to 10: IMD gridded rainfall, SoilGrids soil, merged daily weather from all sources,
season summaries, data-quality checks and a pull log. Prices and yields (steps 7 and 8) have their
own section at the end because they need things only you can provide.
"""),
    code("""
# Setup: get the latest code from GitHub and install the IMD reader
!rm -rf crop-advisor && git clone -q --depth 1 https://github.com/finnmcmissile49/crop-advisor
!pip -q install imdlib
import sys, pandas as pd
sys.path.insert(0, 'crop-advisor/src')
pd.set_option('display.width', 200); pd.set_option('display.max_columns', 30)
"""),
    md("""
## Where data is saved

By default, data goes to the Colab machine and disappears when the runtime stops. Set
`USE_DRIVE = True` to keep it in your Google Drive (Colab will ask you to allow access).
"""),
    code("""
USE_DRIVE = False
if USE_DRIVE:
    from google.colab import drive
    drive.mount('/content/drive')
    DATA_DIR = '/content/drive/MyDrive/crop-advisor-data'
else:
    DATA_DIR = '/content/data'
START_YEAR, END_YEAR = 2021, 2023   # widen to 1997, 2023 once this works
print('Saving to', DATA_DIR)
"""),
    md("## Run everything (steps 5, 6, 9, 10)"),
    code("""
from cropadvisor.pipeline import run
res = run(START_YEAR, END_YEAR, DATA_DIR, locations_csv='crop-advisor/data/locations.csv')
print(res['log'][['source', 'status', 'rows', 'note']].to_string(index=False))
"""),
    md("""
## Step 5: three rainfall sources, kharif seasons

IMD is built from rain gauges, so it is the closest thing to ground truth here. Open-Meteo (ERA5)
and NASA POWER are model and satellite products.
"""),
    code("""
s = res['seasons']
k = s[s.season == 'kharif']
cols = [c for c in ['name', 'year', 'rain_total_imd', 'rain_total_om', 'rain_total_pw',
                    'rain_diff_om_imd', 'rain_diff_pw_imd', 'sources_disagree'] if c in k]
print(k[cols].to_string(index=False))
"""),
    md("## Step 6: soil (0-100 cm, SoilGrids)"),
    code("""
soil = res['soil']
cols = [c for c in ['texture', 'clay_pct', 'sand_pct', 'silt_pct', 'ph', 'soc_g_kg',
                    'bulk_density_g_cm3', 'field_capacity', 'wilting_point', 'awc_mm_per_m',
                    'clay_above_model_range', 'error'] if c in soil]
print(soil[cols].to_string())
"""),
    md("## Step 9: season features for Module 2"),
    code("""
cols = ['name', 'year', 'season', 'rain_total_om', 'rainy_days_om', 'longest_dry_spell_om',
        'tmax_mean', 'hot_days_35c', 'et0_total_om', 'water_balance_om']
print(s[cols].to_string(index=False))
"""),
    md("## Step 9: data-quality report"),
    code("""
qc = res['qc']
print('No issues found' if qc.empty else qc.to_string(index=False))
"""),
    md("""
## Steps 7 and 8: prices and yields

**Prices** need a free data.gov.in API key. Register at data.gov.in, then add the key as a Colab
secret named `DATA_GOV_IN_KEY` (key icon in the left sidebar) and turn on notebook access.
This cell skips itself until the key exists.

**Yields** have no public API. Download district crop statistics for Maharashtra from the DES /
UPAg portal as CSV, upload it here, and map its columns with `cropadvisor.yields.standardise`.
"""),
    code("""
try:
    from google.colab import userdata
    key = userdata.get('DATA_GOV_IN_KEY')
except Exception:
    key = None
if key:
    from cropadvisor.prices import fetch_prices, COMMODITIES
    p = fetch_prices(key, COMMODITIES['soybean'])
    print(len(p), 'price rows'); print(p.head().to_string())
else:
    print('No DATA_GOV_IN_KEY secret yet: skipping prices.')
"""),
]

nb = {"cells": cells, "metadata": {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"}, "colab": {"provenance": []}},
    "nbformat": 4, "nbformat_minor": 5}
out = root / "notebooks" / "02_full_pipeline.ipynb"
out.write_text(json.dumps(nb, indent=1))
print("wrote", out)
