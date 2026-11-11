"""Rebuild data/reference/district_temperature_periods.csv from NASA POWER (needs internet).

    python scripts/fetch_temperature_periods.py

For each of the 45 Haryana and Punjab districts (the town in data/reference/district_points.csv)
this downloads the daily maximum temperature, 1 January 1991 to 31 March 2024, and writes the mean
of each period of the season model (rabi: Oct-Nov, Dec-Jan, Feb-Mar; kharif: Jun-Jul, Aug-Sep,
Oct) for the seasons that start in 2009 to 2023, plus each period's 1991-2008 mean ("normal").

NASA POWER's temperature is on a grid of about 0.5 x 0.625 degrees, so neighbouring districts can
share a cell and get the same numbers (32 different cells for the 45 districts).

The file in the repository was made on 11 November 2026 with the same calculation run in a web
browser (this workspace could not reach NASA POWER); running this script should reproduce it to
within rounding. The season model does not use temperature at present (it was tested and did not
lower the validation error), so this file only feeds scripts/check_season_model.py.
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from cropadvisor.common import http_get_json  # noqa: E402

REF = os.path.join(HERE, "..", "data", "reference")
URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PERIODS = [("rabi", 1, "Oct-Nov", (0, 10), (0, 11)), ("rabi", 2, "Dec-Jan", (0, 12), (1, 1)),
           ("rabi", 3, "Feb-Mar", (1, 2), (1, 3)), ("kharif", 1, "Jun-Jul", (0, 6), (0, 7)),
           ("kharif", 2, "Aug-Sep", (0, 8), (0, 9)), ("kharif", 3, "Oct", (0, 10), (0, 10))]


def period_mean(series, year, start, end):
    lo = pd.Timestamp(year + start[0], start[1], 1)
    hi = pd.Timestamp(year + end[0], end[1], 1) + pd.offsets.MonthEnd(0)
    days = pd.date_range(lo, hi)
    v = series.reindex(days).dropna()
    return float(v.mean()) if len(v) >= 0.9 * len(days) else None


def main():
    points = pd.read_csv(os.path.join(REF, "district_points.csv"))
    rows = []
    for p in points.itertuples():
        data = http_get_json(URL, {"parameters": "T2M_MAX", "community": "AG",
                                   "longitude": p.lon, "latitude": p.lat, "start": "19910101",
                                   "end": "20240331", "format": "JSON"}, timeout=120)
        raw = data["properties"]["parameter"]["T2M_MAX"]
        s = pd.Series({pd.Timestamp(k): v for k, v in raw.items() if v > -900})
        for season, i, months, start, end in PERIODS:
            base = [period_mean(s, y, start, end) for y in range(1991, 2009)]
            base = [b for b in base if b is not None]
            rows.append([p.district, p.state, season, i, months, "normal_1991_2008",
                         round(sum(base) / len(base), 1)])
            for y in range(2009, 2024):
                m = period_mean(s, y, start, end)
                if m is not None:
                    rows.append([p.district, p.state, season, i, months, y, round(m, 1)])
        print(p.district, "done")
    out = pd.DataFrame(rows, columns=["district", "state", "season", "period", "months", "year",
                                      "tmax_mean_c"])
    out.to_csv(os.path.join(REF, "district_temperature_periods.csv"), index=False)
    print(f"wrote {len(out)} rows")


if __name__ == "__main__":
    main()
