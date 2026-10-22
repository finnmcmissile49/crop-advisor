"""Run the public-data irrigation baseline for rabi wheat on the pipeline's output.

    python scripts/run_irrigation_baseline.py --processed data_north_india/processed --years 2021 2022

Reads daily_weather.csv and soil.csv (never modifies them). Writes, into --out (default: the
processed folder):
  irrigation_runs.csv          one row per district, season, rule and rain source
  irrigation_compare.csv       how often advice differs: Open-Meteo or NASA POWER rain vs IMD, and
                               the PAU calendar vs the FAO trigger
  irrigation_stress.csv        every stress-test scenario for every district-season (FAO rule)
  irrigation_stress_summary.csv  the same, summarised per scenario
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cropadvisor import irrigation_eval as ev  # noqa: E402

RULES = ("fao_trigger", "pau_calendar")
RAIN = ("imd", "om", "pw")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", required=True)
    ap.add_argument("--years", type=int, nargs="+", required=True,
                    help="sowing years; a season must end inside the weather data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tol-days", type=int, default=3,
                    help="irrigation dates closer than this count as the same decision")
    a = ap.parse_args()
    out = a.out or a.processed
    os.makedirs(out, exist_ok=True)

    daily = pd.read_csv(os.path.join(a.processed, "daily_weather.csv"), parse_dates=["date"])
    soil = pd.read_csv(os.path.join(a.processed, "soil.csv")).set_index("name")
    if "error" in soil:
        bad = soil[soil["error"].notna()]
        if len(bad):
            print("No soil data, skipped:", ", ".join(bad.index))
        soil = soil[soil["error"].isna()]

    m, d = ev.DEFAULT_SOWING
    runs, compare = [], []
    for name in soil.index:
        awc = float(soil.loc[name, "awc_mm_per_m"])
        for yr in a.years:
            sowing = pd.Timestamp(yr, m, d)
            season = f"{yr}-{yr + 1 - 2000}"
            dates = {}
            for rule in RULES:
                for rain in RAIN:
                    _, s = ev.run_one(daily, name, awc, sowing, rule, rain_src=rain)
                    runs.append({"name": name, "season": season, "sowing": sowing.date(),
                                 "rule": rule, "rain_src": rain, "awc_mm_per_m": awc, **s})
                    dates[rule, rain] = s["irrigation_dates"].split(";") if s["irrigation_dates"] else []
            for rule in RULES:
                for rain in ("om", "pw"):
                    c = ev.compare_events(dates[rule, "imd"], dates[rule, rain], a.tol_days)
                    compare.append({"name": name, "season": season, "comparison":
                                    f"{rule}: rain_{rain} vs rain_imd", **c})
            for rain in RAIN:
                c = ev.compare_events(dates["fao_trigger", rain], dates["pau_calendar", rain],
                                      a.tol_days)
                compare.append({"name": name, "season": season,
                                "comparison": f"pau_calendar vs fao_trigger (rain_{rain})", **c})

    runs, compare = pd.DataFrame(runs), pd.DataFrame(compare)
    stress = ev.stress_test(daily, soil, a.years, "fao_trigger", tol_days=a.tol_days)
    summary = ev.scenario_table(stress)

    runs.to_csv(os.path.join(out, "irrigation_runs.csv"), index=False)
    compare.to_csv(os.path.join(out, "irrigation_compare.csv"), index=False)
    stress.to_csv(os.path.join(out, "irrigation_stress.csv"), index=False)
    summary.to_csv(os.path.join(out, "irrigation_stress_summary.csv"))

    pd.set_option("display.width", 200)
    print(f"{runs[['name', 'season']].drop_duplicates().shape[0]} district-seasons, "
          f"sowing {m}/{d}, tolerance {a.tol_days} days\n")
    print(runs.groupby(["rule", "rain_src"])[["n_irrigations", "irrigation_mm", "stress_days",
                                               "deep_percolation_mm"]].mean().round(1))
    print()
    print(compare.groupby("comparison")[["count_diff", "share_events_differ",
                                         "mean_abs_shift_days"]].mean().round(2))
    print()
    print(summary)
    worst = runs["closure_error_mm"].abs().max()
    print(f"\nLargest water-balance closure error: {worst:.2e} mm")


if __name__ == "__main__":
    main()
