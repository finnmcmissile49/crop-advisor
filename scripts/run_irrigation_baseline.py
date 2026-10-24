"""Run the public-data irrigation baseline for rabi wheat on the pipeline's output.

    python scripts/run_irrigation_baseline.py --processed data_10states/processed \
        --locations data/locations_wheat_10states.csv --years 2021 2022

Reads daily_weather.csv and soil.csv (never modifies them). The locations file gives each
district's state and ICAR wheat zone, which set the season length, sowing date and calendar rule
(PAU for Punjab, ICAR-IIWBR elsewhere). Without --locations every district is treated with the
Punjab pilot settings. Writes, into --out (default: the processed folder):
  irrigation_runs.csv            one row per district, season, rule and rain source
  irrigation_compare.csv         how often advice differs: other rain sources vs IMD, and the
                                 calendar rule vs the FAO trigger
  irrigation_stress.csv          every stress-test scenario for every district-season (advice rule)
  irrigation_stress_summary.csv  the same, summarised per scenario
  irrigation_by_state.csv        per-state summary
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cropadvisor import irrigation as ir  # noqa: E402
from cropadvisor import irrigation_eval as ev  # noqa: E402

RAIN = ("imd", "om", "pw")
# advice = always the first irrigation at crown root initiation, then the water balance (agreed
# 24 Oct 2026); fao_trigger = water balance only; calendar = PAU (Punjab) or ICAR-IIWBR
RULE_TYPE = {"first_then_fao": "advice", "fao_trigger": "fao_trigger"}


def load_sites(processed, locations):
    soil = pd.read_csv(os.path.join(processed, "soil.csv")).set_index("name")
    if "error" in soil:
        bad = soil[soil["error"].notna()]
        if len(bad):
            print("No soil data, skipped:", ", ".join(bad.index))
        soil = soil[soil["error"].isna()]
    sites = soil[["awc_mm_per_m"]].copy()
    if locations:
        loc = pd.read_csv(locations).set_index("name")[["state", "zone"]]
        missing = sorted(set(sites.index) - set(loc.index))
        if missing:
            raise SystemExit(f"Not in the locations file: {', '.join(missing)}")
        sites = sites.join(loc)
    else:
        sites["state"], sites["zone"] = "Punjab", "NWPZ"
    return sites


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--processed", required=True)
    ap.add_argument("--locations", default=None, help="CSV with name, state, zone")
    ap.add_argument("--years", type=int, nargs="+", required=True,
                    help="sowing years; a season must end inside the weather data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tol-days", type=int, default=3,
                    help="irrigation dates closer than this count as the same decision")
    a = ap.parse_args()
    out = a.out or a.processed
    os.makedirs(out, exist_ok=True)

    daily = pd.read_csv(os.path.join(a.processed, "daily_weather.csv"), parse_dates=["date"])
    sites = load_sites(a.processed, a.locations)

    runs, compare = [], []
    for name, site in sites.iterrows():
        awc, zone, state = float(site["awc_mm_per_m"]), site["zone"], site["state"]
        cal = ir.calendar_rule_name(state)
        m, d = ev.zone_sowing(zone)
        for yr in a.years:
            sowing = pd.Timestamp(yr, m, d)
            season = f"{yr}-{yr + 1 - 2000}"
            dates = {}
            for rule in ("first_then_fao", "fao_trigger", cal):
                for rain in RAIN:
                    _, s = ev.run_one(daily, name, awc, sowing, rule, rain_src=rain,
                                      zone=zone, state=state)
                    runs.append({"name": name, "state": state, "zone": zone, "season": season,
                                 "sowing": sowing.date(), "rule": rule, "rule_type":
                                 RULE_TYPE.get(rule, "calendar"),
                                 "rain_src": rain, "awc_mm_per_m": awc, **s})
                    dates[rule, rain] = s["irrigation_dates"].split(";") if s["irrigation_dates"] else []
            for rule in ("first_then_fao", "fao_trigger", cal):
                for rain in ("om", "pw"):
                    c = ev.compare_events(dates[rule, "imd"], dates[rule, rain], a.tol_days)
                    compare.append({"name": name, "state": state, "zone": zone, "season": season,
                                    "comparison": f"{RULE_TYPE.get(rule, 'calendar')}"
                                                  f": rain_{rain} vs rain_imd", **c})
            for rain in RAIN:
                for other in (cal, "fao_trigger"):
                    c = ev.compare_events(dates["first_then_fao", rain], dates[other, rain],
                                          a.tol_days)
                    compare.append({"name": name, "state": state, "zone": zone, "season": season,
                                    "comparison": f"{RULE_TYPE.get(other, 'calendar')} vs advice"
                                                  f" (rain_{rain})", **c})

    runs, compare = pd.DataFrame(runs), pd.DataFrame(compare)
    stress = ev.stress_test(daily, sites, a.years, "first_then_fao", tol_days=a.tol_days)
    summary = ev.scenario_table(stress)

    base = runs[runs["rain_src"] == "imd"]
    adv = base[base["rule_type"] == "advice"]
    fao, calr = base[base["rule_type"] == "fao_trigger"], base[base["rule_type"] == "calendar"]
    om = compare[compare["comparison"] == "advice: rain_om vs rain_imd"]
    g = adv.groupby("state")
    by_state = pd.DataFrame({
        "zone": g["zone"].agg(lambda z: "/".join(sorted(set(z)))),
        "districts": g["name"].nunique(),
        "district_seasons": g.size(),
        "season_rain_imd_mm": g["rain_mm"].mean().round(0),
        "crop_water_use_mm": g["etc_mm"].mean().round(0),
        "advice_irrigations_mean": g["n_irrigations"].mean().round(1),
        "advice_irrigations_min": g["n_irrigations"].min(),
        "advice_irrigations_max": g["n_irrigations"].max(),
        "advice_irrigation_mm": g["irrigation_mm"].mean().round(0),
        "advice_stress_days": g["stress_days"].mean().round(1),
        "fao_only_irrigations_mean": fao.groupby("state")["n_irrigations"].mean().round(1),
        "calendar_rule": calr.groupby("state")["rule"].first(),
        "calendar_irrigations_mean": calr.groupby("state")["n_irrigations"].mean().round(1),
        "om_vs_imd_events_differ": om.groupby("state")["share_events_differ"].mean().round(2),
        "om_vs_imd_count_changed": om.groupby("state")["count_diff"].apply(lambda s: (s != 0).mean()).round(2),
    })

    runs.to_csv(os.path.join(out, "irrigation_runs.csv"), index=False)
    compare.to_csv(os.path.join(out, "irrigation_compare.csv"), index=False)
    stress.to_csv(os.path.join(out, "irrigation_stress.csv"), index=False)
    summary.to_csv(os.path.join(out, "irrigation_stress_summary.csv"))
    by_state.to_csv(os.path.join(out, "irrigation_by_state.csv"))

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"{len(sites)} districts, {len(adv)} district-seasons, tolerance {a.tol_days} days\n")
    print(by_state.to_string())
    print()
    print(summary.to_string())
    print(f"\nLargest water-balance closure error: {runs['closure_error_mm'].abs().max():.2e} mm")


if __name__ == "__main__":
    main()
