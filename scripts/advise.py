"""Wheat irrigation calculator (v0): when should this field be watered next?

    python scripts/advise.py --district Hisar --sowing 2026-11-10
    python scripts/advise.py --district Hisar --sowing 2026-11-10 --watered 2026-12-08 2027-01-10
    python scripts/advise.py --list

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

DEFAULT_LOCATIONS = os.path.join(HERE, "..", "data", "locations_wheat_10states.csv")
DEFAULT_SOIL = os.path.join(HERE, "..", "data_10states", "processed", "soil.csv")


def load_site(name, locations, soil_csv):
    loc = pd.read_csv(locations)
    match = loc[loc["name"].str.lower() == name.strip().lower()]
    if match.empty:
        raise advisor.AdviceError(f"'{name}' is not one of the {len(loc)} districts set up. "
                                  "Run with --list to see them.")
    row = match.iloc[0]
    if not os.path.exists(soil_csv):
        raise advisor.AdviceError(f"Soil file not found at {soil_csv}. Run the 10-state data "
                                  "pull first (see README).")
    soil = pd.read_csv(soil_csv).set_index("name")
    if row["name"] not in soil.index or pd.isna(soil.loc[row["name"], "awc_mm_per_m"]):
        raise advisor.AdviceError(f"No soil data for {row['name']}. Rerun the data pull.")
    return advisor.Site(name=row["name"], state=row["state"], zone=row["zone"],
                        awc_mm_per_m=float(soil.loc[row["name"], "awc_mm_per_m"]),
                        lat=float(row["lat"]), lon=float(row["lon"]))


def main():
    ap = argparse.ArgumentParser(description="When should this wheat field be watered next?")
    ap.add_argument("--district", help="district name, e.g. Hisar (see --list)")
    ap.add_argument("--sowing", help="sowing date, YYYY-MM-DD")
    ap.add_argument("--watered", nargs="*", default=[],
                    help="dates already irrigated after sowing, YYYY-MM-DD (not the pre-sowing one)")
    ap.add_argument("--today", default=None, help="pretend today is this date (testing on past seasons)")
    ap.add_argument("--depth-cm", type=float, default=None,
                    help="water given per irrigation in cm (default 7.5 Punjab, 7 elsewhere)")
    ap.add_argument("--lang", choices=["both", "en", "hi"], default="both")
    ap.add_argument("--locations", default=DEFAULT_LOCATIONS)
    ap.add_argument("--soil", default=DEFAULT_SOIL)
    ap.add_argument("--list", action="store_true", help="list the districts that are set up")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Hindi in the Windows terminal

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
        advisor.check_inputs(site, sowing, today, a.watered)
        weather, mode = advisor.get_weather(site.lat, site.lon, sowing, today)
        result = advisor.advise(site, sowing, today, a.watered, weather,
                                depth_mm=a.depth_cm * 10 if a.depth_cm else None, mode=mode)
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
