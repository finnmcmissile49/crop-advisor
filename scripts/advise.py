"""Irrigation calculator: when should this field be watered next?

    python scripts/advise.py --district Hisar --sowing 2026-11-10
    python scripts/advise.py --district Hisar --sowing 2026-11-10 --watered 2026-12-08 2027-01-10
    python scripts/advise.py --crop mustard --district Bathinda --sowing 2026-10-25
    python scripts/advise.py --list          (districts)
    python scripts/advise.py --crops         (crops and their sowing times)

Wheat works in all 27 districts. The other crops follow PAU's guidance and work in the Punjab and
Haryana districts.

Test on a past season (the weather after --today is what was actually recorded):
    python scripts/advise.py --district Hisar --sowing 2025-11-10 --watered 2025-12-08 --today 2026-01-05

Needs internet (Open-Meteo) and the soil file from the 10-state data pull. Advice is for a
typical field in the district from public data; it has not been checked against real fields.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import advisor  # noqa: E402
from cropadvisor import crops as cr  # noqa: E402

DEFAULT_LOCATIONS = os.path.join(HERE, "..", "data", "locations_wheat_10states.csv")
DEFAULT_SOIL = os.path.join(HERE, "..", "data_10states", "processed", "soil.csv")
# Committed with the repo, so the calculator runs from a fresh copy for these six districts
FALLBACK_SOIL = os.path.join(HERE, "..", "data", "soil_awc_pilot.csv")


def load_site(name, locations, soil_csv):
    loc = pd.read_csv(locations)
    match = loc[loc["name"].str.lower() == name.strip().lower()]
    if match.empty:
        raise advisor.AdviceError(f"'{name}' is not one of the {len(loc)} districts set up. "
                                  "Run with --list to see them.")
    row = match.iloc[0]
    soil = None
    for path in (soil_csv, FALLBACK_SOIL):
        if os.path.exists(path):
            s = pd.read_csv(path).set_index("name")
            if row["name"] in s.index and not pd.isna(s.loc[row["name"], "awc_mm_per_m"]):
                soil = s
                break
    if soil is None:
        raise advisor.AdviceError(f"No soil data for {row['name']}. Run the 10-state data pull "
                                  "first (see README).")
    return advisor.Site(name=row["name"], state=row["state"], zone=row["zone"],
                        awc_mm_per_m=float(soil.loc[row["name"], "awc_mm_per_m"]),
                        lat=float(row["lat"]), lon=float(row["lon"]))


def main():
    ap = argparse.ArgumentParser(description="When should this wheat field be watered next?")
    ap.add_argument("--crop", default="wheat", choices=["wheat"] + list(cr.CROPS),
                    help="crop (default wheat; see --crops)")
    ap.add_argument("--district", help="district name, e.g. Hisar (see --list)")
    ap.add_argument("--sowing", help="sowing date, YYYY-MM-DD")
    ap.add_argument("--watered", nargs="*", default=[],
                    help="dates already irrigated after sowing, YYYY-MM-DD (not the pre-sowing one)")
    ap.add_argument("--today", default=None, help="pretend today is this date (testing on past seasons)")
    ap.add_argument("--depth-cm", type=float, default=None,
                    help="water given per irrigation in cm (wheat default 7.5 Punjab, 7 "
                         "elsewhere; other crops: each watering refills the root zone)")
    ap.add_argument("--lang", choices=["both", "en", "hi"], default="both")
    ap.add_argument("--locations", default=DEFAULT_LOCATIONS)
    ap.add_argument("--soil", default=DEFAULT_SOIL)
    ap.add_argument("--list", action="store_true", help="list the districts that are set up")
    ap.add_argument("--crops", action="store_true", help="list the crops and their sowing times")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Hindi in the Windows terminal

    if a.crops:
        print("wheat: Wheat (all 27 districts; sowing 15 October to 15 January)")
        for k, sp in cr.CROPS.items():
            (m1, d1), (m2, d2) = sp.sowing_window
            lo, hi = pd.Timestamp(2001, m1, d1), pd.Timestamp(2001, m2, d2)
            flag = " [lower confidence]" if sp.confidence != "normal" else ""
            print(f"{k}: {sp.en}, {sp.season_en}; PAU sowing {lo:%d %b} to {hi:%d %b}; "
                  f"Punjab and Haryana{flag}")
        return
    if a.list:
        loc = pd.read_csv(a.locations)
        for state, g in loc.groupby("state"):
            print(f"{state}: {', '.join(g['name'])}")
        return
    if not a.district or not a.sowing:
        ap.error("--district and --sowing are needed (or --list)")

    try:
        site = load_site(a.district, a.locations, a.soil)
        sowing = pd.Timestamp(a.sowing)
        today = pd.Timestamp(a.today) if a.today else pd.Timestamp.today().normalize()
        if a.crop == "wheat":
            advisor.check_inputs(site, sowing, today, a.watered)
        else:
            advisor.check_crop_inputs(cr.get(a.crop), site, sowing, today, a.watered)
        weather, mode = advisor.get_weather(site.lat, site.lon, sowing, today)
        result = advisor.advise(site, sowing, today, a.watered, weather,
                                depth_mm=a.depth_cm * 10 if a.depth_cm else None, mode=mode,
                                crop=a.crop)
        en, hi = advisor.render(result)
    except advisor.AdviceError as e:
        en, hi = advisor.i_do_not_know(str(e))
    except ValueError as e:   # bad date format and similar
        en, hi = advisor.i_do_not_know(f"could not read the input ({e}).")
    except Exception as e:  # network or service errors: say so plainly
        en, hi = advisor.i_do_not_know(f"could not get the weather data ({str(e)[:150]}). "
                                       "Check the internet connection and try again.")
    if a.lang in ("both", "en"):
        print(en)
    if a.lang in ("both", "hi"):
        print()
        print(hi)


if __name__ == "__main__":
    main()
