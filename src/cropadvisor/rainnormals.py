"""IMD rainfall for context in the advice: how this season's rain so far compares with normal, and
what is normal for the month after the 16-day forecast ends.

IMD's gridded and district rainfall is released months late, so it can never be today's rain.
What it can give live is the background: IMD's own district normal per month, and the 2009-2024
average of IMD's district rainfall (data/reference/imd_rain_monthly.csv, built by
scripts/build_reference_tables.py from rainfall_district_monthly_2009_2024.csv). The rain so far
that is compared with the normal comes from NASA POWER and Open-Meteo, which read above IMD in
November-April in these districts (median about 1.3 and 1.6 times IMD, data/checks), so a season can
look wetter than normal partly because of the source.
"""
import calendar
import functools
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
TABLE = os.path.join(ROOT, "data", "reference", "imd_rain_monthly.csv")


@functools.lru_cache(maxsize=1)
def _table(path=TABLE):
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def monthly(name, path=TABLE):
    """{month: (normal_mm, mean_2009_2024_mm)} for a calculator district, or None."""
    t = _table(path)
    if t is None:
        return None
    g = t[t["name"].str.lower() == str(name).lower()]
    if g.empty:
        return None
    return {int(r.month): (float(r.normal_mm), float(r.mean_2009_2024_mm)) for r in g.itertuples()}


def normal_between(name, start, end, path=TABLE):
    """IMD normal rain (mm) from start to end (inclusive), each month pro rata by days."""
    m = monthly(name, path)
    if m is None:
        return None
    total = 0.0
    for d in pd.date_range(pd.Timestamp(start), pd.Timestamp(end)):
        total += m[d.month][0] / calendar.monthrange(d.year, d.month)[1]
    return round(total, 1)


def context(name, sowing, today, rain_so_far_mm, forecast_end, path=TABLE):
    """Dict for the advice: season rain so far vs IMD normal, and next month's IMD normal."""
    m = monthly(name, path)
    if m is None:
        return None
    sowing, today = pd.Timestamp(sowing), pd.Timestamp(today)
    out = {"normal_so_far_mm": normal_between(name, sowing, today, path) if today > sowing else 0.0,
           "rain_so_far_mm": rain_so_far_mm}
    nxt = (pd.Timestamp(forecast_end) + pd.Timedelta(days=1))
    out["after_forecast_month"] = int(nxt.month)
    out["after_forecast_normal_mm"] = m[nxt.month][0]
    out["after_forecast_mean_mm"] = m[nxt.month][1]
    return out


HI_MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर",
             "अक्टूबर", "नवंबर", "दिसंबर"]


def text(c):
    """English and Hindi lines for the context dict."""
    if not c:
        return [], []
    en, hi = [], []
    if c["normal_so_far_mm"] and c["rain_so_far_mm"] is not None:
        en.append(f"Rain since sowing: about {c['rain_so_far_mm']:g} mm. IMD's normal for this "
                  f"period: about {c['normal_so_far_mm']:g} mm.")
        hi.append(f"बुवाई से अब तक बारिश: लगभग {c['rain_so_far_mm']:g} मिमी। IMD के अनुसार इस "
                  f"समय की सामान्य बारिश: लगभग {c['normal_so_far_mm']:g} मिमी।")
    mon = calendar.month_name[c["after_forecast_month"]]
    en.append(f"After the forecast ends: IMD's normal rain for {mon} here is about "
              f"{c['after_forecast_normal_mm']:g} mm (2009-2024 average: "
              f"{c['after_forecast_mean_mm']:g} mm).")
    hi.append(f"मौसम-अनुमान के बाद: यहाँ {HI_MONTHS[c['after_forecast_month'] - 1]} में IMD की "
              f"सामान्य बारिश लगभग {c['after_forecast_normal_mm']:g} मिमी है (2009-2024 का औसत: "
              f"{c['after_forecast_mean_mm']:g} मिमी)।")
    return en, hi
