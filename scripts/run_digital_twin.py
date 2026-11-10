"""Digital twin: test the irrigation advice over past seasons with AquaCrop.

    python scripts/run_digital_twin.py --district Hisar --crop wheat --years 2021 2022
    python scripts/run_digital_twin.py --district Bathinda --crop wheat --years 2005-2024 --live

Without --live it uses the committed 2021-2023 weather (data/reference/daily_weather_2021_2023.csv;
seasons sown in 2021 and 2022 are complete). With --live it downloads Open-Meteo history
(temperatures, ET0, rain) for any years from 1981, which needs the internet (run on your PC).
--rain picks the rain record for the committed weather: imd (default, the gauge-based reference),
pw (NASA POWER) or om (Open-Meteo).

For each season: the calculator's advice, the guidance calendar (wheat), no irrigation and
frequent irrigation, as a share of the best yield and the water used. See src/cropadvisor/twin.py
for the limits (AquaCrop is not calibrated for Indian varieties: compare strategies, not yields).
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import irrigation_eval as ev  # noqa: E402
from cropadvisor import openmeteo, sites, twin  # noqa: E402
from cropadvisor import crops as cr  # noqa: E402


def years_arg(vals):
    out = []
    for v in vals:
        if "-" in v:
            a, b = v.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(v))
    return out


def sowing_for(crop, zone, year):
    if crop == "wheat":
        m, d = ev.zone_sowing(zone)
    else:
        m, d = cr.get(crop).default_sowing
    return pd.Timestamp(year, m, d)


def live_weather(lat, lon, start, end):
    h = openmeteo.fetch_history(lat, lon, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    return pd.DataFrame({"date": h["date"], "tmax": h["tmax"], "tmin": h["tmin"],
                         "rain_mm": h["rain_mm"], "et0_mm": h["et0_openmeteo_mm"]})


def main():
    ap = argparse.ArgumentParser(description="Test the irrigation advice over past seasons")
    ap.add_argument("--district", required=True)
    ap.add_argument("--crop", default="wheat", choices=list(twin.AQUACROP_CROPS))
    ap.add_argument("--years", nargs="+", default=["2021", "2022"], help="sowing years, e.g. 2021 2022 or 2005-2024")
    ap.add_argument("--rain", choices=["imd", "pw", "om"], default="imd")
    ap.add_argument("--live", action="store_true", help="download Open-Meteo history (internet)")
    ap.add_argument("--out", help="save all results to this CSV")
    ap.add_argument("--lang", choices=["en", "hi"], default="en")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    row = sites.district_row(a.district)
    if a.crop != "wheat" and row["state"] not in cr.STATES:
        sys.exit(f"{a.crop} is set up for Punjab and Haryana only.")
    soil = pd.read_csv(os.path.join(HERE, "..", "data", "soil_awc.csv")).set_index("name")
    awc, texture = float(soil.loc[row["name"], "awc_mm_per_m"]), soil.loc[row["name"], "texture"]
    if not a.live:
        w = twin.load_weather()
        w = w[w["name"] == row["name"]].rename(columns={f"rain_{a.rain}_mm": "rain_mm"})
    results = []
    for yr in years_arg(a.years):
        sowing = sowing_for(a.crop, row["zone"], yr)
        need_end = sowing + pd.Timedelta(days=twin.season_days(a.crop, row["zone"]) + 45)
        ww = live_weather(row["lat"], row["lon"], sowing, need_end) if a.live else w
        if ww["date"].max() < need_end - pd.Timedelta(days=45):
            print(f"{yr}: weather does not cover the season (use --live for other years)")
            continue
        df = twin.compare_strategies(a.crop, row["name"], sowing, ww, awc, texture, row["zone"],
                                     row["state"])
        results.append(df)
        en, hi = twin.text(df)
        print(f"\n{row['name']}, {a.crop}, sown {sowing:%d %b %Y}:")
        print("\n".join(en if a.lang == "en" else hi))
    if a.out and results:
        pd.concat(results).to_csv(a.out, index=False)
        print(f"\nSaved {a.out}")


if __name__ == "__main__":
    main()
