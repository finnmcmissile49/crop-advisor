"""Independent check: oven-dried soil samples against the station's sensors, the water balance and
the Kalman estimate.

    python scripts/check_soil_samples.py --samples samples.csv
    python scripts/check_soil_samples.py --samples samples.csv --station readings.csv \\
        --district Hisar --sowing 2026-11-10 --watered 2026-12-08 2027-01-10

Sample sheet: data/templates/soil_samples.csv (date, depth, tin, wet and dry weights, bulk
density). With --station only, the sensors are compared. With --district and --sowing as well, the
water balance and the fused estimate are compared too (needs the internet for the weather, like
the calculator). Results are bias and RMSE in m3/m3 with the number of samples: with one field and
one season they are case studies, not accuracy figures.
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor import advisor, fusion, groundtruth, sites, station  # noqa: E402
from cropadvisor import irrigation as ir  # noqa: E402
from cropadvisor import crops as cr  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Oven-dried samples against sensors and models")
    ap.add_argument("--samples", required=True)
    ap.add_argument("--station")
    ap.add_argument("--district")
    ap.add_argument("--sowing")
    ap.add_argument("--watered", nargs="*", default=[])
    ap.add_argument("--crop", default="wheat")
    ap.add_argument("--depth-cm", type=float)
    a = ap.parse_args()
    soil = sites.district_soil(a.district) if a.district else None
    samples = groundtruth.load_samples(a.samples, (soil or {}).get("bulk_density_g_cm3"))
    bad = samples[samples["problem"] != ""]
    if len(bad):
        print(f"{len(bad)} sample rows skipped (check the weights and date): rows "
              f"{', '.join(str(i + 2) for i in bad.index)}")
    print(samples[["date", "depth_cm", "theta_g", "theta_v", "bulk_density_source"]]
          .round(3).to_string(index=False))
    readings = station.prepare(a.station)[0] if a.station else None
    fused, awc, fc = None, None, None
    if a.district and a.sowing:
        site, _ = sites.build_site(a.district)
        last = samples["date"].max() + pd.Timedelta(days=1)
        weather, _ = advisor.get_weather(site.lat, site.lon, a.sowing, last)
        awc = advisor.soil_cases(site)["likely"]
        fc = soil["field_capacity"]
        if a.crop == "wheat":
            params = ir.zone_params(site.zone, awc, state=site.state)
            depth = (a.depth_cm or 0) * 10 or ir.first_watering(site.state, a.sowing)[3]
        else:
            params, depth = cr.get(a.crop).params(awc), (a.depth_cm * 10 if a.depth_cm else None)
        fused, _ = fusion.run(weather, a.sowing, last, params, a.watered, depth, readings, fc)
    res = groundtruth.compare(samples, readings, fused, fc, awc)
    print("\nAgainst the oven-dried samples (m3/m3; bias = estimate minus sample):")
    print(res.to_string(index=False) if len(res) else "nothing to compare (no matching dates)")


if __name__ == "__main__":
    main()
