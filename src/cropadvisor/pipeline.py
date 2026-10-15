"""Step 10: refresh the whole Module 1 dataset with one call.

    from cropadvisor.pipeline import run
    results = run(start_year=2021, end_year=2023, data_dir="data")

Each source is wrapped so one failing API does not stop the others; failures are written to
pull_log.csv with the error message.
"""
import datetime as dt
import os

import pandas as pd

from cropadvisor import imd, soil, weather


def _log(log, source, status, rows=None, note=""):
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    log.append({"source": source, "pulled_at_utc": now.isoformat(timespec="seconds"),
                "status": status, "rows": rows, "note": str(note)[:300]})


def run(start_year, end_year, data_dir="data", locations_csv=None, include_imd=True,
        include_soil=True):
    here = os.path.dirname(os.path.abspath(__file__))
    locations_csv = locations_csv or os.path.join(here, "..", "..", "data", "locations.csv")
    locations = pd.read_csv(locations_csv).set_index("name")
    raw, out = os.path.join(data_dir, "raw"), os.path.join(data_dir, "processed")
    os.makedirs(out, exist_ok=True)
    years = list(range(start_year, end_year + 1))
    log, res = [], {"locations": locations}

    imd_daily = None
    if include_imd:
        try:
            ds = imd.load_rain(start_year, end_year, cache_dir=os.path.join(raw, "imd"))
            imd_daily = imd.point_series(ds, locations)
            _log(log, "IMD gridded rainfall", "ok", len(imd_daily))
        except Exception as e:
            _log(log, "IMD gridded rainfall", "failed", note=e)

    daily = weather.build_daily(locations, years, raw_dir=raw, imd_daily=imd_daily)
    _log(log, "Open-Meteo + NASA POWER daily", "ok", len(daily))
    seasons = weather.disagreement(weather.season_table(daily))
    qc = weather.qc_daily(daily)
    res.update(daily=daily, seasons=seasons, qc=qc)

    if include_soil:
        soil_df = soil.fetch_locations(locations, raw_dir=os.path.join(raw, "soilgrids"))
        ok = soil_df["error"].isna().sum() if "error" in soil_df else len(soil_df)
        _log(log, "SoilGrids", "ok" if ok == len(soil_df) else "partial", int(ok))
        res["soil"] = soil_df
        soil_df.to_csv(os.path.join(out, "soil.csv"))

    daily.to_csv(os.path.join(out, "daily_weather.csv"), index=False)
    seasons.to_csv(os.path.join(out, "seasons.csv"), index=False)
    qc.to_csv(os.path.join(out, "qc_report.csv"), index=False)
    log_df = pd.DataFrame(log)
    log_path = os.path.join(out, "pull_log.csv")
    log_df.to_csv(log_path, mode="a", header=not os.path.exists(log_path), index=False)
    res["log"] = log_df
    return res
