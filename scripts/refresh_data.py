"""Refresh all Module 1 data with one command.

    python scripts/refresh_data.py --start 2021 --end 2023
    python scripts/refresh_data.py --start 1997 --end 2023 --data-dir /content/drive/MyDrive/crop-advisor-data
    python scripts/refresh_data.py --start 2021 --end 2023 --locations data/locations_north_india.csv --data-dir data_north_india
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cropadvisor.pipeline import run  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--start", type=int, required=True)
p.add_argument("--end", type=int, required=True)
p.add_argument("--data-dir", default="data")
p.add_argument("--locations", default=None,
               help="locations CSV (default: data/locations.csv, the Maharashtra and Delhi test set)")
p.add_argument("--no-imd", action="store_true")
p.add_argument("--no-soil", action="store_true")
a = p.parse_args()

res = run(a.start, a.end, a.data_dir, locations_csv=a.locations,
          include_imd=not a.no_imd, include_soil=not a.no_soil)
print(res["log"].to_string(index=False))
print(f"\n{len(res['seasons'])} season rows, {len(res['qc'])} QC issues")
