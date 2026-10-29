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

Your own field and soil (both optional):
    python scripts/advise.py --district Hisar --sowing 2026-11-10 --lat 29.21 --lon 75.65 --soil-type loam

Needs internet (Open-Meteo; SoilGrids for --lat/--lon). Advice is from public data; it has not
been checked against real fields.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import advisor  # noqa: E402
from cropadvisor import crops as cr  # noqa: E402
from cropadvisor import service, sites  # noqa: E402

DEFAULT_LOCATIONS = sites.LOCATIONS
DEFAULT_SOIL = sites.SOIL_FILES[0]


def load_site(name, locations, soil_csv):
    """District site (kept for older callers and tests)."""
    site, _ = sites.build_site(name, locations=locations, soil_files=(soil_csv,) +
                               sites.SOIL_FILES[1:])
    return site


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
    ap.add_argument("--lat", type=float, help="field latitude (optional; else the district point)")
    ap.add_argument("--lon", type=float, help="field longitude")
    ap.add_argument("--soil-type", choices=list(advisor.SOIL_TYPES),
                    help="the farmer's soil: sandy, light_loam, loam or clay (optional)")
    ap.add_argument("--json", action="store_true", help="print the advice as JSON")
    ap.add_argument("--lang", choices=["both", "en", "hi"], default="both")
    ap.add_argument("--locations", default=DEFAULT_LOCATIONS)
    ap.add_argument("--soil", default=DEFAULT_SOIL)
    ap.add_argument("--list", action="store_true", help="list the districts that are set up")
    ap.add_argument("--crops", action="store_true", help="list the crops and their sowing times")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # Hindi in the Windows terminal

    if a.crops:
        print("wheat: Wheat (all 27 districts; timely sowing, up to 10 days after the zone's "
              "window)")
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

    req = {"district": a.district, "sowing": a.sowing, "watered": a.watered, "crop": a.crop,
           "today": a.today, "depth_cm": a.depth_cm, "lat": a.lat, "lon": a.lon,
           "soil_type": a.soil_type}
    res = service.advise_request(req, soil_files=(a.soil,) + sites.SOIL_FILES[1:],
                                 locations=a.locations)
    if a.json:
        import json
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    en, hi = res["text_en"], res["text_hi"]
    if a.lang in ("both", "en"):
        print(en)
    if a.lang in ("both", "hi"):
        print()
        print(hi)


if __name__ == "__main__":
    main()
