"""IMD 0.25 degree gridded daily rainfall (step 5), via the imdlib package.

IMD publishes one binary file per year (about 25 MB each). Files are cached in `cache_dir`
and never downloaded twice. Values of -999 mean "no data" (e.g. ocean cells) and become NaN.

Coverage: 1901 onwards; the latest year appears with a lag of a few months.
"""
import glob
import os

import numpy as np
import pandas as pd


def _imdlib():
    try:
        import imdlib
    except ImportError as e:  # pragma: no cover
        raise ImportError("imdlib is not installed: pip install imdlib") from e
    return imdlib


def _year_cached(cache_dir, year):
    return bool(glob.glob(os.path.join(cache_dir, "rain", f"{year}*")))


def load_rain(start_yr, end_yr, cache_dir="data/raw/imd"):
    """Download (if needed) and open IMD daily rainfall for start_yr..end_yr as an xarray Dataset."""
    imd = _imdlib()
    os.makedirs(cache_dir, exist_ok=True)
    for yr in range(start_yr, end_yr + 1):
        if not _year_cached(cache_dir, yr):
            imd.get_data("rain", yr, yr, fn_format="yearwise", file_dir=cache_dir)
    return imd.open_data("rain", start_yr, end_yr, fn_format="yearwise",
                         file_dir=cache_dir).get_xarray()


def _coord(ds, *names):
    for n in names:
        if n in ds.coords:
            return n
    raise KeyError(f"none of {names} in coordinates {list(ds.coords)}")


def point_series(ds, locations):
    """Extract the nearest grid cell for each location.

    locations: DataFrame indexed by name with `lat` and `lon` columns.
    Returns long DataFrame: date, name, rain_imd_mm, imd_lat, imd_lon.
    """
    var = "rain" if "rain" in ds.data_vars else list(ds.data_vars)[0]
    lat_c, lon_c = _coord(ds, "lat", "latitude"), _coord(ds, "lon", "longitude")
    time_c = _coord(ds, "time", "date")
    frames = []
    for name, row in locations.iterrows():
        cell = ds[var].sel({lat_c: row["lat"], lon_c: row["lon"]}, method="nearest")
        df = pd.DataFrame({"date": pd.to_datetime(cell[time_c].values),
                           "rain_imd_mm": cell.values.astype(float)})
        df["name"] = name
        df["imd_lat"] = float(cell[lat_c])
        df["imd_lon"] = float(cell[lon_c])
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out.loc[out["rain_imd_mm"] < 0, "rain_imd_mm"] = np.nan  # -999 missing flag
    return out[["date", "name", "rain_imd_mm", "imd_lat", "imd_lon"]]
