"""Which free rain source should the calculator trust for rain already fallen? (1 November 2026)

For every district and wheat season in the 10-state pull (27 districts, sowings in November 2021
and November 2022), run the advice rule (first watering at crown root initiation, then the FAO-56
trigger) four times with the same soil and ET0 (Open-Meteo), changing only the rain:
    imd    IMD gridded rain (the reference: the best estimate we have, but itself a grid estimate,
           and released months late, so it cannot be used live)
    om     Open-Meteo
    pw     NASA POWER
    omadj  Open-Meteo scaled by that district's IMD/Open-Meteo rain ratio from the OTHER season
           (so the correction is never fitted on the season it is tested on)
Each run's watering dates are compared with the IMD run (3-day tolerance, as elsewhere).

    python scripts/check_weather_sources.py --daily data_10states/processed/daily_weather.csv

Writes data/checks/rain_source_vs_imd.csv (one row per district, season and source),
data/checks/rain_source_vs_imd_summary.csv and data/checks/rain_totals_by_source.csv.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import irrigation_eval as ev  # noqa: E402

ROOT = os.path.join(HERE, "..")
SEASONS = (2021, 2022)          # sowing years with a full season in the 2021-2023 pull
RATIO_LIMITS = (0.25, 2.0)      # keep a correction from a near-dry season within reason


def rabi_year(d):
    return d.year if d.month >= 11 else (d.year - 1 if d.month <= 4 else None)


def season_totals(daily):
    d = daily.assign(ry=daily["date"].map(rabi_year)).dropna(subset=["ry"])
    t = d.groupby(["name", "ry"])[["rain_om", "rain_pw", "rain_imd"]].sum().reset_index()
    return t.rename(columns={"ry": "season"}).astype({"season": int})


def run(daily, locations, soil, seasons=SEASONS, tol_days=3):
    tot = season_totals(daily).set_index(["name", "season"])
    rows = []
    for name, loc in locations.iterrows():
        zone, state = loc["zone"], loc["state"]
        awc = float(soil.loc[name, "awc_mm_per_m"])
        for yr in seasons:
            m, d = ev.zone_sowing(zone)
            sowing = pd.Timestamp(yr, m, d)
            others = [y for y in seasons if y != yr]
            o = tot.loc[[(name, y) for y in others]].sum()
            ratio = o["rain_imd"] / o["rain_om"] if o["rain_om"] > 0 else 1.0
            ratio = min(max(ratio, RATIO_LIMITS[0]), RATIO_LIMITS[1])
            dd = daily.assign(rain_omadj=daily["rain_om"] * ratio)
            dates = {}
            for src in ("imd", "om", "pw", "omadj"):
                _, s = ev.run_one(dd, name, awc, sowing, "first_then_fao", rain_src=src,
                                  zone=zone, state=state)
                dates[src] = s["irrigation_dates"].split(";") if s["irrigation_dates"] else []
            for src in ("om", "pw", "omadj"):
                c = ev.compare_events(dates["imd"], dates[src], tol_days)
                rows.append({"name": name, "state": state, "season": f"{yr}-{yr + 1 - 2000}",
                             "source": src, "omadj_ratio": round(ratio, 2),
                             "dates_imd": ";".join(dates["imd"]), "dates_source": ";".join(dates[src]),
                             **c})
    return pd.DataFrame(rows)


def summary(res):
    g = res.groupby("source")
    out = pd.DataFrame({
        "district_seasons": g.size(),
        "share_waterings_differ_from_imd": g["share_events_differ"].mean().round(3),
        "share_seasons_count_differs": g["count_diff"].apply(lambda s: (s != 0).mean()).round(2),
        "mean_abs_shift_days_matched": g["mean_abs_shift_days"].mean().round(2)})
    piv = res.pivot_table(index=["name", "season"], columns="source", values="share_events_differ")
    for src in ("pw", "omadj"):
        out.loc[src, "closer_than_om"] = int((piv[src] < piv["om"]).sum())
        out.loc[src, "same_as_om"] = int((piv[src] == piv["om"]).sum())
        out.loc[src, "further_than_om"] = int((piv[src] > piv["om"]).sum())
    return out.reset_index()


def main():
    ap = argparse.ArgumentParser(description="Rain sources against IMD, through the advice rule")
    ap.add_argument("--daily", required=True, help="daily_weather.csv from the 10-state pull")
    ap.add_argument("--locations", default=os.path.join(ROOT, "data", "locations_wheat_10states.csv"))
    ap.add_argument("--soil", default=os.path.join(ROOT, "data", "soil_awc.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "checks"))
    a = ap.parse_args()
    daily = pd.read_csv(a.daily, parse_dates=["date"])
    loc = pd.read_csv(a.locations).set_index("name")
    soil = pd.read_csv(a.soil).set_index("name")
    res = run(daily, loc, soil)
    tot = season_totals(daily)
    tot = tot[tot["season"].isin(SEASONS)]
    tot = tot.assign(om_over_imd=(tot["rain_om"] / tot["rain_imd"]).round(2),
                     pw_over_imd=(tot["rain_pw"] / tot["rain_imd"]).round(2))
    os.makedirs(a.out, exist_ok=True)
    res.to_csv(os.path.join(a.out, "rain_source_vs_imd.csv"), index=False)
    s = summary(res)
    s.to_csv(os.path.join(a.out, "rain_source_vs_imd_summary.csv"), index=False)
    tot.round(1).to_csv(os.path.join(a.out, "rain_totals_by_source.csv"), index=False)
    print(s.to_string(index=False))
    print("\nNovember-April rain, median ratio to IMD: Open-Meteo "
          f"{tot['om_over_imd'].median():.2f}, NASA POWER {tot['pw_over_imd'].median():.2f}")


if __name__ == "__main__":
    main()
