"""Build the North India (Haryana, Punjab) district table from files already in 03_processed_data.

    python scripts/build_north_india_table.py --processed 03_processed_data --reference 02_reference_tables

Reads (never modifies): multistate_yield_rain_2009_2019.csv, des_apy_district_2015_2022.csv,
rainfall_district_seasons_2009_2024.csv, shc_district_nutrient_status_2023_2027.csv,
rain_districts_lgd.csv. Writes new files named north_india_*.csv next to them.
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cropadvisor import northindia as ni  # noqa: E402
from cropadvisor.yields import year_scale_flags  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", required=True, help="folder with the processed CSVs")
    ap.add_argument("--reference", required=True, help="folder with rain_districts_lgd.csv")
    ap.add_argument("--out", default=None, help="output folder (default: --processed)")
    a = ap.parse_args()
    out = a.out or a.processed
    os.makedirs(out, exist_ok=True)

    P = lambda f: os.path.join(a.processed, f)  # noqa: E731
    icr_raw = pd.read_csv(P("multistate_yield_rain_2009_2019.csv"), low_memory=False)
    des_raw = pd.read_csv(P("des_apy_district_2015_2022.csv"), low_memory=False)
    seasons = pd.read_csv(P("rainfall_district_seasons_2009_2024.csv"), low_memory=False)
    shc_raw = pd.read_csv(P("shc_district_nutrient_status_2023_2027.csv"), low_memory=False)
    lgd = pd.read_csv(os.path.join(a.reference, "rain_districts_lgd.csv"))

    icr = ni.icrisat_north_india(icr_raw)
    des = ni.des_north_india(des_raw)
    known = set(ni.DISTRICT_MAP["district"])
    for name, t in (("ICRISAT", icr), ("DES", des)):
        stray = set(t["district"]) - known
        if stray:
            raise SystemExit(f"{name}: names changed during standardising: {sorted(stray)}")
        suspicious = year_scale_flags(t.assign(season=t["season"].astype(str)))
        print(f"{name}: {len(t)} rows, years {t['year'].min()}-{t['year'].max()}, "
              f"years that look wrongly scaled: {list(suspicious.index) or 'none'}")

    summary, pairs = ni.overlap_check(icr, des)
    print("\nICRISAT vs DES where both report the same district-crop-year (2015-2019):")
    print(summary.round(3).to_string(index=False))
    summary.round(4).to_csv(os.path.join(out, "north_india_yield_source_check.csv"), index=False)

    table, conflicts = ni.stitch_yields(icr, des)
    table = table[table["yield_t_ha"].notna() | table["area_ha"].notna()]
    table = ni.rain_for_yields(table, seasons, lgd)
    table = table.sort_values(["state", "district", "crop", "year"]).reset_index(drop=True)
    table.to_csv(os.path.join(out, "north_india_yields_2009_2022.csv"), index=False)
    conflicts.to_csv(os.path.join(out, "north_india_yield_conflicts.csv"), index=False)
    print(f"\nstitched table: {len(table)} rows; {len(conflicts)} ICRISAT/DES conflicts (>5 percent)")

    shc_ni = ni.shc_north_india(shc_raw)
    keep = ["cycle", "state", "district", "n_samples"] + ni.SHC_PCT
    shc_ni[keep].round(2).to_csv(os.path.join(out, "north_india_shc_by_cycle.csv"), index=False)
    best = ni.shc_best_cycle(shc_ni)
    summary_d = ni.district_summary(table, best)
    summary_d.to_csv(os.path.join(out, "north_india_district_summary.csv"), index=False)
    ni.DISTRICT_MAP.to_csv(os.path.join(out, "north_india_district_map.csv"), index=False)
    print(f"district summary: {len(summary_d)} districts; "
          f"{int(best['shc_reliable'].sum())} have a Soil Health Card cycle with at least "
          f"{ni.SHC_MIN_SAMPLES} samples")


if __name__ == "__main__":
    main()
