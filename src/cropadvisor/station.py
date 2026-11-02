"""On-farm sensor station readings: load, check and turn into daily values.

The station does not exist yet. This module fixes the data format the firmware should write, so
the software is ready when it does. One row per reading (any interval), CSV:

    timestamp            ISO date-time in local time, e.g. 2026-12-01T06:00
    sm_top               volumetric soil moisture at the shallow depth (default 15 cm), m3/m3
    sm_deep              volumetric soil moisture at the deep depth (default 45 cm), m3/m3
    rain_mm              rain gauge, mm since the previous reading (optional)
    soil_temp_c, air_temp_c, rh_pct    optional (logged, not used in the water balance yet)

Quality checks (each failed value is dropped and counted, never guessed):
    - soil moisture outside 0.02-0.60 m3/m3 (outside what a soil can hold: a wiring fault or a
      sensor out of the ground);
    - a sensor reading exactly the same value for STUCK_HOURS or more (stuck sensor);
    - rain below 0 or above 300 mm in one reading.
Daily values: the mean of the day's soil moisture readings (needs at least MIN_READINGS), the
day's total rain. A day with no valid reading for a sensor is missing for that sensor; the Kalman
filter (fusion.py) then carries on with the model alone.
"""
import io

import numpy as np
import pandas as pd

SM_RANGE = (0.02, 0.60)
RAIN_MAX_MM = 300.0
STUCK_HOURS = 48
MIN_READINGS = 1
COLUMNS = ["timestamp", "sm_top", "sm_deep", "rain_mm", "soil_temp_c", "air_temp_c", "rh_pct"]


def load(source):
    """Readings from a CSV path, a CSV string or a list of dicts (the web service)."""
    if isinstance(source, list):
        df = pd.DataFrame(source)
    elif isinstance(source, str) and "\n" in source:
        df = pd.read_csv(io.StringIO(source))
    else:
        df = pd.read_csv(source)
    if "timestamp" not in df:
        raise ValueError("station readings need a 'timestamp' column")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    for c in COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    return df[COLUMNS].reset_index(drop=True)


def _stuck(series, ts, hours=STUCK_HOURS):
    """True where the value has not changed at all for `hours` or more."""
    flag = pd.Series(False, index=series.index)
    run_start = 0
    vals, times = series.to_numpy(), ts.to_numpy()
    for i in range(1, len(vals) + 1):
        if i == len(vals) or not (vals[i] == vals[run_start]):
            span = (times[i - 1] - times[run_start]) / np.timedelta64(1, "h")
            if span >= hours and i - run_start >= 3 and not np.isnan(vals[run_start]):
                flag.iloc[run_start:i] = True
            run_start = i
    return flag


def check(df):
    """Drop values that fail the checks. Returns (clean DataFrame, {check: count})."""
    df = df.copy()
    report = {}
    for c in ("sm_top", "sm_deep"):
        bad = df[c].notna() & ~df[c].between(*SM_RANGE)
        stuck = _stuck(df[c], df["timestamp"]) & ~bad
        report[f"{c}_out_of_range"] = int(bad.sum())
        report[f"{c}_stuck"] = int(stuck.sum())
        df.loc[bad | stuck, c] = np.nan
    bad = df["rain_mm"].notna() & ~df["rain_mm"].between(0, RAIN_MAX_MM)
    report["rain_out_of_range"] = int(bad.sum())
    df.loc[bad, "rain_mm"] = np.nan
    return df, report


def daily(df):
    """Daily soil moisture (mean) and rain (sum). Missing stays missing."""
    d = df.assign(date=df["timestamp"].dt.normalize())
    g = d.groupby("date")
    out = pd.DataFrame({
        "sm_top": g["sm_top"].mean().where(g["sm_top"].count() >= MIN_READINGS),
        "sm_deep": g["sm_deep"].mean().where(g["sm_deep"].count() >= MIN_READINGS),
        "rain_mm": g["rain_mm"].sum(min_count=1),
        "n_readings": g.size(),
    })
    return out.reset_index()


def prepare(source):
    """load -> check -> daily. Returns (daily DataFrame, check report)."""
    clean, report = check(load(source))
    return daily(clean), report
