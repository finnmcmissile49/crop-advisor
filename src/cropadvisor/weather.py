"""Step 9 for weather: one daily table per location from all sources, season summaries, and QC.

Daily table columns (one row per location per day):
  date, name,
  tmax_om tmin_om rain_om solar_om rh_om wind2_om et0_om        (Open-Meteo, ERA5-based)
  tmax_pw tmin_pw rain_pw solar_pw rh_pw wind2_pw et0_pw        (NASA POWER; ET0 computed here)
  rain_imd                                                      (IMD gridded gauge rainfall)
"""
import numpy as np
import pandas as pd

from cropadvisor import nasapower, openmeteo
from cropadvisor.et0 import add_et0

RAINY_DAY_MM = 2.5  # IMD definition of a rainy day
SEASONS = {  # name: (start month, start day, end month, end day, end-year offset)
    "kharif": (6, 1, 10, 31, 0),
    "rabi": (11, 1, 3, 31, 1),
}
_SHORT = {"tmax": "tmax", "tmin": "tmin", "rain_mm": "rain", "solar_mj": "solar",
          "rh_mean": "rh", "wind_2m_ms": "wind2"}


def _rename(df, suffix):
    cols = {k: f"{v}_{suffix}" for k, v in _SHORT.items()}
    cols.update({"et0_openmeteo_mm": f"et0_{suffix}", "et0_calc_mm": f"et0_{suffix}"})
    return df.rename(columns=cols)


def fetch_location(name, lat, lon, elev_m, years, raw_dir="data/raw"):
    """Open-Meteo + NASA POWER daily data for one location, fetched and cached one year at a time."""
    om_parts, pw_parts = [], []
    for yr in years:
        s, e = f"{yr}-01-01", f"{yr}-12-31"
        om_parts.append(openmeteo.fetch_history(
            lat, lon, s, e, raw_path=f"{raw_dir}/openmeteo/{name}_{yr}.json"))
        pw_parts.append(nasapower.fetch_history(
            lat, lon, s, e, raw_path=f"{raw_dir}/nasapower/{name}_{yr}.json"))
    om = _rename(pd.concat(om_parts, ignore_index=True), "om")
    pw = pd.concat(pw_parts, ignore_index=True)
    pw = _rename(add_et0(pw, lat, elev_m), "pw")
    out = om.merge(pw, on="date", how="outer").sort_values("date")
    out.insert(1, "name", name)
    return out.reset_index(drop=True)


def build_daily(locations, years, raw_dir="data/raw", imd_daily=None):
    """Daily table for all locations. imd_daily: optional output of imd.point_series()."""
    frames = [fetch_location(n, r["lat"], r["lon"], r["elevation_m"], years, raw_dir)
              for n, r in locations.iterrows()]
    daily = pd.concat(frames, ignore_index=True)
    if imd_daily is not None:
        imd = imd_daily[["date", "name", "rain_imd_mm"]].rename(columns={"rain_imd_mm": "rain_imd"})
        daily = daily.merge(imd, on=["date", "name"], how="left")
    return daily


def longest_run(mask):
    """Longest run of consecutive True values."""
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def season_window(year, season):
    sm, sd, em, ed, off = SEASONS[season]
    return pd.Timestamp(year, sm, sd), pd.Timestamp(year + off, em, ed)


def season_table(daily, seasons=("kharif", "rabi")):
    """One row per location, season and year with the features Module 2 will use."""
    rows = []
    sources = [s for s in ("om", "pw", "imd") if f"rain_{s}" in daily.columns]
    years = sorted(daily["date"].dt.year.unique())
    for name, d in daily.groupby("name"):
        d = d.set_index("date").sort_index()
        for yr in years:
            for season in seasons:
                start, end = season_window(yr, season)
                w = d.loc[start:end]
                expected = (end - start).days + 1
                if len(w) < expected:  # season not fully covered by the data
                    continue
                row = {"name": name, "year": yr, "season": season, "n_days": len(w)}
                for s in sources:
                    r = w[f"rain_{s}"]
                    row[f"rain_total_{s}"] = round(r.sum(min_count=1), 1)
                    row[f"rainy_days_{s}"] = int((r >= RAINY_DAY_MM).sum())
                    row[f"longest_dry_spell_{s}"] = longest_run((r < RAINY_DAY_MM).to_numpy())
                    row[f"missing_rain_days_{s}"] = int(r.isna().sum())
                row.update({
                    "tmax_mean": round(w["tmax_om"].mean(), 2),
                    "tmin_mean": round(w["tmin_om"].mean(), 2),
                    "hot_days_35c": int((w["tmax_om"] >= 35).sum()),
                    "et0_total_om": round(w["et0_om"].sum(), 1),
                    "et0_total_pw": round(w["et0_pw"].sum(min_count=1), 1),
                })
                row["water_balance_om"] = round(row["rain_total_om"] - row["et0_total_om"], 1)
                rows.append(row)
    return pd.DataFrame(rows)


CHECKS = {
    "tmax below tmin": lambda d, s: d[f"tmax_{s}"] < d[f"tmin_{s}"],
    "negative rain": lambda d, s: d[f"rain_{s}"] < 0,
    "humidity outside 0-100": lambda d, s: (d[f"rh_{s}"] < 0) | (d[f"rh_{s}"] > 100),
    "solar outside 0-40 MJ": lambda d, s: (d[f"solar_{s}"] < 0) | (d[f"solar_{s}"] > 40),
    "tmax above 50 C": lambda d, s: d[f"tmax_{s}"] > 50,
    "tmin below -10 C": lambda d, s: d[f"tmin_{s}"] < -10,
    "wind above 30 m/s": lambda d, s: d[f"wind2_{s}"] > 30,
}


def qc_daily(daily):
    """Data-quality report: one row per (location, check) with a count and an example date."""
    issues = []

    def add(name, check, mask, dates):
        n = int(mask.sum())
        if n:
            issues.append({"name": name, "check": check, "count": n,
                           "example_date": str(dates[mask].iloc[0].date())})

    for name, d in daily.groupby("name"):
        d = d.reset_index(drop=True)
        add(name, "duplicate dates", d["date"].duplicated(), d["date"])
        full = pd.date_range(d["date"].min(), d["date"].max())
        gaps = len(full.difference(pd.DatetimeIndex(d["date"])))
        if gaps:
            issues.append({"name": name, "check": "missing dates", "count": gaps,
                           "example_date": str(full.difference(pd.DatetimeIndex(d["date"]))[0].date())})
        for col in [c for c in d.columns if c not in ("date", "name")]:
            add(name, f"missing values: {col}", d[col].isna(), d["date"])
        for s in ("om", "pw"):
            for check, fn in CHECKS.items():
                try:
                    add(name, f"{check} ({s})", fn(d, s).fillna(False), d["date"])
                except KeyError:
                    pass
    return pd.DataFrame(issues, columns=["name", "check", "count", "example_date"])


def disagreement(seasons, threshold=0.30):
    """Seasons where two rainfall sources differ by more than `threshold` (fraction)."""
    out = seasons.copy()
    pairs = [("om", "pw"), ("om", "imd"), ("pw", "imd")]
    flags = []
    for a, b in pairs:
        ca, cb = f"rain_total_{a}", f"rain_total_{b}"
        if ca in out and cb in out:
            rel = (out[ca] - out[cb]).abs() / out[[ca, cb]].mean(axis=1)
            out[f"rain_diff_{a}_{b}"] = rel.round(3)
            flags.append(rel > threshold)
    out["sources_disagree"] = np.logical_or.reduce(flags) if flags else False
    return out
