"""Refresh the Soil Health Card table after a new download from the nutrient dashboard.

The dashboard (soilhealth.dac.gov.in, nutrient dashboard) publishes district results once a cycle;
it has no documented API, so a new cycle means saving its district records as JSON again (same
format as 01_raw_data/soil_health_card/shc_district_nutrient_status_raw.json). Then run:

    python scripts/refresh_soil_health_card.py --agri-dir "C:/Users/Aviral/OneDrive/Desktop/agri-project"

    optional: --raw path/to/new_download.json   (default: the raw file in the agri folder)

What it does:
1. parses the raw records (soilcard.parse_dashboard; checked to give the same counts as the
   current processed file, 2,758 district-cycles);
2. writes 03_processed_data/shc_district_nutrient_status_<first>_<last>.csv in the agri folder,
   keeping the old file as .bak if the name is the same;
3. rebuilds data/reference/soil_health_card.csv with the same rules as build_reference_tables.py.
"""
import argparse
import json
import os
import shutil
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

from cropadvisor import soilcard as sc  # noqa: E402
import build_reference_tables as brt  # noqa: E402

RAW = os.path.join("01_raw_data", "soil_health_card", "shc_district_nutrient_status_raw.json")
CURRENT = os.path.join("03_processed_data", "shc_district_nutrient_status_2023_2027.csv")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--agri-dir", required=True)
    ap.add_argument("--raw", default=None)
    a = ap.parse_args()
    raw = a.raw or os.path.join(a.agri_dir, RAW)
    with open(raw, encoding="utf-8") as f:
        records = json.load(f)
    df = sc.parse_dashboard(records)
    if df.empty:
        sys.exit("no district records in the file")
    cycles = sorted(df["cycle"].dropna().unique())
    first, last = cycles[0][:4], "20" + cycles[-1][-2:]   # cycles look like "2023-24"
    name = f"shc_district_nutrient_status_{first}_{last}.csv"
    out = os.path.join(a.agri_dir, "03_processed_data", name)
    if os.path.exists(out):
        shutil.copy(out, out + ".bak")
    df.to_csv(out, index=False)
    print(f"{name}: {len(df)} district-cycles, cycles {', '.join(cycles)}")
    if os.path.abspath(out) != os.path.abspath(os.path.join(a.agri_dir, CURRENT)):
        # build_reference_tables reads the fixed file name; point it at the new one
        cur = os.path.join(a.agri_dir, CURRENT)
        if os.path.exists(cur):
            shutil.copy(cur, cur + ".bak")
        shutil.copy(out, cur)
    ref = brt.soil_health_card(a.agri_dir, pd.read_csv(brt.LOCATIONS))
    ref.to_csv(os.path.join(brt.REF, "soil_health_card.csv"), index=False)
    print(f"data/reference/soil_health_card.csv: {len(ref)} rows")


if __name__ == "__main__":
    main()
