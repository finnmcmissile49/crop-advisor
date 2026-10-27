"""Open-Meteo fetchers (history + forecast), returning the project's harmonised daily columns.

Harmonised columns: date, tmax, tmin, rain_mm, solar_mj, rh_mean, wind_2m_ms, et0_openmeteo_mm,
plus rh_min (daily minimum relative humidity, percent; empty in responses saved before it was
requested), used for the FAO-56 crop coefficient adjustment.
No API key needed. Free for non-commercial use.
"""
import pandas as pd

from cropadvisor.common import http_get_json

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

DAILY_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
              "shortwave_radiation_sum", "et0_fao_evapotranspiration", "relative_humidity_2m_min"]
HOURLY_VARS = ["relative_humidity_2m", "wind_speed_10m"]


def _wind_10m_to_2m(u10):
    import numpy as np
    return u10 * 4.87 / np.log(67.8 * 10 - 5.42)


def _parse(data):
    daily = pd.DataFrame(data["daily"]).rename(columns={
        "time": "date", "temperature_2m_max": "tmax", "temperature_2m_min": "tmin",
        "precipitation_sum": "rain_mm", "shortwave_radiation_sum": "solar_mj",
        "et0_fao_evapotranspiration": "et0_openmeteo_mm", "relative_humidity_2m_min": "rh_min"})
    if "rh_min" not in daily:
        daily["rh_min"] = float("nan")
    hourly = pd.DataFrame(data["hourly"])
    hourly["date"] = hourly["time"].str.slice(0, 10)
    agg = hourly.groupby("date").agg(
        rh_mean=("relative_humidity_2m", "mean"),
        wind_10m=("wind_speed_10m", "mean")).reset_index()
    agg["wind_2m_ms"] = _wind_10m_to_2m(agg["wind_10m"])
    out = daily.merge(agg[["date", "rh_mean", "wind_2m_ms"]], on="date", how="left")
    out["date"] = pd.to_datetime(out["date"])
    out.attrs["elevation_m"] = data.get("elevation")
    return out[["date", "tmax", "tmin", "rain_mm", "solar_mj", "rh_mean",
                "wind_2m_ms", "et0_openmeteo_mm", "rh_min"]]


def fetch_history(lat, lon, start, end, raw_path=None):
    """Daily weather history. start/end as 'YYYY-MM-DD'."""
    params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "daily": ",".join(DAILY_VARS), "hourly": ",".join(HOURLY_VARS),
              "wind_speed_unit": "ms", "timezone": "Asia/Kolkata"}
    return _parse(http_get_json(ARCHIVE_URL, params, raw_path=raw_path))


def fetch_forecast(lat, lon, days=16, past_days=0, raw_path=None):
    """Daily forecast for the next `days` (max 16), optionally with some recent past days."""
    params = {"latitude": lat, "longitude": lon, "forecast_days": days,
              "past_days": past_days, "daily": ",".join(DAILY_VARS),
              "hourly": ",".join(HOURLY_VARS), "wind_speed_unit": "ms",
              "timezone": "Asia/Kolkata"}
    return _parse(http_get_json(FORECAST_URL, params, raw_path=raw_path))
